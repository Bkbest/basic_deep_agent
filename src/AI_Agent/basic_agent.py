import asyncio
import logging
import sys

from croniter import croniter
from langgraph.graph import START, StateGraph
from AI_Nodes.nodes import (
    is_tool_required,
    llm_with_tools,
    llm_is_task_complete,
    route_after_completion_check,
    seed_standing_todos,
)
from AI_State.state import State
from langgraph.prebuilt.tool_node import (
    ToolNode
)
from AI_Tools.tools import MyTools
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres import PostgresSaver
import os
from dotenv import load_dotenv
import asyncpg
from langgraph.types import RetryPolicy
from datetime import datetime, timezone

load_dotenv()

logger = logging.getLogger(__name__)


def _tool_error_message(error: Exception) -> str:
    """Turn a tool failure into a ToolMessage the model can recover from.

    Without this, ``ToolNode`` re-raises and a single transient MCP timeout
    (e.g. ``httpcore.ReadTimeout`` from a streamable-HTTP server) aborts the
    whole agent run instead of letting the model try another approach.
    """
    detail = str(error).strip() or type(error).__name__
    return (
        f"Tool call failed: {detail}\n"
        "This may be a temporary network or service problem. "
        "Retry the call, or continue with a different approach."
    )


def create_research_brief_workflow():
    # Create the workflow graph
    workflow = StateGraph(state_schema=State)
    all_tools = MyTools().getToolsSync()

    # Add nodes
    workflow.add_node("llm_with_tools", llm_with_tools,retry_policy=RetryPolicy(max_attempts=3))
    workflow.add_node(
        "tool_node",
        ToolNode(all_tools, handle_tool_errors=_tool_error_message),
        retry_policy=RetryPolicy(max_attempts=3),
    )
    workflow.add_node("llm_is_task_complete", llm_is_task_complete)
    workflow.add_node("seed_todos", seed_standing_todos)

    # Add edges
    # Seeding runs once per human turn, so the standing todos are not reset
    # again on each tool round.
    workflow.add_edge(START, "seed_todos")
    workflow.add_edge("seed_todos", "llm_with_tools")
    workflow.add_conditional_edges("llm_with_tools", is_tool_required)
    workflow.add_edge("tool_node", "llm_with_tools")
    workflow.add_conditional_edges("llm_is_task_complete", route_after_completion_check)
    
    graph = workflow.compile()
    
    return graph

async def invoke_workflow_stream(thread_id, message):
    """
    Async generator that yields chunks from the workflow
    """
    # Create the workflow graph
    workflow = StateGraph(state_schema=State)
    all_tools = await MyTools().getAllTools()
    # Add nodes
    workflow.add_node("llm_with_tools", llm_with_tools,retry_policy=RetryPolicy(max_attempts=3))
    workflow.add_node(
        "tool_node",
        ToolNode(all_tools, handle_tool_errors=_tool_error_message),
        retry_policy=RetryPolicy(max_attempts=3),
    )
    workflow.add_node("llm_is_task_complete", llm_is_task_complete)
    workflow.add_node("seed_todos", seed_standing_todos)

    # Add edges
    workflow.add_edge(START, "seed_todos")
    workflow.add_edge("seed_todos", "llm_with_tools")
    workflow.add_conditional_edges("llm_with_tools", is_tool_required)
    workflow.add_edge("tool_node", "llm_with_tools")
    workflow.add_conditional_edges("llm_is_task_complete", route_after_completion_check)

    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:  
        
        try:
            await checkpointer.setup()
        except Exception as e:
            print(f"Error setting up checkpointer: {e}")
            return
        
        try:
            await create_thread(thread_id)
        except Exception as e:
            print(f"Error creating thread: {e}")
            # Checkpointer might have done its job, so clean it up
            await asyncio.to_thread(checkpointer.delete_thread, thread_id)
            return
        
    
        graph = workflow.compile(checkpointer=checkpointer)
        skills = await get_skills_description()
        soul = await get_thread_soul(thread_id)
        
        
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10000}
        
        async for chunk in graph.astream({"messages": message,"current_date": get_current_date(), "skills_description": skills, "soul": soul},stream_mode="updates", config=config ):
            yield chunk


