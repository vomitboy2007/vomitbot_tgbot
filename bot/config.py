"""Конфигурация бота. Все значения переопределяются через переменные окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = ROOT / "data" / "persona_corpus.json"
SITE_IMAGES_PATH = ROOT / "data" / "site_images.json"
IMAGES_DIR = ROOT / "images"
LORE_SITE_URL = "https://vomitboycom.neocities.org/"


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения {name!r}")
    return value or ""


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    xai_api_key: str
    xai_model: str
    xai_base_url: str
    temperature: float
    max_tokens: int
    history_size: int
    history_max_chars: int
    group_reply_chance: float
    request_timeout: int
    bot_name_aliases: tuple[str, ...]
    log_level: str
    health_port: int
    web_search_enabled: bool
    web_search_max_tokens: int
    search_timeout: int


def load_settings() -> Settings:
    aliases_raw = _env(
        "BOT_NAME_ALIASES",
        "ярик,ярослав,вомит,вомитбой,вомитбойчик,vomit,vomitboy,v0mitboy",
    )
    aliases = tuple(
        a.strip().lower() for a in aliases_raw.split(",") if a.strip()
    )

    return Settings(
        telegram_token=_env("TG_BOT_TOKEN", required=True),
        xai_api_key=_env("XAI_API_KEY", required=True),
        xai_model=_env("XAI_MODEL", "grok-4.3"),
        xai_base_url=_env("XAI_BASE_URL", "https://api.x.ai/v1"),
        temperature=_env_float("XAI_TEMPERATURE", 0.95),
        max_tokens=_env_int("XAI_MAX_TOKENS", 500),
        history_size=_env_int("HISTORY_SIZE", 100),
        history_max_chars=_env_int("HISTORY_MAX_CHARS", 700),
        group_reply_chance=_env_float("GROUP_REPLY_CHANCE", 0.05),
        request_timeout=_env_int("REQUEST_TIMEOUT", 60),
        bot_name_aliases=aliases,
        log_level=_env("LOG_LEVEL", "INFO"),
        health_port=_env_int("PORT", 8080),
        web_search_enabled=_env("WEB_SEARCH_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
        web_search_max_tokens=_env_int("WEB_SEARCH_MAX_TOKENS", 700),
        search_timeout=_env_int("SEARCH_TIMEOUT", 120),
    )
