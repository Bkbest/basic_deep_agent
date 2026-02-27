import asyncio
import json
import sys
from typing import Set, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

# Set Windows-compatible event loop policy for psycopg
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add the src directory to the path so we can import our modules
sys.path.append('.')

from AI_Agent.basic_agent import invoke_workflow_stream
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

            function addMessage(message) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message';
                messageDiv.textContent = message;
                messagesDiv.appendChild(messageDiv);
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }

            function connect() {
                if (ws === null || ws.readyState === WebSocket.CLOSED) {
                    ws = new WebSocket('ws://localhost:8000/ws');
                    
                    ws.onopen = function(event) {
                        addMessage('Connected to server');
                    };

                    ws.onmessage = function(event) {
                        addMessage('Server: ' + event.data);
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
                if (message && ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(message);
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

            // Auto-connect on page load
            window.onload = function() {
                connect();
            };
        </script>
    </body>
    </html>
    """)

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