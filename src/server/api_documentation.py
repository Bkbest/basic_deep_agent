"""
API Documentation for AI Agent WebSocket Server

This module contains comprehensive documentation for all available API endpoints.
"""

API_DOCUMENTATION = {
    "title": "AI Agent WebSocket Server API",
    "version": "1.0.0",
    "description": "RESTful API and WebSocket server for AI Agent with real-time communication capabilities",
    "base_url": "http://localhost:8000",
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
                    "endpoints": {...}
                }
            }
        },
        "GET /api/threads": {
            "description": "Get all distinct thread IDs from the database",
            "parameters": None,
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
                "request": "GET http://localhost:8000/api/threads",
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
        "GET /api/thread/{thread_id}": {
            "description": "Get a specific thread by thread_id, returns current state of the chat",
            "parameters": {
                "thread_id": {
                    "type": "string",
                    "description": "Unique identifier for the thread",
                    "required": True
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
                "request": "GET http://localhost:8000/api/thread/thread_abc123_1640995200000",
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
                "request": "DELETE http://localhost:8000/api/thread/thread_abc123_1640995200000",
                "response": {
                    "success": True,
                    "message": "Thread thread_abc123_1640995200000 deleted successfully"
                }
            }
        },
        "WebSocket /ws": {
            "description": "WebSocket endpoint for real-time communication with the AI agent",
            "parameters": None,
            "connection": {
                "url": "ws://localhost:8000/ws",
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
                "connection": "WebSocket connection to ws://localhost:8000/ws",
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