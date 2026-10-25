"""Tests for ``delete_cron`` also removing its thread.

A cron owns its thread: ``save_cron`` creates it and cron runs are checkpointed
there. Deleting only the cron row therefore leaves an orphaned thread plus its
checkpoints, so ``delete_cron`` cleans up both.

The database and ``delete_thread`` are stubbed, so these run offline.

Run with::

    python -m pytest tests/unit_tests/test_delete_cron.py -v
"""

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

import AI_Agent.basic_agent as basic_agent  # noqa: E402

pytestmark = pytest.mark.anyio if pytest else []

DSN = "postgresql://user:pass@localhost:5432/test"


class FakeConn:
    """Minimal asyncpg connection stand-in."""

    def __init__(self, row, delete_status):
        self.row = row
        self.delete_status = delete_status
        self.queries = []
        self.closed = False

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        return self.row

    async def execute(self, query, *args):
        self.queries.append(query)
        return self.delete_status

    async def close(self):
        self.closed = True


def _install(monkeypatch, *, row, delete_status, thread_error=None):
    """Stub the DB layer and record ``delete_thread`` calls."""
    conn = FakeConn(row, delete_status)
    thread_calls = []

    async def fake_connect(dsn):
        assert dsn == DSN
        return conn

    async def fake_ensure_crons_table(_conn):
        return None

    async def fake_delete_thread(thread_id):
        thread_calls.append(thread_id)
        if thread_error is not None:
            raise thread_error

    monkeypatch.setenv("POSTGRES_CONNECTION_STRING", DSN)
    monkeypatch.setattr(basic_agent.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(basic_agent, "ensure_crons_table", fake_ensure_crons_table)
    monkeypatch.setattr(basic_agent, "delete_thread", fake_delete_thread)
    return conn, thread_calls


# ---------------------------------------------------------------------------
# Deleting a cron also deletes its thread
# ---------------------------------------------------------------------------


async def test_deletes_thread_when_cron_is_deleted(monkeypatch):
    _conn, threads = _install(
        monkeypatch, row={"thread_id": "thread-1"}, delete_status="DELETE 1"
    )

    assert await basic_agent.delete_cron("cron-1") is True
    assert threads == ["thread-1"]


async def test_uses_stored_thread_id_not_the_argument(monkeypatch):
    """Callers may pass a cron_id that differs from the thread_id."""
    _conn, threads = _install(
        monkeypatch, row={"thread_id": "actual-thread"}, delete_status="DELETE 1"
    )

    await basic_agent.delete_cron("some-cron-id")

    assert threads == ["actual-thread"]


async def test_no_thread_delete_when_cron_not_found(monkeypatch):
    _conn, threads = _install(monkeypatch, row=None, delete_status="DELETE 0")

    assert await basic_agent.delete_cron("missing") is False
    assert threads == []


async def test_no_thread_delete_when_row_has_no_thread_id(monkeypatch):
    _conn, threads = _install(
        monkeypatch, row={"thread_id": ""}, delete_status="DELETE 1"
    )

    assert await basic_agent.delete_cron("cron-1") is True
    assert threads == []


async def test_thread_failure_does_not_mark_delete_failed(monkeypatch):
    """The cron row is already gone, so the call still reports success."""
    _conn, threads = _install(
        monkeypatch,
        row={"thread_id": "thread-1"},
        delete_status="DELETE 1",
        thread_error=RuntimeError("checkpointer unavailable"),
    )

    assert await basic_agent.delete_cron("cron-1") is True
    assert threads == ["thread-1"]


async def test_connection_is_closed_before_deleting_thread(monkeypatch):
    """No DB connection is held open while the thread cleanup runs."""
    conn, _threads = _install(
        monkeypatch, row={"thread_id": "thread-1"}, delete_status="DELETE 1"
    )

    await basic_agent.delete_cron("cron-1")

    assert conn.closed is True


async def test_connection_closed_even_when_delete_raises(monkeypatch):
    class BoomConn(FakeConn):
        async def execute(self, query, *args):
            raise RuntimeError("delete failed")

    conn = BoomConn(row={"thread_id": "t"}, delete_status="DELETE 1")

    async def fake_connect(dsn):
        return conn

    async def fake_ensure(_conn):
        return None

    monkeypatch.setenv("POSTGRES_CONNECTION_STRING", DSN)
    monkeypatch.setattr(basic_agent.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(basic_agent, "ensure_crons_table", fake_ensure)

    try:
        await basic_agent.delete_cron("cron-1")
    except RuntimeError:
        pass

    assert conn.closed is True


async def test_missing_dsn_raises(monkeypatch):
    monkeypatch.delenv("POSTGRES_CONNECTION_STRING", raising=False)

    try:
        await basic_agent.delete_cron("cron-1")
    except ValueError as e:
        assert "POSTGRES_CONNECTION_STRING" in str(e)
    else:
        raise AssertionError("expected ValueError when the DSN is unset")
