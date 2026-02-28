import asyncio
import json
import sys
from typing import Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
from dotenv import load_dotenv
import asyncpg
import os

# Set Windows-compatible event loop policy for psycopg
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add the src directory to the path so we can import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Load environment variables
load_dotenv()


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
                elif msg_type == 'ai' and content and content.strip():
                    message_content = {
                        'content': content,
                        'type': msg_type,
                        'id': msg_id
                    }
                    
                    # Add usage metadata if present (for AI messages)
                    if usage_metadata:
                        message_content['usage_metadata'] = usage_metadata
                    
                    ai_messages.append(message_content)
                elif msg_type == 'tool' and content and content.strip():
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

app = FastAPI(title="AI Agent WebSocket Server")
API_DOCUMENTATION = {
    "title": "AI Agent WebSocket Server API",
    "version": "1.0.0",
    "description": "RESTful API and WebSocket server for AI Agent with real-time communication capabilities",
    "base_url": "http://localhost:8000",  # Update this to match your deployment
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
                        "GET /api/threads": "Get all thread IDs",
                        "GET /api/health": "Health check endpoint",
                        "GET /api/thread/{thread_id}": "Get specific thread",
                        "DELETE /api/thread/{thread_id}": "Delete specific thread",
                        "WebSocket /ws": "WebSocket endpoint for real-time communication"
                    }
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
# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/")
async def get_index():
    """
    Serve the main HTML page with WebSocket client interface.
    
    Returns:
        HTMLResponse: The main HTML page containing the WebSocket client UI
    """
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Agent WebSocket Client</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                max-width: 800px; 
                margin: 0 auto; 
                padding: 20px;
            }
            #messages { 
                border: 1px solid #ccc; 
                height: 400px; 
                overflow-y: scroll; 
                padding: 10px; 
                margin: 10px 0;
                background-color: #f5f5f5;
            }
            #input { 
                width: 70%; 
                padding: 10px; 
                margin-right: 10px;
            }
            button { 
                padding: 10px 20px; 
                background-color: #007bff; 
                color: white; 
                border: none; 
                cursor: pointer;
            }
            button:hover { 
                background-color: #0056b3; 
            }
            button[style*="background-color: #28a745"] { 
                background-color: #28a745 !important; 
            }
            button[style*="background-color: #28a745"]:hover { 
                background-color: #218838 !important; 
            }
            button[style*="background-color: #dc3545"] { 
                background-color: #dc3545 !important; 
            }
            button[style*="background-color: #dc3545"]:hover { 
                background-color: #c82333 !important; 
            }
            .message { 
                margin: 5px 0; 
                padding: 5px; 
                background-color: white; 
                border-radius: 5px;
            }
        </style>
    </head>
    <body>
        <h1>AI Agent WebSocket Client</h1>
        <div style="margin-bottom: 20px;">
            <label for="threadSelect">Select Thread:</label>
            <select id="threadSelect" onchange="loadThread()" style="margin-right: 10px; padding: 5px;">
                <option value="">-- Select a thread --</option>
            </select>
            <button onclick="loadThreads()">Refresh Threads</button>
            <button onclick="newConversation()" style="background-color: #28a745; margin-left: 10px;">New Conversation</button>
        </div>
        <div>
            <input type="text" id="input" placeholder="Enter your message..." />
            <button onclick="sendMessage()">Send</button>
            <button onclick="connect()">Connect Thread</button>
            <button onclick="disconnect()">Disconnect Thread</button>
            <button onclick="disconnectAll()" style="background-color: #6c757d; margin-left: 5px;">Disconnect All</button>
            <button onclick="deleteCurrentThread()" style="background-color: #dc3545; margin-left: 10px;">Delete Thread</button>
        </div>
        <div id="messages"></div>

        <script>
            // Map to store WebSocket connections per thread
            const threadConnections = new Map();
            const messagesDiv = document.getElementById('messages');
            const input = document.getElementById('input');
            const threadSelect = document.getElementById('threadSelect');

            function addMessage(message) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                messageDiv.textContent = message;
                messagesDiv.appendChild(messageDiv);
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }

            function addFormattedMessage(data) {
                if (typeof data === 'string') {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message';
                    messageDiv.textContent = data;
                    messagesDiv.appendChild(messageDiv);
                } else {
                    // Handle JSON data from workflow chunks - display messages consistently with loadThread
                    for (const [nodeName, nodeData] of Object.entries(data)) {
                        // Display AI messages
                        if (nodeData.ai_messages && nodeData.ai_messages.length > 0) {
                            nodeData.ai_messages.forEach(msg => {
                                let aiMessage = `🤖 AI: ${msg.content}`;
                                
                                // Add usage metadata if available (for token count, etc.)
                                if (msg.usage_metadata) {
                                    const tokens = msg.usage_metadata.total_tokens || msg.usage_metadata.input_tokens || 0;
                                    if (tokens > 0) {
                                        aiMessage += ` (${tokens} tokens)`;
                                    }
                                }
                                
                                const messageDiv = document.createElement('div');
                                messageDiv.className = 'message';
                                messageDiv.textContent = aiMessage;
                                messagesDiv.appendChild(messageDiv);
                            });
                        }
                        
                        // Display Human messages
                        if (nodeData.human_messages && nodeData.human_messages.length > 0) {
                            nodeData.human_messages.forEach(msg => {
                                const messageDiv = document.createElement('div');
                                messageDiv.className = 'message';
                                messageDiv.textContent = `👤 Human: ${msg.content}`;
                                messagesDiv.appendChild(messageDiv);
                            });
                        }
                        
                        // Display Tool messages (AI thinking in mind)
                        if (nodeData.tool_messages && nodeData.tool_messages.length > 0) {
                            nodeData.tool_messages.forEach(msg => {
                                const messageDiv = document.createElement('div');
                                messageDiv.className = 'message';
                                messageDiv.textContent = `🧠 ${msg.content}`;
                                messagesDiv.appendChild(messageDiv);
                            });
                        }
                        
                        // Add other data as separate messages (for debugging/workflow info)
                        for (const [key, value] of Object.entries(nodeData)) {
                            if (key !== 'ai_messages' && key !== 'human_messages' && key !== 'tool_messages') {
                                const messageDiv = document.createElement('div');
                                messageDiv.className = 'message';
                                messageDiv.textContent = `[${nodeName}] ${key}: ${value}`;
                                messagesDiv.appendChild(messageDiv);
                            }
                        }
                    }
                }
                
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }

            async function loadThreads() {
                try {
                    console.log('Loading threads...');
                    const response = await fetch('/api/threads');
                    console.log('Response status:', response.status);
                    
                    if (!response.ok) {
                        throw new Error('HTTP error! status: ' + response.status);
                    }
                    
                    const data = await response.json();
                    console.log('Threads data received:', data);
                    console.log('Thread select element:', threadSelect);
                    
                    // Clear existing options except the first one
                    threadSelect.innerHTML = '<option value="">-- Select a thread --</option>';
                    
                    if (data.threads && data.threads.length > 0) {
                        console.log('Adding', data.threads.length, 'threads to dropdown');
                        data.threads.forEach(function(thread, index) {
                            console.log('Adding thread ' + index + ':', thread);
                            const option = document.createElement('option');
                            option.value = thread.thread_id;
                            option.textContent = thread.thread_id + ' (' + thread.created_at + ')';
                            threadSelect.appendChild(option);
                        });
                        console.log('Final dropdown options:', threadSelect.options.length);
                        console.log('Loaded', data.threads.length, 'threads');
                    } else {
                        console.log('No threads found in response');
                        addMessage('No existing threads found. Start a new conversation!');
                    }
                } catch (error) {
                    console.error('Error loading threads:', error);
                    addMessage('Error loading threads: ' + error.message);
                }
            }

            async function loadThread() {
                const threadId = threadSelect.value;
                if (!threadId) {
                    return;
                }
                
                try {
                    const response = await fetch(`/api/thread/${threadId}`);
                    const data = await response.json();
                    
                    // Clear messages
                    messagesDiv.innerHTML = '';
                    
                    console.log('Thread data received:', data);
                    
                    // Handle the simplified result - data is directly a list of messages
                    let messages = [];
                    
                    if (Array.isArray(data)) {
                        // New simplified format - data is directly a list of messages
                        messages = data;
                        console.log('Found messages (simplified format):', messages);
                    } else {
                        console.log('No messages found in data structure');
                    }
                    
                    if (messages && messages.length > 0) {
                        // Display the conversation history with better formatting
                        messages.forEach(msg => {
                            if (msg.type === 'human') {
                                addMessage(`👤 Human: ${msg.content}`);
                            } else if (msg.type === 'ai') {
                                let aiMessage = `🤖 AI: ${msg.content}`;
                                
                                // Add usage metadata if available (for token count, etc.)
                                if (msg.usage_metadata) {
                                    const tokens = msg.usage_metadata.total_tokens || msg.usage_metadata.input_tokens || 0;
                                    if (tokens > 0) {
                                        aiMessage += ` (${tokens} tokens)`;
                                    }
                                }
                                
                                addMessage(aiMessage);
                            } else if (msg.type === 'tool') {
                                addMessage(`🧠 ${msg.content}`);
                            }
                        });
                        
                        // Add a separator if there are messages
                        addMessage('--- End of conversation ---');
                    } else {
                        addMessage('No conversation found for this thread');
                    }

                    // Automatically connect to this thread when switching
                    // This ensures smooth thread switching with one connection per thread
                    console.log(`Switching to thread: ${threadId}`);
                    connectThread();
                    
                } catch (error) {
                    console.error('Error loading thread:', error);
                    addMessage('Error loading thread: ' + error.message);
                }
            }

            function newConversation() {
                // Clear messages
                messagesDiv.innerHTML = '';
                
                // Generate a random thread ID
                const newThreadId = 'thread_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
                
                // Create a new option for the dropdown
                const option = document.createElement('option');
                option.value = newThreadId;
                option.textContent = `${newThreadId} (new)`;
                option.selected = true;
                
                // Add to dropdown and select it
                threadSelect.appendChild(option);
                
                addMessage(`Started new conversation with thread ID: ${newThreadId}`);
                
                // Automatically connect to the new thread
                connectThread();
            }

            async function deleteCurrentThread() {
                const threadId = threadSelect.value;
                if (!threadId) {
                    addMessage('Please select a thread to delete');
                    return;
                }
                
                // Confirm deletion
                if (!confirm(`Are you sure you want to delete thread "${threadId}"? This action cannot be undone.`)) {
                    return;
                }
                
                try {
                    const response = await fetch(`/api/thread/${threadId}`, {
                        method: 'DELETE'
                    });
                    
                    if (response.ok) {
                        addMessage(`Thread "${threadId}" deleted successfully`);
                        
                        // Close and remove connection for this thread
                        if (threadConnections.has(threadId)) {
                            const connection = threadConnections.get(threadId);
                            if (connection && connection.readyState === WebSocket.OPEN) {
                                connection.close();
                            }
                            threadConnections.delete(threadId);
                            console.log(`Closed connection for deleted thread: ${threadId}`);
                        }
                        
                        // Remove from dropdown
                        const optionToRemove = threadSelect.querySelector(`option[value="${threadId}"]`);
                        if (optionToRemove) {
                            optionToRemove.remove();
                        }
                        
                        // Clear messages
                        messagesDiv.innerHTML = '';
                        
                        // Select first available thread or clear selection
                        if (threadSelect.options.length > 1) {
                            threadSelect.selectedIndex = 1;
                            loadThread();
                        } else {
                            threadSelect.value = '';
                        }
                        
                        // Refresh threads list
                        loadThreads();
                    } else {
                        const errorData = await response.json();
                        addMessage(`Error deleting thread: ${errorData.error || 'Unknown error'}`);
                    }
                } catch (error) {
                    console.error('Error deleting thread:', error);
                    addMessage(`Error deleting thread: ${error.message}`);
                }
            }

            function connectThread() {
                // Always use the global thread ID from dropdown selection
                const threadId = threadSelect.value;
                
                if (!threadId) {
                    addMessage('Please select a thread first');
                    return null;
                }

                // Check if connection already exists and is active
                if (threadConnections.has(threadId)) {
                    const existingConnection = threadConnections.get(threadId);
                    if (existingConnection && existingConnection.readyState === WebSocket.OPEN) {
                        console.log(`Using existing connection for thread: ${threadId}`);
                        return existingConnection;
                    }
                }

                // Create new connection for this thread
                console.log(`Creating new connection for thread: ${threadId}`);
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const host = window.location.hostname;
                const port = window.location.port || '8000';
                const wsUrl = `${protocol}//${host}:${port}/ws`;
                const ws = new WebSocket(wsUrl);
                
                ws.onopen = function(event) {
                    console.log(`Connected to server for thread: ${threadId}`);
                    addMessage(`🔗 Connected to thread: ${threadId}`);
                };

                ws.onmessage = function(event) {
                    try {
                        // Try to parse as JSON
                        const data = JSON.parse(event.data);
                        
                        // Check if this is a message with thread_id (new format)
                        if (data.thread_id) {
                            // Only show message if it matches this thread's connection
                            if (data.thread_id === threadSelect.value) {
                                addFormattedMessage(data.data);
                            } else {
                                console.log('Skipping message for thread:', data.thread_id, 'Expected thread:', threadId);
                            }
                        } else {
                            // Legacy format without thread_id - show to all
                            addFormattedMessage(data);
                        }
                    } catch (e) {
                        // If not JSON, treat as plain text
                        addMessage('Server: ' + event.data);
                    }
                };

                ws.onclose = function(event) {
                    console.log(`Disconnected from server for thread: ${threadId}`);
                    addMessage(`❌ Disconnected from thread: ${threadId}`);
                    // Remove from connections map when closed
                    threadConnections.delete(threadId);
                };

                ws.onerror = function(error) {
                    console.error(`WebSocket error for thread ${threadId}:`, error);
                    addMessage(`❌ Error in thread ${threadId}: ` + error);
                };

                // Store the connection in our map
                threadConnections.set(threadId, ws);
                return ws;
            }

            function connect() {
                connectThread();
            }

            function disconnect() {
                const selectedThreadId = threadSelect.value;
                if (!selectedThreadId) {
                    addMessage('Please select a thread to disconnect');
                    return;
                }

                if (threadConnections.has(selectedThreadId)) {
                    const connection = threadConnections.get(selectedThreadId);
                    if (connection && connection.readyState === WebSocket.OPEN) {
                        connection.close();
                        threadConnections.delete(selectedThreadId);
                        addMessage(`🔌 Disconnected from thread: ${selectedThreadId}`);
                    }
                } else {
                    addMessage('No active connection found for this thread');
                }
            }

            function disconnectAll() {
                // Close all connections
                for (const [threadId, connection] of threadConnections) {
                    if (connection && connection.readyState === WebSocket.OPEN) {
                        connection.close();
                    }
                }
                threadConnections.clear();
                addMessage('🔌 Disconnected from all threads');
            }

            function sendMessage() {
                const message = input.value;
                const selectedThreadId = threadSelect.value;
                
                if (!selectedThreadId) {
                    addMessage('Please select a thread first');
                    return;
                }

                if (!message) {
                    addMessage('Please enter a message');
                    return;
                }

                // Get or create connection for this thread
                const ws = connectThread();
                
                if (ws && ws.readyState === WebSocket.OPEN) {
                    // Send message with thread_id
                    const messageData = {
                        message: message,
                        thread_id: selectedThreadId
                    };
                    ws.send(JSON.stringify(messageData));
                    addMessage(`📤 You (${selectedThreadId}): ${message}`);
                    input.value = '';
                } else {
                    addMessage(`❌ Cannot send message - not connected to thread: ${selectedThreadId}`);
                }
            }

            // Allow Enter key to send message
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });

            // Load threads on page load (connections will be created per thread as needed)
            window.onload = function() {
                loadThreads();
            };
        </script>
    </body>
    </html>
    """)

@app.get("/agentAPIDoc")
async def get_api_documentation():
    """
    Get comprehensive API documentation for all available endpoints.
    
    Returns:
        JSON: Complete API documentation with examples, schemas, and usage instructions
    """
    return API_DOCUMENTATION

@app.get("/api/threads")
async def get_threads_endpoint():
    """
    Get all distinct thread IDs from the database
    """
    try:
        print("Fetching threads...")
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
    Simple health check endpoint
    """
    try:
        connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
        if not connection_string:
            return {"status": "error", "message": "POSTGRES_CONNECTION_STRING not set"}
        
        # Test database connection
        conn = await asyncpg.connect(connection_string)
        await conn.execute('SELECT 1')
        await conn.close()
        
        return {"status": "ok", "message": "Database connection successful"}
    except Exception as e:
        return {"status": "error", "message": f"Database connection failed: {str(e)}"}

