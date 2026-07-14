FROM python:3.8-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY telebot_funk.py .
COPY request_to_chatgpt.py .

# Config and Telethon sessions are expected via volume mount: ./data -> /app/data
CMD ["python", "telebot_funk.py"]
