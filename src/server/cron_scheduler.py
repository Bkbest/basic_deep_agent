"""Background scheduler that turns cron rows into agent runs.

The database is the source of truth: every tick asks `claim_due_crons()` for
rows whose `next_run_at` has passed and which are committed as claimed before
any work starts. That makes the scheduler restart-safe -- a run that was
already claimed is never fired twice, and occurrences missed while the server
was down are skipped rather than replayed.

Each occurrence is a fresh start: the cron's thread is deleted before the run
so no checkpoint history leaks from the previous occurrence. The workflow
recreates the thread itself, so a failed reset is logged and the run continues
rather than losing the already-claimed occurrence.
"""

import asyncio
import os
from typing import Awaitable, Callable, Optional

from AI_Agent.basic_agent import (
    claim_due_crons,
    delete_thread,
    recompute_cron_next_runs,
)

# A runner takes (thread_id, prompt) and streams the workflow, exactly like a
# user message would.
CronRunner = Callable[[str, str], Awaitable[None]]


def _env_int(name: str, default: int) -> int:
    """Read a positive integer from the environment, falling back to default."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(f"⚠️  Ignoring invalid {name}={raw!r}, using {default}")
        return default
    return value if value > 0 else default


class CronScheduler:
    """Poll the crons table and dispatch due prompts to the agent."""

    def __init__(
        self,
        runner: CronRunner,
        poll_interval: Optional[float] = None,
        max_concurrent: Optional[int] = None,
    ) -> None:
        self._runner = runner
        self._poll_interval = poll_interval or _env_int("CRON_POLL_INTERVAL_SECONDS", 30)
        self._max_concurrent = max_concurrent or _env_int("CRON_MAX_CONCURRENT_RUNS", 3)
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._task: Optional[asyncio.Task] = None
        self._running_cron_ids: set[str] = set()
        self._in_flight: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Reconcile schedules, then start the polling loop."""
        if self._task is not None:
            return

        try:
            adjusted = await recompute_cron_next_runs()
            if adjusted:
                print(f"🕒 Reconciled {adjusted} cron schedule(s); missed runs are skipped")
        except Exception as e:
            print(f"⚠️  Could not reconcile cron schedules on startup: {e}")

        self._task = asyncio.create_task(self._loop(), name="cron-scheduler")
        print(
            f"⏰ Cron scheduler started "
            f"(poll every {self._poll_interval}s, max {self._max_concurrent} concurrent)"
        )

    async def stop(self) -> None:
        """Stop polling and wait for in-flight runs to finish."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._in_flight:
            pending = list(self._in_flight)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        print("⏰ Cron scheduler stopped")

    async def _loop(self) -> None:
        """Poll forever, surviving individual tick failures."""
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                import traceback
                print(f"❌ Error in cron scheduler tick: {e}\n{traceback.format_exc()}")

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                raise

    async def _tick(self) -> None:
        """Claim due crons and dispatch each one as a bounded background task."""
        due = await claim_due_crons()

        for cron in due:
            cron_id = cron["cron_id"]

            # Guard against overlapping ticks dispatching the same cron
            if cron_id in self._running_cron_ids:
                print(f"⚠️  Cron {cron['name']!r} is still running, skipping this occurrence")
                continue

            self._running_cron_ids.add(cron_id)
            task = asyncio.create_task(
                self._run(cron), name=f"cron-{cron_id}"
            )
            self._in_flight.add(task)
            task.add_done_callback(self._in_flight.discard)

    async def _reset_thread(self, thread_id: str, name: str) -> None:
        """Clear the cron's thread so the run starts from an empty history.

        Best effort: the occurrence has already been claimed, so a failure here
        must not stop the run. `invoke_workflow_stream` recreates the thread
        row, so the run works even when the delete did not happen.
        """
        try:
            print(f"🧹 Resetting thread {thread_id} for cron {name!r}")
            await delete_thread(thread_id)
            print(f"🧹 Thread {thread_id} reset for cron {name!r}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            import traceback
            print(
                f"⚠️  Could not reset thread {thread_id} for cron {name!r}: {e}\n"
                f"{traceback.format_exc()}"
            )

    async def _run(self, cron: dict) -> None:
        """Run one cron's prompt on its thread, bounded by the semaphore."""
        cron_id = cron["cron_id"]
        thread_id = cron["thread_id"]
        name = cron["name"]

        try:
            # Reset before waiting for a slot: the occurrence owns this thread,
            # so its history is cleared even while other runs are in flight.
            await self._reset_thread(thread_id, name)

            async with self._semaphore:
                print(f"⏰ Running cron {name!r} on thread {thread_id}")
                await self._runner(thread_id, cron["prompt"])
                print(f"✅ Cron {name!r} completed")
        except asyncio.CancelledError:
            print(f"🛑 Cron {name!r} cancelled")
            raise
        except Exception as e:
            import traceback
            print(f"❌ Cron {name!r} failed: {e}\n{traceback.format_exc()}")
        finally:
            self._running_cron_ids.discard(cron_id)
