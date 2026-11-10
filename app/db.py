"""SQLite storage: schema, simple migrations, settings and small helpers."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from . import config

SCHEMA_VERSION = 2

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS profiles(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT, icon TEXT,
        settings TEXT NOT NULL DEFAULT '{}', created_at REAL);
    CREATE TABLE IF NOT EXISTS channels(
        id TEXT PRIMARY KEY, handle TEXT, title TEXT, url TEXT, thumb TEXT, description TEXT,
        added_at REAL, last_fetch REAL, fetch_error TEXT, listing_source TEXT);
    CREATE TABLE IF NOT EXISTS profile_channels(
        profile_id TEXT NOT NULL, channel_id TEXT NOT NULL, weight REAL NOT NULL DEFAULT 0,
        paused INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, added_at REAL,
        PRIMARY KEY(profile_id, channel_id));
    CREATE TABLE IF NOT EXISTS videos(
        id TEXT PRIMARY KEY, channel_id TEXT, title TEXT, description TEXT, tags TEXT, lang TEXT,
        duration INTEGER, published_at REAL, views INTEGER, age_restricted INTEGER NOT NULL DEFAULT 0,
        live_status TEXT, is_short INTEGER NOT NULL DEFAULT 0,
        subtitles_text TEXT, subtitles_lang TEXT, comments_text TEXT, thumb_desc TEXT, chapters TEXT,
        evidence TEXT NOT NULL DEFAULT '{}', probe TEXT, meta_source TEXT,
        meta_state INTEGER NOT NULL DEFAULT 0, subs_state INTEGER NOT NULL DEFAULT 0,
        comments_state INTEGER NOT NULL DEFAULT 0, thumb_state INTEGER NOT NULL DEFAULT 0,
        embedding BLOB, embedding_model TEXT, first_seen REAL);
    CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
    CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, video_id TEXT NOT NULL,
        kind TEXT NOT NULL, ts REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_feedback_profile ON feedback(profile_id);
    CREATE TABLE IF NOT EXISTS video_scores(
        profile_id TEXT NOT NULL, video_id TEXT NOT NULL, llm_scores TEXT, llm_model TEXT, llm_qhash TEXT,
        score REAL, rank INTEGER, breakdown TEXT, explore INTEGER NOT NULL DEFAULT 0, updated_at REAL,
        PRIMARY KEY(profile_id, video_id));
    CREATE TABLE IF NOT EXISTS rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id TEXT NOT NULL, kind TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT '*', pattern TEXT NOT NULL, weight REAL NOT NULL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_rules_profile ON rules(profile_id);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, profile_id TEXT, status TEXT, progress INTEGER,
        total INTEGER, message TEXT, log TEXT, started REAL, finished REAL, params TEXT);
    """,
    2: """
    CREATE TABLE IF NOT EXISTS candidates(
        profile_id TEXT NOT NULL, channel_id TEXT NOT NULL, title TEXT, url TEXT, source TEXT, reason TEXT,
        score REAL, status TEXT NOT NULL DEFAULT 'new', found_at REAL,
        PRIMARY KEY(profile_id, channel_id));
    """,
}

_local = threading.local()
_lock = threading.RLock()
_db_path: Path | None = None


def db_path() -> Path:
    return _db_path or (config.data_dir() / "OpenTubeRecommendations.sqlite3")


def set_db_path(p: Path | None) -> None:
    """Used by tests to point at a temporary database."""
    global _db_path
    _db_path = p
    _local.__dict__.clear()


def conn() -> sqlite3.Connection:
    path = str(db_path())
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "path", None) != path:
        c = sqlite3.connect(path, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.conn, _local.path = c, path
    return c


def init() -> None:
    with _lock:
        c = conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER)")
        row = c.execute("SELECT version FROM schema_version").fetchone()
        cur = row[0] if row else 0
        for v in sorted(MIGRATIONS):
            if v > cur:
                c.executescript(MIGRATIONS[v])
                cur = v
        c.execute("DELETE FROM schema_version")
        c.execute("INSERT INTO schema_version(version) VALUES (?)", (cur,))
        c.commit()


def q(sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, args: tuple | list = ()) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def ex(sql: str, args: tuple | list = (), bump_version: bool = True) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        if bump_version:
            bump()
        return cur.lastrowid


def exmany(sql: str, rows: list) -> None:
    with _lock:
        c = conn()
        c.executemany(sql, rows)
        c.commit()
        bump()


# Data version: bumped on any write; ranking caches key on it.
_version = [0]


def bump() -> None:
    _version[0] += 1


def version() -> int:
    return _version[0]


# ---------------------------------------------------------------- settings
def get_settings() -> dict:
    stored = {r["key"]: json.loads(r["value"]) for r in q("SELECT key, value FROM settings")}
    return config.deep_merge(config.DEFAULT_SETTINGS, stored)


def get_setting(key: str):
    return get_settings().get(key)


def set_setting(key: str, value) -> None:
    ex("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, json.dumps(value, ensure_ascii=False)))


def now() -> float:
    return time.time()


def jloads(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def jdumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)
