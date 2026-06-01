#!/usr/bin/env bash
# Deployment script called by GitHub Actions (and usable manually).
# Run from the repo root on the server.
set -euo pipefail

echo "[deploy] Pulling latest changes..."
git pull --ff-only

echo "[deploy] Building and restarting containers..."
docker compose up -d --build

echo "[deploy] Cleaning up unused Docker images..."
docker image prune -f

echo "[deploy] Done."
