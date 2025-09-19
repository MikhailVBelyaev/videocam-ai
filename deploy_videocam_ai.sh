#!/bin/bash
set -e

TARGET_SERVER="user@192.168.100.194"
PROJECT_NAME="videocam-ai"
REMOTE_DIR="~/Projects/${PROJECT_NAME}"

echo "📤 Syncing source code to $TARGET_SERVER..."
rsync -av \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='output' \
  --exclude='*.env' \
  ./ "$TARGET_SERVER:$REMOTE_DIR/"

if [ "$#" -eq 0 ]; then
  echo "🚀 Rebuilding and restarting ALL containers on $TARGET_SERVER..."
  ssh "$TARGET_SERVER" "cd $REMOTE_DIR && docker compose up -d --build"
  echo "✅ Deployment finished for $PROJECT_NAME (all services)"
else
  echo "🚀 Rebuilding and restarting containers for services: $* on $TARGET_SERVER..."
  ssh "$TARGET_SERVER" "cd $REMOTE_DIR && docker compose up -d --build $*"
  echo "✅ Deployment finished for $PROJECT_NAME (services: $*)"
fi