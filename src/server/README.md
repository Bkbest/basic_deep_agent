# AI Agent WebSocket Server

This directory contains a WebSocket server that streams chunks from the AI Agent workflow to connected clients.

## Features

- **WebSocket Streaming**: Real-time streaming of AI agent workflow chunks
- **FastAPI Backend**: High-performance async web framework
- **CORS Enabled**: Cross-origin requests supported
- **Web Client**: Built-in HTML client for testing
- **Multiple Clients**: Supports multiple concurrent WebSocket connections

## Files

- `websocket_server.py` - Main WebSocket server implementation
- `test_client.py` - Simple Python test client
- `start_server.py` - Startup script with automatic dependency installation
- `requirements.txt` - Python dependencies
- `README.md` - This file

## Quick Start

### Option 1: Using the startup script (Recommended)

```bash
cd src/server
python start_server.py
```

This will automatically install dependencies and start the server.

### Option 2: Manual setup

1. Install dependencies:
```bash
cd src/server
pip install -r requirements.txt
```

2. Start the server:
```bash
python websocket_server.py
```

## Usage

### Web Interface

1. Open your browser and navigate to `http://localhost:8000`
2. Click "Connect" to establish a WebSocket connection
3. Enter your message in the input field and click "Send"
4. Watch the streaming responses in the messages area

### Python Client

Run the test client:
```bash
python test_client.py
```

### Custom Client

You can connect to the WebSocket server using any WebSocket client:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = function(event) {
    // Send a message
    ws.send(JSON.stringify({
        thread_id: "1",
        message: "research about renewable energy"
    }));
};

ws.onmessage = function(event) {
    // Handle received chunks
    const data = JSON.parse(event.data);
    console.log('Received chunk:', data);
};
```

## API Endpoints

### WebSocket Endpoint: `/ws`

**Connection**: WebSocket connection to `ws://localhost:8000/ws`

**Message Format** (JSON):
```json
{
    "thread_id": "1",
    "message": "Your message here"
}
```

**Response Format**: JSON chunks streamed from the AI agent workflow

### HTTP Endpoints

- `GET /` - Web interface for testing
- `GET /health` - Health check endpoint (if needed)

## Configuration

The server runs on `localhost:8000` by default. To change the port, modify the `uvicorn.run()` call in `websocket_server.py`:

```python
uvicorn.run(app, host="0.0.0.0", port=8000)  # Change port here
```

## Error Handling

- Connection errors are handled gracefully
- Invalid JSON messages are treated as simple text
- Workflow errors are streamed back to the client
- Disconnected clients are automatically removed

## Dependencies

- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `websockets` - WebSocket support
- `python-multipart` - Multipart form data support

## Troubleshooting

1. **Connection Refused**: Make sure the server is running on port 8000
2. **Import Errors**: Ensure the `src` directory is in the Python path
3. **CORS Issues**: The server is configured to allow all origins for development
4. **Workflow Errors**: Check the AI agent configuration and dependencies

## Development

To modify the server:

1. Edit `websocket_server.py` for server logic
2. Edit `test_client.py` for client testing
3. Test changes with the web interface or test client

The server uses async/await patterns for handling multiple concurrent connections efficiently.