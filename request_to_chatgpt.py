# -*- coding: utf-8 -*-
import asyncio
import re
import openai
import openai_async
import datetime
import json
import os
import time
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MAX_CHARS_PER_BATCH = 6000
MAX_CHARS_PER_REQUEST = 2000
MAX_BATCHES = 10


def _hard_cut(text, max_chars):
    """Cut on spaces when nothing softer works; avoid mid-word cuts when possible."""
    parts = []
    rest = text
    while rest:
        if len(rest) <= max_chars:
            parts.append(rest)
            break
        cut = rest.rfind(' ', 0, max_chars)
        if cut <= 0:
            cut = max_chars
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    return parts


def _split_long_unit(text, max_chars):
    """Split one oversized block: paragraphs -> lines -> sentences -> hard cut."""
    if len(text) <= max_chars:
        return [text]

    pieces = []
    for paragraph in re.split(r'\n\s*\n', text):
        paragraph = paragraph.strip()
        if paragraph:
            pieces.append(paragraph)

    if len(pieces) <= 1:
        pieces = [line for line in text.splitlines() if line.strip()] or [text]

    result = []
    for piece in pieces:
        if len(piece) <= max_chars:
            result.append(piece)
            continue
        sentences = re.split(r'(?<=[.!?…])\s+', piece)
        for sentence in sentences:
            sentence = (sentence or '').strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                result.append(sentence)
            else:
                result.extend(_hard_cut(sentence, max_chars))

    return result


def pack_text_units(units, max_chars):
    """
    Pack whole text units into chunks under max_chars.
    Never starts a new unit mid-way; oversized units are split carefully first.
    """
    chunks = []
    current = []
    current_len = 0

    for unit in units:
        unit = (unit or '').strip()
        if not unit:
            continue

        parts = [unit] if len(unit) <= max_chars else _split_long_unit(unit, max_chars)
        for part in parts:
            extra = len(part) + (1 if current else 0)  # newline join
            if current and current_len + extra > max_chars:
                chunks.append('\n'.join(current))
                current = [part]
                current_len = len(part)
            else:
                current.append(part)
                current_len += extra

    if current:
        chunks.append('\n'.join(current))
    return chunks


def format_message_unit(message, id_to_message):
    """One Telegram message as a single text unit (kept whole when packing)."""
    lines = []
    reply_to = message.get('reply_to_msg_id')
    if reply_to is not None:
        replied = id_to_message.get(reply_to)
        if replied is not None:
            lines.append(f" ответ на : {replied.get('text') or ''}")
    lines.append(f"{message['id']}: {message.get('text') or ''}")
    return '\n'.join(lines)


def pack_messages_into_batches(messages, max_chars=MAX_CHARS_PER_BATCH, max_batches=MAX_BATCHES):
    """Group messages into batches without splitting a message across batches."""
    batches = []
    current = []
    current_len = 0
    id_to_message = {m['id']: m for m in messages}

    for message in messages:
        unit = format_message_unit(message, id_to_message)
        unit_len = len(unit)
        extra = unit_len + (1 if current else 0)

        if current and current_len + extra > max_chars:
            batches.append(current)
            if len(batches) >= max_batches:
                return batches
            current = [message]
            current_len = unit_len
        else:
            current.append(message)
            current_len += extra

    if current and len(batches) < max_batches:
        batches.append(current)
    return batches


