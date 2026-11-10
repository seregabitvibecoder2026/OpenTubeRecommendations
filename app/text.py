"""Text utilities: tokenization, language detection, profanity density, rule matching, comment cleanup."""
from __future__ import annotations

import fnmatch
import re
from functools import lru_cache

_TOKEN_RE = re.compile(r"[0-9a-zа-яё#@*]+", re.IGNORECASE)
_CYR = re.compile(r"[а-яё]", re.IGNORECASE)
_LAT = re.compile(r"[a-z]", re.IGNORECASE)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


# ---------------------------------------------------------------- language
def detect_lang(text: str, hint: str | None = None) -> str | None:
    """ISO-639-1 code. `hint` (e.g. yt-dlp `language`) wins when present."""
    if hint:
        return hint.split("-")[0].lower()
    text = (text or "").strip()
    if not text:
        return None
    cyr = len(_CYR.findall(text))
    lat = len(_LAT.findall(text))
    letters = cyr + lat
    if letters == 0:
        return None
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0
        cands = detect_langs(text[:3000])
    except Exception:
        cands = []
    best = cands[0] if cands else None
    if cyr / letters > 0.3:
        # Cyrillic script: trust langdetect only for other Cyrillic languages with high confidence.
        if best and best.lang in ("uk", "bg", "mk", "sr", "be", "kk") and best.prob > 0.9:
            return best.lang
        return "ru"
    if best and best.prob >= 0.8 and best.lang != "ru":
        return best.lang
    return "en"


# ---------------------------------------------------------------- patterns
@lru_cache(maxsize=4096)
def _compile_glob(pattern: str):
    p = pattern.lower().strip()
    if not any(ch in p for ch in "*?["):
        return lambda tok, _p=p: tok == _p
    rx = re.compile(fnmatch.translate(p))
    return lambda tok, _rx=rx: _rx.match(tok) is not None


def count_matches(toks: list[str], patterns: list[str]) -> int:
    if not toks or not patterns:
        return 0
    fns = [_compile_glob(p) for p in patterns if p.strip()]
    return sum(1 for t in toks if any(f(t) for f in fns))


def profanity_density(text: str, patterns: list[str]) -> tuple[float, int, int]:
    """Matches per 1000 words; returns (density, matches, words)."""
    toks = tokens(text)
    if not toks:
        return 0.0, 0, 0
    n = count_matches(toks, patterns)
    return 1000.0 * n / len(toks), n, len(toks)


def phrase_in(text_lower: str, toks: set[str], pattern: str) -> bool:
    """Rule pattern: a phrase (substring match on lowercased text) or a glob on single tokens."""
    p = pattern.lower().strip()
    if not p:
        return False
    if any(ch in p for ch in "*?[") and " " not in p:
        f = _compile_glob(p)
        return any(f(t) for t in toks)
    if " " in p or p.startswith("#"):
        return p in text_lower
    return p in toks


# ---------------------------------------------------------------- comments
_TS_ONLY = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}\s*\S{0,25}\s*$")
_URL = re.compile(r"https?://\S+")


def clean_comments(comments: list[dict], max_chars: int = 4000, max_one: int = 400) -> str:
    """Drop spam/bots/timestamp-only one-liners, dedupe, cap length. Input: yt-dlp comment dicts."""
    out, seen, total = [], set(), 0
    for c in sorted(comments, key=lambda c: -(c.get("like_count") or 0)):
        t = (c.get("text") or "").strip()
        if not t or len(t) < 8:
            continue
        if _TS_ONLY.match(t):
            continue
        if len(_URL.findall(t)) >= 1 and len(_URL.sub("", t).strip()) < 40:
            continue  # link spam
        if c.get("author_is_uploader") and _URL.search(t):
            continue  # sponsor/pinned promo
        letters = sum(ch.isalpha() for ch in t)
        if letters < len(t) * 0.4:
            continue  # emoji walls
        key = re.sub(r"\W+", "", t.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        t = t[:max_one]
        if total + len(t) > max_chars:
            break
        out.append(t)
        total += len(t)
    return "\n".join(out)
