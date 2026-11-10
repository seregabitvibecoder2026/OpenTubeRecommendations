"""Profiles: local data partitions (not accounts). Export/import as JSON presets."""
from __future__ import annotations

import uuid

from . import config, db

EXPORT_FORMAT = "OpenTubeRecommendations-profile/1"


def all_profiles() -> list[dict]:
    return [dict(r) for r in db.q("SELECT id, name, color, icon, created_at FROM profiles ORDER BY created_at")]


def get(pid: str) -> dict | None:
    r = db.q1("SELECT * FROM profiles WHERE id=?", (pid,))
    if not r:
        return None
    d = dict(r)
    d["settings"] = config.deep_merge(config.DEFAULT_PROFILE_SETTINGS, db.jloads(d["settings"], {}))
    return d


def settings(pid: str) -> dict:
    p = get(pid)
    return p["settings"] if p else config.profile_defaults()


def update_settings(pid: str, patch: dict) -> None:
    p = get(pid)
    if not p:
        return
    s = config.deep_merge(p["settings"], patch)
    db.ex("UPDATE profiles SET settings=? WHERE id=?", (db.jdumps(s), pid))


def replace_setting(pid: str, key: str, value) -> None:
    """Replace a whole key (lists such as llm_questions should not be merged)."""
    p = get(pid)
    if not p:
        return
    s = p["settings"]
    s[key] = value
    db.ex("UPDATE profiles SET settings=? WHERE id=?", (db.jdumps(s), pid))


def create(name: str | None = None, template: str = "empty", pid: str | None = None) -> str:
    tpl = config.TEMPLATES.get(template, config.TEMPLATES["empty"])
    pid = pid or str(uuid.uuid4())
    s = config.deep_merge(config.DEFAULT_PROFILE_SETTINGS, tpl["settings"])
    db.ex("INSERT INTO profiles(id, name, color, icon, settings, created_at) VALUES(?,?,?,?,?,?)",
          (pid, name or tpl["name"], tpl["color"], tpl["icon"], db.jdumps(s), db.now()))
    rules = list(tpl["rules"]) + list(config.COMMON_RULES)
    db.exmany("INSERT INTO rules(profile_id, kind, lang, pattern, weight) VALUES(?,?,?,?,?)",
              [(pid, k, lang, pat, w) for (k, lang, pat, w) in rules])
    return pid


def rename(pid: str, name: str, color: str | None = None, icon: str | None = None) -> None:
    p = get(pid)
    if not p:
        return
    db.ex("UPDATE profiles SET name=?, color=?, icon=? WHERE id=?",
          (name or p["name"], color or p["color"], icon or p["icon"], pid))


def delete(pid: str) -> None:
    for t in ("feedback", "video_scores", "rules", "profile_channels", "candidates"):
        db.ex(f"DELETE FROM {t} WHERE profile_id=?", (pid,))
    db.ex("DELETE FROM profiles WHERE id=?", (pid,))
    if active_id() == pid:
        rest = all_profiles()
        db.set_setting("active_profile", rest[0]["id"] if rest else None)


def reset(pid: str) -> None:
    """Forget ratings, scores and history of a profile, keep rules/channels/settings."""
    for t in ("feedback", "video_scores"):
        db.ex(f"DELETE FROM {t} WHERE profile_id=?", (pid,))


def active_id() -> str | None:
    pid = db.get_settings().get("active_profile")
    if pid and get(pid):
        return pid
    rows = all_profiles()
    if rows:
        db.set_setting("active_profile", rows[0]["id"])
        return rows[0]["id"]
    return None


def ensure_active() -> str:
    pid = active_id()
    if not pid:
        pid = create(template="rest")
        db.set_setting("active_profile", pid)
    return pid


def set_active(pid: str) -> None:
    if get(pid):
        db.set_setting("active_profile", pid)


