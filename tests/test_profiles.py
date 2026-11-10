from app import profiles
from tests.helpers import add_channel, add_video, new_profile, rate


def test_export_without_history_by_default():
    pid = new_profile("rest")
    ch = add_channel(pid, title="C", weight=1.5)
    v = add_video(ch, "x")
    rate(pid, v, "like")
    data = profiles.export(pid)
    assert data["profile"]["id"] == pid and "feedback" not in data
    assert data["channels"][0]["weight"] == 1.5 and data["rules"]
    data_h = profiles.export(pid, include_history=True)
    assert data_h["feedback"][0]["video_id"] == v


def test_import_as_new_and_replace():
    pid = new_profile("edu")
    add_channel(pid)
    data = profiles.export(pid)
    new = profiles.import_(data, "new")
    assert new != pid and profiles.get(new)["name"] == profiles.get(pid)["name"]
    data["profile"]["name"] = "Renamed"
    data["settings"]["exploration"] = 33
    same = profiles.import_(data, "replace")
    assert same == pid and profiles.get(pid)["name"] == "Renamed" and profiles.settings(pid)["exploration"] == 33
    assert len(profiles.all_profiles()) == 2


def test_duplicate_and_templates():
    pid = new_profile("edu")
    assert profiles.settings(pid)["fresh_half_life_days"] == 90
    dup = profiles.duplicate(pid)
    assert profiles.settings(dup)["fresh_half_life_days"] == 90
    assert len(profiles.rules(dup)) == len(profiles.rules(pid))


def test_delete_and_reset():
    a = new_profile()
    b = new_profile()
    ch = add_channel(a)
    v = add_video(ch, "x")
    rate(a, v, "like")
    profiles.reset(a)
    from app import db
    assert db.q1("SELECT count(*) FROM feedback WHERE profile_id=?", (a,))[0] == 0
    profiles.set_active(a)
    profiles.delete(a)
    assert profiles.get(a) is None and profiles.active_id() == b
