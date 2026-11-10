"""yt-dlp based provider (no login). Channel listing, full metadata, subtitles, comments, audio."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from .. import db, net
from . import ProviderError, Unavailable

log = logging.getLogger(__name__)

AGE_RE = re.compile(r"confirm your age|age[- ]restricted|inappropriate for some users", re.I)


class _Quiet:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        log.debug("yt-dlp: %s", msg)


def _opts(extra: dict | None = None) -> dict:
    s = db.get_settings()
    o = {
        "quiet": True, "no_warnings": True, "skip_download": True, "logger": _Quiet(),
        "socket_timeout": s.get("timeout", 20), "retries": s.get("retries", 3),
        "sleep_interval_requests": float(s.get("request_pause", 1.5)) / 2,
        "noplaylist": True, "cachedir": False,
    }
    if net.proxy():
        o["proxy"] = net.proxy()
    if s.get("cookies_browser"):
        o["cookiesfrombrowser"] = (s["cookies_browser"],)
    if extra:
        o.update(extra)
    return o


def _ydl(extra: dict | None = None):
    import yt_dlp
    return yt_dlp.YoutubeDL(_opts(extra))


def _polite():
    net.THROTTLE.wait(float(db.get_settings().get("request_pause", 1.5)))


def _is_age_error(e: Exception) -> bool:
    return bool(AGE_RE.search(str(e)))


# ---------------------------------------------------------------- listing
def list_channel(channel_id_or_url: str, limit: int = 15) -> dict:
    """Flat listing of the channel's /videos tab (long videos only; shorts live in /shorts)."""
    url = channel_id_or_url
    if url.startswith("UC"):
        url = f"https://www.youtube.com/channel/{url}"
    url = url.rstrip("/")
    if not url.endswith("/videos"):
        url += "/videos"
    _polite()
    try:
        with _ydl({"extract_flat": "in_playlist", "playlistend": limit, "noplaylist": False,
                   "extractor_args": {"youtubetab": {"approximate_date": [""]}}}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:
        raise ProviderError(f"yt-dlp tab: {e}") from e
    entries = []
    for e in info.get("entries") or []:
        if not e or not e.get("id") or e.get("live_status") in ("is_upcoming", "is_live"):
            continue
        entries.append({
            "id": e["id"], "channel_id": info.get("channel_id"), "title": e.get("title") or "",
            "duration": e.get("duration"), "views": e.get("view_count"),
            "published_at": e.get("timestamp"), "is_short": 0,
            "description": e.get("description") or "",
        })
    return {"channel_id": info.get("channel_id"), "channel_title": info.get("channel") or info.get("title"),
            "handle": info.get("uploader_id"), "entries": entries, "only_long": True}


def search(query: str, limit: int = 10) -> list[dict]:
    _polite()
    try:
        with _ydl({"extract_flat": "in_playlist", "noplaylist": False}) as y:
            info = y.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as e:
        raise ProviderError(f"yt-dlp search: {e}") from e
    return [{"id": e.get("id"), "channel_id": e.get("channel_id"), "channel": e.get("channel"),
             "title": e.get("title"), "duration": e.get("duration")} for e in (info.get("entries") or []) if e]


# ---------------------------------------------------------------- full info
_AGE_FAIL: dict[str, float] = {}  # video_id -> time when all clients failed with the age gate
AGE_FAIL_TTL = 6 * 3600


def video_info(video_id: str, comments: int = 0, clients: list[str] | None = None, log_fn=None) -> dict:
    """Full extraction, trying player clients in order. Raises Unavailable for age-gated videos."""
    s = db.get_settings()
    explicit = clients is not None
    clients = clients or s.get("ytdlp_clients") or ["default"]
    if not explicit and time.time() - _AGE_FAIL.get(video_id, 0) < AGE_FAIL_TTL:
        raise Unavailable("age-restricted: all yt-dlp clients failed recently (cached)")
    last: Exception | None = None
    age = False
    for cl in clients:
        extra: dict = {"extractor_args": {"youtube": {}}}
        if cl and cl != "default":
            extra["extractor_args"]["youtube"]["player_client"] = [cl]
        if comments:
            extra["getcomments"] = True
            extra["extractor_args"]["youtube"]["max_comments"] = [str(comments), "all", str(min(comments, 20)), "0"]
            extra["extractor_args"]["youtube"]["comment_sort"] = ["top"]
        _polite()
        try:
            with _ydl(extra) as y:
                info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if log_fn:
                log_fn(f"yt-dlp[{cl}] {video_id}: ok")
            info["_client"] = cl
            return info
        except Exception as e:
            last = e
            age = age or _is_age_error(e)
            if log_fn:
                log_fn(f"yt-dlp[{cl}] {video_id}: {str(e)[:160]}")
    if age:
        if not explicit:
            _AGE_FAIL[video_id] = time.time()
        raise Unavailable(f"age-restricted, no client worked: {last}")
    raise ProviderError(str(last))


def meta_from_info(info: dict) -> dict:
    return {
        "id": info.get("id"), "channel_id": info.get("channel_id"), "title": info.get("title") or "",
        "description": info.get("description") or "", "tags": info.get("tags") or [],
        "lang": info.get("language"), "duration": info.get("duration"), "views": info.get("view_count"),
        "published_at": info.get("timestamp") or _date(info.get("upload_date")),
        "age_restricted": 1 if (info.get("age_limit") or 0) >= 18 else 0,
        "live_status": info.get("live_status"),
        "chapters": [c.get("title") for c in (info.get("chapters") or []) if c.get("title")],
        "channel_title": info.get("channel"), "handle": info.get("uploader_id"),
    }


def _date(d: str | None) -> float | None:
    if not d:
        return None
    try:
        return time.mktime(time.strptime(d, "%Y%m%d"))
    except ValueError:
        return None


# ---------------------------------------------------------------- subtitles
def pick_sub_track(info: dict, pref_langs: list[str]) -> tuple[str, str, bool] | None:
    """Returns (lang, url, is_auto). Manual subs in preferred langs > original-language auto subs > other."""
    def json3(tracks):
        for f in tracks or []:
            if f.get("ext") == "json3":
                return f.get("url")
        return None

    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    vlang = (info.get("language") or "").split("-")[0]
    order = list(dict.fromkeys([vlang] + list(pref_langs) if vlang else list(pref_langs)))
    for lg in order:
        for k in (lg, f"{lg}-orig") + tuple(k for k in subs if k.split("-")[0] == lg):
            if k in subs and json3(subs[k]):
                return lg, json3(subs[k]), False
    for lg in order:
        for k in (f"{lg}-orig", lg):
            if k in auto and json3(auto[k]):
                return lg, json3(auto[k]), True
    # any original-language auto track
    for k, v in auto.items():
        if k.endswith("-orig") and json3(v):
            return k.split("-")[0], json3(v), True
    return None


def json3_to_text(d: dict) -> str:
    parts = []
    for ev in d.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if t:
            parts.append(t)
    text = " ".join(parts)
    return re.sub(r"\s+", " ", re.sub(r"\[(?:music|музыка|applause|аплодисменты)\]", " ", text, flags=re.I)).strip()


def subtitles(info: dict, pref_langs: list[str], stop=None) -> tuple[str, str]:
    tr = pick_sub_track(info, pref_langs)
    if not tr:
        raise Unavailable("no subtitle tracks")
    lang, url, _auto = tr
    r = net.get(url, stop=stop)
    if r.status_code != 200:
        raise ProviderError(f"timedtext HTTP {r.status_code}")
    try:
        return json3_to_text(r.json()), lang
    except ValueError as e:
        raise ProviderError(f"timedtext parse: {e}") from e


# ---------------------------------------------------------------- audio for whisper
def download_audio(video_id: str, out_dir: Path, max_minutes: int = 30) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    _polite()
    tmpl = str(out_dir / f"{video_id}.%(ext)s")
    extra = {"skip_download": False, "format": "bestaudio[abr<=96]/bestaudio/worst",
             "outtmpl": tmpl, "match_filter": None,
             "download_ranges": None}
    try:
        with _ydl(extra) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if (info.get("duration") or 0) > max_minutes * 60:
                raise Unavailable(f"too long for ASR (> {max_minutes} min)")
            y.process_ie_result(info, download=True)
    except Unavailable:
        raise
    except Exception as e:
        if _is_age_error(e):
            raise Unavailable("age-restricted audio") from e
        raise ProviderError(f"audio: {e}") from e
    files = sorted(out_dir.glob(f"{video_id}.*"))
    if not files:
        raise ProviderError("audio file missing")
    return files[0]
