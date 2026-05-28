"""Команда /pic: случайная картинка с vomitboycom.neocities.org → ASCII."""

from __future__ import annotations

import io
import json
import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from .config import SITE_IMAGES_PATH

logger = logging.getLogger(__name__)

SITE_BASE = "https://vomitboycom.neocities.org/"
SITE_PAGES = ("/", "/gallery.html", "/articles.html", "/map.html")

IMG_RE = re.compile(
    r"""(?:src|href|data-src|data-original)\s*=\s*["']([^"']+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^"']*)?)["']""",
    re.I,
)
CSS_URL_RE = re.compile(
    r"""url\(\s*['"]?([^'"\)]+\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^'"\)]*)?)['"]?\s*\)""",
    re.I,
)

# От UI-баннеров отказываемся — берём контент с /images/ и /gifs/.
SKIP_PATH_PARTS = ("/banners/",)

ASCII_CHARS = "@%#*+=-:. "
DEFAULT_WIDTH = 64
DEFAULT_MAX_LINES = 32
TELEGRAM_TEXT_LIMIT = 4096
CACHE_TTL_SECONDS = 6 * 60 * 60

_cache_urls: list[str] | None = None
_cache_ts: float = 0.0
_http: httpx.AsyncClient | None = None


class PicError(RuntimeError):
    """Не удалось собрать ascii-картинку."""


def _normalize_url(page_url: str, raw: str) -> str | None:
    full = urljoin(page_url, raw.replace("\\", "/"))
    parsed = urlparse(full)
    if not parsed.netloc.endswith("neocities.org"):
        return None
    if any(part in parsed.path.lower() for part in SKIP_PATH_PARTS):
        return None
    return full


def _extract_urls(html: str, page_url: str) -> set[str]:
    found: set[str] = set()
    for rx in (IMG_RE, CSS_URL_RE):
        for match in rx.findall(html):
            url = _normalize_url(page_url, match)
            if url:
                found.add(url)
    return found


def _load_bundled_urls() -> list[str]:
    if not SITE_IMAGES_PATH.exists():
        return []
    try:
        data = json.loads(SITE_IMAGES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Не удалось прочитать %s: %s", SITE_IMAGES_PATH, exc)
        return []
    urls = data.get("urls", data if isinstance(data, list) else [])
    return [u for u in urls if isinstance(u, str)]


async def _get_client(timeout: int = 25) -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    return _http


async def close_pic_client() -> None:
    global _http
    if _http is not None and not _http.is_closed:
        await _http.aclose()
    _http = None


async def refresh_image_urls(*, force: bool = False) -> list[str]:
    """Качает список картинок с сайта. Кэширует на CACHE_TTL_SECONDS."""
    global _cache_urls, _cache_ts

    now = time.monotonic()
    if not force and _cache_urls and (now - _cache_ts) < CACHE_TTL_SECONDS:
        return _cache_urls

    client = await _get_client()
    found: set[str] = set()

    for page in SITE_PAGES:
        url = urljoin(SITE_BASE, page)
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Не удалось загрузить %s: %s", url, exc)
            continue
        found.update(_extract_urls(response.text, url))

    urls = sorted(found)
    if urls:
        _cache_urls = urls
        _cache_ts = now
        logger.info("Обновлён список картинок сайта: %s шт.", len(urls))
        return urls

    bundled = _load_bundled_urls()
    if bundled:
        logger.warning("Краул не дал результатов, используем bundled (%s шт.)", len(bundled))
        _cache_urls = bundled
        _cache_ts = now
        return bundled

    raise PicError("не удалось получить список картинок с сайта")


def _prepare_image(raw: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw))
    if getattr(img, "is_animated", False):
        img.seek(0)
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (0, 0, 0))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    else:
        img = img.convert("L")
        return img
    return img.convert("L")


def image_to_ascii(
    raw: bytes,
    *,
    width: int = DEFAULT_WIDTH,
    max_lines: int = DEFAULT_MAX_LINES,
) -> str:
    """Конвертирует байты картинки в ASCII-арт."""
    img = _prepare_image(raw)

    aspect = img.height / max(img.width, 1)
    height = max(1, int(width * aspect * 0.55))
    height = min(height, max_lines)

    img = img.resize((width, height), Image.Resampling.LANCZOS)
    pixels = img.getdata()

    lines: list[str] = []
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        line = "".join(ASCII_CHARS[min(len(ASCII_CHARS) - 1, px * len(ASCII_CHARS) // 256)] for px in row)
        lines.append(line.rstrip())

    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        raise PicError("картинка получилась пустой")

    return "\n".join(lines)


async def fetch_image_bytes(url: str) -> bytes:
    client = await _get_client()
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PicError(f"не скачалась: {exc}") from exc

    if len(response.content) < 256:
        raise PicError("файл слишком маленький")

    return response.content


async def compose_pic_reply(
    *,
    width: int = DEFAULT_WIDTH,
    max_lines: int = DEFAULT_MAX_LINES,
    attempts: int = 6,
    rng: random.Random | None = None,
) -> tuple[str, str]:
    """Возвращает (ascii_art, source_url)."""
    rng = rng or random.Random()
    urls = await refresh_image_urls()
    if not urls:
        raise PicError("на сайте нет картинок")

    tried: set[str] = set()
    last_error = "неизвестная ошибка"

    for _ in range(min(attempts, len(urls))):
        candidates = [u for u in urls if u not in tried]
        if not candidates:
            break
        url = rng.choice(candidates)
        tried.add(url)

        try:
            raw = await fetch_image_bytes(url)
            art = image_to_ascii(raw, width=width, max_lines=max_lines)
            return art, url
        except (PicError, UnidentifiedImageError, OSError, ValueError) as exc:
            last_error = str(exc)
            logger.debug("Пропускаем %s: %s", url, exc)
            continue

    raise PicError(last_error)


def format_pic_message(ascii_art: str, source_url: str) -> str:
    """Собирает финальный текст для Telegram с учётом лимита 4096."""
    footer = f"\n\nисточник:\n{source_url}"
    header = "ну смотри.\n\n"
    max_art_len = TELEGRAM_TEXT_LIMIT - len(header) - len(footer) - 16

    art = ascii_art
    if len(art) > max_art_len:
        art = art[: max_art_len - 3].rstrip() + "..."

    return f"{header}{art}{footer}"
