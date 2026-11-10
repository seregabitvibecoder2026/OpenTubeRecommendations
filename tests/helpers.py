import itertools
import time

from app import collect, db, profiles

_c = itertools.count()


def vid():
    return f"v{next(_c):010d}"


def add_channel(pid, cid=None, title="Chan", weight=0.0):
    cid = cid or ("UC" + f"{next(_c):022d}")
    collect.upsert_channel(cid, title=title)
    if pid:
        collect.attach(pid, cid, weight)
    return cid


def add_video(cid, title, desc="", lang="ru", age=0, days=3, duration=900, subs=None, comments=None, vid_id=None):
    v = vid_id or vid()
    db.ex("""INSERT INTO videos(id, channel_id, title, description, tags, lang, duration, published_at, views,
             age_restricted, subtitles_text, comments_text, meta_state, first_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
          (v, cid, title, desc, "[]", lang, duration, time.time() - days * 86400, 1000, age, subs, comments, time.time()))
    collect.refresh_evidence(v)
    return v


def rate(pid, v, kind):
    db.ex("INSERT INTO feedback(profile_id, video_id, kind, ts) VALUES(?,?,?,?)", (pid, v, kind, time.time()))


def new_profile(template="empty", **settings):
    pid = profiles.create(template=template)
    if settings:
        profiles.update_settings(pid, settings)
    return pid
