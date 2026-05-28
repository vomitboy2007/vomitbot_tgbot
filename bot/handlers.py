"""Хендлеры Telegram-бота: личка, группы, команды."""

from __future__ import annotations

import html
import logging
import random
import re
from collections import deque
from typing import Deque

from telegram import Update
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import Settings
from .grok_client import GrokClient, GrokError
from .guards import is_manipulation_attempt, pick_deflection
from .intent import extract_plain_question, needs_web_search
from .lore import LORE_SITE_URL, compose_lore_reply
from .persona import (
    FACTUAL_FALLBACK_ADDENDUM,
    build_search_instructions,
    build_system_prompt,
    sample_dialogue_examples,
    strip_emoji,
)
from .pic import PicError, compose_pic_reply, format_pic_message
from .search import search_web

logger = logging.getLogger(__name__)


# История диалогов на чат. Размер буфера = settings.history_size (по умолчанию 100).
_history: dict[int, Deque[dict[str, str]]] = {}


def _get_history(chat_id: int, max_size: int) -> Deque[dict[str, str]]:
    dq = _history.get(chat_id)
    if dq is None:
        dq = deque(maxlen=max_size)
        _history[chat_id] = dq
    elif dq.maxlen != max_size:
        dq = deque(list(dq)[-max_size:], maxlen=max_size)
        _history[chat_id] = dq
    return dq


def _trim_for_context(
    messages: list[dict[str, str]],
    *,
    max_messages: int,
    max_chars: int,
) -> list[dict[str, str]]:
    """Обрезает историю до лимита сообщений и длины каждой реплики."""
    return [
        {"role": m["role"], "content": m["content"][:max_chars]}
        for m in messages[-max_messages:]
    ]


def _few_shot_count(history_len: int) -> int:
    """Меньше эталонных пар, когда история уже длинная — экономим контекст."""
    if history_len > 60:
        return 4
    if history_len > 30:
        return 6
    if history_len > 12:
        return 8
    return 10


def _conversation_for_search(
    context: list[dict[str, str]],
    plain_question: str,
    *,
    max_turns: int = 8,
) -> list[dict[str, str]]:
    """Короткий контекст + чистый вопрос для web_search (без префикса [имя])."""
    recent = context[-max_turns:] if context else []
    if recent and recent[-1].get("role") == "user":
        recent = recent[:-1]
    out = list(recent)
    out.append({"role": "user", "content": plain_question})
    return out


_DISMISSIVE_SEARCH_RE = re.compile(
    r"^(?:"
    r"хуй\s+(?:его\s+)?знает|"
    r"хз|"
    r"и\s+что|"
    r"не\s+знаю|"
    r"нямк|"
    r"че\.?|"
    r"угу\.?"
    r")(?:[.!?]|$)",
    re.I,
)


def _looks_dismissive(reply: str, plain_question: str) -> bool:
    """True — модель проигнорировала фактический вопрос."""
    text = reply.strip()
    if len(text) > 120:
        return False
    if _DISMISSIVE_SEARCH_RE.match(text):
        return True
    # «гобзавр. хуй его знает. и что.» — короткий ответ без объяснения.
    entity = plain_question.lower()
    for prefix in ("кто такой ", "кто такая ", "что такое ", "что за "):
        if entity.startswith(prefix):
            entity = entity[len(prefix) :].strip(" ?!.,")
            break
    if entity and len(entity) <= 40 and entity in text.lower() and len(text) < 80:
        return True
    return False


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


