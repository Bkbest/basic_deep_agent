import asyncio
import json
import sys
from typing import Set, Any
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
sys.path.append('.')

# Load environment variables
load_dotenv()

from AI_Agent.basic_agent import invoke_workflow_stream, get_threads, get_thread
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

def extract_meaningful_content(chunk: dict) -> dict:
    """
    Extract messages from workflow chunks and convert to clean JSON format
    """
    result = {}
    
    for node_name, node_data in chunk.items():
        if not isinstance(node_data, dict):
            result[node_name] = node_data
            continue
            
        node_result = {}
        
        # Handle messages with separate keys for AI and Human
        if 'messages' in node_data:
            ai_messages = []
            human_messages = []
            
            for msg in node_data['messages']:
                if hasattr(msg, 'content'):
                    message_content = {
                        'content': getattr(msg, 'content', ''),
                        'id': getattr(msg, 'id', None)
                    }
                    
                    # Add usage metadata if present
                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                        message_content['usage_metadata'] = msg.usage_metadata
                    
                    # Separate by message type
                    msg_type = getattr(msg, 'type', 'unknown')
                    if msg_type == 'ai':
                        ai_messages.append(message_content)
                    elif msg_type == 'human':
                        human_messages.append(message_content)
                    else:
                        # Default to AI for unknown types
                        ai_messages.append(message_content)
            
            if ai_messages:
                node_result['ai_messages'] = ai_messages
            if human_messages:
                node_result['human_messages'] = human_messages
        
        # Add any other clean data
        for key, value in node_data.items():
            if key != 'messages':
                if isinstance(value, (str, int, float, bool, list, dict)):
                    node_result[key] = value
                else:
                    node_result[key] = str(value)
        
        result[node_name] = node_result
    
    return result

app = FastAPI(title="AI Agent WebSocket Server")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connected WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: str):
        # Send message to all connected clients
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                disconnected.add(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

@app.get("/")
async def get_index():
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
            <button onclick="connect()">Connect</button>
            <button onclick="disconnect()">Disconnect</button>
        </div>
        <div id="messages"></div>

        <script>
            let ws = null;
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
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                
                if (typeof data === 'string') {
                    messageDiv.textContent = data;
                } else {
                    // Handle JSON data from workflow chunks
                    let formattedText = '';
                    for (const [nodeName, nodeData] of Object.entries(data)) {
                        formattedText += `[${nodeName}] `;
                        
                        if (nodeData.ai_messages && nodeData.ai_messages.length > 0) {
                            formattedText += 'AI: ';
                            nodeData.ai_messages.forEach(msg => {
                                formattedText += msg.content + ' ';
                            });
                        }
                        
                        if (nodeData.human_messages && nodeData.human_messages.length > 0) {
                            formattedText += 'Human: ';
                            nodeData.human_messages.forEach(msg => {
                                formattedText += msg.content + ' ';
                            });
                        }
                        
                        // Add other data
                        for (const [key, value] of Object.entries(nodeData)) {
                            if (key !== 'ai_messages' && key !== 'human_messages') {
                                formattedText += key + ': ' + value + ' ';
                            }
                        }
                        
                        formattedText += '\\n';
                    }
                    messageDiv.textContent = formattedText;
                }
                
                messagesDiv.appendChild(messageDiv);
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
                            }
                        });
                        
                        // Add a separator if there are messages
                        addMessage('--- End of conversation ---');
                    } else {
                        addMessage('No conversation found for this thread');
                    }
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
            }

            function connect() {
                if (ws === null || ws.readyState === WebSocket.CLOSED) {
                    ws = new WebSocket('ws://localhost:8000/ws');
                    
                    ws.onopen = function(event) {
                        addMessage('Connected to server');
                    };

                    ws.onmessage = function(event) {
                        try {
                            // Try to parse as JSON
                            const data = JSON.parse(event.data);
                            addFormattedMessage(data);
                        } catch (e) {
                            // If not JSON, treat as plain text
                            addMessage('Server: ' + event.data);
                        }
                    };

                    ws.onclose = function(event) {
                        addMessage('Disconnected from server');
                    };

                    ws.onerror = function(error) {
                        addMessage('Error: ' + error);
                    };
                }
            }

            function disconnect() {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.close();
                }
            }

            function sendMessage() {
                const message = input.value;
                const selectedThreadId = threadSelect.value;
                
                if (message && ws && ws.readyState === WebSocket.OPEN) {
                    // Send message with thread_id if selected
                    const messageData = {
                        message: message,
                        thread_id: selectedThreadId || "1"
                    };
                    ws.send(JSON.stringify(messageData));
                    addMessage('You: ' + message);
                    input.value = '';
                }
            }

            // Allow Enter key to send message
            input.addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });

            // Auto-connect and load threads on page load
            window.onload = function() {
                connect();
                loadThreads();
            };
        </script>
    </body>
    </html>
    """)

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
    Get a specific thread by thread_id
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

def process_thread_result(result):
    """
    Process thread result to extract only human and AI messages
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
                
                # Include human messages and AI messages without tool calls
                if msg_type == 'human':
                    clean_msg = {
                        'content': content,
                        'type': msg_type,
                        'id': msg_id
                    }
                    filtered_messages.append(clean_msg)
                    print(f"Added human message: {clean_msg}")
                elif msg_type == 'ai' and (not tool_calls or len(tool_calls) == 0):
                    clean_msg = {
                        'content': content,
                        'type': msg_type,
                        'id': msg_id
                    }
                    
                    # Add usage metadata if present (for AI messages)
                    if usage_metadata:
                        clean_msg['usage_metadata'] = usage_metadata
                    
                    filtered_messages.append(clean_msg)
                    print(f"Added AI message (no tool calls): {clean_msg}")
                elif msg_type == 'ai' and tool_calls and len(tool_calls) > 0:
                    print(f"Skipping AI message with tool calls: {msg_id}")
            
            print(f"Returning {len(filtered_messages)} filtered messages")
            return filtered_messages
        else:
            print("No channel_values found in checkpoint")
    else:
        print(f"Result is not a list/tuple or doesn't have enough elements. Type: {type(result)}, Length: {len(result) if hasattr(result, '__len__') else 'N/A'}")
    
    return []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
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
                    await websocket.send_text(json.dumps(clean_chunk))
                    
            except Exception as e:
                await websocket.send_text(f"Error running workflow: {str(e)}")
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    print("Starting WebSocket server on http://localhost:8000")
    print("WebSocket endpoint: ws://localhost:8000/ws")
    uvicorn.run(app, host="0.0.0.0", port=8000)