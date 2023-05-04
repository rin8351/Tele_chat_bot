# -*- coding: utf-8 -*-

from aiogram import Bot, types
import re
import datetime
import json
import os
import queue
import asyncio
import pytz
import logging
import time


from telethon import TelegramClient
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

prompt = ''
bot_is_running = False
chat_id_in_bot = None
bot_busy = False

path = 'data'
file = 'data.json'
file_path = os.path.join(path, file)
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

api_id = data['api_id']
api_hash = data['api_hash']
phone_number =  data['phone_number']
username= data['username']
password = data['password']

YOUR_PRIVATE_CHANNEL = data['YOUR_PRIVATE_CHANNEL']
chat_origin_mess = data['chat_origin_mess']
YOUR_ADMIN_CHAT_ID = data['YOUR_ADMIN_CHAT_ID']
CHANNEL_to_send = data['CHANNEL_to_send']
TELEGRAM_BOT_TOKEN = data['TELEGRAM_BOT_TOKEN']

storage = MemoryStorage()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot,storage=storage)

class SetPromptStates(StatesGroup):
    waiting_for_prompt = State()

class SetScheduleStates(StatesGroup):
    waiting_for_schedule = State()

class SetStyleStates(StatesGroup):
    waiting_for_style = State()

def is_file_empty(file_path):
    return os.stat(file_path).st_size == 0

async def create_telegram_client():
    client = TelegramClient(username, api_id, api_hash)
    logger.info('Connecting...')

    await client.connect()
    if not await client.is_user_authorized():
        await bot.send_message(chat_id_in_bot, 'Вы не авторизованы. Вам выслано смс с кодом авторизации')
        result = await client.send_code_request(phone_number)
        phone_code_hash = result.phone_code_hash
        logger.info('Sent to phone number - %s', phone_number)
        sms_path = 'data'
        sms_filename = 'sms_code.txt'
        sms_filepath = os.path.join(sms_path, sms_filename)
        while not os.path.exists(sms_filepath) or is_file_empty(sms_filepath):
            time.sleep(1)
        with open(sms_filepath, 'r') as f:
            code = f.read().strip()
        logger.info('Signing in...')
        try:
            await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            try:
                await client.sign_in(password=password)
            except Exception as e:
                logger.error('Error: {}'.format(e))
                return
        except Exception as e:
            logger.error('Error: {}'.format(e))
            return
        logger.info('phone number - %s', phone_number)
        logger.info('code - %s', code)
    await bot.send_message(chat_id_in_bot, 'Авторизация прошла успешно')
    if not await client.is_user_authorized():
        return False, None

    return True, client

async def long_running_function(result_queue):
    with open ('summary_funal.txt', 'r', encoding='utf-8') as f:
        final_result = f.read()
    summary_with_links = replace_id_exter_links(final_result)
    result_queue.put((summary_with_links))

def replace_id_exter_links(text_with_names):

    def replace_id_with_link(match):
        message_id = match.group(1)
        first_word = match.group(2)
        rest_of_line = match.group(3)
        return f'[{first_word}](https://t.me/c/chat_origin_mess/{message_id}){rest_of_line}'

    def replace_external_links(match):
        external_link = match.group(1)
        rest_of_line = match.group(2)
        return f'{rest_of_line} [Здесь ссылка]({external_link})'

    # Replace external links with the word "Link" with a hyperlink, put at the end of the line
    summary_with_external_links = re.sub(r'(https?://\S+)(.*)', replace_external_links, text_with_names)

    # Replace message IDs with links inside the channel
    summary_with_links = re.sub(r'(\d+): (\w+)(.*)', replace_id_with_link, summary_with_external_links)

    return summary_with_links

async def send_prompt():
    global last_filter_time, bot_busy
    while bot_is_running:
        if chat_id_in_bot is not None and not bot_busy:
            bot_busy = True
            await bot.send_message(chat_id_in_bot, "Запрос отправлен, бот занят")
            result_queue = queue.Queue()
            task = asyncio.create_task(long_running_function(result_queue))
            await task
            summary_with_links = result_queue.get()
            await bot.send_message(CHANNEL_to_send, summary_with_links,parse_mode='Markdown')
            await bot.send_message(chat_id_in_bot, "Запрос выполнен, бот свободен")
            bot_busy = False


async def start_bot(message):
    global bot_is_running, chat_id_in_bot, bot_busy
    chat_id_in_bot = message.chat.id
    if not prompt:
        await bot.send_message(message.chat.id, "Промпт не задан. Нажмите на команду /set_prompt.")
        return
    if not bot_is_running:
        bot_is_running = True
        await bot.send_message(chat_id_in_bot, "Бот запущен")
        await send_prompt() 

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    global chat_id_in_bot,bot_busy
    if not bot_busy:
        chat_id_in_bot = message.chat.id
        await bot.send_message(chat_id=message.chat.id, text="Привет! Я бот, который будет присылать тебе сообщения в заданное время. Для начала работы введи команду /start_bot")
    else:
        await bot.send_message(chat_id=message.chat.id, text= "Бот занят выполнением запроса. Пожалуйста, подождите.")

@dp.message_handler(commands=['start_bot'])
async def handle_start_bot(message: types.Message):
    await start_bot(message)
    if bot_is_running:
        if not bot_busy:
            await message.answer("Бот запущен")
        else:
            await message.answer("Бот запущен, но занят")


@dp.message_handler(Command("set_prompt"), state=None)
async def handle_set_prompt(message: types.Message, state: FSMContext):
    if not bot_busy:
        await bot.send_message(message.chat.id, "Введите новый текст для запроса:")
        await SetPromptStates.waiting_for_prompt.set()
    else:
        await bot.send_message(message.chat.id, "Бот занят выполнением запроса. Пожалуйста, подождите.")

@dp.message_handler(lambda message: not message.text.startswith("/"), state=SetPromptStates.waiting_for_prompt)
async def process_set_prompt(message: types.Message, state: FSMContext):
    global prompt
    prompt = message.text
    await bot.send_message(message.chat.id, "Промпт изменен. Убедитесь, что бот запущен командой /start_bot.")
    await state.finish()

async def set_prompt(message):
    global prompt, bot_busy,bot_is_running, chat_id_in_bot
    prompt = message.text
    await bot.send_message(message.chat.id, "Промт изменен. Убедитесь чтот бот запущен командой /start_bot.")


@dp.message_handler(commands=['see_prompt'])
async def handle_see_prompt(message: types.Message):
    await bot.send_message(message.chat.id, f"Текущий текст для запроса:\n {prompt}")


@dp.message_handler(commands=['check_bot'])
async def handle_check_bot(message: types.Message):
    await check_bot_status(message)

async def check_bot_status(message):
    global bot_is_running,bot_busy
    if bot_is_running:
        if bot_busy:
            await bot.send_message(message.chat.id, "Бот запущен, но занят выполнением запроса")
        else:
            await bot.send_message(message.chat.id, "Бот запущен")
    else:
        await bot.send_message(message.chat.id, "Бот остановлен")

async def on_startup(dp):
    await bot.send_message(chat_id=YOUR_ADMIN_CHAT_ID, text="Сервер запущен")

async def on_shutdown(dp):
    await bot.send_message(chat_id=YOUR_ADMIN_CHAT_ID, text="Сервер остановлен")
    await bot.close()

if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)