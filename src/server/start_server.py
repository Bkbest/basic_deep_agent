#!/usr/bin/env python3
"""
Startup script for the AI Agent WebSocket server
"""
import subprocess
import sys
import os

def install_requirements():
    """Install required packages"""
    print("Installing requirements...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("Requirements installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Error installing requirements: {e}")
        return False
    return True

def start_server():
    """Start the WebSocket server"""
    print("Starting AI Agent WebSocket Server...")
    print("Server will be available at: http://localhost:8000")
    print("WebSocket endpoint: ws://localhost:8000/ws")
    print("Press Ctrl+C to stop the server")
    
    try:
        subprocess.run([sys.executable, "websocket_server.py"])
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Error starting server: {e}")

if __name__ == "__main__":
    # Change to the server directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Install requirements
    if not install_requirements():
        sys.exit(1)
    
    # Start the server
    start_server()