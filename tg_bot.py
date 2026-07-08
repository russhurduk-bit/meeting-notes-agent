#!/usr/bin/env python3
"""Telegram bot for the Meeting Notes Agent.

Supports:
1. Google Meet — send link, bot joins via Chrome, records, sends notes
2. Telegram calls — send TG call link, bot joins via Telegram Desktop, records, sends notes
"""
import asyncio
import os
import re
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)

from config import RECORDINGS_DIR, PULSE_SINK_NAME
from audio_capture import AudioCapture
from meet_bot import connect_browser, google_login, join_meeting, wait_for_meeting_end, CDP_URL
from transcribe import transcribe_audio, save_transcript
from structurize import structurize_transcript
from doc_export import create_protocol_docx

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MEET_URL_PATTERN = re.compile(r'https?://meet\.google\.com/[a-z]+-[a-z]+-[a-z]+')
TG_CALL_PATTERN = re.compile(r'https?://t\.me/call/[A-Za-z0-9_-]+')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
log = logging.getLogger("meeting-notes-bot")

active_sessions = {}
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Записываю созвоны и делаю протокол.\n\n"
        "Кинь ссылку на Google Meet или TG-звонок.\n"
        "/stop — остановить запись\n"
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_sessions:
        active_sessions[chat_id]["stop"] = True
        await update.message.reply_text("⏹ Останавливаю запись...")
    else:
        await update.message.reply_text("Нет активной записи.")


