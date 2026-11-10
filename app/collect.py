"""Data collection: channels, listing, metadata/subtitles/comments chains, source probing."""
from __future__ import annotations

import csv
import io
import re
import time

from . import db, text
from .providers import ProviderError, Unavailable, altfront, rss, watchpage, ytapi, ytdlp

# states for meta/subs/comments/thumb columns
NOT_TRIED, OK, UNAVAILABLE, ERROR = 0, 1, -1, -2


# ---------------------------------------------------------------- channels
def upsert_channel(cid: str, title: str | None = None, handle: str | None = None, description: str | None = None,
                   url: str | None = None) -> None:
    db.ex("""INSERT INTO channels(id, title, handle, description, url, added_at) VALUES(?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET title=COALESCE(excluded.title, title), handle=COALESCE(excluded.handle, handle),
             description=COALESCE(excluded.description, description), url=COALESCE(excluded.url, url)""",
          (cid, title, handle, description, url or f"https://www.youtube.com/channel/{cid}", db.now()))


def attach(pid: str, cid: str, weight: float = 0.0) -> None:
    db.ex("""INSERT INTO profile_channels(profile_id, channel_id, weight, added_at) VALUES(?,?,?,?)
             ON CONFLICT(profile_id, channel_id) DO UPDATE SET hidden=0""", (pid, cid, weight, db.now()))


def resolve(s: str, stop=None) -> dict:
    """User input (UC id, @handle, channel/video URL) -> {'id', 'title', 'handle'}."""
    kind, val = watchpage.parse_channel_input(s)
    if kind == "id":
        known = db.q1("SELECT * FROM channels WHERE id=?", (val,))
        if known and known["title"]:
            return {"id": val, "title": known["title"], "handle": known["handle"]}
        try:
            return watchpage.resolve_channel_url(f"https://www.youtube.com/channel/{val}", stop=stop)
        except ProviderError:
            return {"id": val, "title": None, "handle": None}
    if kind == "video":
        m = watchpage.video_meta(val, stop=stop)
        if not m.get("channel_id"):
            raise ProviderError("no channel for video")
        return {"id": m["channel_id"], "title": m.get("channel_title"), "handle": None}
    try:
        return watchpage.resolve_channel_url(val, stop=stop)
    except ProviderError:
        d = ytdlp.list_channel(val, limit=1)
        if not d.get("channel_id"):
            raise
        return {"id": d["channel_id"], "title": d.get("channel_title"), "handle": d.get("handle")}


def split_inputs(blob: str) -> list[str]:
    return [p for p in re.split(r"[\s,;]+", blob or "") if p.strip()]


def parse_takeout_csv(data: str) -> list[dict]:
    """Google Takeout subscriptions.csv (any UI language): first column = channel id."""
    out = []
    for row in csv.reader(io.StringIO(data.lstrip("﻿"))):
        if not row:
            continue
        cid = next((c.strip() for c in row if watchpage.UC_RE.match(c.strip())), None)
        if not cid:
            continue
        title = row[2].strip() if len(row) > 2 else None
        out.append({"id": cid, "title": title or None})
    return out


