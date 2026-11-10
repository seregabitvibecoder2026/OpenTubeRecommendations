"""FastAPI app: pages (Jinja2 + HTMX), listens on 127.0.0.1 only."""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import collect, config, db, i18n, jobs, profiles, ranking, tasks  # noqa: F401  (tasks registers jobs)
from .ml import catalog, engines, hw

# Offline by default for model libraries: they only touch the network inside explicit download jobs.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

APP_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app):
    db.init()
    jobs.mark_orphans()
    profiles.ensure_active()
    jobs.start_auto_updater()
    yield
    jobs.stop_all()
    engines.LLAMA.stop()


app = FastAPI(title="OpenTubeRecommendations", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals.update(t=i18n.t, fmt_duration=ranking.fmt_duration, fmt_age=ranking.fmt_age,
                             jloads=db.jloads, kinds=catalog.KINDS, now=time.time)


def back(request: Request, default: str = "/feed") -> RedirectResponse:
    ref = request.headers.get("referer") or default
    return RedirectResponse(ref, status_code=303)


def header_ctx() -> dict:
    s = db.get_settings()
    pid = profiles.ensure_active()
    emb = s["embed"].get("model") or ""
    return {
        "settings": s, "pid": pid, "profile": profiles.get(pid), "profiles": profiles.all_profiles(),
        "running": jobs.running(), "mode": s.get("mode", "light"),
        "emb_model": emb.split("/")[-1] if emb else "", "llm_model": s["llm"].get("model") or "",
    }


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    base = header_ctx()
    base.update(ctx)
    return templates.TemplateResponse(request, name, base)


# ---------------------------------------------------------------- wizard / root
@app.get("/")
def root():
    if not db.get_settings().get("wizard_done"):
        return RedirectResponse("/wizard", 303)
    return RedirectResponse("/feed", 303)


@app.get("/wizard")
def wizard(request: Request):
    return render(request, "wizard.html", templates_=config.TEMPLATES)


@app.post("/wizard")
def wizard_post(mode: str = Form("light"), template: str = Form("rest"), name: str = Form("")):
    db.set_setting("mode", mode if mode in ("light", "medium", "full") else "light")
    rows = profiles.all_profiles()
    # the auto-created default profile is replaced by the chosen template if it is untouched
    if len(rows) == 1 and not db.q1("SELECT 1 FROM profile_channels WHERE profile_id=?", (rows[0]["id"],)):
        profiles.delete(rows[0]["id"])
    pid = profiles.create(name or None, template)
    profiles.set_active(pid)
    db.set_setting("wizard_done", True)
    if mode == "medium":
        return RedirectResponse("/models?kind=embed", 303)
    if mode == "full":
        return RedirectResponse("/models?kind=llm", 303)
    return RedirectResponse("/channels", 303)


# ---------------------------------------------------------------- feed
@app.get("/feed")
def feed(request: Request, similar: str | None = None):
    pid = profiles.ensure_active()
    res = ranking.feed(pid, similar_to=similar)
    ch_titles = {r["id"]: r["title"] for r in db.q("SELECT id, title FROM channels")}
    opened = {r["video_id"] for r in db.q("SELECT video_id FROM feedback WHERE profile_id=? AND kind='opened'", (pid,))}
    for it in res["items"]:
        it["opened"] = it["v"]["id"] in opened
    sim_title = None
    if similar:
        r = db.q1("SELECT title FROM videos WHERE id=?", (similar,))
        sim_title = r["title"] if r else similar
    n_channels = db.q1("SELECT count(*) FROM profile_channels WHERE profile_id=?", (pid,))[0]
    return render(request, "feed.html", res=res, ch_titles=ch_titles, ps=profiles.settings(pid), similar=similar,
                  sim_title=sim_title, n_channels=n_channels)


@app.post("/feed/filter")
def feed_filter(request: Request, lang_filter: str = Form("all"), show_18: str = Form("yes")):
    pid = profiles.ensure_active()
    profiles.update_settings(pid, {"lang_filter": lang_filter, "show_18": show_18})
    return back(request)


@app.post("/fb/{vid}/{kind}")
def feedback(request: Request, vid: str, kind: str):
    pid = profiles.ensure_active()
    if kind not in ("like", "dislike", "hide", "more", "opened"):
        return Response(status_code=400)
    db.ex("INSERT INTO feedback(profile_id, video_id, kind, ts) VALUES(?,?,?,?)", (pid, vid, kind, time.time()))
    if kind == "more":
        if request.headers.get("HX-Request"):
            return Response(headers={"HX-Redirect": f"/feed?similar={vid}"})
        return RedirectResponse(f"/feed?similar={vid}", 303)
    if request.headers.get("HX-Request"):
        return HTMLResponse("")  # card disappears
    return back(request)


@app.get("/open/{vid}")
def open_video(vid: str):
    pid = profiles.ensure_active()
    db.ex("INSERT INTO feedback(profile_id, video_id, kind, ts) VALUES(?,?,?,?)", (pid, vid, "opened", time.time()))
    return RedirectResponse(f"https://www.youtube.com/watch?v={vid}", 303)


@app.post("/channel/{cid}/hide")
def hide_channel(request: Request, cid: str):
    pid = profiles.ensure_active()
    db.ex("""INSERT INTO profile_channels(profile_id, channel_id, hidden, added_at) VALUES(?,?,1,?)
             ON CONFLICT(profile_id, channel_id) DO UPDATE SET hidden=1""", (pid, cid, time.time()))
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Refresh": "true"})
    return back(request)


@app.get("/thumb/{vid}")
def thumb(vid: str):
    """Thumbnails go through the app (proxy + cache), the browser never talks to YouTube directly."""
    if not vid.replace("-", "").replace("_", "").isalnum() or len(vid) != 11:
        return Response(status_code=404)
    p = tasks.thumb_path(vid)
    if not p.exists():
        try:
            tasks.thumb_bytes(vid)
        except Exception:  # noqa: BLE001 - offline etc.
            return FileResponse(APP_DIR / "static" / "nothumb.svg", media_type="image/svg+xml")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=604800"})


@app.get("/video/{vid}")
def video_page(request: Request, vid: str):
    pid = profiles.ensure_active()
    v = db.q1("SELECT * FROM videos WHERE id=?", (vid,))
    if not v:
        return RedirectResponse("/feed", 303)
    res = ranking.compute(pid, include_all=True)
    item = next((it for it in res["items"] if it["v"]["id"] == vid), None)
    sc = db.q1("SELECT * FROM video_scores WHERE profile_id=? AND video_id=?", (pid, vid))
    ch = db.q1("SELECT * FROM channels WHERE id=?", (v["channel_id"],))
    return render(request, "video.html", v=dict(v), item=item, sc=dict(sc) if sc else None, ch=dict(ch) if ch else None,
                  probe=db.jloads(v["probe"], None), ev=db.jloads(v["evidence"], {}), ps=profiles.settings(pid))


@app.post("/video/{vid}/probe")
def video_probe(request: Request, vid: str):
    jobs.start("probe", profiles.ensure_active(), {"video_ids": [vid]})
    return back(request)


@app.post("/video/{vid}/job/{kind}")
def video_job(request: Request, vid: str, kind: str):
    if kind in ("subs", "comments", "llm", "vision"):
        jobs.start(kind, profiles.ensure_active(), {"video_ids": [vid]})
    return back(request)


# ---------------------------------------------------------------- channels
@app.get("/channels")
def channels_page(request: Request):
    pid = profiles.ensure_active()
    rows = db.q("""SELECT c.*, pc.weight, pc.paused, pc.hidden,
                   (SELECT count(*) FROM videos v WHERE v.channel_id=c.id) AS n_videos
                   FROM profile_channels pc JOIN channels c ON c.id=pc.channel_id WHERE pc.profile_id=?
                   ORDER BY pc.hidden, lower(coalesce(c.title, c.id))""", (pid,))
    cands = db.q("SELECT * FROM candidates WHERE profile_id=? AND status='new' ORDER BY score DESC NULLS LAST", (pid,))
    return render(request, "channels.html", rows=[dict(r) for r in rows], cands=[dict(r) for r in cands])


@app.post("/channels/add")
def channels_add(request: Request, items: str = Form("")):
    parts = collect.split_inputs(items)
    if parts:
        jobs.start("add_channels", profiles.ensure_active(), {"items": parts})
    return back(request)


@app.post("/channels/import")
async def channels_import(request: Request, file: UploadFile = File(...)):
    data = (await file.read()).decode("utf-8", errors="replace")
    rows = collect.parse_takeout_csv(data)
    pid = profiles.ensure_active()
    for r in rows:
        collect.upsert_channel(r["id"], r.get("title"))
        collect.attach(pid, r["id"])
    return back(request)


@app.post("/channels/{cid}/set")
def channel_set(request: Request, cid: str, weight: float = Form(None), action: str = Form("")):
    pid = profiles.ensure_active()
    if weight is not None and action == "":
        db.ex("UPDATE profile_channels SET weight=? WHERE profile_id=? AND channel_id=?", (max(-2, min(2, weight)), pid, cid))
    elif action == "pause":
        db.ex("UPDATE profile_channels SET paused=1-paused WHERE profile_id=? AND channel_id=?", (pid, cid))
    elif action == "unhide":
        db.ex("UPDATE profile_channels SET hidden=0 WHERE profile_id=? AND channel_id=?", (pid, cid))
    elif action == "remove":
        db.ex("DELETE FROM profile_channels WHERE profile_id=? AND channel_id=?", (pid, cid))
    elif action == "refresh":
        jobs.start("refresh", pid, {"channel_ids": [cid]})
    if request.headers.get("HX-Request") and action == "":
        return HTMLResponse("✓")
    return back(request)


@app.post("/candidates/{cid}/{action}")
def candidate(request: Request, cid: str, action: str):
    pid = profiles.ensure_active()
    if action == "accept":
        collect.attach(pid, cid)
        db.ex("UPDATE candidates SET status='accepted' WHERE profile_id=? AND channel_id=?", (pid, cid))
    elif action == "reject":
        db.ex("UPDATE candidates SET status='rejected' WHERE profile_id=? AND channel_id=?", (pid, cid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return back(request)


# ---------------------------------------------------------------- rules
@app.get("/rules")
def rules_page(request: Request):
    pid = profiles.ensure_active()
    rules = profiles.rules(pid)
    lists: dict = {}
    for r in rules:
        lists.setdefault((r["kind"], r["lang"]), []).append(r)
    return render(request, "rules.html", ps=profiles.settings(pid), lists=lists)


@app.post("/rules/settings")
async def rules_settings(request: Request):
    pid = profiles.ensure_active()
    f = await request.form()
    ps = profiles.settings(pid)
    num = lambda k, d: float(f.get(k, d))  # noqa: E731
    patch = {
        "weights": {k: num(f"w_{k}", ps["weights"][k]) for k in ps["weights"]},
        "exploration": num("exploration", ps["exploration"]),
        "fresh_half_life_days": num("fresh_half_life_days", ps["fresh_half_life_days"]),
        "max_age_days": int(num("max_age_days", ps["max_age_days"])),
        "min_duration_sec": int(num("min_duration_sec", ps["min_duration_sec"])),
        "feed_size": int(num("feed_size", ps["feed_size"])),
        "incomplete_trust": num("incomplete_trust", ps["incomplete_trust"]),
        "profanity_weight": num("profanity_weight", ps["profanity_weight"]),
        "profanity_target": num("profanity_target", ps["profanity_target"]),
        "taste_min_ratings": int(num("taste_min_ratings", ps["taste_min_ratings"])),
        "logreg_min_ratings": int(num("logreg_min_ratings", ps["logreg_min_ratings"])),
        "lang_weights": {lg: num(f"lw_{lg}", ps["lang_weights"].get(lg, 0)) for lg in ("ru", "en")},
        "lang_selected": [x for x in str(f.get("lang_selected", "ru en")).split() if x],
    }
    profiles.update_settings(pid, patch)
    return back(request, "/rules")


def _parse_list(blob: str, default_w: float) -> list[tuple[str, float]]:
    out = []
    for ln in (blob or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ":" in ln:
            p, w = ln.rsplit(":", 1)
            try:
                out.append((p.strip(), float(w)))
                continue
            except ValueError:
                pass
        out.append((ln, default_w))
    return out


@app.post("/rules/lists")
async def rules_lists(request: Request):
    pid = profiles.ensure_active()
    f = await request.form()
    defaults = {"stopword": -1.0, "stoptopic": -0.8, "topic": 0.4, "profanity": 1.0}
    for key, val in f.items():
        if not key.startswith("list__"):
            continue
        _, kind, lang = key.split("__")
        if kind in defaults:
            profiles.set_rules(pid, kind, lang, _parse_list(str(val), defaults[kind]))
    new_kind, new_lang = f.get("new_kind"), (f.get("new_lang") or "").strip()
    if new_kind in defaults and new_lang:
        existing = profiles.rules(pid, new_kind)
        if not any(r["lang"] == new_lang for r in existing):
            profiles.set_rules(pid, new_kind, new_lang, _parse_list(str(f.get("new_items", "")), defaults[new_kind]))
    return back(request, "/rules")


@app.post("/rules/questions")
async def rules_questions(request: Request):
    pid = profiles.ensure_active()
    f = await request.form()
    qs = []
    keys, texts, ws = f.getlist("q_key"), f.getlist("q_text"), f.getlist("q_weight")
    for k, tx, w in zip(keys, texts, ws):
        k = "".join(ch for ch in str(k).strip().lower() if ch.isalnum() or ch == "_")
        if k and str(tx).strip():
            try:
                wv = max(-1.0, min(1.0, float(w)))
            except ValueError:
                wv = 0.0
            qs.append({"key": k, "text": str(tx).strip(), "weight": wv})
    profiles.replace_setting(pid, "llm_questions", qs)
    if f.get("llm_prompt"):
        profiles.replace_setting(pid, "llm_prompt", str(f.get("llm_prompt")))
    return back(request, "/rules")


# ---------------------------------------------------------------- jobs
JOB_BUTTONS = [("refresh", True), ("subs", True), ("comments", True), ("probe", True), ("vision", True), ("embed", False),
               ("llm", True), ("rank", False), ("discover", False)]


@app.get("/jobs")
def jobs_page(request: Request):
    return render(request, "jobs.html", buttons=[(k, jobs.REGISTRY[k][0], n) for k, n in JOB_BUTTONS])


@app.get("/jobs/panel")
def jobs_panel(request: Request):
    return templates.TemplateResponse(request, "_jobs_panel.html", {"recent": jobs.recent(25), "running_ids": set(jobs.RUNNING),
                                                                    "titles": {k: v[0] for k, v in jobs.REGISTRY.items()}})


@app.get("/jobs/indicator")
def jobs_indicator(request: Request):
    return templates.TemplateResponse(request, "_indicator.html", {"running": jobs.running(),
                                                                   "titles": {k: v[0] for k, v in jobs.REGISTRY.items()}})


@app.post("/jobs/start/{kind}")
async def jobs_start(request: Request, kind: str):
    f = await request.form()
    params = {}
    if f.get("n"):
        params["n"] = int(f.get("n"))
    for k in ("search", "llm", "all"):
        if f.get(k):
            params[k] = True
    jobs.start(kind, profiles.ensure_active(), params or None)
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Trigger": "jobs-changed"})
    return back(request, "/jobs")


@app.post("/jobs/{jid}/stop")
def jobs_stop(request: Request, jid: int):
    jobs.stop(jid)
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Trigger": "jobs-changed"})
    return back(request, "/jobs")


@app.post("/jobs/stop_all")
def jobs_stop_all(request: Request):
    jobs.stop_all()
    return back(request, "/jobs")


# ---------------------------------------------------------------- settings
@app.get("/settings")
def settings_page(request: Request):
    return render(request, "settings.html", data_dir=str(config.data_dir()))


@app.post("/settings")
async def settings_post(request: Request):
    f = await request.form()
    s = db.get_settings()
    def fnum(k, d):
        try:
            return float(f.get(k, d))
        except (TypeError, ValueError):
            return d
    db.set_setting("proxy", str(f.get("proxy", "")).strip())
    db.set_setting("request_pause", max(0.0, fnum("request_pause", s["request_pause"])))
    db.set_setting("max_parallel", max(1, int(fnum("max_parallel", s["max_parallel"]))))
    db.set_setting("retries", max(0, int(fnum("retries", s["retries"]))))
    db.set_setting("videos_per_channel", max(1, int(fnum("videos_per_channel", s["videos_per_channel"]))))
    db.set_setting("comments_max", max(1, int(fnum("comments_max", s["comments_max"]))))
    db.set_setting("sub_langs", [x for x in str(f.get("sub_langs", "ru en")).split() if x])
    db.set_setting("ytdlp_clients", [x for x in str(f.get("ytdlp_clients", "default")).split() if x])
    db.set_setting("api_key", str(f.get("api_key", "")).strip())
    db.set_setting("api_enabled", bool(f.get("api_enabled")))
    db.set_setting("altfront_url", str(f.get("altfront_url", "")).strip())
    db.set_setting("altfront_kind", f.get("altfront_kind", "invidious"))
    db.set_setting("cookies_browser", str(f.get("cookies_browser", "")).strip())
    db.set_setting("auto_update_hours", max(0.0, fnum("auto_update_hours", 0)))
    db.set_setting("theme", f.get("theme", "auto"))
    # source chains: "<group>__<name>" checkbox + "<group>__<name>__order"
    def chain(group_items, prefix):
        items = []
        for idx, p in enumerate(group_items):
            order = fnum(f"{prefix}__{p['name']}__order", 100 + idx)
            items.append((order, {"name": p["name"], "on": bool(f.get(f"{prefix}__{p['name']}"))}))
        return [x for _, x in sorted(items, key=lambda t: t[0])]
    db.set_setting("listing_order", chain(s["listing_order"], "listing"))
    db.set_setting("providers", {g: chain(s["providers"][g], g) for g in s["providers"]})
    return back(request, "/settings")


# ---------------------------------------------------------------- models
@app.get("/models")
def models_page(request: Request, kind: str = "all", restricted: int = -1):
    s = db.get_settings()
    if restricted in (0, 1):
        db.set_setting("show_restricted_licenses", bool(restricted))
        s = db.get_settings()
    gpu = hw.gpu_info()
    ollama_url = s["llm"]["url"]
    ollama_up = engines.ollama_alive(ollama_url)
    ollama_names = {m.get("name") for m in engines.ollama_tags(ollama_url)} if ollama_up else set()
    rows = []
    for m in catalog.CATALOG + custom_models():
        if kind != "all" and m["kind"] != kind:
            continue
        if not m["open"] and not s["show_restricted_licenses"]:
            continue
        r = dict(m)
        r["fits"] = catalog.fits(m, gpu["free_gb"] if gpu["gpu"] else 0, float(s["vram_budget_max"]))
        r["in_budget"] = catalog.min_vram(m) <= float(s["vram_budget_max"])
        r["installed"] = model_installed(m, ollama_names)
        r["in_use"] = model_in_use(m, s)
        rows.append(r)
    extras = {k: hw.has_module(mod) for k, (mod, _) in tasks.EXTRAS.items()}
    ggufs = sorted(str(p) for p in engines.gguf_dir().rglob("*.gguf"))
    return render(request, "models.html", rows=rows, kind=kind, gpu=gpu, ollama_up=ollama_up, extras=extras,
                  extra_titles={k: v[1] for k, v in tasks.EXTRAS.items()}, ggufs=ggufs, llama_running=engines.LLAMA.running(),
                  ram=hw.ram_gb(), gguf_files=request.query_params.get("gguf_files"), gguf_repo=request.query_params.get("repo"))


def custom_models() -> list[dict]:
    return db.get_settings().get("custom_models") or []


def model_installed(m: dict, ollama_names: set) -> bool:
    if m["engine"] in ("st", "whisper"):
        return engines.hf_dir(m["ref"]).exists() and any(engines.hf_dir(m["ref"]).iterdir())
    if m["engine"] == "ollama":
        return m["ref"] in ollama_names or f"{m['ref']}:latest" in ollama_names
    if m["engine"] == "gguf":
        d = engines.gguf_dir() / m["ref"].replace("/", "--")
        return d.exists() and any(d.rglob("*.gguf"))
    return False


def model_in_use(m: dict, s: dict) -> bool:
    if m["kind"] == "embed":
        return s["embed"].get("model") == m["ref"] and s["embed"].get("engine") == m["engine"]
    if m["kind"] == "llm":
        return s["llm"].get("model") == m["ref"]
    if m["kind"] == "vision":
        return s["vision"].get("model") == m["ref"]
    if m["kind"] == "asr":
        return s["asr"].get("model") == m["ref"]
    return False


def _find_model(mid: str) -> dict | None:
    return catalog.by_id(mid) or next((m for m in custom_models() if m["id"] == mid), None)


@app.post("/models/{mid}/download")
def models_download(request: Request, mid: str, file: str = Form(""), size_gb: float = Form(0)):
    m = _find_model(mid)
    if m:
        jobs.start("model_download", None, {"model": m, "file": file, "size_gb": size_gb})
    return back(request, "/models")


@app.post("/models/{mid}/test")
def models_test(request: Request, mid: str):
    m = _find_model(mid)
    if m:
        jobs.start("model_test", None, {"model": m})
    return back(request, "/models")


@app.post("/models/{mid}/use")
def models_use(request: Request, mid: str):
    m = _find_model(mid)
    s = db.get_settings()
    if m:
        if m["kind"] == "embed":
            db.set_setting("embed", dict(s["embed"], model=m["ref"], engine="st" if m["engine"] == "st" else m["engine"]))
        elif m["kind"] == "llm":
            if m["engine"] == "gguf":
                files = sorted((engines.gguf_dir() / m["ref"].replace("/", "--")).rglob("*.gguf"))
                db.set_setting("llm", dict(s["llm"], engine="llamacpp", gguf_path=str(files[0]) if files else "", model=m["ref"]))
            else:
                db.set_setting("llm", dict(s["llm"], engine="ollama", model=m["ref"]))
        elif m["kind"] == "vision":
            db.set_setting("vision", dict(s["vision"], engine="ollama", model=m["ref"]))
        elif m["kind"] == "asr":
            db.set_setting("asr", dict(s["asr"], model=m["ref"]))
    return back(request, "/models")


@app.post("/models/unuse/{kind}")
def models_unuse(request: Request, kind: str):
    s = db.get_settings()
    if kind in ("embed", "llm", "vision", "asr"):
        db.set_setting(kind, dict(s[kind], model=""))
        if kind == "embed":
            engines.unload_embed()
    return back(request, "/models")


@app.post("/models/{mid}/delete")
def models_delete(request: Request, mid: str):
    import shutil
    m = _find_model(mid)
    if m:
        if m["engine"] in ("st", "whisper"):
            shutil.rmtree(engines.hf_dir(m["ref"]), ignore_errors=True)
        elif m["engine"] == "gguf":
            shutil.rmtree(engines.gguf_dir() / m["ref"].replace("/", "--"), ignore_errors=True)
        elif m["engine"] == "ollama":
            url = db.get_settings()["llm"]["url"].rstrip("/")
            try:
                import httpx
                httpx.request("DELETE", url + "/api/delete", json={"model": m["ref"]}, timeout=30, trust_env=False)
            except Exception:  # noqa: BLE001
                pass
    return back(request, "/models")


@app.post("/models/custom")
def models_custom(request: Request, kind: str = Form(...), engine: str = Form(...), ref: str = Form(...),
                  vram: float = Form(0), disk: float = Form(0), license: str = Form("?")):
    ref = ref.strip()
    if ref:
        cm = custom_models()
        mid = "custom-" + "".join(ch if ch.isalnum() else "-" for ch in ref.lower())
        cm = [m for m in cm if m["id"] != mid]
        m = catalog.M(mid, kind, engine, ref, ref + " (своя)", disk, {"?": vram}, "?", license.strip() or "?")
        m["open"] = True  # user's own choice: always visible
        cm.append(m)
        db.set_setting("custom_models", cm)
    return back(request, "/models")


@app.post("/models/gguf_files")
def models_gguf_files(repo: str = Form(...)):
    import subprocess
    import sys
    from urllib.parse import quote
    try:
        out = subprocess.run([sys.executable, "-m", "app.ml.dl", "list", repo.strip()], capture_output=True, text=True,
                             timeout=60, env=tasks._dl_env(), cwd=str(config.ROOT))
        files = [(f, s) for f, s in json.loads(out.stdout or "[]") if f.endswith(".gguf")]
    except Exception:  # noqa: BLE001
        files = []
    return RedirectResponse(f"/models?kind=llm&repo={quote(repo.strip())}&gguf_files={quote(json.dumps(files))}", 303)


@app.post("/models/llm_endpoint")
def models_llm_endpoint(request: Request, engine: str = Form("ollama"), url: str = Form(""), model: str = Form(""),
                        gguf_path: str = Form(""), llama_server_bin: str = Form("llama-server"), top_n: int = Form(40)):
    s = db.get_settings()
    db.set_setting("llm", dict(s["llm"], engine=engine, url=url.strip() or s["llm"]["url"], model=model.strip(),
                               gguf_path=gguf_path.strip(), llama_server_bin=llama_server_bin.strip() or "llama-server",
                               top_n=top_n))
    return back(request, "/models")


@app.post("/models/budget")
def models_budget(request: Request, vmin: float = Form(4), vmax: float = Form(6)):
    db.set_setting("vram_budget_min", vmin)
    db.set_setting("vram_budget_max", vmax)
    return back(request, "/models")


@app.post("/models/extra/{extra}")
def models_extra(request: Request, extra: str):
    jobs.start("install_extra", None, {"extra": extra})
    return back(request, "/models")


@app.post("/models/llama/{action}")
def models_llama(request: Request, action: str):
    s = db.get_settings()["llm"]
    try:
        if action == "start":
            engines.LLAMA.start(s.get("gguf_path", ""), int(s.get("ngl", 99)), int(s.get("ctx", 8192)), s.get("llama_server_bin"))
        else:
            engines.LLAMA.stop()
    except engines.EngineError as e:
        return HTMLResponse(f"<p>{e}</p><a href='/models'>←</a>", status_code=400)
    return back(request, "/models")


@app.post("/settings/mode")
def set_mode(request: Request, mode: str = Form("light")):
    db.set_setting("mode", mode)
    return back(request)


# ---------------------------------------------------------------- profiles
@app.get("/profiles")
def profiles_page(request: Request):
    rows = []
    for p in profiles.all_profiles():
        p["n_fb"] = db.q1("SELECT count(*) FROM feedback WHERE profile_id=?", (p["id"],))[0]
        p["n_ch"] = db.q1("SELECT count(*) FROM profile_channels WHERE profile_id=?", (p["id"],))[0]
        rows.append(p)
    return render(request, "profiles.html", rows=rows, templates_=config.TEMPLATES)


@app.post("/profiles/switch")
def profiles_switch(request: Request, pid: str = Form(...)):
    profiles.set_active(pid)
    return back(request)


@app.post("/profiles/create")
def profiles_create(request: Request, name: str = Form(""), template: str = Form("empty")):
    pid = profiles.create(name.strip() or None, template)
    profiles.set_active(pid)
    return back(request, "/profiles")


@app.post("/profiles/{pid}/{action}")
async def profiles_action(request: Request, pid: str, action: str):
    f = await request.form()
    if action == "rename":
        profiles.rename(pid, str(f.get("name", "")).strip(), f.get("color"), f.get("icon"))
    elif action == "duplicate":
        new = profiles.duplicate(pid, with_history=bool(f.get("with_history")))
        profiles.set_active(new)
    elif action == "delete":
        profiles.delete(pid)
        profiles.ensure_active()
    elif action == "reset":
        profiles.reset(pid)
    elif action == "export":
        data = profiles.export(pid, include_history=bool(f.get("with_history")))
        name = "".join(ch if ch.isalnum() else "_" for ch in data["profile"]["name"])
        return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="profile-{name}.json"'})
    return back(request, "/profiles")


@app.post("/profiles_import")
async def profiles_import(request: Request, file: UploadFile = File(...), mode: str = Form("new")):
    try:
        data = json.loads((await file.read()).decode("utf-8"))
        pid = profiles.import_(data, mode="replace" if mode == "replace" else "new")
        profiles.set_active(pid)
    except (ValueError, KeyError) as e:
        return HTMLResponse(f"<p>Не удалось импортировать: {e}</p><a href='/profiles'>←</a>", status_code=400)
    return RedirectResponse("/profiles", 303)


@app.post("/reset_all")
def reset_all(confirm: str = Form("")):
    if confirm == "yes":
        jobs.stop_all()
        profiles.reset_all()
        profiles.ensure_active()
    return RedirectResponse("/", 303)


@app.get("/api/health")
def health():
    return JSONResponse({"ok": True, "version": config.VERSION})
