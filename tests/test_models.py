"""LLM / vision / embeddings jobs on fake local engines (no Ollama, no GPU needed)."""
import time

import numpy as np

from app import db, jobs, profiles, ranking, tasks  # noqa: F401
from app.ml import catalog, engines
from tests.helpers import add_channel, add_video, new_profile


def wait(jid):
    for _ in range(200):
        if jid not in jobs.RUNNING:
            break
        time.sleep(0.02)
    return db.q1("SELECT status, log FROM jobs WHERE id=?", (jid,))


def test_llm_job_writes_scores_and_marks_missing_fields(monkeypatch):
    pid = new_profile(exploration=0)
    ch = add_channel(pid)
    v1 = add_video(ch, "Смешной кот", subs="кот " * 50)
    v2 = add_video(ch, "Restricted video", age=1, lang="en")
    prompts = []

    def fake_chat(system, user, schema, cfg=None, images=None):
        prompts.append(user)
        assert set(schema["properties"]["scores"]["required"]) == {"humor", "agenda", "clickbait"}
        assert "JSON" in system
        return {"scores": {"humor": 9, "agenda": 1, "clickbait": 3}, "confidence": 0.8, "summary": "смешно"}
    monkeypatch.setattr(engines, "chat_json", fake_chat)
    monkeypatch.setattr(engines, "llm_status", lambda: {"ok": True, "model": "fake", "engine": "ollama"})
    r = wait(jobs.start("llm", pid))
    assert r["status"] == "done", r["log"]
    assert len(prompts) == 2
    restricted_prompt = next(p for p in prompts if "Restricted video" in p)
    assert "### Субтитры (фрагмент)\nНЕДОСТУПНО" in restricted_prompt and "18+: да" in restricted_prompt
    res = ranking.compute(pid, include_all=True)
    assert all("llm" in it["comp"] for it in res["items"])
    # changing the questions invalidates old answers (hash)
    profiles.replace_setting(pid, "llm_questions", [{"key": "new", "text": "?", "weight": 1}])
    assert all("llm" not in it["comp"] for it in ranking.compute(pid, include_all=True)["items"])


def test_vision_job(monkeypatch):
    pid = new_profile(exploration=0)
    ch = add_channel(pid)
    v = add_video(ch, "x")
    s = db.get_settings()
    db.set_setting("vision", dict(s["vision"], model="moondream"))
    monkeypatch.setattr(tasks, "thumb_bytes", lambda vid: b"jpeg")
    monkeypatch.setattr(engines, "describe_image", lambda img, cfg=None: "кот на диване | юмор | яркий")
    r = wait(jobs.start("vision", pid))
    assert r["status"] == "done", r["log"]
    row = db.q1("SELECT thumb_desc, evidence FROM videos WHERE id=?", (v,))
    assert "кот" in row["thumb_desc"] and db.jloads(row["evidence"])["thumbnail"] is True


def test_embed_job_and_ranking_uses_embeddings(monkeypatch):
    pid = new_profile(exploration=0, taste_min_ratings=2)
    ch = add_channel(pid)
    cats = [add_video(ch, f"кот {i}") for i in range(4)]
    cars = [add_video(ch, f"машина {i}") for i in range(4)]
    s = db.get_settings()
    db.set_setting("embed", dict(s["embed"], model="fake-emb", engine="ollama"))
    monkeypatch.setattr(engines, "embed", lambda texts, cfg=None: [[1.0, 0.1] if "кот" in t else [0.1, 1.0] for t in texts])
    r = wait(jobs.start("embed", pid))
    assert r["status"] == "done", r["log"]
    for v in cats[:2]:
        db.ex("INSERT INTO feedback(profile_id, video_id, kind, ts) VALUES(?,?,?,?)", (pid, v, "like", time.time()))
    res = ranking.compute(pid)
    assert "эмбеддингов" in res["stats"]["taste_mode"]
    order = [it["v"]["id"] for it in res["items"]]
    assert set(order[:2]) == set(cats[2:])


def test_catalog_has_licenses_and_fit_logic():
    assert all(m["license"] for m in catalog.CATALOG)
    assert {m["kind"] for m in catalog.CATALOG} == {"embed", "llm", "vision", "asr"}
    restricted = [m for m in catalog.CATALOG if not m["open"]]
    assert restricted and all(m["license"] not in catalog.OPEN_LICENSES for m in restricted)
    q8 = catalog.by_id("qwen3-8b")
    assert catalog.fits(q8, free_gb=7.5, budget_max=6) == "offload"
    assert catalog.fits(catalog.by_id("qwen3-4b"), free_gb=7.5, budget_max=6) == "yes"
    assert catalog.fits(catalog.by_id("qwen3-30b-a3b"), free_gb=7.5, budget_max=6) == "no"


def test_models_page_hides_restricted_by_default():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        html = c.get("/models?kind=all").text
        assert "Qwen3 8B" in html and "Gemma 3 4B" not in html
        html = c.get("/models?kind=all&restricted=1").text
        assert "Gemma 3 4B" in html
