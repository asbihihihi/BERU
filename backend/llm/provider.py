"""Provider selection and safe Gemini-to-Ollama fallback."""

from __future__ import annotations

import logging
import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from .gemini_client import GeminiConfigurationError, describe_gemini_error

LOG = logging.getLogger("beru.llm")


class LLMClient(Protocol):
    provider: str
    model: str

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...


class FallbackLLM:
    """Use Ollama only after a runtime Gemini failure, never for bad config."""

    provider = "gemini"

    def __init__(self, primary: LLMClient, fallback: LLMClient, timeout_seconds: float = 15.0):
        self.primary = primary
        self.fallback = fallback
        self.model = primary.model
        self.last_provider = primary.provider
        self.timeout_seconds = timeout_seconds

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        try:
            result = await asyncio.wait_for(self.primary.chat(messages, tools), timeout=self.timeout_seconds)
            self.last_provider = self.primary.provider
            return result
        except GeminiConfigurationError:
            raise
        except Exception as exc:
            self._log_gemini_error(exc, "chat")
            try:
                result = await asyncio.wait_for(self.fallback.chat(messages, tools), timeout=30.0)
                self.last_provider = self.fallback.provider
                return result
            except Exception as fallback_exc:
                LOG.warning("Ollama fallback failed (%s).", type(fallback_exc).__name__)
                raise RuntimeError("Gemini dan Ollama tidak tersedia.") from fallback_exc

    async def chat_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[str]:
        """Stream Gemini's final text, with a complete Ollama fallback on failure."""
        stream = getattr(self.primary, "chat_stream", None)
        if stream is None:
            reply = await self.chat(messages, tools)
            if reply.get("content"):
                yield str(reply["content"])
            return
        emitted = False
        try:
            iterator = stream(messages, tools).__aiter__()
            while True:
                try:
                    delta = await asyncio.wait_for(anext(iterator), timeout=self.timeout_seconds)
                except StopAsyncIteration:
                    break
                emitted = True
                yield delta
            self.last_provider = self.primary.provider
        except GeminiConfigurationError:
            raise
        except Exception as exc:
            # A partial answer must not be followed by a duplicated fallback.
            if emitted:
                self._log_gemini_error(exc, "stream")
                raise
            self._log_gemini_error(exc, "stream")
            reply = await asyncio.wait_for(self.fallback.chat(messages, tools), timeout=30.0)
            self.last_provider = self.fallback.provider
            if reply.get("content"):
                yield str(reply["content"])

    def _log_gemini_error(self, exc: Exception, operation: str) -> None:
        detail = describe_gemini_error(exc, self.primary.model, operation)
        LOG.warning(
            "[Gemini] request failed | model=%s | operation=%s | status=%s | reason=%s | message=%s | trying Ollama fallback.",
            detail["model"], detail["operation"], detail["status"], detail["reason"], detail["message"],
        )
