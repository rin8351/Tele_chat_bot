# Run with data/ mounted for config + Telethon session files
docker run -d \
  --name telegram-summarizer \
  --restart always \
  -v "$(pwd)/data:/app/data" \
  telegram-summarizer
