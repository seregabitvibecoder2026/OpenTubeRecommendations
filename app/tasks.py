"""Job implementations (each one is a button on the Jobs/Models pages)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import collect, config, db, net, profiles, ranking, text
from .jobs import JobCtx, register
from .ml import catalog, engines, hw
from .providers import watchpage, ytdlp


def _profile_channels(pid: str) -> list[dict]:
    return [dict(r) for r in db.q("""SELECT c.* FROM channels c JOIN profile_channels pc ON pc.channel_id=c.id
                                     WHERE pc.profile_id=? AND pc.paused=0 AND pc.hidden=0 ORDER BY c.title""", (pid,))]


def _target_ids(ctx: JobCtx, n: int, state_col: str | None = None) -> list[str]:
    """Videos to process: explicit list, else top of the current ranking that still lacks the data."""
    if ctx.params.get("video_ids"):
        return list(ctx.params["video_ids"])
    ids = ranking.top_ids(ctx.pid, n * 3)
    if state_col:
        st = {r["id"]: r[state_col] for r in db.q(
            f"SELECT id, {state_col} FROM videos WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else {}
        ids = [i for i in ids if st.get(i, 0) in (collect.NOT_TRIED, collect.ERROR)]
    return ids[:n]


# ---------------------------------------------------------------- refresh
@register("refresh", "Обновить ленту")
def job_refresh(ctx: JobCtx) -> None:
    s = db.get_settings()
    chans = _profile_channels(ctx.pid) if not ctx.params.get("all") else [dict(r) for r in db.q("SELECT * FROM channels")]
    if ctx.params.get("channel_ids"):
        chans = [dict(r) for r in db.q(f"SELECT * FROM channels WHERE id IN ({','.join('?' * len(ctx.params['channel_ids']))})",
                                       ctx.params["channel_ids"])]
    ctx.progress(0, len(chans), "список видео")
    breaker: dict = {}
    new_ids: list[str] = []
    for i, ch in enumerate(chans, 1):
        ctx.check()
        try:
            d = collect.list_channel(ch["id"], int(s["videos_per_channel"]), log=ctx.log, stop=ctx.stopped, breaker=breaker)
            new = collect.upsert_listing(d["entries"], ch["id"])
            new_ids += new
            db.ex("UPDATE channels SET last_fetch=?, fetch_error=NULL, listing_source=?, title=COALESCE(title, ?) WHERE id=?",
                  (time.time(), d["source"], d.get("channel_title"), ch["id"]))
            ctx.log(f"{ch['title'] or ch['id']}: {len(d['entries'])} видео ({d['source']}), новых {len(new)}")
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            db.ex("UPDATE channels SET fetch_error=? WHERE id=?", (str(e)[:300], ch["id"]))
            ctx.log(f"{ch['title'] or ch['id']}: ошибка: {str(e)[:200]}")
        ctx.progress(i, len(chans), f"каналы {i}/{len(chans)}")
    # metadata for new videos (cheap chain: public page first)
    todo = [r["id"] for r in db.q("SELECT id FROM videos WHERE meta_state IN (0, -2) ORDER BY first_seen DESC LIMIT ?",
                                  (int(s.get("meta_new_per_refresh", 200)),))]
    todo = [v for v in todo if v in set(new_ids)] + [v for v in todo if v not in set(new_ids)]
    ctx.progress(0, len(todo), "метаданные")
    for i, vid in enumerate(todo, 1):
        ctx.check()
        src = collect.fetch_meta(vid, log=ctx.log, stop=ctx.stopped)
        if i % 10 == 0 or i == len(todo):
            ctx.log(f"метаданные: {i}/{len(todo)} (последний источник: {src})")
        ctx.progress(i, len(todo), f"метаданные {i}/{len(todo)}")
    ctx.log(f"готово: новых видео {len(new_ids)}")


@register("add_channels", "Добавить каналы")
def job_add_channels(ctx: JobCtx) -> None:
    items = ctx.params.get("items") or []
    ctx.progress(0, len(items))
    added = []
    for i, it in enumerate(items, 1):
        ctx.check()
        try:
            if isinstance(it, dict):
                info = {"id": it["id"], "title": it.get("title"), "handle": None}
            else:
                info = collect.resolve(it, stop=ctx.stopped)
            collect.upsert_channel(info["id"], info.get("title"), info.get("handle"), info.get("description"))
            collect.attach(ctx.pid, info["id"])
            added.append(info["id"])
            ctx.log(f"+ {info.get('title') or info['id']} ({info['id']})")
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            ctx.log(f"не удалось добавить «{it}»: {str(e)[:200]}")
        ctx.progress(i, len(items))
    ctx.log(f"добавлено каналов: {len(added)}. Нажмите «Обновить ленту», чтобы загрузить видео.")


# ---------------------------------------------------------------- subtitles / comments / probe
@register("subs", "Скачать субтитры")
def job_subs(ctx: JobCtx) -> None:
    s = db.get_settings()
    ids = _target_ids(ctx, int(ctx.params.get("n", 60)), "subs_state")
    asr_fn = None
    if any(p["name"] == "whisper" and p.get("on") for p in s["providers"]["subs"]) and s["asr"].get("model"):
        tmp = Path(tempfile.mkdtemp(prefix="yng-asr-", dir=config.cache_dir()))

        def asr_fn(vid):
            audio = ytdlp.download_audio(vid, tmp, int(s["asr"].get("max_minutes", 30)))
            try:
                return engines.transcribe(audio)
            finally:
                audio.unlink(missing_ok=True)
    ctx.progress(0, len(ids), "субтитры")
    ok = 0
    for i, vid in enumerate(ids, 1):
        ctx.check()
        if collect.fetch_subs(vid, log=ctx.log, stop=ctx.stopped, asr=asr_fn):
            ok += 1
        ctx.progress(i, len(ids), f"субтитры {i}/{len(ids)}, получено {ok}")
    ctx.log(f"готово: субтитры получены для {ok} из {len(ids)}")


@register("comments", "Загрузить комментарии")
def job_comments(ctx: JobCtx) -> None:
    ids = _target_ids(ctx, int(ctx.params.get("n", 60)), "comments_state")
    ctx.progress(0, len(ids), "комментарии")
    ok = 0
    for i, vid in enumerate(ids, 1):
        ctx.check()
        if collect.fetch_comments(vid, log=ctx.log, stop=ctx.stopped):
            ok += 1
        ctx.progress(i, len(ids), f"комментарии {i}/{len(ids)}, получено {ok}")
    ctx.log(f"готово: комментарии для {ok} из {len(ids)}")


@register("probe", "Проверить доступные источники для 18+")
def job_probe(ctx: JobCtx) -> None:
    if ctx.params.get("video_ids"):
        ids = ctx.params["video_ids"]
    else:
        chans = [c["id"] for c in _profile_channels(ctx.pid)]
        ids = [r["id"] for r in db.q(f"""SELECT id FROM videos WHERE age_restricted=1 AND channel_id IN ({','.join('?' * len(chans))})
                                       ORDER BY published_at DESC LIMIT ?""", (*chans, int(ctx.params.get("n", 10))))] if chans else []
    if not ids:
        ctx.log("18+ видео в профиле не найдено (сначала «Обновить ленту»)")
    summary: Counter = Counter()
    ctx.progress(0, len(ids))
    for i, vid in enumerate(ids, 1):
        ctx.check()
        collect.ensure_video(vid, log=ctx.log, stop=ctx.stopped)
        res = collect.probe(vid, log=ctx.log, stop=ctx.stopped)
        for srow in res["sources"]:
            summary[(srow["source"], srow["kind"], srow["ok"])] += 1
        ctx.progress(i, len(ids))
    if summary:
        ctx.log("итого (источник / тип: успехов–неудач):")
        keys = sorted({(a, b) for a, b, _ in summary})
        for a, b in keys:
            ctx.log(f"  {a} / {b}: {summary[(a, b, True)]}–{summary[(a, b, False)]}")


# ---------------------------------------------------------------- vision
@register("vision", "Проанализировать эскизы (vision)")
def job_vision(ctx: JobCtx) -> None:
    cfg = db.get_settings()["vision"]
    if not cfg.get("model"):
        ctx.log("vision-модель не выбрана (Модели → Vision)")
        return
    ids = _target_ids(ctx, int(ctx.params.get("n", cfg.get("top_n", 60))), "thumb_state")
    ctx.progress(0, len(ids))
    for i, vid in enumerate(ids, 1):
        ctx.check()
        try:
            img = thumb_bytes(vid)
            desc = engines.describe_image(img, cfg)
            db.ex("UPDATE videos SET thumb_desc=?, thumb_state=1 WHERE id=?", (desc[:600], vid))
            collect.refresh_evidence(vid)
            ctx.log(f"{vid}: {desc[:120]}")
        except InterruptedError:
            raise
        except engines.EngineError as e:
            ctx.log(f"{vid}: {e}")
            if "не выбрана" in str(e) or "не локальный" in str(e):
                return
            db.ex("UPDATE videos SET thumb_state=-2 WHERE id=?", (vid,))
        except Exception as e:  # noqa: BLE001
            ctx.log(f"{vid}: {e}")
            db.ex("UPDATE videos SET thumb_state=-2 WHERE id=?", (vid,))
        ctx.progress(i, len(ids))


def thumb_path(vid: str) -> Path:
    d = config.cache_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{vid}.jpg"


def thumb_bytes(vid: str) -> bytes:
    p = thumb_path(vid)
    if p.exists():
        return p.read_bytes()
    r = net.get(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", purpose="thumb")
    if r.status_code != 200:
        raise RuntimeError(f"thumbnail HTTP {r.status_code}")
    p.write_bytes(r.content)
    return r.content


# ---------------------------------------------------------------- embeddings
@register("embed", "Посчитать эмбеддинги")
def job_embed(ctx: JobCtx) -> None:
    cfg = db.get_settings()["embed"]
    model = cfg.get("model")
    if not model:
        ctx.log("эмбеддинг-модель не выбрана (Модели → Эмбеддинги → «Использовать»)")
        return
    rows = db.q("SELECT id, title, tags, chapters, description FROM videos WHERE embedding_model IS NOT ? OR embedding IS NULL",
                (model,))
    ctx.progress(0, len(rows), f"эмбеддинги ({model})")
    bs = max(1, int(cfg.get("batch", 16)))
    t0 = time.time()
    done = 0
    for k in range(0, len(rows), bs):
        ctx.check()
        chunk = rows[k:k + bs]
        texts = [ranking.TextIndex.meta_text(r)[:2000] for r in chunk]
        vecs = engines.embed(texts, cfg)
        db.exmany("UPDATE videos SET embedding=?, embedding_model=? WHERE id=?",
                  [(np.asarray(v, dtype=np.float32).tobytes(), model, r["id"]) for v, r in zip(vecs, chunk)])
        done += len(chunk)
        ctx.progress(done, len(rows), f"{done}/{len(rows)}, {done / max(0.01, time.time() - t0):.1f} видео/с")
    ctx.log(f"готово: {done} видео")


# ---------------------------------------------------------------- LLM
def llm_schema(questions: list[dict]) -> dict:
    return {"type": "object", "properties": {
        "scores": {"type": "object", "properties": {q["key"]: {"type": "integer", "minimum": 0, "maximum": 10} for q in questions},
                   "required": [q["key"] for q in questions]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "summary": {"type": "string"}}, "required": ["scores", "confidence", "summary"]}


def llm_user_prompt(v: dict, questions: list[dict], channel_title: str | None) -> str:
    def field(name, val, limit):
        val = (val or "").strip()
        return f"### {name}\n{val[:limit]}" if val else f"### {name}\nНЕДОСТУПНО"
    tags = ", ".join(db.jloads(v["tags"], []) or [])
    parts = [
        f"Канал: {channel_title or v['channel_id']}",
        f"Язык: {v['lang'] or 'неизвестен'}; длительность: {ranking.fmt_duration(v['duration']) or 'неизвестна'}; "
        f"18+: {'да' if v['age_restricted'] else 'нет'}",
        field("Название", v["title"], 300), field("Теги", tags, 500), field("Описание", v["description"], 2500),
        field("Комментарии зрителей (топ)", v["comments_text"], 2500), field("Субтитры (фрагмент)", v["subtitles_text"], 5000),
        field("Описание превью (vision)", v["thumb_desc"], 500),
        "Вопросы (ключ: вопрос):\n" + "\n".join(f"- {q['key']}: {q['text']}" for q in questions),
        'Ответ: {"scores": {ключ: 0..10}, "confidence": 0..1, "summary": "1 предложение по-русски"}',
    ]
    return "\n\n".join(parts)


@register("llm", "Запустить LLM-анализ")
def job_llm(ctx: JobCtx) -> None:
    s = db.get_settings()
    cfg = s["llm"]
    ps = profiles.settings(ctx.pid)
    qs = ps.get("llm_questions") or []
    if not qs:
        ctx.log("нет вопросов для LLM (Правила → LLM-вопросы)")
        return
    st = engines.llm_status()
    if not st["ok"]:
        ctx.log(f"LLM недоступна: движок {st['engine']}, модель {st['model']}. Проверьте страницу «Модели».")
        return
    qh = ranking.questions_hash(qs)
    n = int(ctx.params.get("n", cfg.get("top_n", 40)))
    cand = ctx.params.get("video_ids") or ranking.top_ids(ctx.pid, n * 2)
    done_ids = {r["video_id"] for r in db.q("SELECT video_id FROM video_scores WHERE profile_id=? AND llm_qhash=?", (ctx.pid, qh))}
    ids = [v for v in cand if v not in done_ids][:n]
    ctx.progress(0, len(ids), f"LLM {st['model']}")
    schema = llm_schema(qs)
    for i, vid in enumerate(ids, 1):
        ctx.check()
        v = db.q1("SELECT * FROM videos WHERE id=?", (vid,))
        ch = db.q1("SELECT title FROM channels WHERE id=?", (v["channel_id"],))
        t0 = time.time()
        try:
            res = engines.chat_json(ps.get("llm_prompt") or config.DEFAULT_LLM_PROMPT,
                                    llm_user_prompt(dict(v), qs, ch["title"] if ch else None), schema, cfg)
            scores = {q["key"]: float(np.clip(float((res.get("scores") or {}).get(q["key"], 0)), 0, 10)) for q in qs}
            out = {"scores": scores, "confidence": res.get("confidence"), "summary": str(res.get("summary", ""))[:300]}
            db.ex("""INSERT INTO video_scores(profile_id, video_id, llm_scores, llm_model, llm_qhash, updated_at) VALUES(?,?,?,?,?,?)
                     ON CONFLICT(profile_id, video_id) DO UPDATE SET llm_scores=excluded.llm_scores, llm_model=excluded.llm_model,
                     llm_qhash=excluded.llm_qhash, updated_at=excluded.updated_at""",
                  (ctx.pid, vid, db.jdumps(out), st["model"], qh, time.time()))
            ctx.log(f"{vid} ({time.time() - t0:.1f} с): {scores} — {out['summary'][:100]}")
        except engines.EngineError as e:
            ctx.log(f"{vid}: {e}")
        except (ValueError, TypeError) as e:
            ctx.log(f"{vid}: плохой ответ модели: {e}")
        ctx.progress(i, len(ids))


# ---------------------------------------------------------------- ranking
@register("rank", "Пересчитать ранг")
def job_rank(ctx: JobCtx) -> None:
    ctx.progress(0, 1, "TF-IDF / эмбеддинги")
    ranking.INDEX.sig = None  # force rebuild
    n = ranking.persist(ctx.pid)
    ctx.progress(1, 1)
    ctx.log(f"готово: оценено {n} видео")


# ---------------------------------------------------------------- discovery
@register("discover", "Искать новые каналы")
def job_discover(ctx: JobCtx) -> None:
    pid = ctx.pid
    known = {r["channel_id"] for r in db.q("SELECT channel_id FROM profile_channels WHERE profile_id=?", (pid,))}
    known |= {r["channel_id"] for r in db.q("SELECT channel_id FROM candidates WHERE profile_id=?", (pid,))}
    found: dict[str, dict] = {}
    chans = _profile_channels(pid)
    use_search = ctx.params.get("search", False)
    use_llm = ctx.params.get("llm", False)
    ctx.progress(0, len(chans), "рекомендованные каналы")
    for i, ch in enumerate(chans[: int(ctx.params.get("max_channels", 30))], 1):
        ctx.check()
        try:
            for c in watchpage.featured_channels(ch["id"], stop=ctx.stopped):
                if c["id"] not in known and c["id"] not in found:
                    found[c["id"]] = {"title": c["title"], "source": "featured", "reason": f"рекомендован каналом «{ch['title']}»"}
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            ctx.log(f"{ch['title']}: {str(e)[:150]}")
        ctx.progress(i, len(chans))
    queries: list[str] = []
    if use_search:
        queries += _topic_queries(pid, int(ctx.params.get("queries", 3)))
    if use_llm:
        try:
            queries += _llm_queries(pid)
        except engines.EngineError as e:
            ctx.log(f"LLM-подсказки недоступны: {e}")
    for q in queries:
        ctx.check()
        ctx.log(f"поиск: «{q}»")
        try:
            for r in ytdlp.search(q, 10):
                cid = r.get("channel_id")
                if cid and cid not in known and cid not in found:
                    found[cid] = {"title": r.get("channel"), "source": "search", "reason": f"поиск «{q}»"}
        except Exception as e:  # noqa: BLE001
            ctx.log(f"поиск не удался: {str(e)[:150]}")
    ctx.log(f"кандидатов: {len(found)}; загружаю последние видео для оценки")
    items = list(found.items())[: int(ctx.params.get("max_candidates", 25))]
    ctx.progress(0, len(items), "оценка кандидатов")
    breaker: dict = {}
    for i, (cid, meta) in enumerate(items, 1):
        ctx.check()
        try:
            collect.upsert_channel(cid, meta.get("title"))
            d = collect.list_channel(cid, 6, log=ctx.log, stop=ctx.stopped, breaker=breaker)
            collect.upsert_listing(d["entries"], cid)
            if d.get("channel_title"):
                db.ex("UPDATE channels SET title=COALESCE(title, ?) WHERE id=?", (d["channel_title"], cid))
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            ctx.log(f"{meta.get('title') or cid}: {str(e)[:150]}")
        db.ex("""INSERT INTO candidates(profile_id, channel_id, title, source, reason, status, found_at) VALUES(?,?,?,?,?,'new',?)
                 ON CONFLICT(profile_id, channel_id) DO NOTHING""", (pid, cid, meta.get("title"), meta["source"], meta["reason"], time.time()))
        ctx.progress(i, len(items))
    score_candidates(pid)
    ctx.log("готово: см. Каналы → Кандидаты")


def score_candidates(pid: str) -> None:
    """Rank candidates the same way as the feed: by the scores of their recent videos."""
    res = ranking.compute(pid, include_all=True)
    by_ch: dict[str, list[float]] = {}
    for it in res["items"]:
        by_ch.setdefault(it["v"]["channel_id"], []).append(it["score"])
    for r in db.q("SELECT channel_id FROM candidates WHERE profile_id=? AND status='new'", (pid,)):
        sc = sorted(by_ch.get(r["channel_id"], []), reverse=True)[:3]
        db.ex("UPDATE candidates SET score=? WHERE profile_id=? AND channel_id=?",
              (float(np.mean(sc)) if sc else None, pid, r["channel_id"]))


def _topic_queries(pid: str, n: int) -> list[str]:
    rows = db.q("""SELECT v.title, v.tags FROM feedback f JOIN videos v ON v.id=f.video_id
                   WHERE f.profile_id=? AND f.kind IN ('like','more')""", (pid,))
    cnt: Counter = Counter()
    stop = {"и", "в", "на", "с", "the", "a", "of", "to", "in", "and", "как", "что", "это", "for", "how", "i", "my", "не", "по"}
    for r in rows:
        for t in (db.jloads(r["tags"], []) or [])[:10]:
            if len(t) > 3:
                cnt[t.lower()] += 2
        for t in text.tokens(r["title"]):
            if len(t) > 3 and t not in stop:
                cnt[t] += 1
    return [w for w, _ in cnt.most_common(n)]


def _llm_queries(pid: str) -> list[str]:
    rows = db.q("""SELECT v.title FROM feedback f JOIN videos v ON v.id=f.video_id
                   WHERE f.profile_id=? AND f.kind IN ('like','more') ORDER BY f.id DESC LIMIT 30""", (pid,))
    if not rows:
        return []
    schema = {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}}, "required": ["queries"]}
    j = engines.chat_json("Ты подбираешь поисковые запросы для YouTube. Отвечай JSON.",
                          "Пользователю понравились видео:\n" + "\n".join(f"- {r['title']}" for r in rows) +
                          "\nПредложи 5 коротких поисковых запросов (на языке видео), чтобы найти похожие каналы.", schema)
    return [str(q)[:80] for q in (j.get("queries") or [])][:5]


# ---------------------------------------------------------------- models
def _run_proc(ctx: JobCtx, cmd: list[str], env: dict | None = None, watch_dir: Path | None = None,
              expect_gb: float = 0) -> int:
    ctx.log("$ " + " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=str(config.ROOT))
    import threading
    lines: list[str] = []

    def reader():
        for ln in p.stdout:
            lines.append(ln.rstrip())
            ctx.log(ln.rstrip()[-300:])
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    while p.poll() is None:
        if ctx.stopped():
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
            raise InterruptedError
        if watch_dir is not None and expect_gb:
            size = sum(f.stat().st_size for f in watch_dir.rglob("*") if f.is_file()) if watch_dir.exists() else 0
            ctx.progress(int(size / 1e6), int(expect_gb * 1e3), f"{size / 1e9:.2f} / ≈{expect_gb:.2f} ГБ")
        time.sleep(1)
    th.join(5)
    return p.returncode


def _dl_env() -> dict:
    env = dict(os.environ)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env.pop("HF_HUB_OFFLINE", None)
    if net.proxy():
        env["HTTPS_PROXY"] = env["HTTP_PROXY"] = env["ALL_PROXY"] = net.proxy()
    return env


@register("model_download", "Скачать модель")
def job_model_download(ctx: JobCtx) -> None:
    m = ctx.params.get("model") or catalog.by_id(ctx.params.get("id", ""))
    if not m:
        raise ValueError("модель не найдена")
    eng = m["engine"]
    ctx.log(f"скачивание {m['name']} ({m['ref']}), ≈{m.get('disk_gb', '?')} ГБ на диске")
    if eng in ("st", "whisper"):
        dest = engines.hf_dir(m["ref"])
        rc = _run_proc(ctx, [sys.executable, "-m", "app.ml.dl", "snapshot", m["ref"], str(dest)], _dl_env(), dest,
                       float(m.get("disk_gb") or 0))
        if rc != 0:
            raise RuntimeError(f"загрузка не удалась (код {rc})")
    elif eng == "gguf":
        fn = ctx.params.get("file")
        if not fn:
            raise ValueError("не выбран GGUF-файл")
        dest = engines.gguf_dir() / m["ref"].replace("/", "--")
        rc = _run_proc(ctx, [sys.executable, "-m", "app.ml.dl", "file", m["ref"], fn, str(dest)], _dl_env(), dest,
                       float(ctx.params.get("size_gb") or m.get("disk_gb") or 0))
        if rc != 0:
            raise RuntimeError(f"загрузка не удалась (код {rc})")
    elif eng == "ollama":
        url = db.get_settings()["llm"]["url"].rstrip("/")
        if not engines.ollama_alive(url):
            raise RuntimeError(f"Ollama не отвечает на {url}. Запустите `ollama serve`.")
        c, stream = engines._local_post(url + "/api/pull", {"model": m["ref"], "stream": True}, timeout=3600, stream=True)
        try:
            with stream as r:
                for ln in r.iter_lines():
                    if ctx.stopped():
                        raise InterruptedError
                    if not ln:
                        continue
                    j = json.loads(ln)
                    if j.get("error"):
                        raise RuntimeError(j["error"])
                    if j.get("total"):
                        ctx.progress(int(j.get("completed", 0) / 1e6), int(j["total"] / 1e6),
                                     f"{j.get('status', '')} {j.get('completed', 0) / 1e9:.2f}/{j['total'] / 1e9:.2f} ГБ")
                    elif j.get("status"):
                        ctx.log(j["status"])
        finally:
            c.close()
    ctx.log("готово")


@register("model_test", "Проверить модель на карточке")
def job_model_test(ctx: JobCtx) -> None:
    m = ctx.params.get("model") or catalog.by_id(ctx.params.get("id", ""))
    kind, eng = m["kind"], m["engine"]
    before = hw.gpu_info(force=True)
    ctx.log(f"GPU: {before['name'] or 'нет'}; свободно VRAM {before['free_gb']} ГБ")
    t0 = time.time()
    if kind == "embed":
        cfg = dict(db.get_settings()["embed"], model=m["ref"], engine=eng)
        v = engines.embed(["Тестовое предложение про котиков.", "A test sentence about cats."], cfg)
        sim = float(np.dot(v[0], v[1]) / (np.linalg.norm(v[0]) * np.linalg.norm(v[1])))
        ctx.log(f"эмбеддинги OK: размерность {len(v[0])}, сходство ru/en {sim:.2f}, {time.time() - t0:.1f} с")
    elif kind in ("llm", "vision"):
        cfg = dict(db.get_settings()["llm" if kind == "llm" else "vision"], model=m["ref"], engine="ollama" if eng == "ollama" else
                   db.get_settings()["llm"]["engine"])
        if kind == "llm":
            j = engines.chat_json("Отвечай JSON.", 'Оцени от 0 до 10, насколько смешна фраза «кот упал в торт». {"score": n}',
                                  {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}, cfg)
        else:
            from PIL import Image
            import io
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "JPEG")
            j = {"description": engines.describe_image(buf.getvalue(), cfg)}
        ctx.log(f"ответ: {j}; {time.time() - t0:.1f} с")
    elif kind == "asr":
        import wave
        tmp = config.cache_dir() / "asr-test.wav"
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 16000)
        cfg = dict(db.get_settings()["asr"], model=m["ref"])
        txt, lang = engines.transcribe(tmp, cfg)
        ctx.log(f"ASR OK ({time.time() - t0:.1f} с), язык {lang}, текст «{txt}»")
    after = hw.gpu_info(force=True)
    if before["gpu"]:
        ctx.log(f"VRAM занято моделью ≈ {max(0.0, before['free_gb'] - after['free_gb']):.2f} ГБ")


EXTRAS = {"embed": ("sentence_transformers", "движок эмбеддингов (sentence-transformers + PyTorch, ~2–3 ГБ)"),
          "asr": ("faster_whisper", "движок ASR (faster-whisper)")}


def installed_extras() -> list[str]:
    f = config.data_dir() / "extras.txt"
    return [x for x in f.read_text().split() if x in EXTRAS] if f.exists() else []


@register("install_extra", "Установить пакеты")
def job_install_extra(ctx: JobCtx) -> None:
    extra = ctx.params["extra"]
    if extra not in EXTRAS:
        raise ValueError(extra)
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv не найден в PATH")
    want = sorted(set(installed_extras() + [extra]))
    cmd = [uv, "sync", "--frozen"] + sum((["--extra", e] for e in want), [])
    env = dict(os.environ)
    if net.proxy():
        env["HTTPS_PROXY"] = env["HTTP_PROXY"] = env["ALL_PROXY"] = net.proxy()
    rc = _run_proc(ctx, cmd, env)
    if rc != 0:
        raise RuntimeError(f"uv sync завершился с кодом {rc}")
    (config.data_dir() / "extras.txt").write_text(" ".join(want))
    ctx.log("готово. Перезапустите приложение (./start), чтобы пакеты подхватились.")