async def send_request_to_chatgpt(constraints, filtered_data, style):
    """
    Summarize filtered Telegram messages.

    Returns (summary_text, status_note, metrics).
    metrics is a dict on success / partial runs, or None on hard early failures.
    """
    started = time.monotonic()

    def _empty_metrics(message_count=0):
        return {
            "messages": message_count,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0,
            "duration_seconds": round(time.monotonic() - started, 1),
            "tokens_estimated": False,
        }

    if not filtered_data:
        # EN: No messages in the selected time window.
        note = "Нет сообщений за выбранный интервал."
        return note, note, _empty_metrics(0)

    path = 'data'
    file = 'data.json'
    file_path = os.path.join(path, file)
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    OPENAI_API_KEY = data['OPENAI_API_KEY']
    if OPENAI_API_KEY == "":
        raise Exception("Необходимо установить API ключ OpenAI")  # EN: OpenAI API key must be set

    # Fallback summarization prompt (Russian — original client language).
    # EN: Summarize; no conclusions; keep message id at line start; if several ids share
    # one fact keep the first; external links at line end; drop "no useful info" filler;
    # style sample is {style}; text is {text}. Prefer overriding via data.json.
    summarization_prompt_template = data.get(
        'summarization_prompt',
        "Сделать суммаризацию текста. Не делать выводов. Сохранять id сообщения в начале строки. "
        "Если информация дается больше чем в одном id сообщении, то оставлять только первый id. "
        "Ссылки на внешние ресурсы нужно ставить в конце строки. Убрать все фразы, где говорится "
        "что Нет полезной информации, что в чате ругаются или болтают неконструктивно и так далее. "
        "Но если в суммаризации совсем нет никакой полезной информации, тогда можно написать один раз об этом. "
        "Пример стиля и желаемого результата: {style} Строки из примера нельзя повторять и включать в суммаризацию. "
        "Вот текст для суммаризации:\n{text}",
    )

    usage_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    api_calls = 0
    tokens_estimated = False

    def _estimate_tokens(text):
        # Rough fallback when the API response has no usage field (~4 chars/token).
        return max(1, len(text or "") // 4)

    def _add_usage(usage, prompt_text='', completion_text=''):
        nonlocal api_calls, tokens_estimated
        api_calls += 1
        if usage and (
            usage.get("prompt_tokens") is not None
            or usage.get("completion_tokens") is not None
            or usage.get("total_tokens") is not None
        ):
            usage_totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            usage_totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            total = usage.get("total_tokens")
            if total is None:
                total = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
            usage_totals["total_tokens"] += int(total)
        else:
            tokens_estimated = True
            pt = _estimate_tokens(prompt_text)
            ct = _estimate_tokens(completion_text)
            usage_totals["prompt_tokens"] += pt
            usage_totals["completion_tokens"] += ct
            usage_totals["total_tokens"] += pt + ct

    def _build_metrics():
        return {
            "messages": len(filtered_data),
            "prompt_tokens": usage_totals["prompt_tokens"],
            "completion_tokens": usage_totals["completion_tokens"],
            "total_tokens": usage_totals["total_tokens"],
            "api_calls": api_calls,
            "duration_seconds": round(time.monotonic() - started, 1),
            "tokens_estimated": tokens_estimated,
        }

    def is_valid_api_key(my_api_key):
        try:
            openai.Model.list(api_key=my_api_key)
            return True
        except Exception:
            return False

    async def send_request_to_chatgpt_funk(api_key, request_text, constraints):
        if not is_valid_api_key(api_key):
            return "Не удалось подключиться к серверу OpenAI. Проверьте API ключ."  # EN: Could not reach OpenAI. Check API key.

        prompt_text = [
            {"role": "system", "content": constraints},
            {"role": "user", "content": request_text},
        ]
        prompt_for_estimate = constraints + "\n" + request_text
        max_retries = 4
        retry_interval = 30
        retries = 0
        while retries < max_retries:
            attempt = retries + 1
            try:
                response = await openai_async.chat_complete(
                    api_key,
                    timeout=120,
                    payload={
                        "model": "gpt-3.5-turbo",
                        "messages": prompt_text,
                    },
                )
                body = response.json()
                content = body["choices"][0]["message"]['content']
                _add_usage(body.get("usage") or {}, prompt_for_estimate, content)
                if attempt > 1:
                    logger.info("OpenAI request succeeded on attempt %s/%s", attempt, max_retries)
                return content

            except openai.OpenAIError as e:
                logger.error(
                    "OpenAI error on attempt %s/%s: %s", attempt, max_retries, e
                )
            except httpx.ReadTimeout:
                logger.error(
                    "OpenAI timeout on attempt %s/%s", attempt, max_retries
                )
            except Exception as e:
                logger.error(
                    "OpenAI unexpected error on attempt %s/%s: %s", attempt, max_retries, e
                )
            retries += 1
            if retries < max_retries:
                logger.warning(
                    "Retrying OpenAI request in %ss (%s/%s left)",
                    retry_interval,
                    max_retries - retries,
                    max_retries,
                )
                await asyncio.sleep(retry_interval)

        logger.error("OpenAI request failed after %s attempts", max_retries)
        return None

    async def summarize_text(text, max_chars, api_key, constraints):
        # Re-summarize by whole lines/paragraphs when possible
        units = [u for u in re.split(r'\n+', text) if u.strip()]
        if not units:
            units = [text]
        text_chunks = pack_text_units(units, max_chars)

        summaries = []
        for summary_part in text_chunks:
            request_text = summarization_prompt_template.format(style=style, text=summary_part)
            summary = await send_request_to_chatgpt_funk(api_key, request_text, constraints)
            if summary is not None:
                summaries.append(summary)

        return summaries

    batches = pack_messages_into_batches(filtered_data)
    summaries = []
    count_all_chunks = 0
    count_of_none = 0
    result_of_none = ''

    for batch in batches:
        id_to_message = {message["id"]: message for message in batch}
        message_units = [format_message_unit(message, id_to_message) for message in batch]
        text_chunks = pack_text_units(message_units, MAX_CHARS_PER_REQUEST)

        await asyncio.sleep(2)
        for text_chunk in text_chunks:
            request_text = f"\n{text_chunk}"
            summary = await send_request_to_chatgpt_funk(OPENAI_API_KEY, request_text, constraints)
            summaries.append(summary)
            if summary is None:
                count_of_none += 1
            count_all_chunks += 1

    filtered_summaries = [summary for summary in summaries if summary is not None]

    if filtered_summaries:
        combined_summary = " ".join(filtered_summaries)
    else:
        # EN: Failed to send the request to the server
        return "НЕ удалось отправить запрос на сервер", "НЕ удалось отправить запрос на сервер", _build_metrics()

    if count_of_none > 0:
        # EN: Failed requests: {n} of {total}
        result_of_none = f"Количество неудачных запросов: {count_of_none} из {count_all_chunks}"

    text = re.sub(r'\d+:\s*Нет полезной информации по криптовалютам', '', combined_summary)
    text = re.sub(r'\d+:\s*Нет полезной информации\.', '', text)
    combined_summary = re.sub(r'^\s*\r?\n', '', text, flags=re.MULTILINE)

    final_parts = await summarize_text(combined_summary, 2000, OPENAI_API_KEY, constraints)
    if not final_parts:
        # EN: Failed to send the request to the server
        return (
            "НЕ удалось отправить запрос на сервер",
            result_of_none or "НЕ удалось отправить запрос на сервер",
            _build_metrics(),
        )
    final_result = " ".join(final_parts)

    while True:
        num_lines = len(final_result.splitlines())
        if num_lines < 30:
            break
        final_parts = await summarize_text(final_result, 2000, OPENAI_API_KEY, constraints)
        if not final_parts:
            break
        final_result = " ".join(final_parts)

    start_time = datetime.datetime.fromisoformat(filtered_data[0]['date'])
    end_time = datetime.datetime.fromisoformat(filtered_data[-1]['date'])
    time_range_str = f"{start_time.strftime('%Y-%m-%d, %H:%M')} - {end_time.strftime('%H:%M')}"
    final_result = time_range_str + "\n" + final_result

    return final_result, result_of_none, _build_metrics()
