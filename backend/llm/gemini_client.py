"""Gemini adapter that exposes BERU's provider-neutral ``chat`` contract."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

try:
    from google import genai
    from google.genai import types
except ImportError:  # Keep the API bootable so it can report setup guidance.
    genai = None
    types = None


class GeminiConfigurationError(RuntimeError):
    """Raised locally when Gemini has not been configured."""


def describe_gemini_error(exc: Exception, model: str, operation: str) -> dict[str, str]:
    """Return diagnostic fields without ever serialising SDK request objects."""
    raw_status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = str(raw_status) if isinstance(raw_status, int) else "unknown"
    raw_message = getattr(exc, "message", None)
    if isinstance(raw_message, dict):
        # Google SDK may store the parsed response body here. Keep only its
        # human-readable message, never the full response structure.
        payload = raw_message.get("error", raw_message)
        raw_message = payload.get("message", "") if isinstance(payload, dict) else ""
    message = str(raw_message if raw_message is not None else exc)
    # Gemini errors normally contain no credentials, but sanitize defensively
    # before logging an SDK-provided message.
    message = re.sub(r"AIza[0-9A-Za-z_-]{12,}", "[REDACTED_API_KEY]", message)
    message = re.sub(r"(?i)authorization\s*[:=]?\s*bearer\s+[^\s,;]+", "authorization=[REDACTED]", message)
    message = re.sub(r"(?i)(authorization|bearer|credential|secret)\s*[:=]?\s*[^\s,;]+", r"\1=[REDACTED]", message)
    message = re.sub(r"(?i)([?&](?:key|api[_-]?key)=)[^&\s]+", r"\1[REDACTED]", message)
    message = " ".join(message.split())[:1000]
    lower = message.lower()
    if status == "429" or "quota" in lower or "rate limit" in lower:
        reason = "quota/rate limit"
    elif status == "401" or "api key" in lower or "authentication" in lower or "unauthenticated" in lower:
        reason = "authentication"
    elif status == "403" or "permission" in lower or "forbidden" in lower:
        reason = "permission"
    elif status == "404" or "model not found" in lower or "not found" in lower:
        reason = "model not found"
    elif status == "400" or "invalid argument" in lower:
        reason = "invalid argument"
    elif "timeout" in lower or "timed out" in lower:
        reason = "timeout"
    else:
        reason = type(exc).__name__
    return {"model": model, "operation": operation, "status": status, "reason": reason, "message": message}


class GeminiClient:
    """Translate BERU/Ollama-shaped messages and tools to the Gemini API."""

    provider = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self._client = genai.Client(api_key=api_key) if api_key and genai else None

    @staticmethod
    def _tool_declarations(tools: list[dict[str, Any]]) -> list[types.Tool]:
        declarations = [
            {
                "name": item["function"]["name"],
                "description": item["function"].get("description", ""),
                "parameters": item["function"].get("parameters", {"type": "object"}),
            }
            for item in tools
            if item.get("type") == "function" and item.get("function", {}).get("name")
        ]
        return [types.Tool(function_declarations=declarations)] if declarations else []

    @staticmethod
    def _contents(messages: list[dict[str, Any]]) -> tuple[str | None, list[types.Content]]:
        system_parts: list[str] = []
        contents: list[types.Content] = []
        for message in messages:
            role = message.get("role")
            if role == "system":
                system_parts.append(str(message.get("content", "")))
            elif role == "assistant":
                parts: list[types.Part] = []
                text = message.get("content")
                if text:
                    parts.append(types.Part.from_text(text=str(text)))
                for call in message.get("tool_calls", []):
                    function = call.get("function", {})
                    arguments = function.get("arguments", {})
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments or "{}")
                    # Gemini 3 requires the model-provided thought signature to
                    # accompany a returned function call on the next turn.
                    # Preserve it in BERU's neutral message format instead of
                    # rebuilding a call without that cryptographic context.
                    parts.append(types.Part(
                        function_call=types.FunctionCall(
                            name=str(function.get("name", "")), args=arguments or {}
                        ),
                        thought_signature=call.get("thought_signature"),
                    ))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                try:
                    response = json.loads(str(message.get("content", "{}")))
                except json.JSONDecodeError:
                    response = {"result": str(message.get("content", ""))}
                name = str(message.get("name", "tool_result"))
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(name=name, response=response)],
                ))
            elif role == "user":
                contents.append(types.Content(
                    role="user", parts=[types.Part.from_text(text=str(message.get("content", "")))]
                ))
        return "\n\n".join(system_parts) or None, contents

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        if not self.api_key:
            raise GeminiConfigurationError("Gemini belum dikonfigurasi: isi GEMINI_API_KEY di file .env.")
        if self._client is None:
            raise GeminiConfigurationError("Paket Gemini belum tersedia: jalankan pip install -r requirements.txt.")
        system_instruction, contents = self._contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._tool_declarations(tools or []),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._client.aio.models.generate_content(
            model=self.model, contents=contents, config=config
        )
        parts = response.candidates[0].content.parts if response.candidates else []
        calls = [
            {"type": "function", "function": {"name": part.function_call.name, "arguments": dict(part.function_call.args or {})},
             "thought_signature": part.thought_signature}
            for part in parts if part.function_call
        ]
        text = "".join(part.text for part in parts if part.text)
        return {"role": "assistant", "content": text, "tool_calls": calls}

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        """Stream text only after BERU has completed a tool round-trip."""
        if not self.api_key:
            raise GeminiConfigurationError("Gemini belum dikonfigurasi: isi GEMINI_API_KEY di file .env.")
        if self._client is None:
            raise GeminiConfigurationError("Paket Gemini belum tersedia: jalankan pip install -r requirements.txt.")
        system_instruction, contents = self._contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._tool_declarations(tools or []),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        stream = await self._client.aio.models.generate_content_stream(
            model=self.model, contents=contents, config=config
        )
        async for chunk in stream:
            for candidate in chunk.candidates or []:
                for part in (candidate.content.parts if candidate.content else []):
                    if part.text:
                        yield part.text
