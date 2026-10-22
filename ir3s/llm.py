"""Thin client for any OpenAI-compatible /v1/chat/completions endpoint.

Configured by environment:
  IR3S_LLM_BASE_URL  default https://openrouter.ai/api/v1
  IR3S_LLM_API_KEY   default: the value of OPENROUTER_API_KEY
  IR3S_LLM_MODEL     default anthropic/claude-sonnet-5.5
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

__all__ = ["LLMError", "chat", "chat_json"]

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"
JSON_INSTRUCTION = "Reply with a single JSON object and nothing else: no prose, no code fences."
_RETRYABLE = {408, 425, 429}


class LLMError(RuntimeError):
    """The LLM call failed for good (bad config, non-retryable HTTP error, retries exhausted)."""


def chat(
    prompt: str,
    *,
    system: str | None = None,
    json_mode: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    max_attempts: int = 4,
    backoff: float = 1.0,
    # A mapping of a whole statement asks for a lot of thinking, and a
    # reasoning model may take a few minutes over it.
    timeout: float = 240.0,
    # A reasoning model spends most of its budget thinking before it answers.
    # Cutting it off mid-reasoning yields an empty reply, so the budget has to
    # be generous: a mapping of a whole statement reasons for about 35,000
    # tokens before it writes the JSON.
    max_tokens: int | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Send one prompt, return the assistant text.

    Retries network errors, 408/425/429 and 5xx with exponential backoff
    (backoff, 2*backoff, ...). Any other 4xx fails immediately.
    Explicit arguments win over environment variables.
    """
    key = api_key or os.environ.get("IR3S_LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("no API key: set IR3S_LLM_API_KEY (or OPENROUTER_API_KEY) or pass api_key=")
    url = (base_url or os.environ.get("IR3S_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    system_text = system or ""
    if json_mode:
        system_text = (system_text + "\n" + JSON_INSTRUCTION).strip()
    messages = ([{"role": "system", "content": system_text}] if system_text else []) + [
        {"role": "user", "content": prompt}
    ]
    body: dict = {
        "model": model or os.environ.get("IR3S_LLM_MODEL") or DEFAULT_MODEL,
        "messages": messages,
        "temperature": 0,
        # The mapping reply is a short JSON object, but the provider reserves
        # the model's whole output allowance against the key's credit, so it
        # has to be capped explicitly.
        "max_tokens": max_tokens if max_tokens is not None
        else int(os.environ.get("IR3S_LLM_MAX_TOKENS", 65536)),
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {key}"}

    http = client or httpx.Client(timeout=timeout)
    last = "unknown error"
    try:
        for attempt in range(max_attempts):
            if attempt:
                time.sleep(backoff * 2 ** (attempt - 1))
            try:
                resp = http.post(url, json=body, headers=headers)
            except httpx.TransportError as exc:
                last = f"network error: {exc}"
                continue
            if resp.status_code in _RETRYABLE or resp.status_code >= 500:
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
            if resp.status_code >= 400:
                raise LLMError(f"LLM request rejected, HTTP {resp.status_code}: {resp.text[:300]}")
            try:
                content = resp.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"unexpected response shape: {resp.text[:300]}") from exc
            if not content or not content.strip():
                # An empty reply is a truncated generation or a transient
                # upstream failure. A model that ran out of budget
                # mid-reasoning says so here, and retrying it unchanged
                # would fail the same way, so that is reported instead.
                choice = resp.json().get("choices", [{}])[0]
                reason = choice.get("finish_reason", "")
                if reason == "length":
                    raise LLMError(
                        f"the model ran out of output budget ({body['max_tokens']} tokens) "
                        "before it answered; raise IR3S_LLM_MAX_TOKENS"
                    )
                if reason == "tool_calls":
                    # The model answered with a tool call instead of text,
                    # which some upstreams do when the prompt is long. It
                    # carries no answer, so it is asked again, this time
                    # saying plainly that the answer is text.
                    last = "the model answered with a tool call instead of text"
                    body["messages"] = messages + [
                        {"role": "user", "content": "Answer with the JSON object as text. "
                         "Do not call any tool."}
                    ]
                    continue
                last = f"the model returned an empty reply (finish_reason={reason})"
                continue
            return content
    finally:
        if client is None:
            http.close()
    raise LLMError(f"LLM request failed after {max_attempts} attempts; last: {last}")


def chat_json(prompt: str, **kwargs) -> dict:
    """`chat` in JSON mode, parsed. Tolerates a stray ```json fence.

    A model that thinks out loud before answering puts prose in front of the
    JSON, so the object is extracted from wherever it appears rather than
    requiring the whole reply to be one.
    """
    kwargs.pop("json_mode", None)
    text = chat(prompt, json_mode=True, **kwargs).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        data = _extract_json(text)
        if data is None:
            # The tail matters more than the head: a reply cut short shows where.
            raise LLMError(
                f"model did not return valid JSON; reply ended: ...{text[-200:]}"
            )
    if not isinstance(data, dict):
        # A reply holding more than one object is not a dict, so the objects
        # are picked out of it.
        data = _extract_json(text) or data
    if not isinstance(data, dict):
        raise LLMError(f"model returned JSON that is not an object: {text[:300]}")
    return data


def _extract_json(text: str) -> dict | None:
    """The JSON object in a string that may contain prose.

    A reply can hold more than one object: an upstream that echoes its own
    envelope, or a model that answers twice. The one that looks like the
    answer wins, and otherwise the last one does, because a model that
    repeats itself puts the final answer last.
    """
    objects: list[dict] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    candidate = json.loads(text[start : index + 1])
                except ValueError:
                    start = -1
                    continue
                if isinstance(candidate, dict):
                    objects.append(candidate)
                start = -1
    if not objects:
        return None
    for candidate in objects:
        if "mapping" in candidate:
            return candidate
    return objects[-1]
