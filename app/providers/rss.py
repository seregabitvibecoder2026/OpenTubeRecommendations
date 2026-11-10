"""YouTube RSS feeds. UULF playlist = long videos only (no shorts)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from .. import net
from . import ProviderError

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
FEED = "https://www.youtube.com/feeds/videos.xml"


def long_playlist_id(channel_id: str) -> str:
    """UCxxxx -> UULFxxxx (uploads without shorts)."""
    if not channel_id.startswith("UC"):
        raise ValueError(channel_id)
    return "UULF" + channel_id[2:]


def shorts_playlist_id(channel_id: str) -> str:
    return "UUSH" + channel_id[2:]


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ProviderError(f"rss parse: {e}") from e
    ch_title = root.findtext("a:title", default="", namespaces=NS)
    ch_id = root.findtext("yt:channelId", default="", namespaces=NS)
    if ch_id and not ch_id.startswith("UC"):
        ch_id = "UC" + ch_id
    entries = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        group = e.find("media:group", NS)
        desc = group.findtext("media:description", default="", namespaces=NS) if group is not None else ""
        views = None
        if group is not None:
            st = group.find("media:community/media:statistics", NS)
            if st is not None and st.get("views", "").isdigit():
                views = int(st.get("views"))
        link = e.find("a:link", NS)
        href = link.get("href") if link is not None else ""
        entries.append({
            "id": vid,
            "channel_id": e.findtext("yt:channelId", default=ch_id, namespaces=NS) or ch_id,
            "title": e.findtext("a:title", default="", namespaces=NS),
            "description": desc,
            "published_at": _ts(e.findtext("a:published", namespaces=NS)),
            "views": views,
            "is_short": 1 if "/shorts/" in (href or "") else 0,
        })
    return {"channel_id": ch_id, "channel_title": ch_title, "entries": entries}


def fetch(channel_id: str, stop=None) -> dict:
    """Try the long-only playlist first, then the full channel feed."""
    errors = []
    for params, only_long in (({"playlist_id": long_playlist_id(channel_id)}, True), ({"channel_id": channel_id}, False)):
        try:
            r = net.get(FEED, params=params, stop=stop)
        except net.BlockedHost:
            raise
        except InterruptedError:
            raise
        except Exception as e:  # network
            errors.append(f"{params}: {e}")
            continue
        if r.status_code != 200:
            errors.append(f"{list(params.values())[0]}: HTTP {r.status_code}")
            continue
        d = parse(r.text)
        d["only_long"] = only_long
        if not d["channel_id"]:
            d["channel_id"] = channel_id
        return d
    raise ProviderError("rss: " + "; ".join(errors))
