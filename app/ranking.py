"""Feed ranking. Everything is computed inside one profile.

score = Σ W_c·x_c / Σ W_c over *available* components c (renormalization), where missing data
is first filled from the channel prior (mean of that component over the channel's videos that
have it). Then incomplete-data trust blends towards the channel mean. See SPEC §4.2 and §6.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
from collections import defaultdict

import numpy as np

from . import db, profiles, text

FB_WEIGHTS = {"like": 1.0, "more": 2.0, "dislike": -1.0, "hide": -1.0, "opened": 0.25}
EXPLICIT = ("like", "more", "dislike", "hide")
EVIDENCE_W = {"meta": 0.3, "comments": 0.2, "subtitles": 0.3, "thumbnail": 0.1, "channel_prior": 0.1}
_VIDEO_COLS = """id, channel_id, title, description, tags, lang, duration, published_at, views, age_restricted,
    live_status, is_short, subtitles_text, comments_text, thumb_desc, chapters, evidence, meta_state, subs_state,
    comments_state, embedding_model"""


def questions_hash(questions: list[dict]) -> str:
    return hashlib.sha1(db.jdumps([(q["key"], q["text"]) for q in questions]).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- text index (shared by all profiles)
class TextIndex:
    def __init__(self):
        self.sig = None
        self.lock = threading.Lock()
        self.idx: dict[str, int] = {}
        self.meta = None
        self.extra = None
        self.extra_ok = None
        self.emb_sig = None
        self.emb: dict[str, np.ndarray] = {}

    @staticmethod
    def meta_text(r) -> str:
        tags = " ".join(db.jloads(r["tags"], []) or [])
        chapters = " ".join(db.jloads(r["chapters"], []) or [])
        title = r["title"] or ""
        return f"{title}. {title}. {tags}. {chapters}. {(r['description'] or '')[:1500]}"

    @staticmethod
    def extra_text(r) -> str:
        return " ".join(x for x in ((r["comments_text"] or "")[:3000], (r["subtitles_text"] or "")[:6000],
                                    r["thumb_desc"] or "") if x)

    def ensure(self) -> None:
        sig = tuple(db.q1("""SELECT count(*), total(length(coalesce(title,''))+length(coalesce(description,''))
                 +length(coalesce(comments_text,''))+length(coalesce(subtitles_text,''))+length(coalesce(thumb_desc,'')))
                 FROM videos""") or (0, 0))
        with self.lock:
            if sig != self.sig:
                self._build()
                self.sig = sig
            self._ensure_emb()

    def _build(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        rows = db.q("SELECT id, title, tags, chapters, description, comments_text, subtitles_text, thumb_desc FROM videos")
        self.idx = {r["id"]: i for i, r in enumerate(rows)}
        if not rows:
            self.meta = self.extra = None
            return
        n = len(rows)

        def vec():
            # char n-grams within words: robust to Russian morphology and works the same for English
            return TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2 if n > 50 else 1,
                                   max_features=60000, sublinear_tf=True, lowercase=True)
        meta_docs = [self.meta_text(r) for r in rows]
        try:
            self.meta = vec().fit_transform(meta_docs).tocsr()
        except ValueError:
            self.meta = None
        extra_docs = [self.extra_text(r) for r in rows]
        self.extra_ok = np.array([bool(d.strip()) for d in extra_docs])
        try:
            self.extra = vec().fit_transform(extra_docs).tocsr() if self.extra_ok.any() else None
        except ValueError:
            self.extra = None

    def _ensure_emb(self) -> None:
        model = (db.get_settings().get("embed") or {}).get("model") or ""
        if not model:
            self.emb, self.emb_sig = {}, None
            return
        sig = (model, tuple(db.q1("SELECT count(*), max(rowid) FROM videos WHERE embedding_model=?", (model,))))
        if sig == self.emb_sig:
            return
        self.emb = {}
        for r in db.q("SELECT id, embedding FROM videos WHERE embedding_model=? AND embedding IS NOT NULL", (model,)):
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            nv = np.linalg.norm(v)
            if nv > 0:
                self.emb[r["id"]] = v / nv
        self.emb_sig = sig


INDEX = TextIndex()


def _rows_of(mat, ids):
    rows = [INDEX.idx[i] for i in ids]
    return mat[rows]


def _centroid(mat, ids_w: list[tuple[str, float]]):
    ids = [i for i, _ in ids_w if i in INDEX.idx]
    if not ids or mat is None:
        return None
    w = np.array([abs(wt) for i, wt in ids_w if i in INDEX.idx], dtype=np.float64)
    sub = _rows_of(mat, ids)
    c = np.asarray(sub.multiply(w[:, None]).sum(axis=0) / w.sum()).ravel()
    nc = np.linalg.norm(c)
    return c / nc if nc > 0 else None


def _standardize(raw: dict[str, float]) -> dict[str, float]:
    if not raw:
        return {}
    vals = np.array(list(raw.values()))
    med = float(np.median(vals))
    sd = float(vals.std()) or 1.0
    return {k: float(np.clip((v - med) / sd, -2.5, 2.5) / 2.5) for k, v in raw.items()}


# ---------------------------------------------------------------- core
class Ctx:
    """Everything profile-specific needed to score videos."""

    def __init__(self, pid: str):
        self.pid = pid
        self.s = profiles.settings(pid)
        self.rules = profiles.rules(pid)
        pcs = db.q("SELECT * FROM profile_channels WHERE profile_id=?", (pid,))
        self.pc = {r["channel_id"]: dict(r) for r in pcs}
        self.active = {c for c, r in self.pc.items() if not r["paused"] and not r["hidden"]}
        self.hidden = {c for c, r in self.pc.items() if r["hidden"]}
        fb = db.q("SELECT video_id, kind FROM feedback WHERE profile_id=? ORDER BY id", (pid,))
        self.fb: dict[str, float] = defaultdict(float)
        self.fb_kinds: dict[str, set] = defaultdict(set)
        for r in fb:
            self.fb[r["video_id"]] += FB_WEIGHTS.get(r["kind"], 0)
            self.fb_kinds[r["video_id"]].add(r["kind"])
        self.fb = {k: float(np.clip(v, -2, 2)) for k, v in self.fb.items() if v != 0}
        self.n_rated = sum(1 for k in self.fb_kinds.values() if k & set(EXPLICIT))
        qs = self.s.get("llm_questions") or []
        self.qhash = questions_hash(qs)
        self.llm = {}
        for r in db.q("SELECT video_id, llm_scores, llm_qhash FROM video_scores WHERE profile_id=? AND llm_scores IS NOT NULL", (pid,)):
            if r["llm_qhash"] == self.qhash:
                self.llm[r["video_id"]] = db.jloads(r["llm_scores"], {})


def _video_rows(where: str, args: tuple) -> list[dict]:
    return [dict(r) for r in db.q(f"SELECT {_VIDEO_COLS} FROM videos WHERE {where}", args)]


def _passes_filters(v: dict, s: dict, now: float, stop_patterns: list[str]) -> bool:
    if v["is_short"] or v["live_status"] in ("is_upcoming", "is_live", "upcoming", "live"):
        return False
    if v["duration"] is not None and v["duration"] < int(s["min_duration_sec"]):
        return False
    if v["published_at"] and (now - v["published_at"]) > int(s["max_age_days"]) * 86400:
        return False
    ar = s.get("show_18", "yes")
    if ar == "no" and v["age_restricted"]:
        return False
    if ar == "only" and not v["age_restricted"]:
        return False
    lf = s.get("lang_filter", "all")
    if lf in ("ru", "en") and v["lang"] and v["lang"] != lf:
        return False
    if lf == "sel" and v["lang"] and v["lang"] not in (s.get("lang_selected") or []):
        return False
    if stop_patterns:
        tl = (v["title"] or "").lower() + " " + " ".join(db.jloads(v["tags"], []) or []).lower()
        toks = set(text.tokens(tl))
        if any(text.phrase_in(tl, toks, p) for p in stop_patterns):
            return False
    return True


def compute(pid: str, similar_to: str | None = None, limit: int | None = None, include_all: bool = False) -> dict:
    """Return {'items': [...], 'stats': {...}}. Pure function of the DB (cached by caller)."""
    t0 = time.time()
    ctx = Ctx(pid)
    s = ctx.s
    now = time.time()
    INDEX.ensure()
    feed_size = int(limit or s.get("feed_size", 60))

    stop_patterns = [r["pattern"] for r in ctx.rules if r["kind"] == "stopword"]
    seen_explicit = {vid for vid, k in ctx.fb_kinds.items() if k & set(EXPLICIT)}

    in_profile = _video_rows(f"channel_id IN ({','.join('?' * len(ctx.active))})", tuple(ctx.active)) if ctx.active else []
    in_profile = [v for v in in_profile if _passes_filters(v, s, now, stop_patterns)]
    others = []
    if s.get("exploration", 0) > 0 and not similar_to:
        excl = ctx.active | ctx.hidden
        others = _video_rows("1=1", ())
        others = [v for v in others if v["channel_id"] not in excl and _passes_filters(v, s, now, stop_patterns)]
    rated_rows = {v["id"]: v for v in _video_rows(f"id IN ({','.join('?' * len(ctx.fb))})", tuple(ctx.fb))} if ctx.fb else {}

    cands = [v for v in in_profile if v["id"] not in seen_explicit]
    explore = [v for v in others if v["id"] not in seen_explicit]
    pool = cands + explore
    if not pool:
        return {"items": [], "stats": {"candidates": 0, "n_rated": ctx.n_rated, "ms": int((time.time() - t0) * 1000),
                                       "taste_mode": "—"}}

    taste, taste_mode = _taste(ctx, pool, rated_rows, similar_to)
    ch_prior = _channel_prior(ctx, rated_rows)
    prof = _profanity(ctx, pool)
    llm = _llm(ctx, pool)
    ramp = 1.0 if similar_to else min(1.0, ctx.n_rated / max(1, int(s.get("taste_min_ratings", 30))))
    W = dict(s["weights"])
    half = max(0.5, float(s.get("fresh_half_life_days", 14)))
    trust = float(s.get("incomplete_trust", 0.7))
    langw = s.get("lang_weights") or {}

    scored = []
    for v in pool:
        vid, ch = v["id"], v["channel_id"]
        comp: dict[str, float] = {}
        notes: list[str] = []
        pc = ctx.pc.get(ch, {})
        comp["channel"] = float(np.clip((pc.get("weight") or 0) / 2.0 + ch_prior.get(ch, 0.0), -1, 1))
        if vid in taste:
            comp["taste"] = taste[vid]
        rules_x = _topics(ctx, v)
        p_val, p_src = prof.get(vid, (None, None))
        if p_val is not None:
            rules_x += float(s.get("profanity_weight", 0)) * p_val
            if p_src != "own":
                notes.append(f"мат: {p_src}")
        comp["rules"] = float(np.clip(rules_x, -1, 1))
        if v["published_at"]:
            age_d = max(0.0, (now - v["published_at"]) / 86400)
            comp["fresh"] = 2 ** (-age_d / half)
        l_val, l_src = llm.get(vid, (None, None))
        if l_val is not None:
            comp["llm"] = l_val
            if l_src != "own":
                notes.append(f"LLM: {l_src}")
        if v["lang"] in langw:
            comp["lang"] = float(langw.get(v["lang"], 0))
        weights = {c: float(W.get(c, 0)) * (ramp if c == "taste" else 1.0) for c in comp}
        tot = sum(abs(w) for w in weights.values())
        score = sum(weights[c] * comp[c] for c in comp) / tot if tot > 0 else 0.0
        ev = db.jloads(v["evidence"], {}) or {}
        ev = dict(ev, channel_prior=ch in ch_prior)
        conf = sum(EVIDENCE_W[k] for k, ok in ev.items() if ok and k in EVIDENCE_W)
        mat = (p_src == "own" and p_val > 0.15) or has_mat_title(v, ctx.rules)
        scored.append({"v": v, "mat": mat, "comp": comp, "weights": weights, "tot": tot, "raw": score, "conf": round(conf, 2),
                       "ev": ev, "notes": notes, "explore": v["channel_id"] not in ctx.active})

    # trust blending towards the channel mean (no systematic penalty for incomplete videos)
    ch_mean: dict[str, list[float]] = defaultdict(list)
    for it in scored:
        ch_mean[it["v"]["channel_id"]].append(it["raw"])
    ch_mean_v = {c: float(np.mean(xs)) for c, xs in ch_mean.items()}
    for it in scored:
        c = it["conf"]
        a = trust + (1 - trust) * c
        it["score"] = a * it["raw"] + (1 - a) * ch_mean_v[it["v"]["channel_id"]]
        if c < 0.6:
            it["notes"].append("оценка по неполным данным")

    main = sorted([it for it in scored if not it["explore"]], key=lambda x: -x["score"])
    exp_pool = sorted([it for it in scored if it["explore"]], key=lambda x: -x["score"])
    if include_all:
        items = main + exp_pool
    else:
        items = _mix_exploration(ctx, main, exp_pool, feed_size, similar_to)
    for rank, it in enumerate(items, 1):
        it["rank"] = rank
        it["why"] = _why(it)
    stats = {"candidates": len(cands), "explore_pool": len(explore), "n_rated": ctx.n_rated, "taste_mode": taste_mode,
             "taste_ramp": round(ramp, 2), "ms": int((time.time() - t0) * 1000)}
    return {"items": items, "stats": stats}


def _mix_exploration(ctx: Ctx, main: list, exp_pool: list, n: int, similar_to) -> list:
    pct = 0 if similar_to else float(ctx.s.get("exploration", 15))
    n_exp = int(round(n * pct / 100.0))
    rng = random.Random(f"{ctx.pid}:{db.version() // 50}:{time.strftime('%Y%m%d')}")
    picked = []
    if n_exp:
        top = exp_pool[: max(n_exp * 3, n_exp)]
        picked = rng.sample(top, min(n_exp, len(top)))
        if len(picked) < n_exp:  # not enough outside channels: take from the tail of the profile
            tail = main[n:]
            extra = rng.sample(tail, min(n_exp - len(picked), len(tail)))
            for it in extra:
                it["explore"] = True
            picked += extra
    for it in picked:
        it["notes"].append("исследование")
    head = [it for it in main if it not in picked][: max(0, n - len(picked))]
    if not picked:
        return head
    out, step = list(head), max(2, len(head) // (len(picked) + 1) or 2)
    for i, it in enumerate(picked):
        out.insert(min(len(out), (i + 1) * step), it)
    return out[:n]


def _why(it: dict) -> list[dict]:
    names = {"taste": "вкус", "channel": "канал", "rules": "правила", "fresh": "свежесть", "llm": "LLM", "lang": "язык"}
    tot = it["tot"] or 1.0
    out = [{"name": names.get(c, c), "value": round(x, 2), "contrib": round(it["weights"][c] * x / tot, 3)}
           for c, x in it["comp"].items()]
    return sorted(out, key=lambda d: -abs(d["contrib"]))


# ---------------------------------------------------------------- components
def _taste(ctx: Ctx, pool: list[dict], rated: dict, similar_to: str | None) -> tuple[dict[str, float], str]:
    if similar_to:
        pos = [(similar_to, 1.0)]
        neg = []
    else:
        pos = [(vid, w) for vid, w in ctx.fb.items() if w > 0]
        neg = [(vid, w) for vid, w in ctx.fb.items() if w < 0]
    if not pos and not neg:
        return {}, "нет оценок"
    groups: list[tuple[str, float, dict[str, float]]] = []
    pool_ids = [v["id"] for v in pool if v["id"] in INDEX.idx]

    # embeddings (if a model is configured and vectors exist)
    if INDEX.emb:
        ep = [(i, w) for i, w in pos if i in INDEX.emb]
        en = [(i, w) for i, w in neg if i in INDEX.emb]
        if ep or en:
            cp = _dense_centroid(ep)
            cn = _dense_centroid(en)
            raw = {}
            for vid in pool_ids:
                e = INDEX.emb.get(vid)
                if e is None:
                    continue
                raw[vid] = (float(e @ cp) if cp is not None else 0.0) - (float(e @ cn) if cn is not None else 0.0)
            groups.append(("emb", 1.0, _standardize(raw)))
    for name, mat, gw, ok in (("meta", INDEX.meta, 0.6 if INDEX.emb else 1.0, None), ("extra", INDEX.extra, 0.5, INDEX.extra_ok)):
        if mat is None:
            continue
        def has(i):
            return ok is None or bool(ok[INDEX.idx[i]])
        cp = _centroid(mat, [(i, w) for i, w in pos if i in INDEX.idx and has(i)])
        cn = _centroid(mat, [(i, w) for i, w in neg if i in INDEX.idx and has(i)])
        if cp is None and cn is None:
            continue
        ids = [i for i in pool_ids if has(i)]
        if not ids:
            continue
        sub = _rows_of(mat, ids)
        sp = sub @ cp if cp is not None else np.zeros(len(ids))
        sn = sub @ cn if cn is not None else np.zeros(len(ids))
        raw = {i: float(a - b) for i, a, b in zip(ids, np.asarray(sp).ravel(), np.asarray(sn).ravel())}
        groups.append((name, gw, _standardize(raw)))

    mode = "центроиды " + ("эмбеддингов" if INDEX.emb else "TF-IDF")
    lr = None if similar_to else _logreg(ctx, pos, neg)
    if lr is not None:
        groups.append(("logreg", 1.5, lr))
        mode = "логрегрессия + " + mode
    out: dict[str, float] = {}
    for vid in pool_ids:
        num = den = 0.0
        for _name, gw, vals in groups:
            if vid in vals:  # renormalize over the groups this video actually has
                num += gw * vals[vid]
                den += gw
        if den > 0:
            out[vid] = num / den
    return out, mode


def _dense_centroid(ids_w):
    if not ids_w:
        return None
    c = sum(abs(w) * INDEX.emb[i] for i, w in ids_w) / sum(abs(w) for _, w in ids_w)
    n = np.linalg.norm(c)
    return c / n if n > 0 else None


_LR_CACHE: dict = {}


def _logreg(ctx: Ctx, pos, neg) -> dict[str, float] | None:
    if INDEX.meta is None:
        return None
    if ctx.n_rated < int(ctx.s.get("logreg_min_ratings", 120)) or len(pos) < 10 or len(neg) < 10:
        return None
    key = (ctx.pid, tuple(sorted(ctx.fb.items())), INDEX.sig)
    if key in _LR_CACHE:
        return _LR_CACHE[key]
    from sklearn.linear_model import LogisticRegression
    ids = [i for i, _ in pos + neg if i in INDEX.idx]
    y = np.array([1 if ctx.fb[i] > 0 else 0 for i in ids])
    X = _rows_of(INDEX.meta, ids)
    clf = LogisticRegression(C=2.0, class_weight="balanced", max_iter=500)
    clf.fit(X, y)
    allp = clf.predict_proba(INDEX.meta)[:, 1]
    inv = {i: k for k, i in INDEX.idx.items()}
    res = {inv[i]: float(2 * p - 1) for i, p in enumerate(allp)}
    _LR_CACHE.clear()
    _LR_CACHE[key] = res
    return res


def _channel_prior(ctx: Ctx, rated: dict) -> dict[str, float]:
    """Mean feedback per channel inside this profile, shrunk towards 0."""
    agg: dict[str, list[float]] = defaultdict(list)
    for vid, w in ctx.fb.items():
        r = rated.get(vid)
        if r:
            agg[r["channel_id"]].append(w)
    return {c: float(np.clip(sum(ws) / (len(ws) + 3), -1, 1)) for c, ws in agg.items()}


def _topics(ctx: Ctx, v: dict) -> float:
    lang = v["lang"] or "*"
    tl = " ".join([(v["title"] or ""), " ".join(db.jloads(v["tags"], []) or []), (v["description"] or "")[:2000]]).lower()
    toks = set(text.tokens(tl))
    x = 0.0
    for r in ctx.rules:
        if r["kind"] not in ("topic", "stoptopic"):
            continue
        if r["lang"] not in ("*", lang):
            continue
        if text.phrase_in(tl, toks, r["pattern"]):
            x += float(r["weight"])
    return x


def profanity_patterns(ctx_rules: list[dict], lang: str | None) -> list[str]:
    return [r["pattern"] for r in ctx_rules if r["kind"] == "profanity" and r["lang"] in ("*", lang or "*")] or \
           [r["pattern"] for r in ctx_rules if r["kind"] == "profanity"]


def _profanity(ctx: Ctx, pool: list[dict]) -> dict[str, tuple[float, str]]:
    """Mat density on speech-like text (subtitles + comments). Missing -> channel prior -> global mean."""
    target = max(0.1, float(ctx.s.get("profanity_target", 4.0)))
    own: dict[str, float] = {}
    for v in pool:
        speech = " ".join(x for x in (v["subtitles_text"], v["comments_text"]) if x)
        if not speech:
            continue
        d, _n, words = text.profanity_density(speech, profanity_patterns(ctx.rules, v["lang"]))
        if words >= 30:
            own[v["id"]] = min(1.0, d / target)
    by_ch: dict[str, list[float]] = defaultdict(list)
    for v in pool:
        if v["id"] in own:
            by_ch[v["channel_id"]].append(own[v["id"]])
    glob = float(np.mean(list(own.values()))) if own else None
    out = {}
    for v in pool:
        if v["id"] in own:
            out[v["id"]] = (own[v["id"]], "own")
        elif by_ch.get(v["channel_id"]):
            out[v["id"]] = (float(np.mean(by_ch[v["channel_id"]])), "приор канала")
        elif glob is not None:
            out[v["id"]] = (glob, "среднее по базе")
    return out


def llm_value(scores: dict, questions: list[dict]) -> float | None:
    num = den = 0.0
    for q in questions:
        sv = scores.get(q["key"])
        if sv is None:
            continue
        w = float(q.get("weight", 0))
        num += w * float(np.clip(float(sv), 0, 10)) / 10.0
        den += abs(w)
    return num / den if den > 0 else None


def _llm(ctx: Ctx, pool: list[dict]) -> dict[str, tuple[float, str]]:
    qs = ctx.s.get("llm_questions") or []
    own = {}
    for v in pool:
        sc = ctx.llm.get(v["id"])
        if sc:
            val = llm_value(sc.get("scores", sc), qs)
            if val is not None:
                own[v["id"]] = val
    by_ch: dict[str, list[float]] = defaultdict(list)
    for v in pool:
        if v["id"] in own:
            by_ch[v["channel_id"]].append(own[v["id"]])
    out = {}
    for v in pool:
        if v["id"] in own:
            out[v["id"]] = (own[v["id"]], "own")
        elif by_ch.get(v["channel_id"]):
            out[v["id"]] = (float(np.mean(by_ch[v["channel_id"]])), "приор канала")
    return out  # no global fill: missing LLM is dropped (weights renormalized)


# ---------------------------------------------------------------- cache + persistence
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def feed(pid: str, similar_to: str | None = None) -> dict:
    key = (pid, similar_to, db.version())
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]
    res = compute(pid, similar_to=similar_to)
    with _CACHE_LOCK:
        if len(_CACHE) > 16:
            _CACHE.clear()
        _CACHE[key] = res
    return res


def persist(pid: str) -> int:
    res = compute(pid, include_all=True)
    rows = [(pid, it["v"]["id"], it["score"], it["rank"], db.jdumps({"why": it["why"], "notes": it["notes"], "conf": it["conf"]}),
             1 if it["explore"] else 0, db.now()) for it in res["items"]]
    db.exmany("""INSERT INTO video_scores(profile_id, video_id, score, rank, breakdown, explore, updated_at)
                 VALUES(?,?,?,?,?,?,?) ON CONFLICT(profile_id, video_id) DO UPDATE SET score=excluded.score,
                 rank=excluded.rank, breakdown=excluded.breakdown, explore=excluded.explore, updated_at=excluded.updated_at""", rows)
    return len(rows)


def top_ids(pid: str, n: int) -> list[str]:
    """Cheap pre-ranking for heavy jobs (LLM, comments...): the current feed order, then the rest."""
    res = compute(pid, include_all=True)
    return [it["v"]["id"] for it in res["items"][:n]]


def fmt_duration(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_age(ts) -> str:
    if not ts:
        return ""
    d = (time.time() - ts) / 86400
    if d < 1:
        return "сегодня"
    if d < 2:
        return "вчера"
    if d < 30:
        return f"{int(d)} дн. назад"
    if d < 365:
        return f"{int(d // 30)} мес. назад"
    return f"{d / 365:.1f} г. назад"


def has_mat_title(v: dict, rules: list[dict]) -> bool:
    return text.count_matches(text.tokens(v.get("title") or ""), profanity_patterns(rules, v.get("lang"))) > 0


