@echo off
rem Run with data\ mounted for config + Telethon session files
docker run -d ^
  --name telegram-summarizer ^
  --restart always ^
  -v %cd%/data:/app/data ^
  telegram-summarizer
