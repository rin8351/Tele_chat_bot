# -*- coding: utf-8 -*-

from aiogram import Bot, types
import re
import datetime
import json
import os
from request_to_chatgpt import send_request_to_chatgpt
import asyncio
import pytz
import logging

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest
from telethon.errors import SessionPasswordNeededError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

schedule_times = ['00:00', '09:00', '12:00', '17:00', '21:00', '23:59']
bot_is_running = False
chat_id_in_bot = None
bot_busy = False
last_filter_time = schedule_times[0]

# Operator/status strings below stay in Russian (original client locale).
# English glosses are in comments for portfolio readers.
ERROR_SUMMARIES = {
    "Группа не найдена.",  # Group not found.
    "Не найдено сообщений.",  # No messages found.
    "Нет сообщений за выбранный интервал.",  # No messages in the selected time window.
    "НЕ удалось отправить запрос на сервер",  # Failed to send the request to the server.
}


path = 'data'
file = 'data.json'
file_path = os.path.join(path, file)
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Load prompt and style from config with defaults
prompt = data.get('default_prompt', '')
style = data.get('default_style', 'Example style: Clear, concise summaries with key points highlighted.')

path2 = 'data'
file2 = 'result.json'
file_path2 = os.path.join(path2, file2)

api_id = data['api_id']
api_hash = data['api_hash']
phone_number = data['phone_number']
username = data['username']
password = data['password']

YOUR_PRIVATE_CHANNEL = data['YOUR_PRIVATE_CHANNEL']
chat_origin_mess = data['chat_origin_mess']
YOUR_ADMIN_CHAT_ID = data['YOUR_ADMIN_CHAT_ID']
CHANNEL_to_send = data['CHANNEL_to_send']
TELEGRAM_BOT_TOKEN = data['TELEGRAM_BOT_TOKEN']