@app.get("/api/thread/{thread_id}")
async def get_thread_endpoint(thread_id: str):
    """
    Get a specific thread by thread_id, returns current state of the chat.
    """
    try:
        # Call the synchronous function directly
        result = get_thread(thread_id)
        
        # Process the result to filter only human and AI messages
        processed_result = process_thread_result(result)
        return processed_result
    except Exception as e:
        print(f"Error in get_thread_endpoint: {e}")
        return {"error": f"Failed to fetch thread: {str(e)}"}

@app.delete("/api/thread/{thread_id}")
async def delete_thread_endpoint(thread_id: str):
    """
    Delete a specific thread by thread_id
    """
    try:
        # Import the async version
        from AI_Agent.basic_agent import delete_thread as delete_thread_async
        result = await delete_thread_async(thread_id)
        return {"success": True, "message": f"Thread {thread_id} deleted successfully"}
    except Exception as e:
        print(f"Error in delete_thread_endpoint: {e}")
        return {"error": f"Failed to delete thread: {str(e)}"}

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
    print(f"Processing result type: {type(result)}")
    print(f"Result: {result}")
    
    # Handle CheckpointTuple - convert to tuple and access like sample JSON
    if hasattr(result, '__iter__') and not isinstance(result, (str, dict, list)):
        try:
            result = tuple(result)
            print(f"Converted to tuple: {result}")
        except:
            pass
    
    # Handle list/tuple format like sample JSON: [config, checkpoint, ...]
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        checkpoint = result[1]  # Second element contains the checkpoint data
        print(f"Checkpoint: {checkpoint}")
        
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
                    print(f"Added human message: {clean_msg}")
                elif msg_type == 'ai' and content and content.strip():
                    clean_msg = {
                        'content': content,
                        'type': msg_type,
                        'id': msg_id
                    }
                    
                    # Add usage metadata if present (for AI messages)
                    if usage_metadata:
                        clean_msg['usage_metadata'] = usage_metadata
                    
                    filtered_messages.append(clean_msg)
                    print(f"Added AI message (non-empty content): {clean_msg}")
                elif msg_type == 'tool' and content and content.strip():
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
                elif msg_type in ['ai', 'tool'] and (not content or not content.strip()):
                    print(f"Skipping {msg_type} message with empty content: {msg_id}")
            
            print(f"Returning {len(filtered_messages)} filtered messages")
            return filtered_messages
        else:
            print("No channel_values found in checkpoint")
    else:
        print(f"Result is not a list/tuple or doesn't have enough elements. Type: {type(result)}, Length: {len(result) if hasattr(result, '__len__') else 'N/A'}")
    
    return []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication with the AI agent.
    
    This endpoint handles:
    - Real-time message streaming from the AI agent
    - Thread-based conversation management
    - Workflow execution and chunk streaming
    
    Direct point-to-point communication without global connection management.
    
    Args:
        websocket: The WebSocket connection
        
    Raises:
        WebSocketDisconnect: When the client disconnects
    """
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
                    await websocket.send_text(json.dumps(message_with_thread))
                    
            except Exception as e:
                await websocket.send_text(f"Error running workflow: {str(e)}")
                
    except WebSocketDisconnect:
        # Client disconnected - no need to manage global state
        pass

if __name__ == "__main__":
    # Get host and port from environment variables with defaults
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    
    print(f"Starting WebSocket server on http://{host}:{port}")
    print(f"WebSocket endpoint: ws://{host}:{port}/ws")
    uvicorn.run(app, host=host, port=port)