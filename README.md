# Telegram Group Summarization Bot 🤖

An intelligent Telegram bot that monitors group conversations and generates AI-powered summaries using OpenAI's GPT. The project was written in 2023, so it uses GPT-3.5.

## 📋 Overview

This bot was created to help group administrators track important information in high-traffic Telegram groups. It automatically collects messages, filters them by time intervals, and creates concise summaries with links to original messages. The summaries are then published to a specified channel on a customizable schedule.

## ✨ Features

- **Automated Message Collection**: Monitors Telegram groups and collects messages within specified time intervals
- **AI-Powered Summarization**: Uses OpenAI's GPT to create intelligent summaries of conversations
- **Customizable Schedule**: Set multiple times throughout the day for automatic summary generation
- **Flexible Configuration**: Customize AI prompts and writing style to fit your needs
- **Smart Linking**: Automatically adds links to original messages in summaries
- **State Management**: Tracks bot status and prevents concurrent operations
- **User Authentication**: Secure Telegram client authorization with 2FA support

## 🛠️ Technologies

- **[Aiogram](https://docs.aiogram.dev/)** - Modern Telegram Bot framework
- **[Telethon](https://docs.telethon.dev/)** - Telegram client for message collection
- **[OpenAI API](https://platform.openai.com/)** - GPT-3.5 for text summarization
- **Python asyncio** - Asynchronous programming for efficient operation
- **Docker** - Containerization support

## 📦 Installation

### Prerequisites

- Python 3.8 or higher
- Telegram API credentials (api_id, api_hash)
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- OpenAI API Key

### Local Setup

1. Clone the repository:
```bash
git clone https://github.com/rin8351/Tele_chat_bot.git
cd Tele_chat_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create configuration file:
```bash
cp data/data.json.example data/data.json
```

4. Edit `data/data.json` with your credentials:
```json
{
    "api_id": "YOUR_TELEGRAM_API_ID",
    "api_hash": "YOUR_TELEGRAM_API_HASH",
    "phone_number": "+1234567890",
    "username": "your_username",
    "password": "your_2fa_password_if_enabled",
    "YOUR_PRIVATE_CHANNEL": "Name of the channel/group to monitor",
    "chat_origin_mess": "CHAT_ID_FOR_LINKS",
    "YOUR_ADMIN_CHAT_ID": "YOUR_TELEGRAM_USER_ID",
    "CHANNEL_to_send": "CHANNEL_ID_TO_SEND_SUMMARIES",
    "TELEGRAM_BOT_TOKEN": "YOUR_BOT_TOKEN_FROM_BOTFATHER",
    "OPENAI_API_KEY": "YOUR_OPENAI_API_KEY",
    "default_prompt": "System prompt for AI (optional)",
    "default_style": "Example text showing desired writing style (optional)",
    "summarization_prompt": "Custom prompt template for summarization (optional)"
}
```

**Configuration Fields:**
- `default_prompt` - System prompt for OpenAI (constraints), can be changed via `/set_prompt`
- `default_style` - Example text showing the desired writing style, can be changed via `/set_style`
- `summarization_prompt` - Template for summarization instructions. Should include `{style}` and `{text}` placeholders

All prompt-related fields are optional. If not provided, default values will be used.

5. Run the bot:
```bash
python telebot_funk.py
```

### Docker Setup

```bash
# Build the image
docker build -t telegram-summarizer .

# Run the container
docker run -d -v $(pwd)/data:/app/data telegram-summarizer
```

Or use the provided scripts:
```bash
# Linux/Mac
sh build.sh
sh run.sh

# Windows
build.bat
run.bat
```

## 🎮 Bot Commands

### Basic Commands

- `/start` - Initialize the bot and see welcome message
- `/start_bot` - Start the automatic summarization process
- `/stop_bot` - Stop the bot from generating summaries
- `/check_bot` - Check current bot status (running/stopped/busy)

### Configuration Commands

- `/set_prompt` - Set custom prompt for AI summarization
- `/see_prompt` - View current prompt
- `/set_style` - Set writing style example for summaries
- `/see_style` - View current style example
- `/update_schedule` - Update summary generation times (format: `09:00, 12:00, 17:00, 21:00`)
- `/see_schedule` - View current schedule

## 📖 How to Get Telegram API Credentials

1. **API ID and Hash**: 
   - Visit https://my.telegram.org/apps
   - Log in with your phone number
   - Create a new application
   - Copy `api_id` and `api_hash`

2. **Bot Token**:
   - Message [@BotFather](https://t.me/botfather)
   - Create new bot with `/newbot`
   - Copy the token provided

3. **Chat IDs**:
   - For groups: Use [@username_to_id_bot](https://t.me/username_to_id_bot)
   - For private channels: Get the ID from channel link (remove `-100` prefix for configuration)

4. **OpenAI API Key**:
   - Visit https://platform.openai.com/api-keys
   - Create new secret key

## 🔄 Workflow

1. Bot connects to Telegram as a client using Telethon
2. At scheduled times, it collects messages from the specified group
3. Messages are filtered by time intervals
4. Text is sent to OpenAI for summarization
5. Summary is formatted with links to original messages
6. Final summary is published to the target channel

## 🔒 Security Notes

- Never commit `data/data.json` to version control
- Keep your session files private
- Regularly rotate your API keys
- Use environment variables for sensitive data in production

## 📝 Example Use Cases

- **Crypto/Trading Groups**: Monitor market discussions and news
- **Tech Communities**: Stay updated with technical discussions
- **News Aggregation**: Collect and summarize news from various sources
- **Team Communication**: Get daily digests of team conversations

## 🤝 Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest new features
- Submit pull requests

## 📄 License

This project is open source and available for personal and commercial use.

## 👤 Author

Created by [@rin8351](https://github.com/rin8351)

## 🙏 Acknowledgments

- Thanks to the Telegram Bot API and Telethon teams
- OpenAI for providing the GPT API
- All contributors and users of this project

---

**Note**: This bot requires proper authorization and admin rights in the monitored group. Always respect user privacy and follow Telegram's Terms of Service.