async def invoke_workflow(prompt: str, thread_id: str = "default"):
    """
    Invoke the workflow with a prompt and return the full output.
    """
    graph = create_research_brief_workflow()
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 10000}
    
    skills = await get_skills_description()
    soul = await get_thread_soul(thread_id)
   
    output = graph.invoke(
       {"messages": prompt,"current_date": get_current_date(), "skills_description": skills, "soul": soul},
        config=config
    )
    if output and 'messages' in output:
        agent_response = output['messages'][-1].content if output['messages'] else "No response"
        return agent_response
    return "No output from workflow"

            
def get_current_date() -> str:
    """Get current date"""
    return datetime.now().strftime("%a %b %d, %Y")


async def get_skills_description() -> str:
    """Fetch all skills from the database and format them as a readable string."""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        return "Skills: none (database not configured)"

    try:
        conn = await asyncpg.connect(connection_string)
        try:
            rows = await conn.fetch("SELECT skill_name, skill_description FROM skills")
            if not rows:
                return "Skills: none"
            lines = ["Skills:"]
            for row in rows:
                lines.append(f"  - {row['skill_name']}: {row['skill_description']}")
            return "\n".join(lines)
        finally:
            await conn.close()
    except Exception:
        return "Skills: unable to fetch"

            
async def delete_thread(thread_id):
    """
    delete all checkpoints for a thread and remove from threads table
    """

    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    
    try:
        with PostgresSaver.from_conn_string(connection_string) as checkpointer:  
            try:
                checkpointer.delete_thread(thread_id)
            except Exception as e:
                print(f"Error deleting checkpointer thread: {e}")
                return
        
        # Also delete from threads table
        try:
            conn = await asyncpg.connect(connection_string)
            try:
                await conn.execute('DELETE FROM threads WHERE thread_id = $1', thread_id)
            finally:
                await conn.close()
        except Exception as e:
            print(f"Error deleting thread from threads table: {e}")
            
    except Exception as e:
        print(f"Error in delete_thread: {e}")
        
        
async def create_thread(thread_id, soul: str = None):
    """
    create a new thread by inserting thread_id into threads table
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    
    try:
        # Connect to PostgreSQL
        conn = await asyncpg.connect(connection_string)
        
        try:
            # Create threads table if it doesn't exist (with soul column)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id VARCHAR(255) PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    soul TEXT
                )
            ''')
            
            # Add soul column if it doesn't exist (for existing tables)
            try:
                await conn.execute('''
                    ALTER TABLE threads ADD COLUMN IF NOT EXISTS soul TEXT
                ''')
            except Exception:
                pass  # Column might already exist
            
            # Insert the thread_id with soul
            # If thread exists and soul is not None, update soul; otherwise keep existing soul
            if soul is not None:
                # Update if exists, insert if not
                await conn.execute(
                    '''INSERT INTO threads (thread_id, soul) VALUES ($1, $2) 
                       ON CONFLICT (thread_id) DO UPDATE SET soul = $2''',
                    thread_id, soul
                )
            else:
                # Only insert if not exists, do nothing if exists
                await conn.execute(
                    '''INSERT INTO threads (thread_id, soul) VALUES ($1, $2) 
                       ON CONFLICT (thread_id) DO NOTHING''',
                    thread_id, soul
                )
            
        finally:
            await conn.close()
            
    except Exception as e:
        raise Exception(f"Failed to create thread: {str(e)}")

async def get_threads():
    """
    Get all distinct thread IDs from the database
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    
    try:
        conn = await asyncpg.connect(connection_string)
        try:
            # Query distinct thread_ids from the threads table (including soul)
            rows = await conn.fetch('SELECT thread_id, created_at, soul FROM threads ORDER BY created_at DESC')
            
            threads = []
            for row in rows:
                threads.append({
                    "thread_id": row['thread_id'],
                    "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                    "soul": row['soul']
                })
            
            return {"threads": threads, "count": len(threads)}
            
        finally:
            await conn.close()
            
    except Exception as e:
        raise Exception(f"Failed to fetch threads: {str(e)}")


