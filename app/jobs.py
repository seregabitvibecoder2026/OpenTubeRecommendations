"""Background jobs: one thread each, cooperative stop, progress + log persisted in the `jobs` table.
Nothing starts by itself (except the optional auto-updater, off by default)."""
from __future__ import annotations

import threading
import time
import traceback
from typing import Callable

from . import db

MAX_LOG = 400


class JobCtx:
    def __init__(self, jid: int, kind: str, pid: str | None, params: dict):
        self.id, self.kind, self.pid, self.params = jid, kind, pid, params
        self._stop = threading.Event()
        self.progress_i = 0
        self.total = 0
        self.message = ""
        self.lines: list[str] = []
        self._last_flush = 0.0

    # API for job functions
    def stopped(self) -> bool:
        return self._stop.is_set()

    def check(self) -> None:
        if self._stop.is_set():
            raise InterruptedError("stopped")

    def log(self, msg: str) -> None:
        self.lines.append(time.strftime("%H:%M:%S ") + str(msg))
        if len(self.lines) > MAX_LOG:
            self.lines = self.lines[-MAX_LOG:]
        self._flush()

    def progress(self, i: int, total: int | None = None, msg: str | None = None) -> None:
        self.progress_i = i
        if total is not None:
            self.total = total
        if msg is not None:
            self.message = msg
        self._flush()

    def _flush(self, force: bool = False) -> None:
        if not force and time.time() - self._last_flush < 0.5:
            return
        self._last_flush = time.time()
        db.ex("UPDATE jobs SET progress=?, total=?, message=?, log=? WHERE id=?",
              (self.progress_i, self.total, self.message, "\n".join(self.lines), self.id), bump_version=False)


REGISTRY: dict[str, tuple[str, Callable[[JobCtx], None]]] = {}
RUNNING: dict[int, JobCtx] = {}
_lock = threading.Lock()


def register(kind: str, title: str):
    def deco(fn):
        REGISTRY[kind] = (title, fn)
        return fn
    return deco


def start(kind: str, pid: str | None = None, params: dict | None = None) -> int:
    if kind not in REGISTRY:
        raise KeyError(kind)
    with _lock:
        for c in RUNNING.values():
            if c.kind == kind and c.pid == pid and not params:
                return c.id  # already running
        jid = db.ex("INSERT INTO jobs(kind, profile_id, status, progress, total, message, log, started, params) "
                    "VALUES(?,?,?,?,?,?,?,?,?)", (kind, pid, "running", 0, 0, "", "", time.time(), db.jdumps(params or {})),
                    bump_version=False)
        ctx = JobCtx(jid, kind, pid, params or {})
        RUNNING[jid] = ctx
    th = threading.Thread(target=_run, args=(ctx,), daemon=True, name=f"job-{kind}-{jid}")
    th.start()
    return jid


def _run(ctx: JobCtx) -> None:
    fn = REGISTRY[ctx.kind][1]
    status = "done"
    try:
        fn(ctx)
        if ctx.stopped():
            status = "stopped"
    except InterruptedError:
        status = "stopped"
        ctx.log("остановлено пользователем")
    except Exception as e:  # noqa: BLE001
        status = "error"
        ctx.log(f"ошибка: {e}")
        ctx.log(traceback.format_exc()[-1500:])
    finally:
        ctx._flush(force=True)
        db.ex("UPDATE jobs SET status=?, finished=? WHERE id=?", (status, time.time(), ctx.id))
        with _lock:
            RUNNING.pop(ctx.id, None)


def stop(jid: int) -> None:
    c = RUNNING.get(jid)
    if c:
        c._stop.set()
        c.log("запрошена остановка…")


def stop_all() -> None:
    for c in list(RUNNING.values()):
        c._stop.set()


def running() -> list[JobCtx]:
    return list(RUNNING.values())


def recent(limit: int = 30) -> list[dict]:
    return [dict(r) for r in db.q("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]


def mark_orphans() -> None:
    """Jobs left 'running' by a previous process."""
    db.ex("UPDATE jobs SET status='interrupted' WHERE status='running'", bump_version=False)


# ---------------------------------------------------------------- optional auto updater (off by default)
_auto_thread: threading.Thread | None = None


def auto_updater_loop() -> None:
    from . import profiles
    last = time.time()
    while True:
        time.sleep(60)
        hours = float(db.get_settings().get("auto_update_hours") or 0)
        if hours <= 0:
            last = time.time()
            continue
        if time.time() - last >= hours * 3600:
            last = time.time()
            pid = profiles.active_id()
            if pid:
                start("refresh", pid)


def start_auto_updater() -> None:
    global _auto_thread
    if _auto_thread is None:
        _auto_thread = threading.Thread(target=auto_updater_loop, daemon=True, name="auto-updater")
        _auto_thread.start()