async def _try_search_reply(
    user_text: str,
    settings: Settings,
    grok: GrokClient,
    context: list[dict[str, str]],
) -> str | None:
    """Пробует ответить через интернет. None — не получилось, идём в обычный чат."""
    instructions = build_search_instructions()
    plain = extract_plain_question(user_text)
    search_context = _conversation_for_search(context, plain)

    try:
        reply = await grok.respond_with_web_search(
            instructions=instructions,
            conversation=search_context,
            temperature=settings.temperature,
            max_output_tokens=settings.web_search_max_tokens,
        )
        reply = strip_emoji(reply) or ""
        if reply and not _looks_dismissive(reply, plain):
            return reply
        if reply:
            logger.info("web_search дал уклончивый ответ %r — пробуем DDG fallback", reply[:80])
    except GrokError as exc:
        logger.warning("xAI web_search не сработал: %s. Пробуем fallback.", exc)

    query = plain or user_text
    snippets = await search_web(query, timeout=min(settings.search_timeout, 20))
    if not snippets:
        return None

    augmented = (
        f"{plain}\n\n"
        "[сводка из интернета — используй для ответа, перескажи как вомитбой]:\n"
        f"{snippets}"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": instructions}]
    if len(search_context) > 1:
        messages.extend(search_context[:-1])
    messages.append({"role": "user", "content": augmented})
    try:
        reply = await grok.chat(
            messages,
            temperature=settings.temperature,
            max_tokens=settings.web_search_max_tokens,
        )
        reply = strip_emoji(reply) or ""
        if reply and not _looks_dismissive(reply, plain):
            return reply
        logger.info("DDG fallback тоже уклончивый: %r", reply[:80])
        return reply or None
    except GrokError as exc:
        logger.warning("Fallback chat после search упал: %s", exc)
        return None


async def _generate_reply(
    chat_id: int,
    user_text: str,
    settings: Settings,
    grok: GrokClient,
) -> str:
    history = _get_history(chat_id, settings.history_size)
    history.append({"role": "user", "content": user_text})

    seed = random.randint(0, 10_000)
    use_search = settings.web_search_enabled and needs_web_search(user_text)
    context = _trim_for_context(
        list(history),
        max_messages=settings.history_size,
        max_chars=settings.history_max_chars,
    )

    if use_search:
        search_reply = await _try_search_reply(user_text, settings, grok, context)
        if search_reply:
            history.append({"role": "assistant", "content": search_reply})
            return search_reply

    system_prompt = build_system_prompt(seed=seed)
    if use_search:
        system_prompt += FACTUAL_FALLBACK_ADDENDUM
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(
        sample_dialogue_examples(seed=seed, n=_few_shot_count(len(context)))
    )
    messages.extend(context)

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
                "че.",
                "помойка молчит.",
                "мышки мышки мышки мышки.",
            ]
        )

    reply = strip_emoji(reply) or "и что."
    history.append({"role": "assistant", "content": reply})
    return reply


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("я и кто.\n\nпиши что хотел.")


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _history.pop(chat_id, None)
    await update.effective_message.reply_text("забыл всё нахуй.")


async def handle_lore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reply = strip_emoji(compose_lore_reply()) or f"лор сегодня недоступен. {LORE_SITE_URL}"
    await update.effective_message.reply_text(
        reply,
        disable_web_page_preview=False,
    )


async def handle_pic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_typing(update, context)

    try:
        art, source_label = compose_pic_reply()
        pre_body = html.escape(art)
        if len(pre_body) > 3400:
            pre_body = html.escape(art[:3400].rstrip()) + "..."

        reply_html = (
            "ну смотри.\n\n"
            f"<pre>{pre_body}</pre>\n\n"
            f"источник:\n{html.escape(source_label)}"
        )

        try:
            await update.effective_message.reply_text(
                reply_html,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return
        except BadRequest as exc:
            logger.warning("HTML /pic не прошёл, шлём plain: %s", exc)
            await update.effective_message.reply_text(
                format_pic_message(art, source_label),
                disable_web_page_preview=True,
            )
            return
    except PicError as exc:
        logger.warning("Ошибка /pic: %s", exc)
        reply = f"картинка не загрузилась. попробуй ещё раз.\n\n{LORE_SITE_URL}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Неожиданная ошибка /pic: %s", exc)
        reply = f"помойка не отдала картинку.\n\n{LORE_SITE_URL}"

    await update.effective_message.reply_text(
        reply,
        disable_web_page_preview=True,
    )


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

    chat_id = update.effective_chat.id

    if is_manipulation_attempt(text):
        logger.info(
            "Поймана попытка манипуляции в чате %s от %s: %r",
            chat_id,
            name,
            text[:160],
        )
        reply = pick_deflection()
        try:
            await message.reply_text(reply, reply_to_message_id=message.message_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reply_to не прошёл: %s", exc)
            await context.bot.send_message(chat_id=chat_id, text=reply)
        return

    reply_to_text = None
    if message.reply_to_message:
        reply_to_text = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or None
        )

    user_payload = _make_user_message(name, text, reply_to=reply_to_text)

    await _send_typing(update, context)

    reply = await _generate_reply(chat_id, user_payload, settings, grok)

    try:
        await message.reply_text(reply, reply_to_message_id=message.message_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось ответить reply_to: %s. Шлю обычным.", exc)
        await context.bot.send_message(chat_id=chat_id, text=reply)


def register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("reset", handle_reset))
    app.add_handler(CommandHandler("lore", handle_lore))
    app.add_handler(CommandHandler("pic", handle_pic))

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
            handle_message,
        )
    )
