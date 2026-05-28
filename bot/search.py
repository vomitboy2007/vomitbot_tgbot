"""Резервный веб-поиск через DuckDuckGo (если xAI web_search недоступен)."""

from __future__ import annotations

import logging
import re
from html import unescape

import httpx

logger = logging.getLogger(__name__)

RESULT_RE = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'.*?class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
    re.I | re.S,
)
TAG_RE = re.compile(r"<[^>]+>")


async def search_web(query: str, *, max_results: int = 5, timeout: int = 15) -> str:
    """Возвращает текстовую выжимку результатов или пустую строку."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            # POST только на /html/ — query в URL ломает разметку результатов.
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": "", "kl": "ru-ru"},
            )
            response.raise_for_status()
            html = response.text
    except httpx.HTTPError as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return ""

    blocks: list[str] = []
    for match in RESULT_RE.finditer(html):
        link, title_raw, snippet_raw = match.groups()
        title = unescape(TAG_RE.sub("", title_raw)).strip()
        snippet = unescape(TAG_RE.sub("", snippet_raw)).strip()
        if not title and not snippet:
            continue
        blocks.append(f"- {title}. {snippet} ({link})")
        if len(blocks) >= max_results:
            break

    return "\n".join(blocks)
