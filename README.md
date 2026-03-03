# New LangGraph Project

[![CI](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/unit-tests.yml)
[![Integration Tests](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/integration-tests.yml/badge.svg)](https://github.com/langchain-ai/new-langgraph-project/actions/workflows/integration-tests.yml)

This template demonstrates a simple application implemented using [LangGraph](https://github.com/langchain-ai/langgraph), designed for showing how to get started with [LangGraph Server](https://langchain-ai.github.io/langgraph/concepts/langgraph_server/#langgraph-server) and using [LangGraph Studio](https://langchain-ai.github.io/langgraph/concepts/langgraph_studio/), a visual debugging IDE.

<div align="center">
  <img src="./static/studio_ui.png" alt="Graph view in LangGraph studio UI" width="75%" />
</div>

The core logic defined in `src/agent/graph.py`, showcases an single-step application that responds with a fixed string and the configuration provided.

You can extend this graph to orchestrate more complex agentic workflows that can be visualized and debugged in LangGraph Studio.

## Getting Started

### Standard Installation

1. Install dependencies, along with the [LangGraph CLI](https://langchain-ai.github.io/langgraph/concepts/langgraph_cli/), which will be used to run the server.

```bash
cd path/to/your/app
pip install -e . "langgraph-cli[inmem]"
```

2. (Optional) Customize the code and project as needed. Create a `.env` file if you need to use secrets.

```bash
cp .env.example .env
```

If you want to enable LangSmith tracing, add your LangSmith API key to the `.env` file.

```text
# .env
LANGSMITH_API_KEY=lsv2...
```

3. Start the LangGraph Server.

```shell
langgraph dev
```

For more information on getting started with LangGraph Server, [see here](https://langchain-ai.github.io/langgraph/tutorials/langgraph-platform/local-server/).

### Raspbian/Debian OS Installation

This application has been tested on Raspberry Pi OS (Raspbian). Follow these steps for installation:

#### Prerequisites

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Python 3 and pip
sudo apt install python3 python3-pip python3-venv -y

# Install PostgreSQL (required for the application)
sudo apt install postgresql postgresql-contrib -y

# Create a dedicated user for the service (optional, recommended for security)
sudo useradd -m -s /bin/bash bkbest21
sudo -u bkbest21 mkdir -p /home/bkbest21
```

#### Installation Steps

1. **Clone and setup the application:**

```bash
# Clone the repository
git clone <repository-url>
cd basic_deep_agent

# Switch to the service user (if using dedicated user)
sudo su - bkbest21

# Navigate to the server directory
cd src/server

# Run the deployment script
./deploy.sh
```

2. **Configure environment variables:**

Create a `.env` file in the server directory:

```bash
sudo -u bkbest21 nano /home/bkbest21/src/server/.env
```

Add the following variables:

```text
# Database connection
POSTGRES_CONNECTION_STRING=postgresql://username:password@localhost:5432/database_name

# Application settings
HOST=0.0.0.0
PORT=8001
```

3. **Setup PostgreSQL database:**

```bash
# Switch to postgres user
sudo -u postgres psql

# Create database and user
CREATE DATABASE database_name;
CREATE USER username WITH ENCRYPTED PASSWORD 'password';
GRANT ALL PRIVILEGES ON DATABASE database_name TO username;
\q
```

#### Service Management

The application runs as a systemd service named `research-agent.service`. Here are the management commands:

```bash
# Check service status
sudo systemctl status research-agent.service

# Start the service
sudo systemctl start research-agent.service

# Stop the service
sudo systemctl stop research-agent.service

# Restart the service
sudo systemctl restart research-agent.service

# Enable service to start on boot
sudo systemctl enable research-agent.service

# Disable service from starting on boot
sudo systemctl disable research-agent.service

# View service logs
sudo journalctl -u research-agent.service -f

# View logs with timestamps
sudo journalctl -u research-agent.service --since "2024-01-01" --until "2024-01-02"

# Follow logs in real-time
sudo journalctl -u research-agent.service -f
```

#### Customizing Service Configuration

To modify the service user, port, or other settings, edit the `deploy.sh` script:

```bash
nano src/server/deploy.sh
```

Key variables to modify:

- `SERVICE_NAME`: Change the service name (default: "research-agent")
- `RUN_USER`: Change the user that runs the service (default: "bkbest21")
- `PORT`: Change the port number (default: "8001")

Example modifications:

```bash
SERVICE_NAME="my-custom-agent"
RUN_USER="myuser"
PORT="8080"
```

After making changes, redeploy:

```bash
# Stop and disable the current service
sudo systemctl stop research-agent.service
sudo systemctl disable research-agent.service

# Run the deployment script again
./deploy.sh
```

#### Troubleshooting

```bash
# Check if the service is running
sudo systemctl status research-agent.service

# Check for errors in logs
sudo journalctl -u research-agent.service -p err

# Verify port is listening
sudo netstat -tlnp | grep 8001

# Check if the application files exist
ls -la /home/bkbest21/src/server/

# Verify Python environment
sudo -u bkbest21 /home/bkbest21/src/server/.venv/bin/python --version
```

## How to customize

1. **Define runtime context**: Modify the `Context` class in the `graph.py` file to expose the arguments you want to configure per assistant. For example, in a chatbot application you may want to define a dynamic system prompt or LLM to use. For more information on runtime context in LangGraph, [see here](https://langchain-ai.github.io/langgraph/agents/context/?h=context#static-runtime-context).

2. **Extend the graph**: The core logic of the application is defined in [graph.py](./src/agent/graph.py). You can modify this file to add new nodes, edges, or change the flow of information.

## Development

While iterating on your graph in LangGraph Studio, you can edit past state and rerun your app from previous states to debug specific nodes. Local changes will be automatically applied via hot reload.

Follow-up requests extend the same thread. You can create an entirely new thread, clearing previous history, using the `+` button in the top right.

For more advanced features and examples, refer to the [LangGraph documentation](https://langchain-ai.github.io/langgraph/). These resources can help you adapt this template for your specific use case and build more sophisticated conversational agents.

LangGraph Studio also integrates with [LangSmith](https://smith.langchain.com/) for more in-depth tracing and collaboration with teammates, allowing you to analyze and optimize your chatbot's performance.

