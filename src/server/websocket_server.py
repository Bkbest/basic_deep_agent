import asyncio
import json
import sys
from typing import Any, Optional
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
import asyncpg
import os
from langchain_core import load

# The startup banners below use emoji. On Windows consoles the default
# encoding is cp1252, and printing them raised
#   UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'
# which aborted the module import. Reconfiguring with errors="replace" keeps
# logging unbreakable even on a legacy console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        # Stream is not a TextIOWrapper (redirected/piped) -- nothing to do.
        pass

# psycopg (used by langgraph's AsyncPostgresSaver) cannot run on Windows'
# default ProactorEventLoop. It needs a SelectorEventLoop.
#
# Setting the *policy* here is not enough: uvicorn >= 0.36 builds its own loop
# with `asyncio.run(..., loop_factory=...)`, and on Windows it passes
# `asyncio.ProactorEventLoop` unless `--loop asyncio` is used. Under the
# policy alone the app therefore ran on a Proactor loop and every workflow run
# died with:
#   psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' ...
#
# The policy is still set so that any plain `asyncio.run(...)` in this process
# (for example MCP tool discovery at import time) also gets a selector loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Loop factory that always produces a psycopg-compatible event loop."""
    return asyncio.SelectorEventLoop()


def run_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Run the ASGI app on an event loop psycopg can actually use.

    ``uvicorn.run(loop="asyncio")`` is not enough: uvicorn's
    ``asyncio_loop_factory`` returns ``asyncio.ProactorEventLoop`` on Windows
    whenever ``use_subprocess`` is false (i.e. no ``--reload`` and a single
    worker), which is exactly the loop psycopg rejects. So the server is
    served through an explicit ``asyncio.Runner`` with a selector loop
    factory instead.
    """
    host = host or os.getenv("HOST", "0.0.0.0")
    port = int(port or os.getenv("PORT", "8001"))

    print(f"Starting WebSocket server on http://{host}:{port}")
    print(f"WebSocket endpoint: ws://{host}:{port}/ws")

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        try:
            with asyncio.Runner(loop_factory=_selector_loop_factory) as runner:
                runner.run(server.serve())
        except KeyboardInterrupt:
            print("🛑 Server interrupted")
    else:
        server.run()

# Add the src directory to the path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.dirname(__file__))

try:
    # Imported as part of the `server` package
    from .api_documentation import API_DOCUMENTATION
except ImportError:
    # Imported when this file is run directly as a script
    from api_documentation import API_DOCUMENTATION  # type: ignore[import-not-found,no-redef]

try:
    from .cron_scheduler import CronScheduler
except ImportError:
    from cron_scheduler import CronScheduler  # type: ignore[import-not-found,no-redef]

# Load environment variables
load_dotenv()

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing - Use argon2 as primary with bcrypt fallback for compatibility
try:
    pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")
    print("✅ Password context initialized with argon2 and bcrypt support")
except Exception as e:
    print(f"⚠️  Error initializing password context: {e}")
    try:
        # Try bcrypt only
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        print("✅ Password context initialized with bcrypt only")
    except Exception as e2:
        print(f"❌ Failed to initialize password context: {e2}")
        # Create a minimal context that will work
        pwd_context = None

# Simple models
class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class CreateThreadRequest(BaseModel):
    thread_id: str
    soul: str = None

class SaveCronRequest(BaseModel):
    name: str
    prompt: str
    schedule: str
    thread_id: str
    is_active: bool = True

class UpdateCronStatusRequest(BaseModel):
    is_active: bool

# Password utilities
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password with fallback handling for different hash formats."""
    if pwd_context is None:
        # Fallback: try plain text comparison
        return plain_password == hashed_password
    
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"⚠️  Password verification error: {e}")
        # Fallback: try plain text comparison
        return plain_password == hashed_password

def get_password_hash(password: str) -> str:
    """Hash password with fallback handling."""
    if pwd_context is None:
        # Fallback: return plain text (not recommended for production)
        print("⚠️  Warning: Using plain text password storage (fallback mode)")
        return password
    
    try:
        return pwd_context.hash(password)
    except Exception as e:
        print(f"⚠️  Password hashing error: {e}")
        # Fallback: return plain text (not recommended for production)
        print("⚠️  Warning: Using plain text password storage (fallback mode)")
        return password