# ---------------------------------------------------------------- export / import
def export(pid: str, include_history: bool = False) -> dict:
    p = get(pid)
    if not p:
        raise KeyError(pid)
    out = {
        "format": EXPORT_FORMAT,
        "profile": {"id": p["id"], "name": p["name"], "color": p["color"], "icon": p["icon"]},
        "settings": p["settings"],
        "rules": [dict(kind=r["kind"], lang=r["lang"], pattern=r["pattern"], weight=r["weight"])
                  for r in db.q("SELECT * FROM rules WHERE profile_id=? ORDER BY id", (pid,))],
        "channels": [dict(id=r["channel_id"], title=r["title"], handle=r["handle"], weight=r["weight"],
                          paused=r["paused"], hidden=r["hidden"])
                     for r in db.q("""SELECT pc.*, c.title, c.handle FROM profile_channels pc
                                      LEFT JOIN channels c ON c.id=pc.channel_id WHERE pc.profile_id=?""", (pid,))],
    }
    if include_history:
        out["feedback"] = [dict(video_id=r["video_id"], kind=r["kind"], ts=r["ts"])
                           for r in db.q("SELECT * FROM feedback WHERE profile_id=? ORDER BY id", (pid,))]
    return out


def duplicate(pid: str, name: str | None = None, with_history: bool = False) -> str:
    data = export(pid, include_history=with_history)
    data["profile"]["name"] = name or (data["profile"]["name"] + " (копия)")
    return import_(data, mode="new")


def import_(data: dict, mode: str = "new") -> str:
    """mode: 'new' — always a new UUID; 'replace' — overwrite the profile with the same UUID."""
    if data.get("format") != EXPORT_FORMAT:
        raise ValueError("bad format")
    meta = data["profile"]
    if mode == "replace" and get(meta["id"]):
        pid = meta["id"]
        for t in ("rules", "profile_channels"):
            db.ex(f"DELETE FROM {t} WHERE profile_id=?", (pid,))
        if "feedback" in data:
            db.ex("DELETE FROM feedback WHERE profile_id=?", (pid,))
        db.ex("UPDATE profiles SET name=?, color=?, icon=?, settings=? WHERE id=?",
              (meta["name"], meta.get("color"), meta.get("icon"), db.jdumps(data.get("settings", {})), pid))
    else:
        pid = meta["id"] if mode == "replace" else str(uuid.uuid4())
        db.ex("INSERT INTO profiles(id, name, color, icon, settings, created_at) VALUES(?,?,?,?,?,?)",
              (pid, meta["name"], meta.get("color"), meta.get("icon"), db.jdumps(data.get("settings", {})), db.now()))
    db.exmany("INSERT INTO rules(profile_id, kind, lang, pattern, weight) VALUES(?,?,?,?,?)",
              [(pid, r["kind"], r.get("lang", "*"), r["pattern"], float(r.get("weight", 0))) for r in data.get("rules", [])])
    for ch in data.get("channels", []):
        db.ex("INSERT OR IGNORE INTO channels(id, title, handle, added_at) VALUES(?,?,?,?)",
              (ch["id"], ch.get("title"), ch.get("handle"), db.now()))
        db.ex("""INSERT OR REPLACE INTO profile_channels(profile_id, channel_id, weight, paused, hidden, added_at)
                 VALUES(?,?,?,?,?,?)""", (pid, ch["id"], float(ch.get("weight", 0)), int(ch.get("paused", 0)),
                                         int(ch.get("hidden", 0)), db.now()))
    for f in data.get("feedback", []):
        db.ex("INSERT INTO feedback(profile_id, video_id, kind, ts) VALUES(?,?,?,?)",
              (pid, f["video_id"], f["kind"], f.get("ts", db.now())))
    return pid


def rules(pid: str, kind: str | None = None) -> list[dict]:
    if kind:
        rows = db.q("SELECT * FROM rules WHERE profile_id=? AND kind=? ORDER BY id", (pid, kind))
    else:
        rows = db.q("SELECT * FROM rules WHERE profile_id=? ORDER BY id", (pid,))
    return [dict(r) for r in rows]


def set_rules(pid: str, kind: str, lang: str, entries: list[tuple[str, float]]) -> None:
    db.ex("DELETE FROM rules WHERE profile_id=? AND kind=? AND lang=?", (pid, kind, lang))
    db.exmany("INSERT INTO rules(profile_id, kind, lang, pattern, weight) VALUES(?,?,?,?,?)",
              [(pid, kind, lang, p, w) for p, w in entries])


def reset_all() -> None:
    for t in ("feedback", "video_scores", "rules", "profile_channels", "candidates", "profiles", "videos",
              "channels", "jobs", "settings"):
        db.ex(f"DELETE FROM {t}")
