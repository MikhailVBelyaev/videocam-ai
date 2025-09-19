#!/bin/bash
set -e

TARGET_SERVER="user@192.168.100.194"
PROJECT_NAME="videocam-ai"
REMOTE_DIR="~/Projects/${PROJECT_NAME}"

FAST_RESTART=false

# Check for --fast flag
if [[ "$1" == "--fast" ]]; then
  FAST_RESTART=true
  shift
fi

echo "📤 Syncing source code to $TARGET_SERVER..."
rsync -av \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='output' \
  --exclude='*.env' \
  ./ "$TARGET_SERVER:$REMOTE_DIR/"

if [ "$#" -eq 0 ]; then
  if [ "$FAST_RESTART" = true ]; then
    echo "🚀 Fast restart of ALL containers on $TARGET_SERVER..."
    ssh "$TARGET_SERVER" "cd $REMOTE_DIR && docker compose up -d --no-build --force-recreate"
  else
    echo "🚀 Rebuilding and restarting ALL containers on $TARGET_SERVER..."
    ssh "$TARGET_SERVER" "cd $REMOTE_DIR && docker compose up -d --build"
  fi
  echo "✅ Deployment finished for $PROJECT_NAME (all services)"
else
  if [ "$FAST_RESTART" = true ]; then
    echo "🚀 Fast restart of containers for services: $* on $TARGET_SERVER..."
    ssh "$TARGET_SERVER" "cd $REMOTE_DIR && docker compose up -d --no-build --force-recreate $*"
  else
    echo "🚀 Rebuilding and restarting containers for services: $* on $TARGET_SERVER..."
    ssh "$TARGET_SERVER" "cd $REMOTE_DIR && docker compose up -d --build $*"
  fi
  echo "✅ Deployment finished for $PROJECT_NAME (services: $*)"
fi