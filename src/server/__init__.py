"""
AI Agent WebSocket Server Package

This package contains the WebSocket server implementation for streaming
AI agent workflow chunks to connected clients.

Main components:
- websocket_server.py: FastAPI-based WebSocket server
- test_client.py: Python test client
- start_server.py: Startup script with dependency management
"""

__version__ = "1.0.0"
__author__ = "AI Agent Team"

# Export main components
# NOTE: the old ConnectionManager class was replaced by the module-level
# websocket cache (register_websocket / unregister_websocket / get_websocket),
# so only `app` is exported here.
from .websocket_server import app

__all__ = ["app"]