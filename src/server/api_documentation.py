"""API documentation for the AI Agent WebSocket Server.

Extracted from ``websocket_server.py`` so the server module stays focused on
runtime logic. Served verbatim by the ``GET /agentAPIDoc`` endpoint.
"""

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
            "POST /api/crons",
            "GET /api/crons",
            "GET /api/crons/{cron_id}",
            "PATCH /api/crons/{cron_id}",
            "DELETE /api/crons/{cron_id}",
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
                        "POST /api/crons": "Create or update a cron job (requires auth)",
                        "GET /api/crons": "List cron jobs (requires auth)",
                        "GET /api/crons/{cron_id}": "Get one cron job (requires auth)",
                        "PATCH /api/crons/{cron_id}": "Enable/disable a cron job (requires auth)",
                        "DELETE /api/crons/{cron_id}": "Delete a cron job (requires auth)",
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
                "description": "List of messages in the thread. Only human, AI, and UI-visible tool "
                               "messages (write_todos, screenshot) are returned; other tool traffic "
                               "stays internal to the agent loop.",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "oneOf": [
                                    {"type": "string"},
                                    {
                                        "type": "array",
                                        "description": "Multimodal content blocks. `screenshot` tool "
                                                       "messages use this shape: a text block holding "
                                                       "the tool's JSON payload, plus an image_url block "
                                                       "carrying the base64 PNG/JPEG data URL.",
                                        "items": {
                                            "oneOf": [
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "type": {"type": "string", "enum": ["text"]},
                                                        "text": {"type": "string"}
                                                    }
                                                },
                                                {
                                                    "type": "object",
                                                    "properties": {
                                                        "type": {"type": "string", "enum": ["image_url"]},
                                                        "image_url": {
                                                            "type": "string",
                                                            "description": "Data URL, e.g. data:image/png;base64,<data>"
                                                        }
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                ]
                            },
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
                    },
                    {
                        "content": "Updated todo list to [{'content': 'Create a detailed list of pending tasks', 'status': 'in_progress'}, {'content': 'Recheck that the answer reached the user', 'status': 'pending'}]",
                        "type": "tool",
                        "id": "msg3"
                    },
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": "{\"success\": true, \"screenshot\": \"<image data omitted; attached as an image block>\", \"artifact_id\": \"2c0a71edf1c04d3e8ea5552dff7ed2b0\", \"url\": \"/artifacts/2c0a71edf1c04d3e8ea5552dff7ed2b0\", \"mime\": \"image/png\", \"size\": 60724}"
                            },
                            {
                                "type": "image_url",
                                "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...<truncated>"
                            }
                        ],
                        "type": "tool",
                        "id": "msg4"
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
        "POST /api/crons": {
            "description": "Create or update a cron job. Re-saving an existing name updates it in place.",
            "parameters": {
                "name": {
                    "type": "string",
                    "description": "Human readable cron name (unique)",
                    "required": True
                },
                "prompt": {
                    "type": "string",
                    "description": "Prompt sent to the agent on each run",
                    "required": True
                },
                "schedule": {
                    "type": "string",
                    "description": "Standard 5-field cron expression",
                    "required": True,
                    "example": "0 9 * * *"
                },
                "thread_id": {
                    "type": "string",
                    "description": "Thread id the cron is bound to (required). It is also used as "
                                   "the cron_id, so the cron and its thread stay aligned.",
                    "required": True,
                    "example": "cron_daily_tech_digest_1790520617"
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Whether the cron should be scheduled",
                    "required": False,
                    "default": True
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
                "description": "The saved cron record",
                "schema": {
                    "type": "object",
                    "properties": {
                        "cron_id": {"type": "string"},
                        "name": {"type": "string"},
                        "thread_id": {"type": "string"},
                        "prompt": {"type": "string"},
                        "schedule": {"type": "string"},
                        "is_active": {"type": "boolean"},
                        "created_at": {"type": "string", "format": "datetime"},
                        "next_run_at": {"type": "string", "format": "datetime"},
                        "last_run_at": {"type": "string", "format": "datetime"}
                    }
                }
            },
            "example": {
                "request": {
                    "method": "POST",
                    "url": "http://localhost:8000/api/crons",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                    },
                    "body": {
                        "name": "Daily Tech Digest",
                        "prompt": "Summarize top tech news from HackerNews and Arxiv from the last 24 hours.",
                        "schedule": "0 9 * * *",
                        "thread_id": "cron_daily_tech_digest_1790520617",
                        "is_active": True
                    }
                },
                "response": {
                    "cron_id": "cron_daily_tech_digest_1790520617",
                    "name": "Daily Tech Digest",
                    "thread_id": "cron_daily_tech_digest_1790520617",
                    "prompt": "Summarize top tech news from HackerNews and Arxiv from the last 24 hours.",
                    "schedule": "0 9 * * *",
                    "is_active": True,
                    "created_at": "2026-10-24T09:10:00Z",
                    "next_run_at": "2026-10-25T09:00:00Z",
                    "last_run_at": None
                }
            }
        },
        "GET /api/crons": {
            "description": "List cron jobs, newest first",
            "parameters": {
                "active_only": {
                    "type": "boolean",
                    "description": "When true, only enabled crons are returned",
                    "required": False,
                    "default": False
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
                "description": "Array of cron objects (single-element array when only one cron exists)",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cron_id": {"type": "string"},
                            "name": {"type": "string"},
                            "thread_id": {"type": "string"},
                            "prompt": {"type": "string"},
                            "schedule": {"type": "string"},
                            "is_active": {"type": "boolean"},
                            "created_at": {"type": "string", "format": "datetime"},
                            "next_run_at": {"type": "string", "format": "datetime"},
                            "last_run_at": {"type": "string", "format": "datetime"}
                        }
                    }
                }
            },
            "example": {
                "request": {
                    "method": "GET",
                    "url": "http://localhost:8000/api/crons",
                    "headers": {
                        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJqb2huX2RvZSIsImV4cCI6MTY5OTk5OTk5OX0.example_signature"
                    }
                },
                "response": [
                    {
                        "cron_id": "cron_daily_tech_digest_1790520617",
                        "name": "Daily Tech Digest",
                        "thread_id": "cron_daily_tech_digest_1790520617",
                        "prompt": "Summarize top tech news from HackerNews and Arxiv from the last 24 hours.",
                        "schedule": "0 9 * * *",
                        "is_active": True,
                        "created_at": "2026-10-24T09:10:00Z",
                        "next_run_at": "2026-10-25T09:00:00Z",
                        "last_run_at": "2026-10-24T09:00:00Z"
                    }
                ]
            }
        },
        "GET /api/crons/{cron_id}": {
            "description": "Get a single cron by cron_id or thread_id",
            "parameters": {
                "cron_id": {
                    "type": "string",
                    "description": "Cron identifier (cron_id or thread_id)",
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
                "description": "The cron object, or 404 if not found"
            }
        },
        "PATCH /api/crons/{cron_id}": {
            "description": "Enable or disable a cron job (recomputes next_run_at when enabling)",
            "parameters": {
                "cron_id": {
                    "type": "string",
                    "description": "Cron identifier (cron_id or thread_id)",
                    "required": True
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Desired active state",
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
                "description": "The updated cron object, or 404 if not found"
            }
        },
        "DELETE /api/crons/{cron_id}": {
            "description": "Delete a cron job by cron_id or thread_id",
            "parameters": {
                "cron_id": {
                    "type": "string",
                    "description": "Cron identifier (cron_id or thread_id)",
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
                "description": "Deletion confirmation, or 404 if not found",
                "schema": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "cron_id": {"type": "string"}
                    }
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
                            "description": "Workflow chunk data keyed by node name. Each node may hold "
                                           "`ai_messages`, `human_messages`, and `tool_messages` "
                                           "arrays."
                        }
                    }
                },
                "node_message_keys": {
                    "ai_messages": "AI replies with non-empty content, including usage_metadata",
                    "human_messages": "Messages sent by the user",
                    "tool_messages": "Results from UI-visible tools only: write_todos and screenshot"
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
                    },
                    {
                        "thread_id": "thread_abc123_1640995200000",
                        "data": {
                            "tool_node": {
                                "tool_messages": [
                                    {
                                        "content": "Updated todo list to [{'content': 'Check the weather forecast', 'status': 'in_progress'}, {'content': 'Recheck that the answer reached the user', 'status': 'pending'}]",
                                        "type": "tool",
                                        "id": "msg_124"
                                    }
                                ]
                            }
                        }
                    },
                    {
                        "thread_id": "thread_abc123_1640995200000",
                        "data": {
                            "tool_node": {
                                "tool_messages": [
                                    {
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "{\"success\": true, \"screenshot\": \"<image data omitted; attached as an image block>\", \"artifact_id\": \"2c0a71edf1c04d3e8ea5552dff7ed2b0\", \"url\": \"/artifacts/2c0a71edf1c04d3e8ea5552dff7ed2b0\", \"mime\": \"image/png\", \"size\": 60724}"
                                            },
                                            {
                                                "type": "image_url",
                                                "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...<truncated>"
                                            }
                                        ],
                                        "type": "tool",
                                        "id": "msg_125"
                                    }
                                ]
                            }
                        }
                    }
                ]
            }
        }
    },
    "tool_responses": {
        "description": "Sample tool results as they appear in `tool_messages`. Only `write_todos` "
                       "and `screenshot` results are delivered to clients; every other tool message "
                       "stays inside the agent loop.",
        "visible_tools": ["write_todos", "screenshot"],
        "message_shape": {
            "content": "string for write_todos, list of content blocks for screenshot",
            "type": "\"tool\"",
            "id": "message id, e.g. msg_125"
        },
        "examples": {
            "write_todos": {
                "description": "Plain-text confirmation that the agent's TODO list was replaced. "
                               "`content` is a string.",
                "response": {
                    "content": "Updated todo list to [{'content': 'Create a detailed list of pending tasks', 'status': 'completed'}, {'content': 'Check the weather forecast', 'status': 'in_progress'}, {'content': 'Recheck that the answer reached the user', 'status': 'pending'}]",
                    "type": "tool",
                    "id": "msg_124"
                }
            },
            "screenshot": {
                "description": "Page screenshot returned by the MCP `screenshot` tool. The raw base64 "
                               "is moved out of the text and into an `image_url` block, so `content` "
                               "is a list. The text block still carries the tool's original JSON "
                               "(success flag, artifact id, URL, MIME type, byte size) with the "
                               "`screenshot` value replaced by a placeholder. Render the "
                               "`image_url` block directly in an <img> tag.",
                "raw_tool_output": {
                    "success": True,
                    "screenshot": "<base64 image data>",
                    "artifact_id": "2c0a71edf1c04d3e8ea5552dff7ed2b0",
                    "url": "/artifacts/2c0a71edf1c04d3e8ea5552dff7ed2b0",
                    "mime": "image/png",
                    "size": 60724
                },
                "response": {
                    "content": [
                        {
                            "type": "text",
                            "text": "{\"success\": true, \"screenshot\": \"<image data omitted; attached as an image block>\", \"artifact_id\": \"2c0a71edf1c04d3e8ea5552dff7ed2b0\", \"url\": \"/artifacts/2c0a71edf1c04d3e8ea5552dff7ed2b0\", \"mime\": \"image/png\", \"size\": 60724}"
                        },
                        {
                            "type": "image_url",
                            "image_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...<truncated>"
                        }
                    ],
                    "type": "tool",
                    "id": "msg_125"
                },
                "rendering_tip": "Iterate `content`; render blocks with type \"text\" as text and "
                                 "blocks with type \"image_url\" as <img src={block.image_url}>. "
                                 "Do not assume `content` is a string for tool messages."
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
