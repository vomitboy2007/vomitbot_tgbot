"""Тонкий async-клиент к xAI Grok API (OpenAI-совместимый)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GrokError(RuntimeError):
    """Ошибка при обращении к xAI API."""


class GrokClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.x.ai/v1",
        timeout: int = 60,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.9,
        max_tokens: int = 500,
        extra: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if extra:
            payload.update(extra)

        client = await self._get_client()
        url = f"{self._base_url}/chat/completions"

        try:
            response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise GrokError(f"Сетевая ошибка при обращении к xAI: {exc}") from exc

        if response.status_code >= 400:
            body_preview = response.text[:500]
            raise GrokError(
                f"xAI вернул {response.status_code}: {body_preview}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise GrokError(f"Не удалось распарсить ответ xAI: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GrokError(f"Неожиданная структура ответа xAI: {data!r}") from exc

        if not isinstance(content, str):
            raise GrokError(f"Контент в ответе не строка: {content!r}")

        return content.strip()
