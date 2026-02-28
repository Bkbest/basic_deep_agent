#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="research-agent"
RUN_USER="bkbest21"
PORT="8001"

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"

if [[ "$(id -un)" != "$RUN_USER" ]]; then
  echo "Please run this script as user '$RUN_USER' (current: $(id -un))."
  exit 1
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$APP_DIR/../../"

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$UNIT_PATH" >/dev/null <<EOF
[Unit]
Description=research-agent FastAPI Server
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
Environment="HOST=0.0.0.0"
Environment="PORT=${PORT}"
ExecStart=${VENV_DIR}/bin/python websocket_server.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload

# Enable and start the service
sudo systemctl enable --now "${SERVICE_NAME}.service" 


echo "Deployed. FastAPI service is installed and enabled: ${SERVICE_NAME}.service"
echo "Check status with: sudo systemctl status ${SERVICE_NAME}.service"
echo "Logs: sudo journalctl -u ${SERVICE_NAME}.service -f"