# ---------------------------------------------------------------- videos
def upsert_listing(entries: list[dict], channel_id: str) -> list[str]:
    """Insert new videos from a listing; update light fields of known ones. Returns new ids."""
    new = []
    for e in entries:
        vid = e["id"]
        row = db.q1("SELECT id, meta_state FROM videos WHERE id=?", (vid,))
        if row is None:
            db.ex("""INSERT INTO videos(id, channel_id, title, description, duration, published_at, views, is_short,
                     first_seen, meta_source) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                  (vid, e.get("channel_id") or channel_id, e.get("title"), e.get("description") or "",
                   e.get("duration"), e.get("published_at"), e.get("views"), int(e.get("is_short") or 0), db.now(),
                   "listing"))
            new.append(vid)
        else:
            db.ex("""UPDATE videos SET views=COALESCE(?, views), duration=COALESCE(duration, ?),
                     published_at=COALESCE(published_at, ?), title=COALESCE(NULLIF(?, ''), title) WHERE id=?""",
                  (e.get("views"), e.get("duration"), e.get("published_at"), e.get("title"), vid))
        refresh_evidence(vid)
    return new


def list_channel(cid: str, limit: int, log=print, stop=None, breaker: dict | None = None) -> dict:
    """Run the listing chain (rss -> yt-dlp tab -> API). `breaker` skips a source after repeated failures."""
    s = db.get_settings()
    breaker = breaker if breaker is not None else {}
    errors = []
    for p in s["listing_order"]:
        name = p["name"]
        if not p.get("on") or breaker.get(name, 0) >= 3:
            continue
        try:
            if name == "rss":
                d = rss.fetch(cid, stop=stop)
            elif name == "ytdlp_tab":
                d = ytdlp.list_channel(cid, limit=limit)
            elif name == "ytapi":
                d = ytapi.list_channel(cid, limit=limit, stop=stop)
            else:
                continue
            breaker[name] = 0
            d["source"] = name
            d["entries"] = d["entries"][:limit]
            return d
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001 - provider failures are logged and the chain continues
            breaker[name] = breaker.get(name, 0) + 1
            errors.append(f"{name}: {str(e)[:150]}")
            log(f"  {cid}: источник {name} не сработал: {str(e)[:150]}")
            if breaker[name] == 3:
                log(f"  источник {name} отключён до конца задачи (3 ошибки подряд)")
    raise ProviderError("; ".join(errors) or "нет включённых источников")


def save_meta(m: dict, source: str) -> None:
    vid = m["id"]
    lang = text.detect_lang(" ".join([m.get("title") or "", m.get("description") or ""])[:3000], hint=m.get("lang"))
    db.ex("""UPDATE videos SET channel_id=COALESCE(?, channel_id), title=COALESCE(NULLIF(?, ''), title),
             description=CASE WHEN length(COALESCE(?, '')) >= length(COALESCE(description, '')) THEN ? ELSE description END,
             tags=?, lang=COALESCE(?, lang), duration=COALESCE(?, duration), views=COALESCE(?, views),
             published_at=COALESCE(?, published_at), age_restricted=?, live_status=COALESCE(?, live_status),
             chapters=?, meta_source=?, meta_state=? WHERE id=?""",
          (m.get("channel_id"), m.get("title"), m.get("description"), m.get("description"),
           db.jdumps(m.get("tags") or []), lang, m.get("duration"), m.get("views"), m.get("published_at"),
           int(m.get("age_restricted") or 0), m.get("live_status"), db.jdumps(m.get("chapters") or []), source, OK, vid))
    refresh_evidence(vid)


def fetch_meta(vid: str, log=print, stop=None) -> str | None:
    """Metadata chain. Returns the provider name that succeeded."""
    s = db.get_settings()
    for p in s["providers"]["meta"]:
        if not p.get("on"):
            continue
        name = p["name"]
        try:
            if name == "watchpage":
                m = watchpage.video_meta(vid, stop=stop)
                m.pop("_html", None)
            elif name == "ytdlp":
                m = ytdlp.meta_from_info(ytdlp.video_info(vid))
            elif name == "ytapi":
                m = ytapi.video_meta(vid, stop=stop)
            elif name == "altfront":
                m = altfront.video_meta(vid, stop=stop)
            else:
                continue
            save_meta(m, name)
            return name
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            log(f"  {vid}: метаданные через {name}: {str(e)[:150]}")
    db.ex("UPDATE videos SET meta_state=? WHERE id=?", (ERROR, vid))
    return None


def fetch_subs(vid: str, log=print, stop=None, asr=None) -> str | None:
    s = db.get_settings()
    langs = s.get("sub_langs") or ["ru", "en"]
    unavailable = True
    for p in s["providers"]["subs"]:
        if not p.get("on"):
            continue
        name = p["name"]
        try:
            if name == "ytdlp":
                info = ytdlp.video_info(vid, log_fn=log)
                txt, lang = ytdlp.subtitles(info, langs, stop=stop)
            elif name == "altfront":
                txt, lang = altfront.subtitles(vid, langs, stop=stop)
            elif name == "whisper":
                if asr is None:
                    raise Unavailable("ASR model not loaded")
                txt, lang = asr(vid)
            else:
                continue
            if not txt.strip():
                raise Unavailable("empty subtitles")
            db.ex("UPDATE videos SET subtitles_text=?, subtitles_lang=?, subs_state=? WHERE id=?",
                  (txt[: int(s.get("subs_chars", 20000))], lang, OK, vid))
            _maybe_lang_from(vid, txt)
            refresh_evidence(vid)
            log(f"  {vid}: субтитры ({name}, {lang}, {len(txt)} симв.)")
            return name
        except InterruptedError:
            raise
        except Unavailable as e:
            log(f"  {vid}: субтитры через {name} недоступны: {str(e)[:150]}")
        except Exception as e:  # noqa: BLE001
            unavailable = False
            log(f"  {vid}: субтитры через {name}: ошибка {str(e)[:150]}")
    db.ex("UPDATE videos SET subs_state=? WHERE id=?", (UNAVAILABLE if unavailable else ERROR, vid))
    refresh_evidence(vid)
    return None


def fetch_comments(vid: str, log=print, stop=None) -> str | None:
    s = db.get_settings()
    limit = int(s.get("comments_max", 80))
    unavailable = True
    for p in s["providers"]["comments"]:
        if not p.get("on"):
            continue
        name = p["name"]
        try:
            if name == "ytdlp":
                info = ytdlp.video_info(vid, comments=limit, log_fn=log)
                cs = info.get("comments") or []
            elif name == "watchpage":
                cs = watchpage.comments(vid, limit=limit, stop=stop)
            elif name == "altfront":
                cs = altfront.comments(vid, limit=limit, stop=stop)
            else:
                continue
            txt = text.clean_comments(cs, max_chars=int(s.get("comments_chars", 4000)))
            if not txt:
                raise Unavailable("no usable comments")
            db.ex("UPDATE videos SET comments_text=?, comments_state=? WHERE id=?", (txt, OK, vid))
            refresh_evidence(vid)
            log(f"  {vid}: комментарии ({name}, {len(cs)} шт., после фильтра {txt.count(chr(10)) + 1})")
            return name
        except InterruptedError:
            raise
        except Unavailable as e:
            log(f"  {vid}: комментарии через {name} недоступны: {str(e)[:150]}")
        except Exception as e:  # noqa: BLE001
            unavailable = False
            log(f"  {vid}: комментарии через {name}: ошибка {str(e)[:150]}")
    db.ex("UPDATE videos SET comments_state=? WHERE id=?", (UNAVAILABLE if unavailable else ERROR, vid))
    refresh_evidence(vid)
    return None


def _maybe_lang_from(vid: str, txt: str) -> None:
    row = db.q1("SELECT lang FROM videos WHERE id=?", (vid,))
    if row and not row["lang"]:
        db.ex("UPDATE videos SET lang=? WHERE id=?", (text.detect_lang(txt[:3000]), vid))


def refresh_evidence(vid: str) -> dict:
    r = db.q1("SELECT * FROM videos WHERE id=?", (vid,))
    if not r:
        return {}
    ev = {
        "meta": r["meta_state"] == OK,
        "description": bool((r["description"] or "").strip()),
        "comments": bool(r["comments_text"]),
        "subtitles": bool(r["subtitles_text"]),
        "thumbnail": bool(r["thumb_desc"]),
    }
    db.ex("UPDATE videos SET evidence=? WHERE id=?", (db.jdumps(ev), vid))
    return ev


# ---------------------------------------------------------------- probe ("what is available for this video")
def probe(vid: str, log=print, stop=None) -> dict:
    """Empirically try every source for one video; nothing is assumed. Result saved in videos.probe."""
    s = db.get_settings()
    res: dict = {"ts": db.now(), "sources": []}

    def add(source, kind, ok, note=""):
        res["sources"].append({"source": source, "kind": kind, "ok": ok, "note": str(note)[:200]})
        log(f"  {vid} [{source}] {kind}: {'OK' if ok else 'нет'} {str(note)[:160]}")

    html = None
    try:
        m = watchpage.video_meta(vid, stop=stop)
        html = m.pop("_html", None)
        add("watchpage", "meta", True, f"playability={m.get('playability')}, 18+={m.get('age_restricted')}, "
                                       f"описание {len(m.get('description') or '')} симв., тегов {len(m.get('tags') or [])}")
        add("watchpage", "captions-list", bool(m.get("has_captions")), "дорожки субтитров в плеере" if m.get("has_captions") else "")
        res["age_restricted"] = m.get("age_restricted")
    except InterruptedError:
        raise
    except Exception as e:  # noqa: BLE001
        add("watchpage", "meta", False, e)
    try:
        cs = watchpage.comments(vid, limit=20, html=html, stop=stop)
        add("watchpage", "comments", bool(cs), f"{len(cs)} шт.")
    except InterruptedError:
        raise
    except Exception as e:  # noqa: BLE001
        add("watchpage", "comments", False, e)
    for cl in s.get("ytdlp_clients") or ["default"]:
        if stop and stop():
            raise InterruptedError
        try:
            info = ytdlp.video_info(vid, clients=[cl])
            tr = ytdlp.pick_sub_track(info, s.get("sub_langs") or ["ru", "en"])
            add(f"yt-dlp:{cl}", "meta", True, f"язык={info.get('language')}")
            add(f"yt-dlp:{cl}", "subtitles", bool(tr), f"{tr[0]}{' (авто)' if tr and tr[2] else ''}" if tr else "нет дорожек")
            break
        except Exception as e:  # noqa: BLE001
            add(f"yt-dlp:{cl}", "meta", False, e)
    try:
        info = ytdlp.video_info(vid, comments=10)
        add("yt-dlp", "comments", bool(info.get("comments")), f"{len(info.get('comments') or [])} шт.")
    except Exception as e:  # noqa: BLE001
        add("yt-dlp", "comments", False, e)
    if s.get("altfront_url") and any(p["name"] == "altfront" and p.get("on") for p in s["providers"]["meta"]):
        for kind, fn in (("meta", lambda: altfront.video_meta(vid, stop=stop)),
                         ("comments", lambda: altfront.comments(vid, 10, stop=stop)),
                         ("subtitles", lambda: altfront.subtitles(vid, s.get("sub_langs") or ["ru", "en"], stop=stop))):
            try:
                fn()
                add("altfront", kind, True)
            except Exception as e:  # noqa: BLE001
                add("altfront", kind, False, e)
    try:
        from . import net
        r = net.get(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", stop=stop)
        add("ytimg", "thumbnail", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        add("ytimg", "thumbnail", False, e)
    db.ex("UPDATE videos SET probe=? WHERE id=?", (db.jdumps(res), vid))
    return res


def ensure_video(vid: str, log=print, stop=None) -> None:
    if not db.q1("SELECT 1 FROM videos WHERE id=?", (vid,)):
        db.ex("INSERT INTO videos(id, first_seen) VALUES(?, ?)", (vid, time.time()))
        fetch_meta(vid, log=log, stop=stop)
