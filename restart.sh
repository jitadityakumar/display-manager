#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v curl >/dev/null 2>&1 || { echo "Error: curl is required but not installed."; exit 1; }

echo "==> Rebuilding and restarting display-manager (dev)"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --build

echo "==> Waiting for app to come up..."
for i in {1..30}; do
    if curl -sf http://localhost:8080/api/config > /dev/null 2>&1; then
        echo "==> Ready at http://localhost:8080/admin"
        exit 0
    fi
    sleep 1
done

echo "==> App did not respond after 30s — showing logs:"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" logs --tail=30
exit 1
