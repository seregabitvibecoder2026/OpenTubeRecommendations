"""Public HTML pages of youtube.com (no login). Gives metadata even for age-restricted videos
(empirically verified: title, description, keywords, length, views, publish date, isFamilySafe)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from .. import net
from . import ProviderError, Unavailable

UC_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
VID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")


def _json_var(html: str, name: str) -> dict | None:
    m = re.search(r"(?:var\s+)?" + re.escape(name) + r"\s*=\s*(\{.+?\});\s*(?:var\s|</script>)", html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def walk(o, key: str, out: list) -> list:
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                out.append(v)
            walk(v, key, out)
    elif isinstance(o, list):
        for v in o:
            walk(v, key, out)
    return out


def _text(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if "simpleText" in x:
            return x["simpleText"]
        if "runs" in x:
            return "".join(r.get("text", "") for r in x["runs"])
        if "content" in x:
            return x["content"]
    return ""


def _page(url: str, stop=None) -> str:
    r = net.get(url, stop=stop)
    if r.status_code == 404:
        raise Unavailable("HTTP 404")
    if r.status_code != 200:
        raise ProviderError(f"HTTP {r.status_code}")
    return r.text


# ---------------------------------------------------------------- video
def video_meta(video_id: str, stop=None) -> dict:
    html = _page(f"https://www.youtube.com/watch?v={video_id}", stop=stop)
    p = _json_var(html, "ytInitialPlayerResponse")
    if not p:
        raise ProviderError("no ytInitialPlayerResponse")
    vd = p.get("videoDetails") or {}
    mf = (p.get("microformat") or {}).get("playerMicroformatRenderer") or {}
    ps = p.get("playabilityStatus") or {}
    if not vd and ps.get("status") in ("ERROR", "UNPLAYABLE"):
        raise Unavailable(ps.get("reason") or ps.get("status"))
    pub = None
    for k in ("publishDate", "uploadDate"):
        if mf.get(k):
            try:
                pub = datetime.fromisoformat(mf[k]).timestamp()
                break
            except ValueError:
                pass
    age = (ps.get("status") == "LOGIN_REQUIRED" and "age" in (ps.get("reason") or "").lower()) or mf.get("isFamilySafe") is False
    live = "is_live" if vd.get("isLive") else ("is_upcoming" if vd.get("isUpcoming") else "not_live")
    desc = vd.get("shortDescription") or _text(mf.get("description"))
    return {
        "id": video_id, "channel_id": vd.get("channelId") or mf.get("externalChannelId"),
        "title": vd.get("title") or _text(mf.get("title")), "description": desc or "",
        "tags": vd.get("keywords") or [], "duration": int(vd.get("lengthSeconds") or mf.get("lengthSeconds") or 0) or None,
        "views": int(vd.get("viewCount") or mf.get("viewCount") or 0) or None, "published_at": pub,
        "age_restricted": 1 if age else 0, "live_status": live, "lang": None,
        "channel_title": vd.get("author") or mf.get("ownerChannelName"), "chapters": [],
        "playability": ps.get("status"), "has_captions": "captions" in p,
        "_html": html,
    }


def comments(video_id: str, limit: int = 80, html: str | None = None, stop=None) -> list[dict]:
    """Top comments through the public continuation of the watch page. Age-gated pages have no token."""
    html = html or _page(f"https://www.youtube.com/watch?v={video_id}", stop=stop)
    data = _json_var(html, "ytInitialData") or {}
    toks = []
    for sec in walk(data, "itemSectionRenderer", []):
        if sec.get("sectionIdentifier") == "comment-item-section":
            walk(sec, "continuationCommand", toks)
    if not toks:
        raise Unavailable("no comments continuation (comments off or age-gated)")
    ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
    body = {"context": {"client": {"clientName": "WEB", "clientVersion": ver.group(1) if ver else "2.20250101.00.00",
                                   "hl": "en"}}, "continuation": toks[0]["token"]}
    out: list[dict] = []
    for _page_no in range(5):
        r = net.post("https://www.youtube.com/youtubei/v1/next", json=body, stop=stop)
        if r.status_code != 200:
            raise ProviderError(f"next HTTP {r.status_code}")
        j = r.json()
        for e in walk(j, "commentEntityPayload", []):
            props = e.get("properties") or {}
            tb = e.get("toolbar") or {}
            likes = tb.get("likeCountNotliked") or tb.get("likeCountA11y") or "0"
            out.append({"text": _text(props.get("content")), "like_count": _num(likes),
                        "author_is_uploader": bool((e.get("author") or {}).get("isCreator"))})
        if len(out) >= limit:
            break
        nxt = [c for c in walk(j, "continuationCommand", []) if c.get("request") == "CONTINUATION_REQUEST_TYPE_WATCH_NEXT"]
        if not nxt:
            break
        body["continuation"] = nxt[-1]["token"]
    return out[:limit]


def _num(s: str) -> int:
    s = str(s).strip().upper().replace(",", ".").split(" ")[0]
    mult = 1
    if s.endswith("K"):
        mult, s = 1000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


# ---------------------------------------------------------------- channels
def parse_channel_input(s: str) -> tuple[str, str]:
    """Classify user input. Returns (kind, value): ('id', UC..), ('url', channel url), ('video', id)."""
    s = s.strip().strip(",;")
    if not s:
        raise ValueError("empty")
    if UC_RE.match(s):
        return "id", s
    if s.startswith("@"):
        return "url", f"https://www.youtube.com/{s}"
    if not re.match(r"^https?://", s):
        if re.match(r"^(www\.|m\.)?(youtube\.com|youtu\.be)/", s):
            s = "https://" + s
        elif VID_RE.match(s) and not s.startswith("UC"):
            return "video", s
        else:
            return "url", f"https://www.youtube.com/@{s.lstrip('@')}"
    u = urlparse(s)
    host = (u.hostname or "").lower()
    path = u.path.rstrip("/")
    if host.endswith("youtu.be"):
        return "video", path.lstrip("/")[:11]
    if path == "/watch":
        v = parse_qs(u.query).get("v", [""])[0]
        if v:
            return "video", v
    m = re.match(r"^/(shorts|live|embed)/([0-9A-Za-z_-]{11})", path)
    if m:
        return "video", m.group(2)
    m = re.match(r"^/channel/(UC[0-9A-Za-z_-]{22})", path)
    if m:
        return "id", m.group(1)
    m = re.match(r"^/(@[^/]+|c/[^/]+|user/[^/]+)", path)
    if m:
        return "url", f"https://www.youtube.com/{m.group(1)}"
    raise ValueError(f"не распознано: {s}")


def resolve_channel_url(url: str, stop=None) -> dict:
    html = _page(url, stop=stop)
    m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[0-9A-Za-z_-]{22})"', html) \
        or re.search(r'"externalId":"(UC[0-9A-Za-z_-]{22})"', html) \
        or re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html)
    if not m:
        raise ProviderError("channel id not found on page")
    title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    handle = re.search(r'"canonicalBaseUrl":"/(@[^"]+)"', html)
    desc = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    return {"id": m.group(1), "title": _unescape(title.group(1)) if title else None,
            "handle": handle.group(1) if handle else None, "description": _unescape(desc.group(1)) if desc else None}


def _unescape(s: str) -> str:
    import html as h
    return h.unescape(s)


def featured_channels(channel_id: str, stop=None) -> list[dict]:
    """'Recommended/featured channels' shelves of a channel page."""
    out: dict[str, dict] = {}
    for suffix in ("/channels", ""):
        try:
            html = _page(f"https://www.youtube.com/channel/{channel_id}{suffix}", stop=stop)
        except Unavailable:
            continue
        data = _json_var(html, "ytInitialData") or {}
        for key in ("channelRenderer", "gridChannelRenderer"):
            for c in walk(data, key, []):
                cid = c.get("channelId")
                if cid and cid != channel_id and cid not in out:
                    out[cid] = {"id": cid, "title": _text(c.get("title"))}
        if out:
            break
    return list(out.values())