async def handle_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route: Meet link → record_meeting, TG link → record_tg_call."""
    text = update.message.text or ""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id

    if chat_id in active_sessions:
        await update.message.reply_text(
            "⚠️ Уже идёт запись. /stop чтобы остановить.",
            message_thread_id=thread_id,
        )
        return

    # Google Meet
    meet_match = MEET_URL_PATTERN.search(text)
    if meet_match:
        meet_url = meet_match.group(0)
        active_sessions[chat_id] = {"stop": False, "type": "meet", "url": meet_url}
        asyncio.create_task(record_meeting(meet_url, chat_id, thread_id, ctx.application))
        return

    # Telegram call link (t.me/call/SLUG)
    tg_match = TG_CALL_PATTERN.search(text)
    if tg_match:
        call_link = tg_match.group(0)
        active_sessions[chat_id] = {"stop": False, "type": "tg", "url": call_link}
        asyncio.create_task(record_tg_call(call_link, chat_id, thread_id, ctx.application))
        return


# ============== GOOGLE MEET ==============

async def record_meeting(meet_url: str, chat_id: int, thread_id: int, app):
    """Google Meet pipeline: Chrome → join → record → transcribe → send."""
    meeting_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = os.path.join(RECORDINGS_DIR, f"{meeting_id}.wav")

    try:
        audio = AudioCapture(PULSE_SINK_NAME)
        audio.setup_sink()

        pw, browser = await connect_browser()
        bctx = browser.contexts[0]
        page = bctx.pages[0] if bctx.pages else await bctx.new_page()

        await google_login(page)
        audio.start_recording(audio_path)
        await join_meeting(page, meet_url)

        await app.bot.send_message(chat_id, "Подключился.", message_thread_id=thread_id)

        while True:
            if active_sessions.get(chat_id, {}).get("stop"):
                break
            try:
                left = page.locator('text="You left the meeting"')
                left_ru = page.locator('text="Вы покинули"')
                returned = page.locator('text="Return to home screen"')
                if (await left.count() > 0 or await left_ru.count() > 0 or
                        await returned.count() > 0):
                    break
                if "meet.google.com" not in page.url:
                    break
            except Exception:
                break
            await asyncio.sleep(10)

        audio.stop_recording()
        try:
            await page.goto("about:blank", timeout=5000)
        except Exception:
            pass
        await pw.stop()

    except Exception as e:
        log.error(f"Meet recording error: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {e}", message_thread_id=thread_id)
        active_sessions.pop(chat_id, None)
        return

    await _process_and_send(audio_path, meeting_id, chat_id, thread_id, app)


# ============== TELEGRAM CALLS ==============

async def record_tg_call(call_link: str, chat_id: int, thread_id: int, app):
    """TG call pipeline: tdesktop GUI → join → PulseAudio record → transcribe → send."""
    meeting_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    audio_path = os.path.join(RECORDINGS_DIR, f"tg_{meeting_id}.wav")

    try:
        from tg_call_desktop import join_conference_call, is_in_call, leave_call, extract_slug

        slug = extract_slug(call_link)
        if not slug:
            await app.bot.send_message(chat_id, "❌ Неверная ссылка.", message_thread_id=thread_id)
            active_sessions.pop(chat_id, None)
            return

        # Join via tdesktop (runs in thread to not block async)
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(None, join_conference_call, slug)

        if not ok:
            await app.bot.send_message(chat_id, "❌ Не удалось подключиться.", message_thread_id=thread_id)
            active_sessions.pop(chat_id, None)
            return

        # Start audio recording
        audio = AudioCapture(PULSE_SINK_NAME)
        audio.setup_sink()
        audio.start_recording(audio_path)

        await app.bot.send_message(chat_id, "Подключился.", message_thread_id=thread_id)

        # Wait for call end or /stop
        while True:
            if active_sessions.get(chat_id, {}).get("stop"):
                break
            in_call = await loop.run_in_executor(None, is_in_call)
            if not in_call:
                break
            await asyncio.sleep(10)

        audio.stop_recording()
        await loop.run_in_executor(None, leave_call)

    except Exception as e:
        log.error(f"TG call error: {e}")
        await app.bot.send_message(chat_id, f"❌ Ошибка: {e}", message_thread_id=thread_id)
        active_sessions.pop(chat_id, None)
        return

    await _process_and_send(audio_path, meeting_id, chat_id, thread_id, app)


# ============== SHARED PROCESSING ==============

async def _process_and_send(audio_path: str, meeting_id: str, chat_id: int, thread_id: int, app):
    """Transcribe → structurize → send .docx. Shared by Meet and TG call pipelines."""
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 10000:
        await app.bot.send_message(chat_id, "⚠️ Аудио слишком короткое.", message_thread_id=thread_id)
        active_sessions.pop(chat_id, None)
        return

    try:
        transcript = transcribe_audio(audio_path)
        save_transcript(transcript, meeting_id)
    except Exception as e:
        await app.bot.send_message(chat_id, f"❌ Ошибка транскрипции: {e}", message_thread_id=thread_id)
        active_sessions.pop(chat_id, None)
        return

    try:
        date_str = datetime.now().strftime("%d.%m.%Y")
        output_path = structurize_transcript(transcript, meeting_id, date=date_str)
    except Exception as e:
        await app.bot.send_message(chat_id, f"❌ Ошибка структуризации: {e}", message_thread_id=thread_id)
        active_sessions.pop(chat_id, None)
        return

    with open(output_path, "r") as f:
        protocol_md = f.read()

    date_str_file = datetime.now().strftime("%d.%m.%Y")
    docx_path = create_protocol_docx(protocol_md, meeting_id, f"Протокол созвона — {date_str_file}")

    await app.bot.send_document(
        chat_id,
        document=open(docx_path, "rb"),
        filename=f"Протокол_{date_str_file}.docx",
        message_thread_id=thread_id,
    )

    try:
        os.remove(audio_path)
    except Exception:
        pass
    active_sessions.pop(chat_id, None)


async def log_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg:
        log.info(f"MSG chat={msg.chat_id} thread={msg.message_thread_id} text='{(msg.text or '')[:100]}'")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, log_all), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    # Meet links
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(MEET_URL_PATTERN), handle_link))
    # TG links (t.me/...)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(TG_CALL_PATTERN), handle_link))
    log.info("Meeting Notes bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