async def get_thread_soul(thread_id: str) -> str:
    """
    Get the soul for a specific thread from the database.
    
    Args:
        thread_id: The thread ID to look up
        
    Returns:
        The soul string for the thread, or None if not found
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        return None
    
    try:
        conn = await asyncpg.connect(connection_string)
        try:
            row = await conn.fetchrow(
                'SELECT soul FROM threads WHERE thread_id = $1',
                thread_id
            )
            return row['soul'] if row else None
        finally:
            await conn.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cron job persistence
# ---------------------------------------------------------------------------

CRON_TABLE = "crons"


def _to_iso_z(value) -> str:
    """Return a UTC ISO-8601 string with a `Z` suffix (or None)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _cron_row_to_dict(row) -> dict:
    """Map a crons table row to the public cron payload."""
    return {
        "cron_id": row["cron_id"],
        "name": row["name"],
        "thread_id": row["thread_id"],
        "prompt": row["prompt"],
        "schedule": row["schedule"],
        "is_active": row["is_active"],
        "created_at": _to_iso_z(row["created_at"]),
        "next_run_at": _to_iso_z(row["next_run_at"]),
        "last_run_at": _to_iso_z(row["last_run_at"]),
    }


async def ensure_crons_table(conn) -> None:
    """Create the crons table if it does not already exist."""
    await conn.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {CRON_TABLE} (
            cron_id     VARCHAR(255) PRIMARY KEY,
            name        VARCHAR(255) NOT NULL UNIQUE,
            thread_id   VARCHAR(255) NOT NULL,
            prompt      TEXT NOT NULL,
            schedule    VARCHAR(255) NOT NULL,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            next_run_at TIMESTAMPTZ,
            last_run_at TIMESTAMPTZ
        )
        '''
    )
    # Upgrade older databases in place so a reboot needs no manual migration.
    await conn.execute(
        f'ALTER TABLE {CRON_TABLE} ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ'
    )


async def save_cron(
    name: str,
    prompt: str,
    schedule: str,
    thread_id: str,
    is_active: bool = True,
) -> dict:
    """
    Create (or update) a cron job and return the stored record.

    Args:
        name: Human readable cron name, e.g. "Daily Tech Digest".
        prompt: Prompt sent to the agent on every run.
        schedule: Standard 5-field cron expression, e.g. "0 9 * * *".
        thread_id: Thread supplied by the UI (required). It is also used as the
            cron_id, so the cron and its thread always stay aligned.
        is_active: Whether the cron should be scheduled.

    Returns:
        dict: The saved cron, including cron_id, thread_id and next_run_at.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    if not name or not str(name).strip():
        raise ValueError("name is required")
    if not prompt or not str(prompt).strip():
        raise ValueError("prompt is required")
    if not schedule or not croniter.is_valid(str(schedule).strip()):
        raise ValueError(f"invalid cron schedule: {schedule!r}")
    if not thread_id or not str(thread_id).strip():
        raise ValueError("thread_id is required")

    name = str(name).strip()
    prompt = str(prompt)
    schedule = str(schedule).strip()
    thread_id = str(thread_id).strip()

    # Compute the next run time in UTC
    now = datetime.now(timezone.utc)
    next_run_at = croniter(schedule, now).get_next(datetime) if is_active else None

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)

        # Upsert on name so re-saving a cron keeps its cron_id stable.
        existing = await conn.fetchrow(
            f'SELECT cron_id FROM {CRON_TABLE} WHERE name = $1',
            name
        )
        cron_id = existing["cron_id"] if existing else thread_id

        row = await conn.fetchrow(
            f'''
            INSERT INTO {CRON_TABLE}
                (cron_id, name, thread_id, prompt, schedule, is_active, next_run_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (name) DO UPDATE SET
                thread_id   = EXCLUDED.thread_id,
                prompt      = EXCLUDED.prompt,
                schedule    = EXCLUDED.schedule,
                is_active   = EXCLUDED.is_active,
                next_run_at = EXCLUDED.next_run_at
            RETURNING *
            ''',
            cron_id, name, thread_id, prompt, schedule, is_active, next_run_at
        )

        # Ensure the thread used for checkpoints exists
        try:
            await create_thread(row["thread_id"])
        except Exception as e:
            print(f"Warning: could not create thread for cron {row['thread_id']}: {e}")

        return _cron_row_to_dict(row)
    finally:
        await conn.close()


async def get_crons(active_only: bool = False) -> list:
    """
    Fetch all cron jobs.

    Args:
        active_only: When True, only active crons are returned.

    Returns:
        list: Cron payloads ordered by creation time (newest first).
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)

        query = f'SELECT * FROM {CRON_TABLE}'
        if active_only:
            query += ' WHERE is_active = TRUE'
        query += ' ORDER BY created_at DESC'

        rows = await conn.fetch(query)
        return [_cron_row_to_dict(row) for row in rows]
    finally:
        await conn.close()


async def get_cron(cron_id: str) -> dict:
    """Fetch a single cron by cron_id (or thread_id), or None if not found."""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)
        row = await conn.fetchrow(
            f'SELECT * FROM {CRON_TABLE} WHERE cron_id = $1 OR thread_id = $1',
            cron_id
        )
        return _cron_row_to_dict(row) if row else None
    finally:
        await conn.close()


async def delete_cron(cron_id: str) -> bool:
    """Delete a cron and the thread it runs on.

    The cron's thread is created for it alone (`save_cron` creates it and cron
    runs are checkpointed there), so deleting only the cron row would leave an
    orphaned thread plus its checkpoints behind.

    The row is read before deleting so the thread id is known: callers may pass
    either a cron_id or a thread_id, and the two can differ when a cron was
    renamed.

    Args:
        cron_id: The cron's cron_id or its thread_id.

    Returns:
        bool: True if a cron row was removed.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)
        row = await conn.fetchrow(
            f'SELECT thread_id FROM {CRON_TABLE} WHERE cron_id = $1 OR thread_id = $1',
            cron_id
        )
        result = await conn.execute(
            f'DELETE FROM {CRON_TABLE} WHERE cron_id = $1 OR thread_id = $1',
            cron_id
        )
        deleted = result.endswith(" 1")
    finally:
        await conn.close()

    if deleted and row is not None and row["thread_id"]:
        try:
            await delete_thread(row["thread_id"])
        except Exception as e:
            # The cron is already gone; a thread cleanup failure must not make
            # the delete look unsuccessful.
            logger.warning(
                "Could not delete thread %s for cron %s: %s",
                row["thread_id"],
                cron_id,
                e,
            )

    return deleted


async def set_cron_active(cron_id: str, is_active: bool) -> dict:
    """Enable or disable a cron and recompute next_run_at. Returns the updated cron."""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)

        row = await conn.fetchrow(
            f'SELECT * FROM {CRON_TABLE} WHERE cron_id = $1 OR thread_id = $1',
            cron_id
        )
        if not row:
            return None

        next_run_at = None
        if is_active:
            now = datetime.now(timezone.utc)
            next_run_at = croniter(row["schedule"], now).get_next(datetime)

        updated = await conn.fetchrow(
            f'''
            UPDATE {CRON_TABLE}
               SET is_active = $2, next_run_at = $3
             WHERE cron_id = $1
            RETURNING *
            ''',
            row["cron_id"], is_active, next_run_at
        )
        return _cron_row_to_dict(updated)
    finally:
        await conn.close()


async def ensure_crons_table_exists() -> None:
    """Create the crons table (standalone connection, for app startup)."""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)
    finally:
        await conn.close()


def _next_occurrence(schedule: str, after: datetime) -> datetime:
    """Return the next UTC run time strictly after `after`."""
    return croniter(schedule, after).get_next(datetime)


async def claim_due_crons(limit: int = 50) -> list:
    """
    Atomically claim crons that are due and advance their schedule.

    Claiming happens *before* the workflow runs and is committed immediately.
    That gives at-most-once semantics: if the server dies mid-run, the claimed
    occurrence is never re-fired on restart (missed runs are skipped).

    Args:
        limit: Maximum number of crons to claim in one tick.

    Returns:
        list: Claimed cron payloads, including the advanced `next_run_at`.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)

        async with conn.transaction():
            rows = await conn.fetch(
                f'''
                SELECT * FROM {CRON_TABLE}
                 WHERE is_active = TRUE
                   AND next_run_at IS NOT NULL
                   AND next_run_at <= $1
                 ORDER BY next_run_at
                 LIMIT $2
                 FOR UPDATE SKIP LOCKED
                ''',
                datetime.now(timezone.utc), limit
            )

            claimed = []
            for row in rows:
                try:
                    next_run_at = _next_occurrence(row["schedule"], datetime.now(timezone.utc))
                except Exception as e:
                    print(f"⚠️  Cron {row['cron_id']} has an invalid schedule {row['schedule']!r}: {e}")
                    continue

                updated = await conn.fetchrow(
                    f'''
                    UPDATE {CRON_TABLE}
                       SET last_run_at = $2, next_run_at = $3
                     WHERE cron_id = $1
                    RETURNING *
                    ''',
                    row["cron_id"], datetime.now(timezone.utc), next_run_at
                )
                claimed.append(_cron_row_to_dict(updated))

            return claimed
    finally:
        await conn.close()


async def recompute_cron_next_runs() -> int:
    """
    Reconcile `next_run_at` with the stored schedules (called on startup).

    Missed runs are intentionally skipped: any cron whose `next_run_at` is
    NULL or in the past is moved forward to its next future occurrence instead
    of being fired. Inactive crons have `next_run_at` cleared.

    Returns:
        int: Number of rows adjusted.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")

    conn = await asyncpg.connect(connection_string)
    try:
        await ensure_crons_table(conn)
        now = datetime.now(timezone.utc)

        rows = await conn.fetch(f'SELECT cron_id, schedule, is_active, next_run_at FROM {CRON_TABLE}')
        adjusted = 0

        for row in rows:
            if not row["is_active"]:
                if row["next_run_at"] is not None:
                    await conn.execute(
                        f'UPDATE {CRON_TABLE} SET next_run_at = NULL WHERE cron_id = $1',
                        row["cron_id"]
                    )
                    adjusted += 1
                continue

            if row["next_run_at"] is not None and row["next_run_at"] > now:
                continue

            try:
                next_run_at = _next_occurrence(row["schedule"], now)
            except Exception as e:
                print(f"⚠️  Cron {row['cron_id']} has an invalid schedule {row['schedule']!r}: {e}")
                continue

            await conn.execute(
                f'UPDATE {CRON_TABLE} SET next_run_at = $2 WHERE cron_id = $1',
                row["cron_id"], next_run_at
            )
            adjusted += 1

        return adjusted
    finally:
        await conn.close()


def get_thread(thread_id):
    """
    Get a specific thread by thread_id
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    try:
        with PostgresSaver.from_conn_string(connection_string) as checkpointer:  
            try:
                config = {"configurable": {"thread_id": thread_id}}
                result = checkpointer.get_tuple(config)
                return result
            except Exception as e:
                print(f"Error getting checkpointer thread: {e}")
                return
            
    except Exception as e:
        print(f"Error in get_thread: {e}")
    
    
        


graph = create_research_brief_workflow()

if __name__ == "__main__":
    # Example usage
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
    async def main():
        
        # Then invoke the workflow stream
        # async for chunk in invoke_workflow_stream("17", [HumanMessage("do you know any skills, don't access any tools.")]):
        #     print(chunk)
        
        # Finally, clean up by deleting the thread
        print(await get_threads())
        # await print(get_thread("thread_2e61jwp1a_1774693865061"))
    
    asyncio.run(main())