# JWT utilities
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Simple auth dependency
async def get_current_user(authorization: str = Header(None)) -> str:
    """Simple auth dependency that extracts username from JWT token."""
    print(f"🔍 Received authorization header: {authorization}")
    
    if not authorization or not authorization.startswith("Bearer "):
        print("❌ No valid authorization header found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.split(" ")[1]
    print(f"🔑 Extracted token: {token[:20]}...")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            print("❌ No username in token payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        print(f"✅ Successfully authenticated user: {username}")
        return username
    except JWTError as e:
        print(f"❌ JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Simple user verification
async def verify_user(username: str, password: str) -> bool:
    """Verify username and password against database."""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        return False
    
    conn = await asyncpg.connect(connection_string)
    try:
        row = await conn.fetchrow(
            "SELECT password FROM users WHERE username = $1",
            username
        )
        if row:
            return verify_password(password, row["password"])
        return False
    finally:
        await conn.close()

async def ensure_users_table():
    """Create the users table if it does not already exist.
    The table stores email (primary key), username, password, and an is_admin flag.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    conn = await asyncpg.connect(connection_string)
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                email VARCHAR(255) PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                password VARCHAR(255) NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE
            )
        ''')
    finally:
        await conn.close()

async def ensure_skills_table():
    """Create the skills table if it does not already exist.
    The table stores unique skill names, skill data, and skill descriptions.
    """
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("POSTGRES_CONNECTION_STRING environment variable not set")
    conn = await asyncpg.connect(connection_string)
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS skills (
                skill_name VARCHAR(255) PRIMARY KEY,
                skill TEXT NOT NULL,
                skill_description TEXT NOT NULL
            )
        ''')
    finally:
        await conn.close()
        
def get_current_date() -> str:
    """Get current date"""
    return datetime.now().strftime("%a %b %d, %Y")

async def create_test_user():
    """Create a test user with properly hashed password"""
    connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
    if not connection_string:
        print("⚠️  POSTGRES_CONNECTION_STRING not set, skipping test user creation")
        return False
    
    conn = await asyncpg.connect(connection_string)
    try:
        username = "<user>"
        password = "<pass>"
        hashed_password = get_password_hash(password)
        email = "<email>"
        
        # Insert or update the user
        await conn.execute("""
            INSERT INTO users (email, username, password, is_admin)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (email) 
            DO UPDATE SET password = $3, username = $2
        """, email, username, hashed_password, True)
        
        print(f"✅ Test user '{username}' created/updated successfully with proper bcrypt hash")
        return True
    except Exception as e:
        print(f"❌ Error creating test user: {e}")
        return False
    finally:
        await conn.close()





from AI_Agent.basic_agent import invoke_workflow_stream, get_threads, get_thread, create_thread
from AI_Tools.document_processor import document_to_images
from AI_Tools.audio_processor import audio_to_text
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

# WebSocket connection cache: thread_id -> WebSocket
# This allows background tasks to send messages to the latest active connection for a thread
# Thread can have multiple connections (multiple browser tabs), we track the latest per thread_id
websocket_cache: dict[str, WebSocket] = {}
# Lock for thread-safe access to the websocket cache
websocket_cache_lock = asyncio.Lock()


async def register_websocket(thread_id: str, websocket: WebSocket):
    """Register a WebSocket connection for a thread_id."""
    async with websocket_cache_lock:
        websocket_cache[thread_id] = websocket
        print(f"📡 WebSocket registered for thread: {thread_id}")


async def unregister_websocket(thread_id: str):
    """Unregister a WebSocket connection for a thread_id."""
    async with websocket_cache_lock:
        if thread_id in websocket_cache:
            del websocket_cache[thread_id]
            print(f"📡 WebSocket unregistered for thread: {thread_id}")


async def get_websocket(thread_id: str) -> Optional[WebSocket]:
    """Get the latest active WebSocket connection for a thread_id."""
    async with websocket_cache_lock:
        return websocket_cache.get(thread_id)

def extract_meaningful_content(chunk: dict) -> dict:
    """
    Extract messages from workflow chunks and convert to clean JSON format.
    
    This function processes workflow chunks from the AI agent and extracts
    meaningful content (AI messages, human messages, and tool messages) while
    filtering out empty content and organizing them into clean data structures.
    
    Args:
        chunk: Dictionary containing workflow chunk data with node names as keys
        
    Returns:
        dict: Cleaned dictionary with organized messages by type (ai_messages, human_messages, tool_messages)
    """
    try:
        result = {}
        
        for node_name, node_data in chunk.items():
            if not isinstance(node_data, dict):
                result[node_name] = node_data
                continue
                
            node_result = {}
            
            # Handle messages with separate keys for AI, Human, and Tool
            if 'messages' in node_data:
                ai_messages = []
                human_messages = []
                tool_messages = []
                
                for msg in node_data['messages']:
                    # Handle LangChain message objects (HumanMessage, AIMessage, ToolMessage)
                    msg_type = None
                    content = ''
                    msg_id = None
                    usage_metadata = None
                    tool_calls = []
                    
                    if hasattr(msg, 'type'):
                        # LangChain message object
                        msg_type = msg.type
                        content = getattr(msg, 'content', '')
                        msg_id = getattr(msg, 'id', None)
                        if hasattr(msg, 'usage_metadata'):
                            usage_metadata = msg.usage_metadata
                        if hasattr(msg, 'tool_calls'):
                            tool_calls = msg.tool_calls
                    elif isinstance(msg, dict):
                        # Dictionary format (from sample JSON)
                        msg_type = msg.get('type')
                        content = msg.get('content', '')
                        msg_id = msg.get('id', None)
                        usage_metadata = msg.get('usage_metadata')
                        tool_calls = msg.get('tool_calls', [])
                    
                    # Include human messages, AI messages with non-empty content, and tool messages with non-empty content (same logic as process_thread_result)
                    if msg_type == 'human':
                        message_content = {
                            'content': content,
                            'type': msg_type,
                            'id': msg_id
                        }
                        human_messages.append(message_content)
                    elif msg_type == 'ai' and content:
                        message_content = {
                            'content': content,
                            'type': msg_type,
                            'id': msg_id
                        }
                        
                        # Add usage metadata if present (for AI messages)
                        if usage_metadata:
                            message_content['usage_metadata'] = usage_metadata
                        
                        ai_messages.append(message_content)
                    elif msg_type == 'tool' and content:
                        # Check if this is a write_todos tool message
                        tool_name = None
                        if hasattr(msg, 'name'):
                            tool_name = getattr(msg, 'name', None)
                        elif isinstance(msg, dict):
                            tool_name = msg.get('name')
                        
                        if tool_name == 'write_todos':
                            message_content = {
                                'content': content,
                                'type': msg_type,
                                'id': msg_id
                            }
                            tool_messages.append(message_content)
                    # Skip messages with empty content (same as process_thread_result)
                
                if ai_messages:
                    node_result['ai_messages'] = ai_messages
                if human_messages:
                    node_result['human_messages'] = human_messages
                if tool_messages:
                    node_result['tool_messages'] = tool_messages
            
            result[node_name] = node_result
        
        return result
    except Exception:
        import traceback
        print(f"Error in extract_meaningful_content: {traceback.format_exc()}")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI startup and shutdown events."""
    # Startup logic
    try:
        print("🚀 Starting up AI Agent WebSocket Server...")
        print("Ensuring database tables exist...")
        await ensure_users_table()
        print("✅ Users table ensured successfully")
        await ensure_skills_table()
        print("✅ Skills table ensured successfully")
        from AI_Agent.basic_agent import ensure_crons_table_exists
        await ensure_crons_table_exists()
        print("✅ Crons table ensured successfully")
        
        # # Create test user with proper hashing
        # print("Creating test user...")
        # await create_test_user()
        # print("✅ Test user created successfully")
        
        # If other tables need creation, they can be added here.
        print("✅ Database initialization completed")

        # Start the cron scheduler. It reconciles `next_run_at` on startup
        # (skipping runs missed while the server was down) and then polls the
        # crons table, delivering each prompt to its thread exactly like a
        # user message would.
        scheduler = CronScheduler(run_workflow_for_thread)
        await scheduler.start()
        app.state.cron_scheduler = scheduler

        print("✅ Server startup completed successfully")
        yield
    except Exception as e:
        print(f"❌ Error during startup: {e}")
        print("💥 Server startup aborted due to database initialization failure")
        # Exit the process if database setup fails
        import sys
        sys.exit(1)
    finally:
        # Shutdown logic
        scheduler = getattr(app.state, "cron_scheduler", None)
        if scheduler is not None:
            await scheduler.stop()
        print("🛑 Shutting down AI Agent WebSocket Server...")

app = FastAPI(title="AI Agent WebSocket Server", lifespan=lifespan)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple Authentication Endpoints
@app.post("/api/auth/login")
async def login(login_data: LoginRequest):
    """Simple login endpoint - returns JWT token if credentials are valid."""
    if await verify_user(login_data.username, login_data.password):
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": login_data.username}, expires_delta=access_token_expires
        )
        return {"access_token": access_token, "token_type": "bearer"}
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

@app.get("/agentAPIDoc")
async def get_api_documentation():
    """
    Get comprehensive API documentation for all available endpoints.
    
    Returns:
        JSON: Complete API documentation with examples, schemas, and usage instructions
    """
    return API_DOCUMENTATION

@app.get("/api/threads")
async def get_threads_endpoint(username: str = Depends(get_current_user)):
    """
    Get all distinct thread IDs from the database (requires authentication)
    """
    try:
        print(f"Fetching threads for user: {username}")
        # Import the async version
        from AI_Agent.basic_agent import get_threads as get_threads_async
        result = await get_threads_async()
        print(f"Fetched {len(result.get('threads', []))} threads")
        return result
    except Exception as e:
        print(f"Error fetching threads: {e}")
        return {"error": f"Failed to fetch threads: {str(e)}"}

@app.post("/api/thread")
async def create_thread_endpoint(request: CreateThreadRequest, username: str = Depends(get_current_user)):
    """
    Create a new thread with an optional soul (agent personality/prompt).
    
    Args:
        request: CreateThreadRequest with thread_id and optional soul
        username: Authenticated user (from JWT token)
    """
    try:
        print(f"Creating thread {request.thread_id} for user: {username}")
        await create_thread(request.thread_id, request.soul)
        return {"success": True, "thread_id": request.thread_id, "soul": request.soul}
    except Exception as e:
        print(f"Error creating thread: {e}")
        return {"error": f"Failed to create thread: {str(e)}"}

@app.get("/api/health")
async def health_check():
    """
    Comprehensive health check endpoint including database and table verification
    """
    try:
        connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
        if not connection_string:
            return {"status": "error", "message": "POSTGRES_CONNECTION_STRING not set"}
        
        # Test database connection
        conn = await asyncpg.connect(connection_string)
        
        # Test basic connectivity
        await conn.execute('SELECT 1')
        
        # Verify users table exists
        table_check = await conn.fetchval("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'users'
            )
        """)
        
        await conn.close()
        
        if table_check:
            return {
                "status": "ok", 
                "message": "Database connection successful",
                "database": "connected",
                "tables": {"users": "exists"}
            }
        else:
            return {
                "status": "warning", 
                "message": "Database connected but users table missing",
                "database": "connected",
                "tables": {"users": "missing"}
            }
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

@app.get("/api/thread/{thread_id}")
async def get_thread_endpoint(thread_id: str, username: str = Depends(get_current_user)):
    """
    Get a specific thread by thread_id, returns current state of the chat (requires authentication).
    """
    try:
        print(f"Fetching thread {thread_id} for user: {username}")
        # Call the synchronous function directly
        result = get_thread(thread_id)
        
        # Process the result to filter only human and AI messages
        processed_result = process_thread_result(result)
        return processed_result
    except Exception as e:
        print(f"Error in get_thread_endpoint: {e}")
        return {"error": f"Failed to fetch thread: {str(e)}"}

@app.delete("/api/thread/{thread_id}")
async def delete_thread_endpoint(thread_id: str, username: str = Depends(get_current_user)):
    """
    Delete a specific thread by thread_id (requires authentication)
    """
    try:
        print(f"Deleting thread {thread_id} for user: {username}")
        # Import the async version
        from AI_Agent.basic_agent import delete_thread as delete_thread_async
        result = await delete_thread_async(thread_id)
        return {"success": True, "message": f"Thread {thread_id} deleted successfully"}
    except Exception as e:
        print(f"Error in delete_thread_endpoint: {e}")
        return {"error": f"Failed to delete thread: {str(e)}"}

@app.get("/api/thread/{thread_id}/message_count")
async def get_thread_message_count_endpoint(thread_id: str, username: str = Depends(get_current_user)):
    """
    Get the count of messages in a specific thread by thread_id (requires authentication)
    """
    try:
        print(f"Getting message count for thread {thread_id} for user: {username}")
        # Call the synchronous function directly
        result = get_thread(thread_id)
        
        # Get the message count using the new function
        message_count = get_thread_message_count(result)
        return {"thread_id": thread_id, "message_count": message_count}
    except Exception as e:
        print(f"Error in get_thread_message_count_endpoint: {e}")
        return {"error": f"Failed to get message count: {str(e)}"}

# ---------------------------------------------------------------------------
# Cron endpoints (backed by the `crons` table)
# ---------------------------------------------------------------------------

@app.post("/api/crons")
async def save_cron_endpoint(request: SaveCronRequest, username: str = Depends(get_current_user)):
    """
    Create or update a cron job (requires authentication).

    If a cron with the same `name` already exists it is updated in place and
    keeps its existing cron_id/thread_id; otherwise a new one is created.
    """
    from AI_Agent.basic_agent import save_cron as save_cron_async

    try:
        print(f"Saving cron {request.name!r} for user: {username}")
        cron = await save_cron_async(
            name=request.name,
            prompt=request.prompt,
            schedule=request.schedule,
            thread_id=request.thread_id,
            is_active=request.is_active,
        )
        return cron
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        print(f"Error saving cron: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save cron: {str(e)}",
        )

@app.get("/api/crons")
async def get_crons_endpoint(active_only: bool = False, username: str = Depends(get_current_user)):
    """
    List cron jobs (requires authentication).

    Returns a JSON array of cron objects. Pass `?active_only=true` to limit the
    response to enabled crons.
    """
    from AI_Agent.basic_agent import get_crons as get_crons_async

    try:
        print(f"Fetching crons for user: {username} (active_only={active_only})")
        return await get_crons_async(active_only=active_only)
    except Exception as e:
        print(f"Error fetching crons: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch crons: {str(e)}",
        )

@app.get("/api/crons/{cron_id}")
async def get_cron_endpoint(cron_id: str, username: str = Depends(get_current_user)):
    """Get a single cron by cron_id or thread_id (requires authentication)."""
    from AI_Agent.basic_agent import get_cron as get_cron_async

    try:
        cron = await get_cron_async(cron_id)
        if cron is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cron not found")
        return cron
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching cron {cron_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch cron: {str(e)}",
        )

@app.patch("/api/crons/{cron_id}")
async def update_cron_status_endpoint(
    cron_id: str,
    request: UpdateCronStatusRequest,
    username: str = Depends(get_current_user),
):
    """
    Enable or disable a cron job (requires authentication).

    Enabling recomputes `next_run_at` from the stored schedule.
    """
    from AI_Agent.basic_agent import set_cron_active as set_cron_active_async

    try:
        cron = await set_cron_active_async(cron_id, request.is_active)
        if cron is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cron not found")
        return cron
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating cron {cron_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update cron: {str(e)}",
        )

@app.delete("/api/crons/{cron_id}")
async def delete_cron_endpoint(cron_id: str, username: str = Depends(get_current_user)):
    """Delete a cron job by cron_id or thread_id (requires authentication)."""
    from AI_Agent.basic_agent import delete_cron as delete_cron_async

    try:
        deleted = await delete_cron_async(cron_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cron not found")
        return {"success": True, "cron_id": cron_id}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting cron {cron_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete cron: {str(e)}",
        )

def process_thread_result(result):
    """
    Process thread result to extract only human and AI messages.
    
    This function processes the raw result from the agent workflow and extracts
    only meaningful messages (human, AI, and write_todos tool messages) while
    filtering out empty content and other tool messages.
    
    Args:
        result: The raw result from the agent workflow (can be CheckpointTuple, list, or dict)
        
    Returns:
        list: Filtered list of message dictionaries with type, content, and metadata
    """
    try:
        print(f"Processing result type: {type(result)}")
        # Handle CheckpointTuple - convert to tuple and access like sample JSON
        if hasattr(result, '__iter__') and not isinstance(result, (str, dict, list)):
            try:
                result = tuple(result)
            except:
                pass
        
        # Handle list/tuple format like sample JSON: [config, checkpoint, ...]
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            checkpoint = result[1]  # Second element contains the checkpoint data
            
            if isinstance(checkpoint, dict) and 'channel_values' in checkpoint:
                messages = checkpoint['channel_values'].get('messages', [])
                print(f"Found {len(messages)} messages")
                
                # Filter to only include human and AI messages (AI messages without tool calls)
                filtered_messages = []
                for msg in messages:
                    # Handle LangChain message objects (HumanMessage, AIMessage, ToolMessage)
                    msg_type = None
                    content = ''
                    msg_id = None
                    usage_metadata = None
                    tool_calls = []
                    
                    if hasattr(msg, 'type'):
                        # LangChain message object
                        msg_type = msg.type
                        content = getattr(msg, 'content', '')
                        msg_id = getattr(msg, 'id', None)
                        if hasattr(msg, 'usage_metadata'):
                            usage_metadata = msg.usage_metadata
                        if hasattr(msg, 'tool_calls'):
                            tool_calls = msg.tool_calls
                    elif isinstance(msg, dict):
                        # Dictionary format (from sample JSON)
                        msg_type = msg.get('type')
                        content = msg.get('content', '')
                        msg_id = msg.get('id', None)
                        usage_metadata = msg.get('usage_metadata')
                        tool_calls = msg.get('tool_calls', [])
                    
                    # Include human messages, AI messages with non-empty content, and write_todos tool messages with non-empty content
                    if msg_type == 'human':
                        clean_msg = {
                            'content': content,
                            'type': msg_type,
                            'id': msg_id
                        }
                        filtered_messages.append(clean_msg)
                    elif msg_type == 'ai' and content:
                        clean_msg = {
                            'content': content,
                            'type': msg_type,
                            'id': msg_id
                        }
                        
                        # Add usage metadata if present (for AI messages)
                        if usage_metadata:
                            clean_msg['usage_metadata'] = usage_metadata
                        
                        filtered_messages.append(clean_msg)
                    elif msg_type == 'tool' and content:
                        # Check if this is a write_todos tool message
                        tool_name = None
                        if hasattr(msg, 'name'):
                            tool_name = getattr(msg, 'name', None)
                        elif isinstance(msg, dict):
                            tool_name = msg.get('name')
                        
                        if tool_name == 'write_todos':
                            clean_msg = {
                                'content': content,
                                'type': msg_type,
                                'id': msg_id
                            }
                            filtered_messages.append(clean_msg)
                            print(f"Added write_todos tool message: {clean_msg}")
                        else:
                            print(f"Skipping tool message from {tool_name}: {msg_id}")
                    elif msg_type in ['ai', 'tool'] and (not content):
                        print(f"Skipping {msg_type} message with empty content: {msg_id}")
                
                print(f"Returning {len(filtered_messages)} filtered messages")
                return filtered_messages
            else:
                print("No channel_values found in checkpoint")
        else:
            print(f"Result is not a list/tuple or doesn't have enough elements. Type: {type(result)}, Length: {len(result) if hasattr(result, '__len__') else 'N/A'}")
        
        return []
    except Exception:
        import traceback
        print(f"Error in process_thread_result: {traceback.format_exc()}")
        raise

def get_thread_message_count(result):
    """
    Get the count of messages in a thread result.
    
    This function processes the raw result from the agent workflow and counts
    only meaningful messages (human, AI, and write_todos tool messages) while
    filtering out empty content and other tool messages.
    
    Args:
        result: The raw result from the agent workflow (can be CheckpointTuple, list, or dict)
        
    Returns:
        int: Count of filtered messages
    """
    print(f"Counting messages in result type: {type(result)}")
    
    # Handle CheckpointTuple - convert to tuple and access like sample JSON
    if hasattr(result, '__iter__') and not isinstance(result, (str, dict, list)):
        try:
            result = tuple(result)
        except:
            pass
    
    # Handle list/tuple format like sample JSON: [config, checkpoint, ...]
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        checkpoint = result[1]  # Second element contains the checkpoint data
        
        if isinstance(checkpoint, dict) and 'channel_values' in checkpoint:
            messages = checkpoint['channel_values'].get('messages', [])
            print(f"Found {len(messages)} total messages")
            return len(messages)
        else:
            print("No channel_values found in checkpoint")
    else:
        print(f"Result is not a list/tuple or doesn't have enough elements. Type: {type(result)}, Length: {len(result) if hasattr(result, '__len__') else 'N/A'}")
    
    return 0

def prompt_func(data):
    """
    Build a HumanMessage with multimodal content from text, image, and doc_images.
    
    Args:
        data: Dict that may contain:
            - text: str - The text message
            - image: str - Base64 encoded image (direct upload)
            - doc_images: list of dicts with 'page' (int) and 'image' (base64 str)
                         representing pages converted from PDF/DOC/TXT/MD
    
    Returns:
        HumanMessage with content parts for multimodal input
    """
    text = data.get("text", "")
    image = data.get("image")
    doc_images = data.get("doc_images", [])

    content_parts = []

    # Existing image flow (direct uploads like photos)
    if image:
        image_part = {
            "type": "image_url",
            "image_url": f"data:image/png;base64,{image}",
        }
        content_parts.append(image_part)

    # New doc_images flow (converted from PDF pages)
    # Each page is a separate image with page number
    if doc_images:
        for page_data in doc_images:
            page_image = page_data.get('image', '')
            if page_image:
                # Create image_url content for each PDF page
                image_url_obj = {
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{page_image}",
                }
                content_parts.append(image_url_obj)

    # Text part
    if text:
        text_part = {"type": "text", "text": text}
        content_parts.append(text_part)

    return [HumanMessage(content=content_parts)]

async def run_workflow_for_thread(
    workflow_thread_id: str,
    workflow_message: str,
    workflow_document: dict = None,
    image: dict = None,
) -> None:
    """
    Run the agent workflow for a thread and stream each chunk to its WebSocket.

    This is the single delivery path shared by interactive messages and cron
    jobs, so cron output is byte-for-byte the same format as a user message:
    `{"thread_id": ..., "data": ...}`.

    If no client is connected the chunks are dropped, but the run is still
    checkpointed under `workflow_thread_id`, so the UI can recover the result
    with `GET /api/thread/{thread_id}`.

    Args:
        workflow_thread_id: Thread to run and stream into.
        workflow_message: The prompt to send to the agent.
        workflow_document: Optional uploaded document payload.
        image: Optional uploaded image payload.
    """
    try:
        # Process document if provided. The dispatcher routes PDFs through
        # pdf_to_images and TXT/MD/DOC/DOCX/code files through text_to_images,
        # so the same call works for any supported upload.
        doc_images = []
        if workflow_document is not None:
            try:
                doc_images = document_to_images(workflow_document)
                print(f"📄 Document processed into {len(doc_images)} page(s)")
            except Exception as doc_error:
                print(f"⚠️  Error processing document: {doc_error}")
                # Continue without document images rather than failing entirely

        if image is not None:
            messages = prompt_func({
                "text": workflow_message,
                "image": image["data"]
            })
        elif doc_images:
            messages = prompt_func({
                "text": workflow_message,
                "doc_images": doc_images
            })
        else:
            messages = [HumanMessage(content=workflow_message)]

        # Stream the workflow results
        async for chunk in invoke_workflow_stream(workflow_thread_id, messages):
            # Extract meaningful content and convert to clean JSON
            clean_chunk = extract_meaningful_content(chunk)
            # Include thread_id in the message for client-side filtering
            message_with_thread = {
                'thread_id': workflow_thread_id,
                'data': clean_chunk
            }
            try:
                # Get the LATEST websocket from cache (handles reconnect scenarios)
                latest_ws = await get_websocket(workflow_thread_id)
                if latest_ws:
                    await latest_ws.send_text(load.dumps(message_with_thread))
                else:
                    print(f"⚠️  No active WebSocket for thread {workflow_thread_id}, message not sent")
            except Exception as send_error:
                # WebSocket disconnected, but workflow continues
                print(f"⚠️  Could not send to WebSocket (connection may be closed): {send_error}")

    except Exception:
        import traceback
        print(f"❌ Error in background workflow execution: {traceback.format_exc()}")
        try:
            latest_ws = await get_websocket(workflow_thread_id)
            if latest_ws:
                await latest_ws.send_text(f"Error running workflow: {traceback.format_exc()}")
        except Exception:
            # WebSocket already closed
            pass

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication with the AI agent (requires authentication).
    """
    # Authenticate user from query parameters
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Authentication token required")
        return
    
    try:
        # Verify token and get current user
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            await websocket.close(code=4001, reason="Invalid authentication token")
            return
        
    except JWTError:
        await websocket.close(code=4001, reason="Invalid authentication token")
        return
    except Exception as e:
        await websocket.close(code=4001, reason=f"Authentication error: {str(e)}")
        return
    
    await websocket.accept()
    
    # Get thread_id from the client's first message to register this connection
    # Default to "default" thread if not specified
    registered_thread_id = "default"
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Parse the message (expecting JSON with thread_id and message)
            try:
                message_data = json.loads(data)
                thread_id = message_data.get("thread_id", "default")
                user_message = message_data.get("message", "")
                image = message_data.get("image", None)  # Optional image data for future use
                document = message_data.get("document", None)  # Optional document data for future use
                audio = message_data.get("audio", None)  # Optional audio data, transcribed into user_message
                # ```json
                # {
                # "thread_id": "...",
                # "message": "user text",
                # "image": {
                #     "filename": "photo.png",
                #     "mime_type": "image/png",
                #     "data": "<base64 string, no data: prefix>"
                # },
                # "document": {
                #     "filename": "report.pdf",
                #     "mime_type": "application/pdf",
                #     "data": "<base64 string, no data: prefix>"
                # },
                # "audio": {
                #     "filename": "recording.webm",
                #     "mime_type": "audio/webm;codecs=opus",
                #     "data": "<base64 string, no data: prefix>"
                # }
                # }```

                # If audio is provided, transcribe it and use as user_message
                # (audio overrides any text in the "message" field)
                if audio:
                    try:
                        transcribed = audio_to_text(audio)
                        if transcribed:
                            user_message = transcribed
                            print(f"🎤 Audio transcribed: {transcribed[:80]}...")
                    except Exception as audio_err:
                        print(f"⚠️  Audio transcription error: {audio_err}")

                # Check if this is a reconnect message for an existing thread
                if user_message == "reconnect":
                    # Just update the websocket in the cache without running workflow
                    await register_websocket(thread_id, websocket)
                    registered_thread_id = thread_id
                    print(f"📡 WebSocket reconnected and registered for thread: {thread_id}")
                    continue
                
                if not user_message:
                    await websocket.send_text("Error: No message provided")
                    continue
                    
            except json.JSONDecodeError:
                # If not JSON, treat as simple message
                thread_id = "default"
                user_message = data
            
            # Register this websocket for the thread_id on first message
            if registered_thread_id == "default" and thread_id != "default":
                registered_thread_id = thread_id
                await register_websocket(thread_id, websocket)
                print(f"📡 WebSocket connected and registered for thread: {thread_id}")
            
            # acknowledgment
            print(f"Starting workflow with message: {user_message}")
            
            # Start the workflow as a background task (non-blocking) so it
            # continues even if this WebSocket disconnects. `image` is passed
            # explicitly rather than captured, so a later message cannot
            # overwrite it before the task runs.
            asyncio.create_task(
                run_workflow_for_thread(thread_id, user_message, document, image)
            )
                
    except WebSocketDisconnect:
        # Client disconnected - unregister from cache
        if registered_thread_id != "default":
            await unregister_websocket(registered_thread_id)
        print(f"WebSocket disconnected for user: {username}")
        pass

if __name__ == "__main__":
    run_server()