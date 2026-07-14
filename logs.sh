#!/usr/bin/env sh
# Follow logs for the summarizer container
CONTAINER_ID=$(docker ps -aqf "name=telegram-summarizer")
if [ -z "$CONTAINER_ID" ]; then
  echo "No container named telegram-summarizer found."
  exit 1
fi
docker logs -f "$CONTAINER_ID"
