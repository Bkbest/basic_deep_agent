"""Tests for resetting a cron's thread before each run.

Each cron occurrence starts from an empty history, so ``CronScheduler._run``
deletes the thread before invoking the runner. The workflow recreates the
thread, and the occurrence has already been claimed by ``claim_due_crons``,
so a failed reset must be logged and the run must still proceed.

``delete_thread`` is stubbed, so these run offline.

Run with::

    python -m pytest tests/unit_tests/test_cron_scheduler_reset.py -v
"""

import asyncio
import importlib.util
import os
import sys

try:
    import pytest
except ModuleNotFoundError:  # allow running as a plain script
    pytest = None

# Make `src` importable when this file is run directly or via pytest.
_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src",
)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def _load_cron_scheduler():
    """Load `cron_scheduler` without importing the `server` package.

    `server/__init__.py` imports `websocket_server`, which pulls in FastAPI
    wiring, auth and the agent stack. The scheduler itself only needs the
    `AI_Agent.basic_agent` cron helpers, so it is loaded straight from its file.
    """
    path = os.path.join(_SRC, "server", "cron_scheduler.py")
    spec = importlib.util.spec_from_file_location("cron_scheduler_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cron_scheduler = _load_cron_scheduler()
CronScheduler = cron_scheduler.CronScheduler

pytestmark = pytest.mark.anyio if pytest else []

CRON = {
    "cron_id": "cron-1",
    "name": "Daily Digest",
    "thread_id": "thread-1",
    "prompt": "Summarize the news",
    "schedule": "0 9 * * *",
    "is_active": True,
}


class Recorder:
    """Record the order of reset/runner calls."""

    def __init__(self, delete_error=None):
        self.calls = []
        self.delete_error = delete_error

    async def delete(self, thread_id):
        self.calls.append(("delete", thread_id))
        if self.delete_error is not None:
            raise self.delete_error

    async def runner(self, thread_id, prompt):
        self.calls.append(("runner", thread_id, prompt))


def _install(monkeypatch, recorder):
    monkeypatch.setattr(cron_scheduler, "delete_thread", recorder.delete)
    return CronScheduler(recorder.runner, poll_interval=1, max_concurrent=1)


# ---------------------------------------------------------------------------
# Reset happens before the run, on the cron's own thread
# ---------------------------------------------------------------------------


async def test_thread_is_deleted_before_the_runner(monkeypatch):
    recorder = Recorder()
    scheduler = _install(monkeypatch, recorder)

    await scheduler._run(dict(CRON))

    assert recorder.calls == [
        ("delete", "thread-1"),
        ("runner", "thread-1", "Summarize the news"),
    ]


async def test_reset_uses_the_thread_id_not_the_cron_id(monkeypatch):
    recorder = Recorder()
    scheduler = _install(monkeypatch, recorder)

    await scheduler._run({**CRON, "cron_id": "different-cron-id"})

    assert recorder.calls[0] == ("delete", "thread-1")


# ---------------------------------------------------------------------------
# A failed reset must not stop the run
# ---------------------------------------------------------------------------


async def test_run_continues_when_delete_fails(monkeypatch):
    recorder = Recorder(delete_error=RuntimeError("database is down"))
    scheduler = _install(monkeypatch, recorder)

    await scheduler._run(dict(CRON))

    assert recorder.calls == [
        ("delete", "thread-1"),
        ("runner", "thread-1", "Summarize the news"),
    ]


async def test_running_cron_id_is_released_after_a_failed_reset(monkeypatch):
    recorder = Recorder(delete_error=RuntimeError("database is down"))
    scheduler = _install(monkeypatch, recorder)
    scheduler._running_cron_ids.add(CRON["cron_id"])

    await scheduler._run(dict(CRON))

    assert CRON["cron_id"] not in scheduler._running_cron_ids


async def test_cancellation_is_not_swallowed(monkeypatch):
    recorder = Recorder(delete_error=asyncio.CancelledError())
    scheduler = _install(monkeypatch, recorder)

    try:
        await scheduler._run(dict(CRON))
    except asyncio.CancelledError:
        pass
    else:  # pragma: no cover - the reset must not convert cancel into success
        raise AssertionError("CancelledError should propagate from the reset")

    assert ("runner", "thread-1", "Summarize the news") not in recorder.calls
