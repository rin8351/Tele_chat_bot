# -*- coding: utf-8 -*-

from aiogram import Bot, types
import re
import datetime
import json
import os
from  request_to_chatgpt import send_request_to_chatgpt
import queue
import asyncio
import pytz
import logging
import time


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

prompt = ''
schedule_times = ['00:00','09:00', '12:00', '17:00', '21:00' ,'23:59']
bot_is_running = False
chat_id_in_bot = None
bot_busy = False
last_filter_time = schedule_times[0]
style = "AiDoge-миллионеры клеймят свои токены и несут их в стакан который день подряд. Новый мемкоин разжигает и без того огромную жадность на рынке. В сравнении с тем, что дал Arbitrum - это копейки, но стоит ли отказываться от бесплатного бонуса? 😏 Поползли слухи, что биржа Binance отменила ограничение в $10.000 для пользователей из РФ. Официального заявления вроде бы не было, но представитель биржи сказал, что все ограничения соблюдаются. HotBit решили поторговать невыпущенным токеном L0. Команде L0 пришлось отдуваться - говорят, что никто не знает, когда будет токен. Новая статья Артура Хэйеса «Ликвидность на выход». Aptos запустили делегированный стейкинг. Можно отдать  свои токены в оборот «владельцам NYM-инсайдов». Они похолдят их за вас. 😄На ОКХ появилась странная страница о том, как захантить дроп от L0."

path = 'data'
file = 'data.json'
file_path = os.path.join(path, file)
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

path2 = 'data'
file2 = 'result.json'
file_path2 = os.path.join(path2, file2)

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


async def export_message_history(client,group,file_path2):
    # Define the date range for which you want to export messages
    utc = pytz.UTC
    start_date = datetime.datetime.now(utc) - datetime.timedelta(days=1)
    end_date = datetime.datetime.now(utc)
    messages = []

    async for dialog in client.iter_dialogs():
        if dialog.name == group:
            group = dialog.entity
            break

    if group is None:
        logger.info(f"Group '{group}' not found.")
        return "Группа не найдена."
    if hasattr(group, 'megagroup') and group.megagroup:
        group_full = await client(GetFullChannelRequest(group))
    else:
        group_full = await client(GetFullChatRequest(group.id))
    async for message in client.iter_messages(group):
        if message.date > start_date and message.date < end_date:
            messages.append({
                'id': message.id,
                'text': message.text,
                'date': message.date.isoformat(),
                'reply_to_msg_id': message.reply_to_msg_id,
            })

    if not messages:
        return 'Не найдено сообщений.'
    with open(file_path2, 'w', encoding='utf-8') as file:
        json.dump(messages, file, ensure_ascii=False, indent=4)

    return messages

def is_file_empty(file_path):
    return os.stat(file_path).st_size == 0

async def conn_to_tele_and_exp(client):
    data_to_gpt = None
    while data_to_gpt is None:
        data_to_gpt = await export_message_history(client, YOUR_PRIVATE_CHANNEL, file_path2)
        time.sleep(60)
        
    with open(file_path2, 'r', encoding='utf-8') as f:
        data_to_gpt = json.load(f)
    return data_to_gpt

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

async def long_running_function(result_queue, last_filter_time, now,client):
    data_to_gpt = await conn_to_tele_and_exp(client)
    if data_to_gpt == "Группа не найдена." or data_to_gpt == "Не найдено сообщений.": 
        final_result= data_to_gpt
        result_queue.put(data_to_gpt)
        await bot.send_message(chat_id_in_bot, data_to_gpt)
        return
    else:
        filtered_messages=filter_messages_by_time(data_to_gpt, last_filter_time, now)  # function for filtering messages by time
        chatgpt_result_queue = queue.Queue()
        chatgpt_task,result_of_none = asyncio.create_task(send_request_to_chatgpt(chatgpt_result_queue, prompt, filtered_messages,style))
        await chatgpt_task
        final_result = chatgpt_result_queue.get()
        summary_with_links = replace_id_exter_links(final_result)
        result_queue.put((summary_with_links,result_of_none))

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

def filter_messages_by_time(messages, start_time, end_time):
    start_time_obj = datetime.datetime.strptime(start_time, '%H:%M').time()
    end_time_obj = datetime.datetime.strptime(end_time, '%H:%M').time()

    filtered_messages = []

    for message in messages:
        msg_time = datetime.datetime.fromisoformat(message['date']).time()
        if start_time_obj <= msg_time < end_time_obj:
            text = message.get('text', '')

            filtered_message = {
                'id': message['id'],
                'date': message['date'],
                'reply_to_msg_id': message.get('reply_to_msg_id', None),
                'text': text,
            }
            filtered_messages.append(filtered_message)
    return filtered_messages

