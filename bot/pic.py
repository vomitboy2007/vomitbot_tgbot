"""Команда /pic: случайная картинка из локальной папки images/ → ASCII."""

from __future__ import annotations

import io
import logging
import random
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import IMAGES_DIR, LORE_SITE_URL

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
ASCII_CHARS = "@%#*+=-:. "
DEFAULT_WIDTH = 64
DEFAULT_MAX_LINES = 32
MIN_FILE_BYTES = 256

_cached_files: list[Path] | None = None


class PicError(RuntimeError):
    """Не удалось собрать ascii-картинку."""


def _resample_filter():
    try:
        return Image.Resampling.LANCZOS
    except AttributeError:
        return Image.LANCZOS


def list_image_files(*, refresh: bool = False) -> list[Path]:
    """Все картинки из images/ (рекурсивно)."""
    global _cached_files

    if not refresh and _cached_files is not None:
        return _cached_files

    if not IMAGES_DIR.is_dir():
        raise PicError(f"папка {IMAGES_DIR.name}/ не найдена")

    files: list[Path] = []
    for path in IMAGES_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        try:
            if path.stat().st_size < MIN_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(path)

    if not files:
        raise PicError("папка images/ пуста")

    _cached_files = sorted(files)
    logger.info("Найдено %s картинок в %s", len(_cached_files), IMAGES_DIR)
    return _cached_files


def _prepare_image(raw: bytes) -> Image.Image:
    with Image.open(io.BytesIO(raw)) as img:
        if getattr(img, "is_animated", False):
            img.seek(0)
        return img.convert("RGB").convert("L")


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

    img = img.resize((width, height), _resample_filter())
    pixels = list(img.getdata())

    lines: list[str] = []
    for y in range(height):
        row = pixels[y * width : (y + 1) * width]
        line = "".join(
            ASCII_CHARS[min(len(ASCII_CHARS) - 1, px * len(ASCII_CHARS) // 256)]
            for px in row
        )
        lines.append(line.rstrip())

    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        raise PicError("картинка получилась пустой")

    return "\n".join(lines)


def _source_label(path: Path) -> str:
    try:
        rel = path.relative_to(IMAGES_DIR).as_posix()
    except ValueError:
        rel = path.name
    return f"images/{rel}"


def compose_pic_reply(
    *,
    width: int = DEFAULT_WIDTH,
    max_lines: int = DEFAULT_MAX_LINES,
    attempts: int = 8,
    rng: random.Random | None = None,
) -> tuple[str, str]:
    """Возвращает (ascii_art, source_label)."""
    rng = rng or random.Random()
    files = list_image_files()
    tried: set[Path] = set()
    last_error = "неизвестная ошибка"

    for _ in range(min(attempts, len(files))):
        candidates = [f for f in files if f not in tried]
        if not candidates:
            break

        path = rng.choice(candidates)
        tried.add(path)

        try:
            art = image_to_ascii(path.read_bytes(), width=width, max_lines=max_lines)
            return art, _source_label(path)
        except (PicError, UnidentifiedImageError, OSError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("Пропускаем %s: %s", path.name, exc)
            continue

    raise PicError(last_error)


def format_pic_message(ascii_art: str, source_label: str) -> str:
    """Plain-text fallback для Telegram."""
    footer = f"\n\nисточник:\n{source_label}\n\n{LORE_SITE_URL}"
    header = "ну смотри.\n\n"
    max_art = 4096 - len(header) - len(footer) - 8
    art = ascii_art if len(ascii_art) <= max_art else ascii_art[: max_art - 3].rstrip() + "..."
    return f"{header}{art}{footer}"
