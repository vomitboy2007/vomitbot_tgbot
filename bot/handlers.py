"""Хендлеры Telegram-бота: личка, группы, команды."""

from __future__ import annotations

import logging
import random
from collections import defaultdict, deque
from typing import Deque

from telegram import Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .grok_client import GrokClient, GrokError
from .persona import build_system_prompt

logger = logging.getLogger(__name__)


# История диалогов на чат (последние N сообщений в формате xAI chat-completions).
# Ключ — (chat_id, user_id?) — здесь только chat_id, в личке = id юзера.
_history: dict[int, Deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=24))


def _make_user_message(name: str, text: str, reply_to: str | None = None) -> str:
    """Форматирует входящее сообщение для отправки в xAI."""
    header = f"[{name}]"
    if reply_to:
        header += f" (в ответ на: «{reply_to[:140]}»)"
    return f"{header}: {text}"


async def _should_respond(update: Update, settings: Settings, bot_username: str) -> bool:
    if update.effective_message is None:
        return False

    message = update.effective_message
    text = (message.text or message.caption or "").strip()
    if not text:
        return False

    chat = update.effective_chat
    if chat is None:
        return False

    if chat.type == ChatType.PRIVATE:
        return True

    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.username == bot_username:
            return True

    lowered = text.lower()
    if bot_username and f"@{bot_username.lower()}" in lowered:
        return True

    for alias in settings.bot_name_aliases:
        if alias and alias in lowered:
            return True

    if random.random() < settings.group_reply_chance:
        return True

    return False


async def _send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Не удалось показать typing: %s", exc)


async def _generate_reply(
    chat_id: int,
    user_text: str,
    settings: Settings,
    grok: GrokClient,
) -> str:
    history = _history[chat_id]
    history.append({"role": "user", "content": user_text})

    system_prompt = build_system_prompt(seed=random.randint(0, 10_000))

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(list(history)[-settings.history_size :])

    try:
        reply = await grok.chat(
            messages,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
    except GrokError as exc:
        logger.warning("Grok вернул ошибку: %s", exc)
        history.pop()
        return random.choice(
            [
                "я и кто.",
                "нямк.",
                "🤤",
                "че.",
                "помойка молчит.🌟",
                "мышки мышки мышки мышки.",
            ]
        )

    history.append({"role": "assistant", "content": reply})
    return reply


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "я и кто.\n\nпиши что хотел🌟"
    )


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _history.pop(chat_id, None)
    await update.effective_message.reply_text("забыл всё нахуй.🌟")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    grok: GrokClient = context.application.bot_data["grok"]
    bot_username: str = context.application.bot_data["bot_username"]

    if not await _should_respond(update, settings, bot_username):
        return

    message = update.effective_message
    text = (message.text or message.caption or "").strip()

    user = update.effective_user
    name = (user.full_name or user.username or "анон") if user else "анон"

    reply_to_text = None
    if message.reply_to_message:
        reply_to_text = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or None
        )

    user_payload = _make_user_message(name, text, reply_to=reply_to_text)

    await _send_typing(update, context)

    chat_id = update.effective_chat.id
    reply = await _generate_reply(chat_id, user_payload, settings, grok)

    try:
        await message.reply_text(reply, reply_to_message_id=message.message_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось ответить reply_to: %s. Шлю обычным.", exc)
        await context.bot.send_message(chat_id=chat_id, text=reply)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("reset", handle_reset))

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message,
        )
    )
