import asyncio
import logging

from backend.llm.gemini_client import describe_gemini_error
from backend.llm.provider import FallbackLLM


class FakeGeminiError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def test_gemini_error_is_classified_and_redacts_key():
    error = FakeGeminiError(429, "Quota exceeded for key=AIza12345678901234567890")
    detail = describe_gemini_error(error, "gemini-3.6-flash", "chat")
    assert detail["status"] == "429"
    assert detail["reason"] == "quota/rate limit"
    assert "AIza" not in detail["message"]
    assert detail["operation"] == "chat"


def test_gemini_error_keeps_only_nested_google_message():
    error = FakeGeminiError(400, {"error": {"message": "Invalid argument", "details": [{"secret": "never-log"}]}})
    detail = describe_gemini_error(error, "gemini-3.6-flash", "stream")
    assert detail["reason"] == "invalid argument"
    assert detail["message"] == "Invalid argument"


def test_fallback_logs_safe_gemini_details(caplog):
    class Primary:
        provider, model = "gemini", "gemini-3.6-flash"

        async def chat(self, *_):
            raise FakeGeminiError(404, "Model not found; authorization Bearer hidden-value")

    class Fallback:
        provider, model = "ollama", "qwen"

        async def chat(self, *_):
            return {"content": "fallback"}

    with caplog.at_level(logging.WARNING, logger="beru.llm"):
        result = asyncio.run(FallbackLLM(Primary(), Fallback()).chat([]))

    assert result["content"] == "fallback"
    assert "status=404" in caplog.text
    assert "reason=model not found" in caplog.text
    assert "hidden-value" not in caplog.text
