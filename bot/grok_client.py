"""Тонкий async-клиент к xAI Grok API (OpenAI-совместимый)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GrokError(RuntimeError):
    """Ошибка при обращении к xAI API."""


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]+\)")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_CITATION_RE = re.compile(r"\[\[\d+\]\]\([^)]*\)")


def clean_model_output(text: str) -> str:
    """Убирает markdown-ссылки и цитаты из ответа модели."""
    text = _MD_CITATION_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_responses_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output", []):
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for block in item.get("content", []):
            if block.get("type") == "output_text" and block.get("text"):
                parts.append(block["text"])
    if parts:
        return clean_model_output("\n".join(parts))

    # запасной формат
    if isinstance(data.get("output_text"), str):
        return clean_model_output(data["output_text"])

    raise GrokError(f"не удалось извлечь текст из responses: {data!r}")


class GrokClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.x.ai/v1",
        timeout: int = 60,
        search_timeout: int = 120,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._search_timeout = search_timeout
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
            raise GrokError(
                f"xAI вернул {response.status_code}: {response.text[:500]}"
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

        return clean_model_output(content)

    async def respond_with_web_search(
        self,
        *,
        instructions: str,
        user_input: str,
        temperature: float = 0.9,
        max_output_tokens: int = 700,
    ) -> str:
        """Responses API + server-side web_search. Без истории чата."""
        payload: dict[str, Any] = {
            "model": self._model,
            "instructions": instructions,
            "input": [{"role": "user", "content": user_input}],
            "tools": [{"type": "web_search"}],
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }

        url = f"{self._base_url}/responses"

        try:
            async with httpx.AsyncClient(
                timeout=self._search_timeout,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise GrokError(f"Сетевая ошибка web_search: {exc}") from exc

        if response.status_code >= 400:
            raise GrokError(
                f"xAI responses вернул {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise GrokError(f"Не удалось распарсить responses: {exc}") from exc

        if data.get("error"):
            raise GrokError(f"xAI responses error: {data['error']}")

        return _extract_responses_text(data)
