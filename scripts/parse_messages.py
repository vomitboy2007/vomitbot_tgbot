"""
Парсер экспортированного HTML-чата Telegram (messages.html).
Извлекает сообщения от vomitboy.com и сохраняет их как:
  - corpus.txt           — все тексты построчно (для быстрого просмотра)
  - persona_corpus.json  — структурированный корпус для bot'а
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "messages.html"
OUT_TXT = ROOT / "data" / "corpus.txt"
OUT_JSON = ROOT / "data" / "persona_corpus.json"

# Имя автора, чьи сообщения собираем как «эталон стиля»
AUTHOR = "vomitboy.com"


MESSAGE_BLOCK_RE = re.compile(
    r'<div class="message default[^"]*"[^>]*>(.*?)(?=<div class="message |</div>\s*</div>\s*</div>\s*</body>)',
    re.DOTALL,
)
FROM_NAME_RE = re.compile(r'<div class="from_name">\s*(.*?)\s*</div>', re.DOTALL)
TEXT_BLOCK_RE = re.compile(r'<div class="text">\s*(.*?)\s*</div>', re.DOTALL)
DATE_RE = re.compile(r'title="([^"]+)"')
JOINED_RE = re.compile(r'<div class="message default clearfix joined"')


def clean_text(raw: str) -> str:
    """Срезает HTML-теги, разворачивает entities, нормализует пробелы."""
    # Заменяем <br> на перенос строки
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    # Срезаем оставшуюся разметку (ссылки, спойлеры, форматирование)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    # Чистим пробелы и переносы
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def parse() -> list[dict]:
    text = SRC.read_text(encoding="utf-8", errors="ignore")

    # Разбиваем по началу следующего сообщения, чтобы корректно
    # извлечь и «joined»-сообщения (без from_name).
    parts = re.split(r'(?=<div class="message default)', text)

    messages: list[dict] = []
    current_author = None

    for chunk in parts:
        if 'class="message default' not in chunk:
            continue

        is_joined = "clearfix joined" in chunk[:200]

        name_match = FROM_NAME_RE.search(chunk)
        if name_match:
            current_author = clean_text(name_match.group(1))

        if current_author != AUTHOR:
            continue

        text_match = TEXT_BLOCK_RE.search(chunk)
        if not text_match:
            continue

        body = clean_text(text_match.group(1))
        if not body:
            continue

        date_match = DATE_RE.search(chunk)
        date = date_match.group(1) if date_match else None

        messages.append(
            {
                "date": date,
                "joined": is_joined,
                "text": body,
            }
        )

    return messages


def main() -> None:
    messages = parse()

    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)

    OUT_TXT.write_text(
        "\n---\n".join(m["text"] for m in messages),
        encoding="utf-8",
    )

    OUT_JSON.write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_chars = sum(len(m["text"]) for m in messages)
    print(f"Всего сообщений: {len(messages)}")
    print(f"Всего символов: {total_chars}")
    print(f"Средняя длина: {total_chars / max(len(messages), 1):.1f}")


if __name__ == "__main__":
    main()
