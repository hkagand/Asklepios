"""Client for an OpenAI-compatible chat completions endpoint (vLLM, LiteLLM proxy, ...)."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from .config import Settings


class LlmError(Exception):
    pass


EFFORTS = ("minimal", "low", "medium", "high")


def effort_for(configured: str | None, reports: str | None, thorough: bool) -> str | None:
    """The reasoning effort of one request: the configured one, raised to the one set for answers from the epicrisis
    reports when `thorough`. It is never lowered, and none is sent when none is configured (a model that does not
    take the parameter)."""
    if thorough and configured in EFFORTS and reports in EFFORTS and EFFORTS.index(reports) > EFFORTS.index(configured):
        return reports
    return configured


class LlmClient:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.llm_model
        self._url = f"{settings.llm_base_url}/chat/completions"
        self._host = urlsplit(settings.llm_base_url).netloc
        headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10), headers=headers)
        self._options: dict = {"max_tokens": 4096}
        self._effort, self._reports_effort = settings.reasoning_effort, settings.reports_reasoning_effort
        if settings.temperature is not None:
            self._options["temperature"] = settings.temperature

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict],
        tool_choice: str,
        json_mode: bool = False,
        max_tokens: int | None = None,
        thorough: bool = False,
    ) -> tuple[dict, dict]:
        """Returns the assistant message and the token usage. `json_mode` asks the server for a JSON object only;
        `thorough` asks for the reasoning effort set for answers from the epicrisis reports."""
        body = {"model": self.model, "messages": messages, **self._options}
        if effort := effort_for(self._effort, self._reports_effort, thorough):
            # A LiteLLM proxy rejects reasoning_effort for OpenAI-compatible backends unless it is allowed per request.
            body |= {"reasoning_effort": effort, "allowed_openai_params": ["reasoning_effort"]}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body |= {"tools": tools, "tool_choice": tool_choice}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
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
