"""Lightweight LLM API client using stdlib urllib.

Replaces the OpenAI and Anthropic SDKs for chat completion calls.
The SDKs pull in ~1000 transitive imports (httpx, rich, click, pygments,
pydantic) which can hang on macOS when the kernel's Endpoint Security
framework blocks read() syscalls on .pyc files. This module uses only
stdlib, which is already loaded by Python's import machinery.
"""

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2023-06-01"


def call_openai(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    response_format: dict[str, str] | None = None,
    timeout: int = 60,
) -> str:
    """Call OpenAI chat completions API. Returns the assistant message content.

    Args:
        api_key: OpenAI API key.
        model: Model name (e.g. "gpt-4o-mini").
        messages: List of message dicts with "role" and "content".
        temperature: Sampling temperature.
        response_format: Optional response format (e.g. {"type": "json_object"}).
        timeout: Request timeout in seconds.

    Returns:
        The content string from the first choice's message.

    Raises:
        urllib.error.HTTPError: On API errors (4xx, 5xx).
        TimeoutError: If the request exceeds the timeout.
        json.JSONDecodeError: If the response isn't valid JSON.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if response_format:
        payload["response_format"] = response_format

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(_OPENAI_API_URL, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return result["choices"][0]["message"]["content"]


def call_anthropic(
    *,
    api_key: str,
    model: str,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 4096,
    temperature: float = 0,
    timeout: int = 60,
) -> str:
    """Call Anthropic messages API. Returns the first text content block.

    Args:
        api_key: Anthropic API key.
        model: Model name (e.g. "claude-sonnet-4-20250514").
        system: System prompt.
        messages: List of message dicts with "role" and "content".
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        timeout: Request timeout in seconds.

    Returns:
        The text content from the first content block.

    Raises:
        urllib.error.HTTPError: On API errors (4xx, 5xx).
        TimeoutError: If the request exceeds the timeout.
        json.JSONDecodeError: If the response isn't valid JSON.
    """
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "temperature": temperature,
    }

    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": _ANTHROPIC_API_VERSION,
    }

    req = urllib.request.Request(_ANTHROPIC_API_URL, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return result["content"][0]["text"]
