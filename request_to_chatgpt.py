# -*- coding: utf-8 -*-
import asyncio
import re
import openai
import openai_async
import datetime
import json
import os
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

async def send_request_to_chatgpt(result_queue,constraints,filtered_data,style):

    path = 'data'
    file = 'data.json'
    file_path = os.path.join(path, file)
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    OPENAI_API_KEY = data['OPENAI_API_KEY']
    if OPENAI_API_KEY == "":
        raise Exception("Необходимо установить API ключ OpenAI")
    
    # Load summarization prompt from config with default
    summarization_prompt_template = data.get('summarization_prompt', 
        "Сделать суммаризацию текста. Не делать выводов. Сохранять id сообщения в начале строки. " +
        "Если информация дается больше чем в одном id сообщении, то оставлять только первый id. " +
        "Ссылки на внешние ресурсы нужно ставить в конце строки. Убрать все фразы, где говорится " +
        "что Нет полезной информации, что в чате ругаются или болтают неконструктивно и так далее. " +
        "Но если в суммаризации совсем нет никакой полезной информации, тогда можно написать один раз об этом. " +
        "Пример стиля и желаемого результата: {style} Строки из примера нельзя повторять и включать в суммаризацию. " +
        "Вот текст для суммаризации:\n{text}")

    # Формирование текста чата

    def is_valid_api_key(my_api_key):
        try:
            # Try listing models with the provided API key
            openai.Model.list(api_key=my_api_key)
            return True
        except Exception as e:
            # If an error occurs, the API key is likely invalid
            return False

    async def send_request_to_chatgpt_funk(api_key, request_text, constraints):
        if not is_valid_api_key(api_key):
            return "Не удалось подключиться к серверу OpenAI. Проверьте API ключ."

        prompt_text = [
            {"role": "system", "content": constraints},
            {"role": "user", "content": request_text}
        ]
        max_retries=4
        retry_interval=30
        retries = 0
        while retries < max_retries:
            try:
                response = await openai_async.chat_complete(
                    api_key,
                    timeout=120,
                    payload={
                        "model": "gpt-3.5-turbo",
                        "messages": prompt_text,
                    },
                )
                return response.json()["choices"][0]["message"]['content']

            except openai.OpenAIError as e:
                logger.error(f"Не удалось подключиться к серверу OpenAI. {e}")
            except httpx.ReadTimeout:
                logger.error(f"Не удалось подключиться к серверу OpenAI. Таймаут.")
            except Exception as e:
                logger.error(f"Не удалось подключиться к серверу OpenAI. {e}")
            retries += 1
            if retries < max_retries:
                await asyncio.sleep(retry_interval)

        return None
    
    async def summarize_text(text, max_tokens, api_key, constraints):
        summary_parts = []

        while len(text) > 0:
            if len(text) <= max_tokens:
                summary_parts.append(text)
                break
            else:
                # Find the last space before max_tokens and split the string on that space
                split_position = text.rfind(' ', 0, max_tokens)
                summary_part = text[:split_position]
                text = text[split_position + 1:]
                summary_parts.append(summary_part)

        summaries = []

        for summary_part in summary_parts:
            request_text = summarization_prompt_template.format(style=style, text=summary_part)
            summary = await send_request_to_chatgpt_funk(api_key, request_text, constraints)
            summaries.append(summary)

        return summaries

    def split_text_into_chunks(text, max_tokens):
        sentences = re.split('(?<=[.!?]) +', text)
        chunks = []
        current_chunk = []

        for sentence in sentences:
            if len(" ".join(current_chunk + [sentence])) <= max_tokens:
                current_chunk.append(sentence)
            else:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    # Разделение списка сообщений на части
    max_characters_per_chunk = 6500
    chunks = []
    current_chunk = []
    current_chunk_characters = 0

    for message in filtered_data:
        text = message['text']
        text_length = len(text)

        if current_chunk_characters + text_length <= max_characters_per_chunk:
            current_chunk.append(message)
            current_chunk_characters += text_length
        else:
            chunks.append(current_chunk)
            current_chunk = [message]
            current_chunk_characters = text_length

    # Добавляем последний фрагмент, если он не пуст
    if current_chunk:
        chunks.append(current_chunk)

    max_chunks = 10  # adjust this value as needed
    chunks = chunks[:max_chunks]

    # Отправка запросов в ChatGPT
    summaries = []
    count_all_chunks = 0
    count_of_none = 0
    result_of_none = ''
    for chunk in chunks:
        chat_text = ""
        id_to_message = {message["id"]: message for message in chunk}

        for message in chunk:
            id_of_message = message['id']
            reply_to_message_id = message.get('reply_to_message_id', None)
            if reply_to_message_id is not None:
                replied_message = id_to_message.get(reply_to_message_id, None)
                if replied_message is not None:
                    chat_text += f" ответ на : {replied_message['text']}\n"

            chat_text += f"{id_of_message}: {message['text']}\n"
        await asyncio.sleep(2) 
        max_tokens_per_chunk = 2000  # adjust this value as needed to fit within the model's token limit
        text_chunks = split_text_into_chunks(chat_text, max_tokens_per_chunk)
        for text_chunk in text_chunks:
            # написать какой по счету идет чанк
            request_text = f"\n{text_chunk}."
            summary = await  send_request_to_chatgpt_funk(OPENAI_API_KEY,request_text,constraints)
            summaries.append(summary)
            if summary is None:
                count_of_none += 1
            count_all_chunks += 1
    # Фильтрация списка summaries
    filtered_summaries = [summary for summary in summaries if summary is not None]

    # Объединение отфильтрованных выводов в одну строку
    if filtered_summaries:
        combined_summary = " ".join(filtered_summaries)
    else:
        combined_summary = "НЕ удалось отправить запрос на сервер"

    if combined_summary == "НЕ удалось отправить запрос на сервер":
        result_queue.put(combined_summary)
        return
    
    if count_of_none > 0:
        result_of_none=f"Количество неудачных запросов: {count_of_none} из {count_all_chunks}"
    
    text = re.sub(r'\d+:\s*Нет полезной информации по криптовалютам', '', combined_summary)
    text = re.sub(r'\d+:\s*Нет полезной информации\.', '', text)

    combined_summary = re.sub(r'^\s*\r?\n', '', text, flags=re.MULTILINE)

    # Отправка запросов в ChatGPT для суммаризации каждой части
    final_result = await summarize_text(combined_summary, 2000, OPENAI_API_KEY, constraints)
    final_result = " ".join(final_result)
    # Loop until the final_result has less than 30 lines
    while True:
        # Count the number of lines in final_result
        num_lines = len(final_result.splitlines())
        
        # If the number of lines is less than 30, break the loop
        if num_lines < 30:
            break

        # If the number of lines is 30 or more, process the final_result again
        final_result = await summarize_text(final_result, 2000, OPENAI_API_KEY, constraints)
        final_result = " ".join(final_result)

    start_time = datetime.datetime.fromisoformat(filtered_data[0]['date'])
    end_time = datetime.datetime.fromisoformat(filtered_data[-1]['date'])
    time_range_str = f"{start_time.strftime('%Y-%m-%d, %H:%M')} - {end_time.strftime('%H:%M')}"

    # Объединение результатов с добавлением временного диапазона
    final_result = time_range_str + "\n" + final_result

    result_queue.put((final_result, result_of_none))