async def send_prompt(telegram_client):
    global last_filter_time, bot_busy
    while bot_is_running:
        now = datetime.datetime.now().strftime('%H:%M')
        if now in schedule_times: 
            if chat_id_in_bot is not None and not bot_busy:
                bot_busy = True
                await bot.send_message(chat_id_in_bot, "Запрос отправлен, бот занят")
                result_queue = queue.Queue()
                task = asyncio.create_task(long_running_function(result_queue, last_filter_time, now, telegram_client))
                await task
                summary_with_links,result_of_none = result_queue.get()
                if result_of_none !='':
                    await bot.send_message(chat_id_in_bot, result_of_none)
                await bot.send_message(CHANNEL_to_send, summary_with_links,parse_mode='Markdown')
                await bot.send_message(chat_id_in_bot, "Запрос выполнен, бот свободен")
                bot_busy = False
                last_filter_time = now 
                await asyncio.sleep(60)
            await asyncio.sleep(10)

async def start_bot(message):
    global bot_is_running, chat_id_in_bot, bot_busy
    chat_id_in_bot = message.chat.id
    is_authorized, telegram_client = await create_telegram_client()
    if is_authorized:
        if not prompt:
            await bot.send_message(message.chat.id, "Промпт не задан. Нажмите на команду /set_prompt.")
            return
        if not bot_is_running:
            bot_is_running = True
            await bot.send_message(chat_id_in_bot, "Бот запущен")
            await send_prompt(telegram_client) 
    else:
        await bot.send_message(chat_id_in_bot, "Ошибка авторизации, бот не запущен. Попробуйте еще раз.")

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


@dp.message_handler(commands=['stop_bot'])
async def handle_stop_bot(message: types.Message):
    global bot_is_running
    bot_is_running = False
    await bot.send_message(message.chat.id, "Бот не запущен")

@dp.message_handler(Command("update_schedule"), state=None)
async def handle_update_schedule(message: types.Message, state: FSMContext):
    if not bot_busy:
        await bot.send_message(message.chat.id, "Введите новое расписание (через запятую и пробел, в 24 часовом формате)\nПример: 09:00, 12:00, 17:00, 21:00")
        await SetScheduleStates.waiting_for_schedule.set()
    else:
        await bot.send_message(message.chat.id, "Бот занят выполнением запроса. Пожалуйста, подождите.")

@dp.message_handler(lambda message: not message.text.startswith("/"), state=SetScheduleStates.waiting_for_schedule)
async def process_update_schedule(message: types.Message, state: FSMContext):
    global schedule_times
    times = message.text.split(', ')
    pattern = re.compile(r'^\d{2}:\d{2}$')

    if all(pattern.match(time) for time in times):
        if '' in times:
            await bot.send_message(message.chat.id, "Расписание не должно быть пустым. Нажмите еще раз /update_schedule и введите расписание в формате:\n 09:00, 12:00, 17:00, 21:00")
        else:
            schedule_times = times
            await bot.send_message(message.chat.id, f"Установлено расписание: {', '.join(times)}")
    else:
        await bot.send_message(message.chat.id, "Неверный формат расписания. Нажмите еще раз /update_schedule и введите расписание в формате:\n 09:00, 12:00, 17:00, 21:00")
    await state.finish()


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

async def update_schedule(message):
    global schedule_times,bot_busy
    times = message.text.split(', ')
    pattern = re.compile(r'^\d{2}:\d{2}$')

    if all(pattern.match(time) for time in times):
        # не должно быть пустых строк
        if '' in times:
            await bot.send_message(message.chat.id, "Расписание не должно быть пустым. Нажмите еще раз /update_schedule и введите расписание в формате:\n 09:00, 12:00, 17:00, 21:00")
        else:
            schedule_times = times
            await bot.send_message(message.chat.id, f"Установлено расписание: {', '.join(times)}\nУбедитесь, что бот запущен командой /start_bot.")
    else:
        await bot.send_message(message.chat.id, "Неверный формат расписания. Нажмите еще раз /update_schedule и введите расписание в формате:\n 09:00, 12:00, 17:00, 21:00")

@dp.message_handler(Command("set_style"), state=None)
async def handle_set_style(message: types.Message, state: FSMContext):
    if not bot_busy:
        await bot.send_message(message.chat.id, "Введите новый стиль для запроса:")
        await SetStyleStates.waiting_for_style.set()
    else:
        await bot.send_message(message.chat.id, "Бот занят выполнением запроса. Пожалуйста, подождите.")

@dp.message_handler(commands=['see_style'])
async def handle_see_style(message: types.Message):
    await bot.send_message(message.chat.id, f"Текущий стиль для запроса:\n {style}")


@dp.message_handler(lambda message: not message.text.startswith("/"), state=SetStyleStates.waiting_for_style)
async def process_set_style(message: types.Message, state: FSMContext):
    global style
    style = message.text
    await bot.send_message(message.chat.id, "Стиль изменен.")
    await state.finish()


@dp.message_handler(commands=['see_prompt'])
async def handle_see_prompt(message: types.Message):
    await bot.send_message(message.chat.id, f"Текущий текст для запроса:\n {prompt}")

@dp.message_handler(commands=['see_schedule'])
async def handle_see_schedule(message: types.Message):
    await bot.send_message(message.chat.id, f"Текущее расписание:\n {', '.join(schedule_times)}")

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