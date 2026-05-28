"""Точка входа: запуск Telegram-бота через long polling."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder

from .config import load_settings
from .grok_client import GrokClient
from .handlers import register_handlers


BOT_COMMANDS: list[BotCommand] = [
    BotCommand("lore", "интересная инфа по лору"),
    BotCommand("reset", "забыть контекст диалога"),
    BotCommand("start", "представиться"),
]


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/healthz", "/health"):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002, ARG002
        return


def _start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="health-server",
        daemon=True,
    )
    thread.start()
    logging.getLogger(__name__).info("Health-сервер слушает 0.0.0.0:%s", port)
    return server


async def _amain() -> None:
    settings = load_settings()
    _setup_logging(settings.log_level)
    logger = logging.getLogger("bot")

    grok = GrokClient(
        api_key=settings.xai_api_key,
        model=settings.xai_model,
        base_url=settings.xai_base_url,
        timeout=settings.request_timeout,
    )

    application: Application = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .concurrent_updates(True)
        .build()
    )

    application.bot_data["settings"] = settings
    application.bot_data["grok"] = grok

    register_handlers(application)

    await application.initialize()

    me = await application.bot.get_me()
    bot_username = me.username or ""
    application.bot_data["bot_username"] = bot_username
    logger.info("Бот авторизован как @%s (%s)", bot_username, me.id)

    try:
        await application.bot.set_my_commands(BOT_COMMANDS)
        logger.info("Команды бота зарегистрированы: %s", [c.command for c in BOT_COMMANDS])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось зарегистрировать команды: %s", exc)

    health_server = _start_health_server(settings.health_port)

    await application.start()
    await application.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "edited_message", "callback_query"],
    )
    logger.info("Long polling запущен.")

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Получен сигнал остановки.")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _signal_handler)

    try:
        await stop_event.wait()
    finally:
        logger.info("Останавливаюсь…")
        with suppress(Exception):
            await application.updater.stop()
        with suppress(Exception):
            await application.stop()
        with suppress(Exception):
            await application.shutdown()
        with suppress(Exception):
            await grok.close()
        with suppress(Exception):
            health_server.shutdown()
            health_server.server_close()


def main() -> None:
    if os.name == "nt":
        with suppress(Exception):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
