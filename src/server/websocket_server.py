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

# Set Windows-compatible event loop policy for psycopg
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add the src directory to the path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

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





from AI_Agent.basic_agent import invoke_workflow_stream, get_threads, get_thread
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

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

API_DOCUMENTATION = {
    "title": "AI Agent WebSocket Server API",
    "version": "1.0.0",
    "description": "RESTful API and WebSocket server for AI Agent with real-time communication capabilities",
    "base_url": "http://localhost:8000",  # Update this to match your deployment
    "authentication": {
        "description": "Most endpoints require authentication using JWT Bearer tokens",
        "flow": [
            "1. Call POST /api/auth/login with username and password",
            "2. Receive access_token from login response",
            "3. Include 'Authorization: Bearer <token>' header in subsequent requests"
        ],
        "header_format": {
            "name": "Authorization",
            "value": "Bearer <your-jwt-token>",
            "example": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
        },
        "endpoints_requiring_auth": [
            "GET /api/threads",
            "GET /api/thread/{thread_id}",
            "GET /api/thread/{thread_id}/message_count",
            "DELETE /api/thread/{thread_id}",
            "WebSocket /ws"
        ],
        "endpoints_not_requiring_auth": [
            "GET /api/health",
            "POST /api/auth/login",
            "GET /",
            "GET /agentAPIDoc"
        ]
    },
    "endpoints": {
        "GET /": {
            "description": "Serve the main HTML page with WebSocket client interface",
            "parameters": None,
            "response": {
                "type": "HTML",
                "description": "Complete HTML page with embedded JavaScript for WebSocket client"
            },
            "example": {
                "request": "GET http://localhost:8000/",
                "response": "HTML page with WebSocket client interface"
            }
        },
        "GET /agentAPIDoc": {
            "description": "Get comprehensive API documentation",
            "parameters": None,
            "response": {
                "type": "JSON",
                "description": "Complete API documentation with examples"
            },
            "example": {
                "request": "GET http://localhost:8000/agentAPIDoc",
                "response": {
                    "title": "AI Agent WebSocket Server API",
                    "version": "1.0.0",
                    "endpoints": {
                        "GET /": "Main HTML page with WebSocket client interface",
                        "GET /agentAPIDoc": "API documentation endpoint",
                        "GET /api/health": "Health check endpoint (no auth required)",
                        "POST /api/auth/login": "Login and get JWT token",
                        "GET /api/threads": "Get all thread IDs (requires auth)",
                        "GET /api/thread/{thread_id}": "Get specific thread (requires auth)",
                        "GET /api/thread/{thread_id}/message_count": "Get message count for specific thread (requires auth)",
                        "DELETE /api/thread/{thread_id}": "Delete specific thread (requires auth)",
                        "WebSocket /ws": "WebSocket endpoint (requires auth)"
                    }
                }
            }
        },
        "GET /api/threads": {
            "description": "Get all distinct thread IDs from the database",
            "parameters": None,
            "headers": {
                "Authorization": {
                    "type": "string",
                    "description": "JWT Bearer token in format 'Bearer <token>'",
                    "required": True,
                    "example": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                }
            },
            "response": {
                "type": "JSON",
                "description": "List of all available thread IDs with metadata",
                "schema": {
                    "type": "object",
                    "properties": {
                        "threads": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "thread_id": {"type": "string"},
                                    "created_at": {"type": "string", "format": "datetime"}
                                }
                            }
                        }
                    }
                }
            },
            "example": {
                "request": {
                    "method": "GET",
                    "url": "http://localhost:8000/api/threads",
                    "headers": {
                        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                    }
                },
                "response": {
                    "threads": [
                        {
                            "thread_id": "thread_abc123_1640995200000",
                            "created_at": "2024-01-01T00:00:00Z"
                        }
                    ]
                }
            }
        },
        "GET /api/health": {
            "description": "Simple health check endpoint",
            "parameters": None,
            "response": {
                "type": "JSON",
                "description": "Health status of the server and database connection",
                "schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["ok", "error"]},
                        "message": {"type": "string"}
                    }
                }
            },
            "example": {
                "request": "GET http://localhost:8000/api/health",
                "response": {
                    "status": "ok",
                    "message": "Database connection successful"
                }
            }
        },
        "POST /api/auth/login": {
            "description": "Login with username and password to get JWT authentication token",
            "parameters": {
                "username": {
                    "type": "string",
                    "description": "User's username",
                    "required": True
                },
                "password": {
                    "type": "string", 
                    "description": "User's password",
                    "required": True
                }
            },
            "response": {
                "type": "JSON",
                "description": "JWT access token for authenticated requests",
                "schema": {
                    "type": "object",
                    "properties": {
                        "access_token": {"type": "string"},
                        "token_type": {"type": "string", "enum": ["bearer"]}
                    }
                }
            },
            "example": {
                "request": {
                    "method": "POST",
                    "url": "http://localhost:8000/api/auth/login",
                    "headers": {"Content-Type": "application/json"},
                    "body": {
                        "username": "john_doe",
                        "password": "secure_password"
                    }
                },
                "response": {
                    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature",
                    "token_type": "bearer"
                }
            }
        },
        "GET /api/thread/{thread_id}": {
            "description": "Get a specific thread by thread_id, returns current state of the chat",
            "parameters": {
                "thread_id": {
                    "type": "string",
                    "description": "Unique identifier for the thread",
                    "required": True
                }
            },
            "headers": {
                "Authorization": {
                    "type": "string",
                    "description": "JWT Bearer token in format 'Bearer <token>'",
                    "required": True,
                    "example": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                }
            },
            "response": {
                "type": "JSON",
                "description": "List of messages in the thread",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "type": {"type": "string", "enum": ["human", "ai", "tool"]},
                            "id": {"type": "string"},
                            "usage_metadata": {
                                "type": "object",
                                "properties": {
                                    "total_tokens": {"type": "number"},
                                    "input_tokens": {"type": "number"},
                                    "output_tokens": {"type": "number"}
                                }
                            }
                        }
                    }
                }
            },
            "example": {
                "request": {
                    "method": "GET",
                    "url": "http://localhost:8000/api/thread/thread_abc123_1640995200000",
                    "headers": {
                        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                    }
                },
                "response": [
                    {
                        "content": "Hello, how can you help me?",
                        "type": "human",
                        "id": "msg1"
                    },
                    {
                        "content": "Hello! I'm here to help you with research, analysis, and various tasks. What would you like to work on?",
                        "type": "ai",
                        "id": "msg2",
                        "usage_metadata": {
                            "total_tokens": 25,
                            "input_tokens": 10,
                            "output_tokens": 15
                        }
                    }
                ]
            }
        },
        "DELETE /api/thread/{thread_id}": {
            "description": "Delete a specific thread by thread_id",
            "parameters": {
                "thread_id": {
                    "type": "string",
                    "description": "Unique identifier for the thread to delete",
                    "required": True
                }
            },
            "headers": {
                "Authorization": {
                    "type": "string",
                    "description": "JWT Bearer token in format 'Bearer <token>'",
                    "required": True,
                    "example": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                }
            },
            "response": {
                "type": "JSON",
                "description": "Success confirmation",
                "schema": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "message": {"type": "string"}
                    }
                }
            },
            "example": {
                "request": {
                    "method": "DELETE",
                    "url": "http://localhost:8000/api/thread/thread_abc123_1640995200000",
                    "headers": {
                        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                    }
                },
                "response": {
                    "success": True,
                    "message": "Thread thread_abc123_1640995200000 deleted successfully"
                }
            }
        },
        "GET /api/thread/{thread_id}/message_count": {
            "description": "Get the count of messages in a specific thread by thread_id",
            "parameters": {
                "thread_id": {
                    "type": "string",
                    "description": "Unique identifier for the thread",
                    "required": True
                }
            },
            "headers": {
                "Authorization": {
                    "type": "string",
                    "description": "JWT Bearer token in format 'Bearer <token>'",
                    "required": True,
                    "example": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                }
            },
            "response": {
                "type": "JSON",
                "description": "Message count for the thread",
                "schema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string"},
                        "message_count": {"type": "integer"}
                    }
                }
            },
            "example": {
                "request": {
                    "method": "GET",
                    "url": "http://localhost:8000/api/thread/thread_abc123_1640995200000/message_count",
                    "headers": {
                        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                    }
                },
                "response": {
                    "thread_id": "thread_abc123_1640995200000",
                    "message_count": 5
                }
            }
        },
        "WebSocket /ws": {
            "description": "WebSocket endpoint for real-time communication with the AI agent (requires authentication)",
            "authentication": {
                "method": "query_parameter",
                "parameter": "token",
                "description": "JWT authentication token from /api/auth/login passed as query parameter",
                "example": "ws://localhost:8000/ws?token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
            },
            "parameters": {
                "token": {
                    "type": "string",
                    "description": "JWT authentication token from /api/auth/login",
                    "required": True
                }
            },
            "connection": {
                "url": "ws://localhost:8000/ws?token={jwt_token}",
                "protocol": "WebSocket"
            },
            "message_format": {
                "type": "JSON",
                "schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "User message content"},
                        "thread_id": {"type": "string", "description": "Thread ID for conversation context"}
                    },
                    "required": ["message"]
                }
            },
            "response_format": {
                "type": "JSON",
                "schema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string"},
                        "data": {
                            "type": "object",
                            "description": "Workflow chunk data with messages"
                        }
                    }
                }
            },
            "example": {
                "connection": "WebSocket connection to ws://localhost:8000/ws?token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature",
                "send": {
                    "message": "What is the weather like today?",
                    "thread_id": "thread_abc123_1640995200000"
                },
                "receive": [
                    {
                        "thread_id": "thread_abc123_1640995200000",
                        "data": {
                            "agent_node": {
                                "ai_messages": [
                                    {
                                        "content": "I'll help you check the weather. Let me search for current weather information.",
                                        "type": "ai",
                                        "id": "msg_123",
                                        "usage_metadata": {
                                            "total_tokens": 20,
                                            "input_tokens": 8,
                                            "output_tokens": 12
                                        }
                                    }
                                ]
                            }
                        }
                    }
                ]
            }
        }
    },
    "websocket_client_features": {
        "description": "Features available in the web client interface",
        "capabilities": [
            "Real-time messaging with AI agent",
            "Thread-based conversation management",
            "Message history viewing",
            "Thread creation and deletion",
            "Token usage tracking",
            "Auto-reconnection handling"
        ],
        "ui_components": {
            "thread_selector": "Dropdown to select existing threads or create new ones",
            "message_input": "Text input for sending messages to the AI agent",
            "message_display": "Formatted display of conversation history",
            "connection_controls": "Buttons for connect/disconnect functionality",
            "thread_management": "Buttons for creating and deleting threads"
        }
    },
    "error_responses": {
        "400": {
            "description": "Bad Request - Invalid input parameters",
            "example": {
                "error": "Invalid thread_id format"
            }
        },
        "404": {
            "description": "Not Found - Resource does not exist",
            "example": {
                "error": "Thread not found"
            }
        },
        "500": {
            "description": "Internal Server Error",
            "example": {
                "error": "Database connection failed"
            }
        }
    }
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI startup and shutdown events."""
    # Startup logic
    try:
        print("🚀 Starting up AI Agent WebSocket Server...")
        print("Ensuring database tables exist...")
        await ensure_users_table()
        print("✅ Users table ensured successfully")
        
        # # Create test user with proper hashing
        # print("Creating test user...")
        # await create_test_user()
        # print("✅ Test user created successfully")
        
        # If other tables need creation, they can be added here.
        print("✅ Database initialization completed")
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
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Parse the message (expecting JSON with thread_id and message)
            try:
                message_data = json.loads(data)
                thread_id = message_data.get("thread_id", "1")
                user_message = message_data.get("message", "")
                
                if not user_message:
                    await websocket.send_text("Error: No message provided")
                    continue
                    
            except json.JSONDecodeError:
                # If not JSON, treat as simple message
                thread_id = "1"
                user_message = data
            
            # Send acknowledgment
            await websocket.send_text(f"Starting workflow with message: {user_message}")
            
            # Run the workflow and stream chunks
            try:
                # Create the message in the format expected by the workflow
                messages = [HumanMessage(content=user_message)]
                
                # Stream the workflow results
                async for chunk in invoke_workflow_stream(thread_id, messages):
                    # Extract meaningful content and convert to clean JSON
                    clean_chunk = extract_meaningful_content(chunk)
                    # Include thread_id in the message for client-side filtering
                    message_with_thread = {
                        'thread_id': thread_id,
                        'data': clean_chunk
                    }
                    await websocket.send_text(load.dumps(message_with_thread))
                    
            except Exception as e:
                await websocket.send_text(f"Error running workflow: {str(e)}")
                
    except WebSocketDisconnect:
        # Client disconnected - no need to manage global state
        print(f"WebSocket disconnected for user: {username}")
        pass

if __name__ == "__main__":
    # Get host and port from environment variables with defaults
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    
    print(f"Starting WebSocket server on http://{host}:{port}")
    print(f"WebSocket endpoint: ws://{host}:{port}/ws")
    uvicorn.run(app, host=host, port=port)