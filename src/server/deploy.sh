#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="research-agent"
RUN_USER="bkbest21"
PORT="8001"

# 4. Pi-optimized whisper defaults (tiny + int8 = usable latency on Pi).
#    Override any of these by exporting the env var before running the app.
export WHISPER_MODEL="${WHISPER_MODEL:-tiny}"
export WHISPER_DEVICE="${WHISPER_DEVICE:-cpu}"
export WHISPER_COMPUTE="${WHISPER_COMPUTE:-int8}"

# Piper TTS default voice. Override by exporting PIPER_MODEL to an .onnx file path.
export PIPER_MODEL="${PIPER_MODEL:-en_US-ryan-high}"

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"

# Repo-root .env, as an absolute path. systemd reads it directly via
# EnvironmentFile= below, so secrets (LANGSMITH_API_KEY, POSTGRES_CONNECTION_STRING,
# TAVILY_API_KEY) stay in the gitignored .env instead of being copied into
# /etc/systemd/system/*.service, which is world-readable (0644).
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  # The file holds credentials; keep it owner-only.
  if [[ "$(stat -c '%a' "$ENV_FILE")" != "600" ]]; then
    echo "Tightening $ENV_FILE to 600 (it contains secrets)."
    chmod 600 "$ENV_FILE" || sudo chmod 600 "$ENV_FILE" || true
  fi
else
  echo "Warning: $ENV_FILE not found; the service will start without .env values." >&2
fi

# Fail fast on the silent failure mode: with tracing on and no key, langsmith
# does not error, it just fails every upload with HTTP 401 and the UI stays empty.
if grep -qE '^LANGSMITH_TRACING=(true|True|TRUE|1|yes)$' "$ENV_FILE" 2>/dev/null \
   && ! grep -qE '^LANGSMITH_API_KEY=.+' "$ENV_FILE" 2>/dev/null; then
  echo "Warning: LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is empty in $ENV_FILE." >&2
  echo "         Every trace upload will fail with HTTP 401; the LangSmith UI will stay empty." >&2
fi

if [[ "$(id -un)" != "$RUN_USER" ]]; then
  echo "Please run this script as user '$RUN_USER' (current: $(id -un))."
  exit 1
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$APP_DIR/../../"

# Pre-fetch the Piper voice into the project's src/AI_Tools/ directory so
# the service has the .onnx + .onnx.json locally and boots offline.
# Runs only if the voice name (not a path) is given.
"$VENV_DIR/bin/python" -m piper.download_voices en_US-ryan-high --download-dir "$APP_DIR/../../src/AI_Tools"

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=research-agent FastAPI Server
After=network.target pandora-sandbox-mcp.service careerops-server.service


[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
Environment="HOST=0.0.0.0"
Environment="PORT=${PORT}"
Environment="WHISPER_MODEL=${WHISPER_MODEL}"
Environment="WHISPER_DEVICE=${WHISPER_DEVICE}"
Environment="WHISPER_COMPUTE=${WHISPER_COMPUTE}"
Environment="PIPER_MODEL=${PIPER_MODEL}"
# LangSmith tracing config (LANGSMITH_TRACING, LANGSMITH_ENDPOINT,
# LANGSMITH_API_KEY, LANGSMITH_AGENT_ID, LANGSMITH_AGENT_ENVIRONMENT) comes
# from the repo-root .env. The leading '-' makes a missing file non-fatal.
EnvironmentFile=-${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python websocket_server.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

echo "Deployed. FastAPI service is installed and enabled: ${SERVICE_NAME}.service"
echo "Check status with: sudo systemctl status ${SERVICE_NAME}.service"
echo "Logs: sudo journalctl -u ${SERVICE_NAME}.service -f"
