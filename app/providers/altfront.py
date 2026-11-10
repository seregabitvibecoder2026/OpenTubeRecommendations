"""Optional open alternative frontends (Invidious / Piped). The instance URL is entered by the user.
Off by default: instances see your requests and are often unstable."""
from __future__ import annotations

import re

from .. import db, net
from . import ProviderError, Unavailable


def _cfg() -> tuple[str, str]:
    s = db.get_settings()
    base = (s.get("altfront_url") or "").rstrip("/")
    if not base:
        raise Unavailable("alt frontend not configured")
    return base, s.get("altfront_kind", "invidious")


def _get(url: str, stop=None):
    r = net.get(url, purpose="altfront", stop=stop)
    if r.status_code != 200:
        raise ProviderError(f"altfront HTTP {r.status_code}")
    try:
        return r
    except ValueError as e:
        raise ProviderError(str(e)) from e


def video_meta(video_id: str, stop=None) -> dict:
    base, kind = _cfg()
    if kind == "piped":
        j = _get(f"{base}/streams/{video_id}", stop).json()
        return {"id": video_id, "channel_id": (j.get("uploaderUrl") or "").split("/")[-1] or None,
                "title": j.get("title", ""), "description": re.sub(r"<[^>]+>", " ", j.get("description") or ""),
                "tags": j.get("tags") or [], "duration": j.get("duration"), "views": j.get("views"),
                "published_at": None, "age_restricted": 0, "lang": None, "chapters": [c.get("title") for c in j.get("chapters") or []]}
    j = _get(f"{base}/api/v1/videos/{video_id}", stop).json()
    return {"id": video_id, "channel_id": j.get("authorId"), "title": j.get("title", ""),
            "description": j.get("description", ""), "tags": j.get("keywords") or [], "duration": j.get("lengthSeconds"),
            "views": j.get("viewCount"), "published_at": j.get("published"), "age_restricted": 0 if j.get("isFamilyFriendly", True) else 1,
            "lang": None, "chapters": []}


def comments(video_id: str, limit: int = 80, stop=None) -> list[dict]:
    base, kind = _cfg()
    if kind == "piped":
        j = _get(f"{base}/comments/{video_id}", stop).json()
        return [{"text": re.sub(r"<[^>]+>", " ", c.get("commentText") or ""), "like_count": c.get("likeCount") or 0,
                 "author_is_uploader": c.get("verified", False)} for c in j.get("comments", [])][:limit]
    j = _get(f"{base}/api/v1/comments/{video_id}?sort_by=top", stop).json()
    return [{"text": c.get("content") or "", "like_count": c.get("likeCount") or 0,
             "author_is_uploader": c.get("authorIsChannelOwner", False)} for c in j.get("comments", [])][:limit]


def subtitles(video_id: str, pref_langs: list[str], stop=None) -> tuple[str, str]:
    base, kind = _cfg()
    if kind == "piped":
        j = _get(f"{base}/streams/{video_id}", stop).json()
        tracks = [(s.get("code", ""), s.get("url")) for s in j.get("subtitles") or []]
    else:
        j = _get(f"{base}/api/v1/captions/{video_id}", stop).json()
        tracks = [(c.get("language_code", ""), base + c.get("url", "")) for c in j.get("captions", [])]
    for lg in pref_langs:
        for code, url in tracks:
            if code.split("-")[0] == lg and url:
                txt = _get(url, stop).text
                return vtt_to_text(txt), lg
    raise Unavailable("no captions on alt frontend")


def vtt_to_text(vtt: str) -> str:
    lines = []
    for ln in vtt.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in ln or ln.isdigit():
            continue
        ln = re.sub(r"<[^>]+>", "", ln)
        if not lines or lines[-1] != ln:
            lines.append(ln)
    return " ".join(lines)
