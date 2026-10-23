"""Client for an OpenAI-compatible chat completions endpoint (vLLM, LiteLLM proxy, ...)."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from .config import Settings


class LlmError(Exception):
    pass


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.llm_model
        self._url = f"{settings.llm_base_url}/chat/completions"
        self._host = urlsplit(settings.llm_base_url).netloc
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10), headers=headers)
        self._options: dict = {"max_tokens": 4096}
        if settings.reasoning_effort:
            # A LiteLLM proxy rejects reasoning_effort for OpenAI-compatible backends unless it is allowed per request.
            self._options |= {"reasoning_effort": settings.reasoning_effort, "allowed_openai_params": ["reasoning_effort"]}
        if settings.temperature is not None:
            self._options["temperature"] = settings.temperature

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, messages: list[dict], *, tools: list[dict], tool_choice: str) -> tuple[dict, dict]:
        """Returns the assistant message and the token usage."""
        body = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": tool_choice, **self._options}
        for attempt in (1, 2):
            try:
                response = await self._client.post(self._url, json=body)
            except httpx.TransportError as error:
                if attempt == 2:
                    raise LlmError(f"Could not reach the language model at {self._host} ({error}).") from error
                continue
            if response.status_code >= 500 and attempt == 1:
                continue
            if response.is_error:
                raise LlmError(f"The language model at {self._host} answered {response.status_code}: {response.text[:400]}")
            payload = response.json()
            choices = payload.get("choices") or []
            if not choices:
                raise LlmError(f"The language model at {self._host} returned no choices.")
            return choices[0].get("message") or {}, payload.get("usage") or {}
        raise LlmError(f"The language model at {self._host} did not answer.")
