#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env file not found at $ENV_FILE"
    echo "Copy .env.example to .env and fill in the values."
    exit 1
fi

source "$ENV_FILE"

REMOTE="$REMOTE_USER@$REMOTE_HOST"

echo "==> Building image: $IMAGE_NAME:latest"
docker build -t "$IMAGE_NAME:latest" "$SCRIPT_DIR"

echo "==> Transferring image to $REMOTE_HOST (this may take a minute)"
docker save "$IMAGE_NAME:latest" | gzip | ssh "$REMOTE" docker load

echo "==> Pushing compose file"
scp "$SCRIPT_DIR/docker-compose.prod.yml" "$REMOTE:$REMOTE_APP_DIR/docker-compose.prod.yml"

echo "==> Pushing systemd service file"
scp "$SCRIPT_DIR/display-manager.service" "$REMOTE:/tmp/display-manager.service"
ssh "$REMOTE" "sudo cp /tmp/display-manager.service /etc/systemd/system/display-manager.service && sudo systemctl daemon-reload"

echo "==> Restarting services"
ssh "$REMOTE" "sudo systemctl restart display-manager && sudo systemctl restart kiosk"

echo "==> Done. Verifying..."
sleep 3
ssh "$REMOTE" "systemctl is-active display-manager && systemctl is-active kiosk"
