"""The only HTTP client of the app. Enforces a host allowlist, politeness (pause, parallelism, retries) and proxy."""
from __future__ import annotations

import ipaddress
import random
import threading
import time
from urllib.parse import urlparse

import httpx

from . import db

YOUTUBE_HOSTS = ("youtube.com", "ytimg.com", "googlevideo.com", "youtu.be", "ggpht.com", "youtube-nocookie.com")
API_HOSTS = ("googleapis.com",)
MODEL_HOSTS = ("huggingface.co", "hf.co", "cdn-lfs.huggingface.co", "cdn-lfs.hf.co", "xethub.hf.co")


class BlockedHost(RuntimeError):
    pass


def _host_matches(host: str, suffixes) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in suffixes)


def is_local(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def allowed(url: str, purpose: str = "youtube") -> bool:
    """purpose: youtube | api | altfront | local | models."""
    host = urlparse(url).hostname or ""
    s = db.get_settings()
    if purpose == "local":
        return is_local(host)
    if purpose == "thumb":  # static thumbnails from the CDN: allowlisted and proxied, but no politeness pause
        return _host_matches(host, ("ytimg.com",))
    if purpose == "models":
        return _host_matches(host, MODEL_HOSTS)
    if purpose == "api":
        return bool(s.get("api_enabled") and s.get("api_key")) and _host_matches(host, API_HOSTS)
    if purpose == "altfront":
        base = urlparse(s.get("altfront_url") or "").hostname
        return bool(base) and host == base
    return _host_matches(host, YOUTUBE_HOSTS)


class Throttle:
    def __init__(self):
        self._lock = threading.Lock()
        self._last = 0.0
        self._sem = None
        self._sem_n = None

    def _semaphore(self, n: int) -> threading.BoundedSemaphore:
        with self._lock:
            if self._sem is None or self._sem_n != n:
                self._sem, self._sem_n = threading.BoundedSemaphore(max(1, n)), n
            return self._sem

    def wait(self, pause: float) -> None:
        with self._lock:
            delta = time.time() - self._last
            jitter = pause * random.uniform(0, 0.3)
            if delta < pause + jitter:
                time.sleep(pause + jitter - delta)
            self._last = time.time()


THROTTLE = Throttle()


def proxy() -> str | None:
    p = (db.get_settings().get("proxy") or "").strip()
    return p or None


# EU visitors get redirected to consent.youtube.com. "SOCS=CAI" is the "reject all" answer of that
# cookie banner (no identity, no account). Same approach as yt-dlp. Nothing else is ever sent.
CONSENT_COOKIES = {"SOCS": "CAI"}


def client(purpose: str = "youtube", timeout: float | None = None) -> httpx.Client:
    s = db.get_settings()
    px = None if purpose == "local" else proxy()
    cookies = CONSENT_COOKIES if purpose == "youtube" else None
    purpose_headers = {"Accept-Language": "ru,en;q=0.8"}
    return httpx.Client(proxy=px, timeout=timeout or s.get("timeout", 20), follow_redirects=True,
                        trust_env=False, cookies=cookies, headers=purpose_headers)


def request(method: str, url: str, purpose: str = "youtube", stop=None, **kw) -> httpx.Response:
    """Polite request with allowlist, pause, parallelism limit and exponential backoff."""
    if not allowed(url, purpose):
        raise BlockedHost(f"blocked by allowlist ({purpose}): {urlparse(url).hostname}")
    s = db.get_settings()
    retries = int(s.get("retries", 3))
    polite = purpose in ("youtube", "api", "altfront")
    sem = THROTTLE._semaphore(int(s.get("max_parallel", 2))) if polite else None
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        if stop is not None and stop():
            raise InterruptedError("stopped")
        if polite:
            THROTTLE.wait(float(s.get("request_pause", 1.5)))
        try:
            if sem:
                sem.acquire()
            try:
                with client(purpose, kw.pop("timeout", None)) as c:
                    r = c.request(method, url, **kw)
            finally:
                if sem:
                    sem.release()
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(60, 2 ** attempt * 2))
                continue
            return r
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(min(60, 2 ** attempt * 2))
    raise last_exc or RuntimeError("request failed")


def get(url: str, purpose: str = "youtube", **kw) -> httpx.Response:
    return request("GET", url, purpose, **kw)


def post(url: str, purpose: str = "youtube", **kw) -> httpx.Response:
    return request("POST", url, purpose, **kw)
