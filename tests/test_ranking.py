import numpy as np

from app import ranking
from tests.helpers import add_channel, add_video, new_profile, rate

CATS = ["котики смешные коты мурлыкают", "кошки юмор приколы с котами", "смешной кот прыгает"]
CARS = ["ремонт двигателя автомобиля", "замена масла в машине", "диагностика подвески авто"]


def ids(res):
    return [it["v"]["id"] for it in res["items"]]


def setup_two_topics(pid, n=12):
    ch = add_channel(pid, title="Mix")
    cats = [add_video(ch, f"{CATS[i % 3]} выпуск {i}") for i in range(n)]
    cars = [add_video(ch, f"{CARS[i % 3]} выпуск {i}") for i in range(n)]
    return ch, cats, cars


def test_taste_prefers_liked_topic():
    pid = new_profile(exploration=0, taste_min_ratings=4)
    _, cats, cars = setup_two_topics(pid)
    for v in cats[:3]:
        rate(pid, v, "like")
    for v in cars[:3]:
        rate(pid, v, "dislike")
    res = ranking.compute(pid)
    order = ids(res)
    assert set(cats[:3]).isdisjoint(order), "rated videos are not shown again"
    top = order[:6]
    assert sum(v in cats for v in top) >= 5, res["stats"]


def test_profiles_are_isolated():
    a = new_profile(exploration=0, taste_min_ratings=4)
    b = new_profile(exploration=0, taste_min_ratings=4)
    ch, cats, cars = setup_two_topics(a)
    from app import collect
    collect.attach(b, ch)
    base_b = ids(ranking.compute(b))
    for v in cats[:4]:
        rate(a, v, "like")
    for v in cars[:4]:
        rate(a, v, "dislike")
    ranking._CACHE.clear()
    assert ids(ranking.compute(b)) == base_b, "ratings in A must not change feed of B"
    assert ids(ranking.compute(a)) != base_b


def test_age_restricted_equal_treatment():
    """Identical content, one copy 18+ without subtitles/comments: no systematic penalty or bonus."""
    pid = new_profile(exploration=0, taste_min_ratings=4)
    ch = add_channel(pid, title="Same")
    pairs = []
    for i in range(10):
        t = f"{CATS[i % 3]} серия {i}"
        normal = add_video(ch, t, subs="ну это просто кот который прыгает " * 20, comments="кот топ\nсмешно")
        restricted = add_video(ch, t, age=1)  # no subs, no comments: like many 18+ videos without login
        pairs.append((normal, restricted))
    for n_, r_ in pairs[:2]:
        rate(pid, n_, "like")
    rate(pid, pairs[2][1], "like")  # likes on 18+ count the same
    res = ranking.compute(pid, include_all=True)
    sc = {it["v"]["id"]: it["score"] for it in res["items"]}
    diffs = [sc[r] - sc[n] for n, r in pairs[3:]]
    assert abs(float(np.mean(diffs))) < 0.15, diffs
    restricted_items = [it for it in res["items"] if it["v"]["age_restricted"]]
    assert restricted_items and all("оценка по неполным данным" in it["notes"] for it in restricted_items)


def test_missing_profanity_filled_from_channel_prior():
    pid = new_profile(exploration=0, profanity_weight=1.0)
    ch = add_channel(pid)
    with_subs = [add_video(ch, f"обзор {i}", subs=("бля ну это пиздец какой-то нахуй " + "слово " * 40)) for i in range(4)]
    without = [add_video(ch, f"обзор {i + 10}") for i in range(4)]
    res = ranking.compute(pid, include_all=True)
    rules = {it["v"]["id"]: it["comp"]["rules"] for it in res["items"]}
    assert all(rules[v] > 0.3 for v in with_subs)
    assert all(abs(rules[v] - rules[with_subs[0]]) < 0.3 for v in without), "channel prior fills the gap"


def test_shorts_and_duration_filter():
    pid = new_profile(exploration=0, min_duration_sec=180)
    ch = add_channel(pid)
    long_v = add_video(ch, "длинное видео", duration=600)
    short_v = add_video(ch, "короткое", duration=45)
    from app import db
    flagged = add_video(ch, "шортс по флагу", duration=None)
    db.ex("UPDATE videos SET is_short=1 WHERE id=?", (flagged,))
    order = ids(ranking.compute(pid))
    assert long_v in order and short_v not in order and flagged not in order


def test_stopword_hides_and_language_filter():
    pid = new_profile(exploration=0, lang_filter="en")
    ch = add_channel(pid)
    en = add_video(ch, "funny cats compilation", lang="en")
    ru = add_video(ch, "смешные коты", lang="ru")
    stop = add_video(ch, "cats #shorts", lang="en")
    from app import profiles
    profiles.set_rules(pid, "stopword", "*", [("#shorts", -1.0)])
    order = ids(ranking.compute(pid))
    assert order == [en], order
    assert ru not in order and stop not in order


def test_exploration_share():
    pid = new_profile(exploration=20, feed_size=10)
    ch = add_channel(pid)
    for i in range(20):
        add_video(ch, f"видео профиля {i}")
    other = add_channel(None, title="Other")
    for i in range(10):
        add_video(other, f"чужое видео {i}")
    res = ranking.compute(pid)
    exp = [it for it in res["items"] if it["explore"]]
    assert len(res["items"]) == 10 and len(exp) == 2


def test_why_explains_factors_and_freshness():
    pid = new_profile(exploration=0)
    ch = add_channel(pid, weight=2.0)
    fresh = add_video(ch, "новое", days=0)
    old = add_video(ch, "старое", days=200)
    res = ranking.compute(pid)
    assert ids(res)[0] == fresh
    names = {w["name"] for w in res["items"][0]["why"]}
    assert {"канал", "свежесть"} <= names


def test_llm_missing_does_not_bias():
    from app import db
    pid = new_profile(exploration=0)
    ch = add_channel(pid)
    vs = [add_video(ch, f"видео {i}") for i in range(6)]
    qh = ranking.questions_hash(ranking.profiles.settings(pid)["llm_questions"])
    for v in vs[:3]:
        db.ex("INSERT INTO video_scores(profile_id, video_id, llm_scores, llm_qhash) VALUES(?,?,?,?)",
              (pid, v, db.jdumps({"scores": {"humor": 10, "agenda": 0, "clickbait": 0}}), qh))
    res = ranking.compute(pid, include_all=True)
    llm = {it["v"]["id"]: it["comp"].get("llm") for it in res["items"]}
    assert all(llm[v] is not None for v in vs), "channel prior fills missing LLM scores"


def test_logreg_kicks_in():
    pid = new_profile(exploration=0, taste_min_ratings=5, logreg_min_ratings=20)
    _, cats, cars = setup_two_topics(pid, n=24)
    for v in cats[:12]:
        rate(pid, v, "like")
    for v in cars[:12]:
        rate(pid, v, "dislike")
    res = ranking.compute(pid)
    assert "логрегрессия" in res["stats"]["taste_mode"]
    top = ids(res)[:8]
    assert sum(v in cats for v in top) >= 7
