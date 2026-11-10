"""UI smoke test: offline, no models, no GPU — everything renders ("Лёгкий")."""
from fastapi.testclient import TestClient

from app import db, jobs
from app.main import app
from tests.helpers import add_channel, add_video, rate


def client():
    return TestClient(app)


def test_pages_render_offline():
    with client() as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/wizard"
        r = c.post("/wizard", data={"mode": "light", "template": "rest"}, follow_redirects=False)
        assert r.status_code == 303
        for p in ("/feed", "/channels", "/rules", "/jobs", "/jobs/panel", "/jobs/indicator", "/models", "/models?kind=llm",
                  "/settings", "/profiles", "/wizard"):
            assert c.get(p).status_code == 200, p


def test_feed_feedback_and_thumb_fallback():
    with client() as c:
        c.post("/wizard", data={"mode": "light", "template": "rest"})
        from app import profiles
        pid = profiles.active_id()
        ch = add_channel(pid, title="Канал")
        v1 = add_video(ch, "Смешные коты 1", vid_id="AAAAAAAAAA1")
        add_video(ch, "Смешные коты 2", vid_id="AAAAAAAAAA2")
        html = c.get("/feed").text
        assert "Смешные коты 1" in html and "почему тут" in html
        assert c.post(f"/fb/{v1}/like", headers={"HX-Request": "true"}).text == ""
        assert "Смешные коты 1" not in c.get("/feed").text
        r = c.get(f"/open/AAAAAAAAAA2", follow_redirects=False)
        assert r.headers["location"].startswith("https://www.youtube.com/watch?v=")
        assert db.q1("SELECT count(*) FROM feedback WHERE kind='opened'")[0] == 1
        r = c.get("/thumb/AAAAAAAAAA2")  # offline -> placeholder, no crash
        assert r.status_code == 200
        assert c.get(f"/video/AAAAAAAAAA2").status_code == 200


def test_profile_switch_changes_feed():
    with client() as c:
        c.post("/wizard", data={"mode": "light", "template": "rest"})
        from app import profiles
        a = profiles.active_id()
        ch = add_channel(a, title="Only A")
        add_video(ch, "Видео профиля А")
        c.post("/profiles/create", data={"name": "B", "template": "empty"})
        import re
        cards = re.findall(r'<article class="([^"]*)"[^>]*>(.*?)</article>', c.get("/feed").text, re.S)
        # B has no own channels: A's video may only appear as an "exploration" pick from the shared pool
        assert all("explore" in cls for cls, body in cards if "Видео профиля А" in body)
        b = profiles.active_id()
        profiles.update_settings(b, {"exploration": 0})
        assert "Видео профиля А" not in c.get("/feed").text
        c.post("/profiles/switch", data={"pid": a})
        cards = re.findall(r'<article class="([^"]*)"[^>]*>(.*?)</article>', c.get("/feed").text, re.S)
        assert any("Видео профиля А" in body and "explore" not in cls for cls, body in cards)


def test_settings_and_rules_forms():
    with client() as c:
        c.post("/wizard", data={"mode": "light", "template": "rest"})
        c.post("/rules/questions", data={"q_key": ["fun", "x"], "q_text": ["Смешно?", ""], "q_weight": ["0.5", "1"]})
        from app import profiles
        assert profiles.settings(profiles.active_id())["llm_questions"] == [{"key": "fun", "text": "Смешно?", "weight": 0.5}]
        c.post("/rules/lists", data={"list__stopword__*": "#shorts\nреакция", "new_kind": "topic", "new_lang": "de", "new_items": "katze: 0.5"})
        kinds = {(r["kind"], r["lang"], r["pattern"]) for r in profiles.rules(profiles.active_id())}
        assert ("stopword", "*", "реакция") in kinds and ("topic", "de", "katze") in kinds
        c.post("/settings", data={"proxy": "socks5://127.0.0.1:9050", "request_pause": "2", "sub_langs": "ru en de",
                                  "listing__ytdlp_tab": "1", "listing__ytdlp_tab__order": "1", "listing__rss": "1", "listing__rss__order": "2"})
        s = db.get_settings()
        assert s["proxy"] == "socks5://127.0.0.1:9050" and s["sub_langs"] == ["ru", "en", "de"]
        assert [p["name"] for p in s["listing_order"]][:2] == ["ytdlp_tab", "rss"]


def test_jobs_start_and_stop():
    import time
    with client() as c:
        c.post("/wizard", data={"mode": "light", "template": "rest"})

        @jobs.register("_slow", "slow")
        def _slow(ctx):
            for i in range(100):
                ctx.check()
                ctx.progress(i, 100)
                time.sleep(0.05)
        c.post("/jobs/start/_slow")
        time.sleep(0.2)
        assert jobs.running()
        jid = jobs.running()[0].id
        c.post(f"/jobs/{jid}/stop")
        for _ in range(50):
            if not jobs.running():
                break
            time.sleep(0.05)
        assert db.q1("SELECT status FROM jobs WHERE id=?", (jid,))[0] == "stopped"


def test_llm_job_without_model_reports_and_does_not_crash():
    import time
    with client() as c:
        c.post("/wizard", data={"mode": "light", "template": "rest"})
        c.post("/jobs/start/llm")
        for _ in range(100):
            if not jobs.running():
                break
            time.sleep(0.05)
        row = db.q1("SELECT status, log FROM jobs WHERE kind='llm'")
        assert row["status"] == "done" and "LLM недоступна" in row["log"]
