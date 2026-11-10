"""Optional YouTube Data API v3 provider (user's own key, off by default). Cheap calls only."""
from __future__ import annotations

import re
from datetime import datetime

from .. import db, net
from . import ProviderError, Unavailable

BASE = "https://www.googleapis.com/youtube/v3"


def enabled() -> bool:
    s = db.get_settings()
    return bool(s.get("api_enabled") and s.get("api_key"))


def _get(path: str, stop=None, **params) -> dict:
    if not enabled():
        raise Unavailable("API key not configured")
    params["key"] = db.get_settings()["api_key"]
    r = net.get(f"{BASE}/{path}", purpose="api", params=params, stop=stop)
    if r.status_code != 200:
        raise ProviderError(f"API {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def _iso_dur(s: str) -> int | None:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def list_channel(channel_id: str, limit: int = 15, stop=None) -> dict:
    """playlistItems on the UULF (long-only) playlist: 1 quota unit."""
    d = _get("playlistItems", stop=stop, part="snippet,contentDetails", maxResults=min(50, limit),
             playlistId="UULF" + channel_id[2:])
    ents = []
    for it in d.get("items", []):
        sn = it.get("snippet", {})
        ents.append({"id": it["contentDetails"]["videoId"], "channel_id": channel_id, "title": sn.get("title", ""),
                     "description": sn.get("description", ""), "published_at": _ts(sn.get("publishedAt")), "is_short": 0})
    return {"channel_id": channel_id, "channel_title": None, "entries": ents, "only_long": True}


def video_meta(video_id: str, stop=None) -> dict:
    d = _get("videos", stop=stop, part="snippet,contentDetails,statistics", id=video_id)
    if not d.get("items"):
        raise Unavailable("not found")
    it = d["items"][0]
    sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("statistics", {})
    return {
        "id": video_id, "channel_id": sn.get("channelId"), "title": sn.get("title", ""),
        "description": sn.get("description", ""), "tags": sn.get("tags") or [],
        "lang": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"), "duration": _iso_dur(cd.get("duration")),
        "views": int(st.get("viewCount", 0) or 0) or None, "published_at": _ts(sn.get("publishedAt")),
        "age_restricted": 1 if (cd.get("contentRating") or {}).get("ytRating") == "ytAgeRestricted" else 0,
        "live_status": sn.get("liveBroadcastContent"), "channel_title": sn.get("channelTitle"), "chapters": [],
    }