def _as_telegram_id(value):
    """Normalize config values like 123 or "123" to int Telegram ids."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ACL = Access Control List: only these Telegram user ids may run bot commands.
ADMIN_IDS = set()
_main_admin = _as_telegram_id(YOUR_ADMIN_CHAT_ID)
if _main_admin is not None:
    ADMIN_IDS.add(_main_admin)
for _extra in data.get('ALLOWED_ADMIN_IDS') or []:
    _uid = _as_telegram_id(_extra)
    if _uid is not None:
        ADMIN_IDS.add(_uid)

if not ADMIN_IDS:
    logger.warning(
        "ADMIN_IDS is empty — set YOUR_ADMIN_CHAT_ID (and optional ALLOWED_ADMIN_IDS) "
        "or nobody will be able to control the bot."
    )

storage = MemoryStorage()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)


class SetPromptStates(StatesGroup):
    waiting_for_prompt = State()


class SetScheduleStates(StatesGroup):
    waiting_for_schedule = State()


class SetStyleStates(StatesGroup):
    waiting_for_style = State()


def user_is_admin(message: types.Message) -> bool:
    user = message.from_user
    return bool(user and user.id in ADMIN_IDS)


async def require_admin(message: types.Message) -> bool:
    """
    Gate for command handlers.
    Returns True if the sender is allowlisted; otherwise replies and returns False.
    """
    if user_is_admin(message):
        return True
    uid = message.from_user.id if message.from_user else None
    logger.warning("Rejected command from non-admin user_id=%s", uid)
    await message.answer(
        "Нет доступа. Управлять ботом могут только администраторы из списка ACL."
        # EN: Access denied. Only ACL-listed admins can control the bot.
    )
    return False


async def export_message_history(client, group_name, file_path2):
    utc = pytz.UTC
    start_date = datetime.datetime.now(utc) - datetime.timedelta(days=1)
    end_date = datetime.datetime.now(utc)
    messages = []

    entity = None
    async for dialog in client.iter_dialogs():
        if dialog.name == group_name:
            entity = dialog.entity
            break

    if entity is None:
        logger.info("Group '%s' not found.", group_name)
        return "Группа не найдена."  # EN: Group not found.

    # Keep GetFull* call for channel metadata side-effects / future use
    if hasattr(entity, 'megagroup') and entity.megagroup:
        await client(GetFullChannelRequest(entity))
    else:
        await client(GetFullChatRequest(entity.id))

    async for message in client.iter_messages(entity):
        if start_date < message.date < end_date:
            messages.append({
                'id': message.id,
                'text': message.text,
                'date': message.date.isoformat(),
                'reply_to_msg_id': message.reply_to_msg_id,
            })

    if not messages:
        return 'Не найдено сообщений.'  # EN: No messages found.

    with open(file_path2, 'w', encoding='utf-8') as file:
        json.dump(messages, file, ensure_ascii=False, indent=4)

    return messages


def is_file_empty(file_path):
    return os.stat(file_path).st_size == 0


async def conn_to_tele_and_exp(client):
    """Export messages once and return the list or an error string."""
    return await export_message_history(client, YOUR_PRIVATE_CHANNEL, file_path2)


async def create_telegram_client():
    client = TelegramClient(username, api_id, api_hash)
    logger.info('Connecting...')

    await client.connect()
    if not await client.is_user_authorized():
        await bot.send_message(
            chat_id_in_bot,
            'Вы не авторизованы. Вам выслано смс с кодом авторизации',
            # EN: You are not authorized. An SMS login code has been sent.
        )
        result = await client.send_code_request(phone_number)
        phone_code_hash = result.phone_code_hash
        logger.info('Sent to phone number - %s', phone_number)
        sms_filepath = os.path.join('data', 'sms_code.txt')
        while not os.path.exists(sms_filepath) or is_file_empty(sms_filepath):
            await asyncio.sleep(1)
        with open(sms_filepath, 'r') as f:
            code = f.read().strip()
        logger.info('Signing in...')
        try:
            await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            try:
                await client.sign_in(password=password)
            except Exception as e:
                logger.error('Error: %s', e)
                return False, None
        except Exception as e:
            logger.error('Error: %s', e)
            return False, None
        logger.info('phone number - %s', phone_number)
        # Do not log SMS codes

    if not await client.is_user_authorized():
        return False, None

    await bot.send_message(chat_id_in_bot, 'Авторизация прошла успешно')  # EN: Authorization successful.
    return True, client


async def long_running_function(last_filter_time, now, client):
    """Returns (summary_or_error, status_note, metrics_or_none)."""
    data_to_gpt = await conn_to_tele_and_exp(client)
    if isinstance(data_to_gpt, str):
        return data_to_gpt, data_to_gpt, None

    filtered_messages = filter_messages_by_time(data_to_gpt, last_filter_time, now)
    if not filtered_messages:
        note = "Нет сообщений за выбранный интервал."  # EN: No messages in the selected time window.
        return note, note, None

    final_result, result_of_none, metrics = await send_request_to_chatgpt(
        prompt, filtered_messages, style
    )
    if final_result in ERROR_SUMMARIES or final_result.startswith("НЕ удалось"):
        return final_result, result_of_none or final_result, metrics

    summary_with_links = replace_id_exter_links(final_result)
    return summary_with_links, result_of_none, metrics


def format_metrics_message(metrics):
    """Build a short Russian metrics note for the digest channel (English gloss in comments)."""
    if not metrics:
        return None
    # EN: Processing metrics / Messages / Tokens (prompt, completion) / Duration / API calls
    estimated = " (оценка)" if metrics.get("tokens_estimated") else ""  # EN: (estimate)
    return (
        "Метрики обработки\n"
        f"Сообщений: {metrics.get('messages', 0)}\n"
        f"Токены: {metrics.get('total_tokens', 0)}{estimated} "
        f"(prompt {metrics.get('prompt_tokens', 0)}, completion {metrics.get('completion_tokens', 0)})\n"
        f"Время: {metrics.get('duration_seconds', 0)} с\n"
        f"Запросов к API: {metrics.get('api_calls', 0)}"
    )


def replace_id_exter_links(text_with_names):
    skip_first_line = [True]  # first \d+: match is often the HH:MM in the time header

    def replace_id_with_link(match):
        if skip_first_line[0]:
            skip_first_line[0] = False
            return match.group(0)

        message_id = match.group(1)
        rest_of_line = match.group(2)
        words = rest_of_line.split()
        replaced = False
        for i, word in enumerate(words):
            if len(word) > 3:
                words[i] = f'[{word}](https://t.me/c/{chat_origin_mess}/{message_id})'
                replaced = True
                break
        if not replaced:
            if words:
                words[0] = f'[{words[0]}](https://t.me/c/{chat_origin_mess}/{message_id})'
            else:
                words = [f'[{message_id}](https://t.me/c/{chat_origin_mess}/{message_id})']
        return ' '.join(words)

    def replace_external_links(match):
        external_link = match.group(1)
        rest_of_line = match.group(2)
        return f'{rest_of_line} [Здесь ссылка]({external_link})'

    summary_with_external_links = re.sub(r'(https?://\S+)(.*)', replace_external_links, text_with_names)
    summary_with_links = re.sub(r'(\d+):(.*)', replace_id_with_link, summary_with_external_links)

    return summary_with_links


def filter_messages_by_time(messages, start_time, end_time):
    start_time_obj = datetime.datetime.strptime(start_time, '%H:%M').time()
    end_time_obj = datetime.datetime.strptime(end_time, '%H:%M').time()

    def in_window(msg_time):
        # Normal window, e.g. 09:00 <= t < 12:00
        if start_time_obj <= end_time_obj:
            return start_time_obj <= msg_time < end_time_obj
        # Wraps past midnight, e.g. 21:00 -> 09:00
        return msg_time >= start_time_obj or msg_time < end_time_obj

    filtered_messages = []
    for message in messages:
        msg_time = datetime.datetime.fromisoformat(message['date']).time()
        if in_window(msg_time):
            filtered_messages.append({
                'id': message['id'],
                'date': message['date'],
                'reply_to_msg_id': message.get('reply_to_msg_id'),
                'text': message.get('text') or '',
            })
    return filtered_messages


async def send_prompt(telegram_client):
    global last_filter_time, bot_busy
    while bot_is_running:
        now = datetime.datetime.now().strftime('%H:%M')
        if now in schedule_times:
            if chat_id_in_bot is not None and not bot_busy:
                bot_busy = True
                try:
                    # EN: Request sent, bot is busy
                    await bot.send_message(chat_id_in_bot, "Запрос отправлен, бот занят")
                    summary_with_links, result_of_none, metrics = await long_running_function(
                        last_filter_time, now, telegram_client
                    )
                    if result_of_none:
                        await bot.send_message(chat_id_in_bot, result_of_none)

                    is_error = (
                        summary_with_links in ERROR_SUMMARIES
                        # Prefixes of Russian OpenAI/failure messages ("Failed to…")
                        or summary_with_links.startswith("НЕ удалось")
                        or summary_with_links.startswith("Не удалось")
                    )
                    if is_error:
                        # Avoid posting error strings into the digest channel
                        if summary_with_links != result_of_none:
                            await bot.send_message(chat_id_in_bot, summary_with_links)
                    else:
                        await bot.send_message(
                            CHANNEL_to_send, summary_with_links, parse_mode='Markdown'
                        )
                        metrics_text = format_metrics_message(metrics)
                        if metrics_text:
                            # Second message in the digest channel — keeps the summary itself clean
                            await bot.send_message(CHANNEL_to_send, metrics_text)

                    # EN: Request finished, bot is free
                    await bot.send_message(chat_id_in_bot, "Запрос выполнен, бот свободен")
                    last_filter_time = now
                    await asyncio.sleep(60)
                except Exception as e:
                    logger.exception("Summarization cycle failed: %s", e)
                    # EN: Summarization error: …
                    await bot.send_message(chat_id_in_bot, f"Ошибка при суммаризации: {e}")
                finally:
                    bot_busy = False
        await asyncio.sleep(10)


async def start_bot(message):
    global bot_is_running, chat_id_in_bot, bot_busy
    chat_id_in_bot = message.chat.id
    is_authorized, telegram_client = await create_telegram_client()
    if is_authorized:
        if not prompt:
            # EN: Prompt is not set. Use /set_prompt.
            await bot.send_message(message.chat.id, "Промпт не задан. Нажмите на команду /set_prompt.")
            return
        if not bot_is_running:
            bot_is_running = True
            await bot.send_message(chat_id_in_bot, "Бот запущен")  # EN: Bot started
            await send_prompt(telegram_client)
    else:
        # EN: Auth failed, bot not started. Try again.
        await bot.send_message(chat_id_in_bot, "Ошибка авторизации, бот не запущен. Попробуйте еще раз.")


# --- Operator-facing command replies (Russian UI; English glosses in comments) ---

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    global chat_id_in_bot, bot_busy
    if not await require_admin(message):
        return
    if not bot_busy:
        chat_id_in_bot = message.chat.id
        await bot.send_message(
            chat_id=message.chat.id,
            # EN: Hi! I send scheduled digests. Start with /start_bot
            text="Привет! Я бот, который будет присылать тебе сообщения в заданное время. Для начала работы введи команду /start_bot",
        )
    else:
        await bot.send_message(
            chat_id=message.chat.id,
            # EN: Bot is busy. Please wait.
            text="Бот занят выполнением запроса. Пожалуйста, подождите.",
        )


@dp.message_handler(commands=['start_bot'])
async def handle_start_bot(message: types.Message):
    if not await require_admin(message):
        return
    await start_bot(message)
    if bot_is_running:
        if not bot_busy:
            await message.answer("Бот запущен")  # EN: Bot started
        else:
            await message.answer("Бот запущен, но занят")  # EN: Bot started but busy


@dp.message_handler(commands=['stop_bot'])
async def handle_stop_bot(message: types.Message):
    if not await require_admin(message):
        return
    global bot_is_running
    bot_is_running = False
    await bot.send_message(message.chat.id, "Бот не запущен")  # EN: Bot is stopped


@dp.message_handler(Command("update_schedule"), state=None)
async def handle_update_schedule(message: types.Message, state: FSMContext):
    if not await require_admin(message):
        return
    if not bot_busy:
        await bot.send_message(
            message.chat.id,
            # EN: Enter a new schedule (comma+space, 24h). Example: 09:00, 12:00, …
            "Введите новое расписание (через запятую и пробел, в 24 часовом формате)\nПример: 09:00, 12:00, 17:00, 21:00",
        )
        await SetScheduleStates.waiting_for_schedule.set()
    else:
        # EN: Bot is busy. Please wait.
        await bot.send_message(message.chat.id, "Бот занят выполнением запроса. Пожалуйста, подождите.")


@dp.message_handler(lambda message: not message.text.startswith("/"), state=SetScheduleStates.waiting_for_schedule)
async def process_update_schedule(message: types.Message, state: FSMContext):
    if not await require_admin(message):
        await state.finish()
        return
    global schedule_times
    times = message.text.split(', ')
    pattern = re.compile(r'^\d{2}:\d{2}$')

    if all(pattern.match(t) for t in times):
        if '' in times:
            await bot.send_message(
                message.chat.id,
                # EN: Schedule must not be empty. Try /update_schedule again…
                "Расписание не должно быть пустым. Нажмите еще раз /update_schedule и введите расписание в формате:\n 09:00, 12:00, 17:00, 21:00",
            )
        else:
            schedule_times = times
            # EN: Schedule set to: …
            await bot.send_message(message.chat.id, f"Установлено расписание: {', '.join(times)}")
    else:
        await bot.send_message(
            message.chat.id,
            # EN: Invalid schedule format. Try /update_schedule again…
            "Неверный формат расписания. Нажмите еще раз /update_schedule и введите расписание в формате:\n 09:00, 12:00, 17:00, 21:00",
        )
    await state.finish()


@dp.message_handler(Command("set_prompt"), state=None)
async def handle_set_prompt(message: types.Message, state: FSMContext):
    if not await require_admin(message):
        return
    if not bot_busy:
        # EN: Enter the new prompt text:
        await bot.send_message(message.chat.id, "Введите новый текст для запроса:")
        await SetPromptStates.waiting_for_prompt.set()
    else:
        await bot.send_message(message.chat.id, "Бот занят выполнением запроса. Пожалуйста, подождите.")


@dp.message_handler(lambda message: not message.text.startswith("/"), state=SetPromptStates.waiting_for_prompt)
async def process_set_prompt(message: types.Message, state: FSMContext):
    if not await require_admin(message):
        await state.finish()
        return
    global prompt
    prompt = message.text
    # EN: Prompt updated. Make sure the bot is running via /start_bot.
    await bot.send_message(message.chat.id, "Промпт изменен. Убедитесь, что бот запущен командой /start_bot.")
    await state.finish()


@dp.message_handler(Command("set_style"), state=None)
async def handle_set_style(message: types.Message, state: FSMContext):
    if not await require_admin(message):
        return
    if not bot_busy:
        # EN: Enter the new style sample:
        await bot.send_message(message.chat.id, "Введите новый стиль для запроса:")
        await SetStyleStates.waiting_for_style.set()
    else:
        await bot.send_message(message.chat.id, "Бот занят выполнением запроса. Пожалуйста, подождите.")


@dp.message_handler(commands=['see_style'])
async def handle_see_style(message: types.Message):
    if not await require_admin(message):
        return
    # EN: Current style sample:
    await bot.send_message(message.chat.id, f"Текущий стиль для запроса:\n {style}")


@dp.message_handler(lambda message: not message.text.startswith("/"), state=SetStyleStates.waiting_for_style)
async def process_set_style(message: types.Message, state: FSMContext):
    if not await require_admin(message):
        await state.finish()
        return
    global style
    style = message.text
    await bot.send_message(message.chat.id, "Стиль изменен.")  # EN: Style updated.
    await state.finish()


@dp.message_handler(commands=['see_prompt'])
async def handle_see_prompt(message: types.Message):
    if not await require_admin(message):
        return
    # EN: Current prompt text:
    await bot.send_message(message.chat.id, f"Текущий текст для запроса:\n {prompt}")


@dp.message_handler(commands=['see_schedule'])
async def handle_see_schedule(message: types.Message):
    if not await require_admin(message):
        return
    # EN: Current schedule:
    await bot.send_message(message.chat.id, f"Текущее расписание:\n {', '.join(schedule_times)}")


@dp.message_handler(commands=['check_bot'])
async def handle_check_bot(message: types.Message):
    if not await require_admin(message):
        return
    await check_bot_status(message)


async def check_bot_status(message):
    global bot_is_running, bot_busy
    if bot_is_running:
        if bot_busy:
            # EN: Bot is running but busy
            await bot.send_message(message.chat.id, "Бот запущен, но занят выполнением запроса")
        else:
            await bot.send_message(message.chat.id, "Бот запущен")  # EN: Bot is running
    else:
        await bot.send_message(message.chat.id, "Бот остановлен")  # EN: Bot is stopped


async def on_startup(dp):
    await bot.send_message(chat_id=YOUR_ADMIN_CHAT_ID, text="Сервер запущен")  # EN: Server started


async def on_shutdown(dp):
    await bot.send_message(chat_id=YOUR_ADMIN_CHAT_ID, text="Сервер остановлен")  # EN: Server stopped
    await bot.close()


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)
