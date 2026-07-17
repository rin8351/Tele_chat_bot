# Telegram Group Summarization Bot

Scheduled digests for high-traffic Telegram groups: collect messages with a user session (Telethon), summarize with GPT, post a linked digest to a separate chat via a Bot API bot.

> **Project status:** built in **2023** as a working prototype for a **Russian-speaking client** and a private, Russian-language crypto discussion chat. Dependencies are intentionally left on the original stack (Aiogram 2, OpenAI SDK 0.27, GPT-3.5). This is portfolio / archival code, not a maintained SaaS product. There is **no live demo** — access to the original group expired long ago.

## Why it exists

A Russian-speaking admin of a closed, very active chat needed **periodic digests** without reading the full firehose. The bot account (or a volunteer with membership) can read the source group; summaries are delivered to a **separate destination chat/channel** that the admin actually follows.

The source chat was crypto-oriented and full of niche jargon — even as a native Russian speaker, the terminology was dense. Prompts and style examples were written in **Russian** for that deployment so summaries kept ticker names, slang, and message IDs for deep links, instead of rewriting everything into generic “news speak.” Operator-facing bot replies in this repo are also in Russian.

`data/data.json.example` uses **English** prompt templates so international readers can follow the instructions; swap them to Russian (or any language) for a real deployment.
## How it works

1. Authorize a **Telegram user client** (Telethon) — needed for private groups a normal bot may not fully read.
2. At each scheduled time, pull recent messages and keep only the current time window.
3. Send text to **GPT-3.5** in message-aware chunks (large chats exceeded a single context window).
4. Turn retained message IDs into `t.me/c/...` links.
5. Publish the digest to `CHANNEL_to_send`, then a short **metrics** follow-up (message count, tokens, duration); status pings go to the operator chat.

Default schedule slots: `00:00`, `09:00`, `12:00`, `17:00`, `21:00`, `23:59` (editable at runtime via `/update_schedule`).

## Features

- Time-window collection from a named private group/channel
- Multi-pass GPT summarization for long threads
- Deep links back to original messages
- Runtime control: prompt, writing style, schedule
- **Admin ACL** — only allowlisted Telegram user ids can run control commands
- **Run metrics** posted to the digest channel after each summary (messages processed, token usage, duration)
- **OpenAI retries** — up to 4 attempts per request (30s apart), with logging; failed runs do not advance the schedule window; admins are notified on failures / partial API errors
- Docker volume mount for config and session files
- Telethon login with SMS code file drop + optional 2FA

## What an output looked like (illustrative)

No real export is available anymore. Below is a **synthetic** example in the same spirit as the original crypto digests (jargon kept on purpose):

```text
14:00–17:00

[12841](https://t.me/c/xxxxxxxxxx/12841) листинг XYZ на второй CEX слили в стакан за час, обсуждают wash trading
[12855](https://t.me/c/xxxxxxxxxx/12855) [12856](https://t.me/c/xxxxxxxxxx/12856) киты забрали аирдроп и дампят в спот; кто-то ждёт ретест 0.42
[12870](https://t.me/c/xxxxxxxxxx/12870) слух про снапшот DAO — без пруфа, в тред не подтвердили
```

## Known limitations (honest)

- Config lives in `data/data.json` (not env vars yet). See `.env.example` for the secret inventory.
- Schedule / prompt changes from bot commands are **in-memory** and reset on restart.
- OpenAI / Aiogram APIs have moved on since 2023; upgrading would be a separate modernization pass.

Text is packed by **whole Telegram messages** first; only oversized single messages fall back to paragraphs → lines → sentences → word boundaries.

## Tech stack

| Piece | Version era |
|-------|-------------|
| Python | 3.8+ |
| [Aiogram](https://docs.aiogram.dev/) | 2.25 |
| [Telethon](https://docs.telethon.dev/) | 1.28 |
| OpenAI API | `gpt-3.5-turbo` via `openai` 0.27 / `openai_async` |
| Docker | optional runtime |

## Setup

### Prerequisites

- Python 3.8+
- Telegram `api_id` / `api_hash` from [my.telegram.org/apps](https://my.telegram.org/apps)
- Bot token from [@BotFather](https://t.me/botfather)
- OpenAI API key
- Membership (or equivalent access) in the source group

### Local

```bash
git clone https://github.com/rin8351/Tele_chat_bot.git
cd Tele_chat_bot
pip install -r requirements.txt
cp data/data.json.example data/data.json
# edit data/data.json with real credentials
python telebot_funk.py
```

On first Telethon login, write the SMS code into `data/sms_code.txt` when prompted.

### Configuration (`data/data.json`)

| Key | Meaning |
|-----|---------|
| `api_id`, `api_hash`, `phone_number`, `username`, `password` | Telethon user auth (password = 2FA if enabled) |
| `YOUR_PRIVATE_CHANNEL` | **Display name** of the source group to scrape |
| `chat_origin_mess` | Numeric chat id fragment used in `https://t.me/c/{id}/{msg}` links |
| `YOUR_ADMIN_CHAT_ID` | Your Telegram **user id** (operator). Used for startup notices **and** as the primary ACL allowlist entry |
| `ALLOWED_ADMIN_IDS` | Optional list of extra Telegram user ids allowed to control the bot |
| `CHANNEL_to_send` | Where digests are posted (chat/channel id the bot can write to) |
| `TELEGRAM_BOT_TOKEN` | Aiogram bot |
| `OPENAI_API_KEY` | OpenAI |
| `default_prompt` | System constraints for the model |
| `default_style` | Short style sample the summarizer should imitate |
| `summarization_prompt` | Template with `{style}` and `{text}` placeholders |

Prompt fields can also be changed at runtime with bot commands. The example file is in English; the original client used Russian prompts for Russian chat digests.

**Do not commit** `data/data.json`, `*.session`, or `data/sms_code.txt` — they are gitignored.

### Docker

```bash
# Linux / macOS
sh build.sh    # image: telegram-summarizer
sh run.sh      # mounts ./data → /app/data

# Windows
build.bat
run.bat

# logs
sh logs.sh
```

Manual equivalent:

```bash
docker build -t telegram-summarizer .
docker run -d --name telegram-summarizer \
  -v "$(pwd)/data:/app/data" \
  telegram-summarizer
```

## Bot commands

| Command | Action |
|---------|--------|
| `/start` | Welcome |
| `/start_bot` | Start scheduler + Telethon auth if needed |
| `/stop_bot` | Stop summarization loop |
| `/check_bot` | running / stopped / busy |
| `/set_prompt` / `/see_prompt` | Edit / view system prompt |
| `/set_style` / `/see_style` | Edit / view style sample |
| `/update_schedule` / `/see_schedule` | Edit / view `HH:MM` slots (`09:00, 12:00, 17:00`) |
