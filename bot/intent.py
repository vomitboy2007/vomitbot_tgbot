"""Эвристики: когда ответ требует свежих фактов из интернета."""

from __future__ import annotations

import re

# Короткий треп и канон — отвечаем из персонажа, без поиска.
SKIP_SEARCH_RE = re.compile(
    r"(?:^|\s)(?:"
    r"привет|здарова|хай|ку|как дела|че как|нямк|угу|ок|лол|спс|спасиб"
    r"|ты кто|кто ты|ты бот|бот да|я и кто"
    r"|дай рецепт|скинь рецепт|что готовишь"
    r"|/lore|/pic|/reset|/start"
    r")(?:$|\s|[.!?])",
    re.I,
)

# Вопросы о лоре канала — персонаж «знает» сам.
LORE_TOPIC_RE = re.compile(
    r"вагинофаш|вомитбой|vomitboy|v0mitboy|diet\s*13|vomitcorp"
    r"|мышк|рыгош|burpboy|vomit\s*gf|тошнотик|мутант",
    re.I,
)

QUESTION_RE = re.compile(
    r"(?:"
    r"\?"
    r"|\b(?:что|как|когда|где|кто|почему|зачем|сколько|какой|какая|какие|каково"
    r"|чем|откуда|куда|каким|какую|какого|какое|каких|какому)\b"
    r"|\b(?:расскажи|объясни|опиши|найди|узнай|погугли|загугли|поищи|проверь)\b"
    r"|\b(?:что такое|кто такой|кто такая|что за|как называется|есть ли)\b"
    r"|\b(?:новости|news|погода|курс|цена|стоимость|население|дата|версия|релиз"
    r"|сколько стоит|сколько лет|сколько человек)\b"
    r")",
    re.I,
)

FACTUAL_LENGTH = 28


def extract_plain_question(user_payload: str) -> str:
    """Достаёт чистый текст из `[имя]: текст`."""
    text = user_payload.strip()
    if text.startswith("[") and "]:" in text[:80]:
        text = text.split("]:", 1)[1].strip()
    if text.startswith("(") and "):" in text[:160]:
        # убираем «(в ответ на: ...)»
        idx = text.find("):")
        if idx != -1:
            text = text[idx + 2 :].strip()
    return text


def needs_web_search(user_payload: str) -> bool:
    """True — лучше искать в интернете и отвечать без опоры на контекст чата."""
    text = extract_plain_question(user_payload)
    if len(text) < 4:
        return False

    lowered = text.lower().strip()

    if SKIP_SEARCH_RE.search(lowered):
        return False

    if LORE_TOPIC_RE.search(lowered):
        return False

    if QUESTION_RE.search(text):
        return True

    # Длинное сообщение без «?» — часто запрос фактов/мнения на тему.
    if len(text) >= FACTUAL_LENGTH and not lowered.startswith(("я ", "мне ", "у меня")):
        return True

    return False
