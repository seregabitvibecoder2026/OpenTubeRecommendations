import pytest

from app import db, net


def test_allowlist_youtube_only():
    assert net.allowed("https://www.youtube.com/feeds/videos.xml")
    assert net.allowed("https://i.ytimg.com/vi/x/mqdefault.jpg")
    assert not net.allowed("https://example.com/")
    assert not net.allowed("https://youtube.com.evil.example/")
    assert not net.allowed("https://googleapis.com/youtube/v3/videos", "api")  # key not set
    db.set_setting("api_key", "k")
    db.set_setting("api_enabled", True)
    assert net.allowed("https://www.googleapis.com/youtube/v3/videos", "api")
    assert not net.allowed("https://evil.example/", "api")


def test_thumb_purpose_only_ytimg():
    assert net.allowed("https://i.ytimg.com/vi/x/mqdefault.jpg", "thumb")
    assert not net.allowed("https://www.youtube.com/watch?v=x", "thumb")
    assert not net.allowed("https://example.com/a.jpg", "thumb")


def test_local_only_for_models():
    assert net.allowed("http://127.0.0.1:11434/api/chat", "local")
    assert net.allowed("http://localhost:8081", "local")
    assert net.allowed("http://192.168.1.5:11434", "local")
    assert not net.allowed("https://api.openai.com/v1/chat/completions", "local")
    assert not net.allowed("http://8.8.8.8/", "local")


def test_altfront_only_configured_host():
    assert not net.allowed("https://inv.example/api/v1/videos/x", "altfront")
    db.set_setting("altfront_url", "https://inv.example")
    assert net.allowed("https://inv.example/api/v1/videos/x", "altfront")
    assert not net.allowed("https://other.example/", "altfront")


def test_request_refuses_blocked_host():
    with pytest.raises(net.BlockedHost):
        net.get("https://example.com/")


def test_engines_refuse_cloud_endpoints():
    from app.ml import engines
    with pytest.raises(engines.EngineError):
        engines.chat_json("s", "u", {}, cfg={"engine": "openai", "url": "https://api.openai.com", "model": "x"})
