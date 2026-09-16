import asyncio
import json
import logging
from time import perf_counter
from collections.abc import Awaitable, Callable
from typing import Any

from .permissions import PermissionManager
from .tool_registry import ToolRegistry
from backend.llm.provider import LLMClient


EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]
LOG = logging.getLogger("beru.agent")


SYSTEM = """Kamu adalah BERU, asisten desktop pribadi Asbi.

ATURAN:
- SELALU jawab dalam Bahasa Indonesia.
- Gunakan tool untuk tindakan laptop dan semua informasi yang realtime/berubah.
- Cuaca: get_weather. Sepak bola: get_sports_schedule/get_sports_results. Berita: get_latest_news. Waktu/tanggal: get_current_time. Informasi terkini lain: web_search.
- Jangan gunakan tool untuk sapaan atau obrolan biasa.
- Jangan mengarang data realtime atau mengklaim tindakan berhasil tanpa hasil tool. Jika tool error, katakan data realtime tidak tersedia.
- Untuk aplikasi gunakan open_application; folder gunakan open_folder; pencarian file gunakan find_file_or_folder; menutup aplikasi gunakan close_application.
- Jawaban natural, singkat, dan bukan bahasa Inggris kecuali diminta.
"""


class AgentCore:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        permissions: PermissionManager,
    ):
        self.llm = llm
        self.tools = tools
        self.permissions = permissions

    async def run(
        self,
        user_message: str,
        emit: EventSink,
        approved: bool = False,
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        started_at = perf_counter()
        await emit(
            "agent_started",
            {"message": user_message},
        )

        await emit(
            "thinking",
            {"status": "Memproses..."},
        )

        history_length = len(history or [])
        messages = [
            {
                "role": "system",
                "content": SYSTEM,
            },
            *(history or []),
            {
                "role": "user",
                "content": user_message,
            },
        ]

        try:
            llm_started = perf_counter()
            reply = await self.llm.chat(
                messages,
                self.tools.schemas(),
            )
            LOG.info("[BERU] Tool selection: %.2fs", perf_counter() - llm_started)

            calls = reply.get("tool_calls", [])

            if not calls:
                answer = str(
                    reply.get("content") or "Siap."
                )

                await emit(
                    "message_delta",
                    {"delta": answer},
                )

                await emit(
                    "message_complete",
                    {"message": answer},
                )

                self._remember_turn(
                    history,
                    [*messages[1 + history_length:], reply],
                )
                return answer

            tool_messages = []
            for call in calls:
                fn = call.get("function", {})

                name = fn.get("name", "")
                args = fn.get("arguments", {})

                if isinstance(args, str):
                    args = json.loads(args or "{}")

                tool = self.tools.get(name)

                if not tool:
                    result = {
                        "error": "Tool tidak dikenal"
                    }

                elif (
                    self.permissions.requires_confirmation(
                        tool.permission
                    )
                    and not approved
                ):
                    await emit(
                        "permission_required",
                        {
                            "tool": name,
                            "arguments": args,
                            "permission": tool.permission,
                            "message": user_message,
                        },
                    )

                    return (
                        "Saya membutuhkan persetujuan "
                        "sebelum menjalankan tindakan ini."
                    )

                else:
                    await emit(
                        "tool_started",
                        {
                            "tool": name,
                    "status": self._tool_status(name),
                        },
                    )

                    try:
                        tool_started = perf_counter()
                        result = await asyncio.wait_for(
                            tool.handler(args),
                            tool.timeout,
                        )
                        LOG.info("[BERU] Tool %s: %.2fs", name, perf_counter() - tool_started)
                    except Exception as exc:
                        result = {
                            "error": str(exc)
                        }

                    await emit(
                        "tool_finished",
                        {
                            "tool": name,
                            "status": "completed",
                            "result": result,
                        },
                    )

                tool_messages.append({
                    "role": "tool",
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            messages.extend([reply, *tool_messages])

            await emit(
                "thinking",
                {"status": "Menyusun jawaban..."},
            )

            # Gemini requires the same tool declarations when a function
            # response is sent in this stateless follow-up request.
            final_started = perf_counter()
            chunks: list[str] = []
            stream = getattr(self.llm, "chat_stream", None)
            if stream:
                async for delta in stream(messages, self.tools.schemas()):
                    if delta:
                        chunks.append(str(delta))
                        await emit("message_delta", {"delta": str(delta)})
                answer = "".join(chunks) or "Tugas selesai."
            else:
                final = await self.llm.chat(messages, self.tools.schemas())
                answer = str(final.get("content") or "Tugas selesai.")
                await emit("message_delta", {"delta": answer})
            LOG.info("[BERU] Final response: %.2fs", perf_counter() - final_started)

            await emit(
                "message_complete",
                {"message": answer},
            )

            self._remember_turn(
                history,
                [*messages[1 + history_length:], {"role": "assistant", "content": answer}],
            )
            return answer

        except Exception as exc:
            LOG.warning("LLM request failed (%s).", type(exc).__name__)
            detail = str(exc) if type(exc).__name__ == "GeminiConfigurationError" else "Model tidak tersedia."
            await emit(
                "error",
                {
                    "message": detail
                },
            )

            return "Maaf, " + detail

        finally:
            LOG.info("[BERU] Total: %.2fs", perf_counter() - started_at)
            await emit(
                "agent_finished",
                {}
            )

    @staticmethod
    def _remember_turn(history: list[dict[str, Any]] | None, messages: list[dict[str, Any]]) -> None:
        """Retain a small, session-only context without repeatedly sending all history."""
        if history is None:
            return
        history.extend(messages)
        # Keep the newest turns and their tool results; cap prompt growth.
        del history[:-16]

    @staticmethod
    def _tool_status(name: str) -> str:
        labels = {"get_weather": "Mencari cuaca...", "get_sports_schedule": "Mencari jadwal pertandingan...", "get_sports_results": "Mencari hasil pertandingan...", "get_latest_news": "Mencari berita terbaru...", "get_current_time": "Memeriksa waktu...", "web_search": "Mencari di web..."}
        return labels.get(name, f"Menjalankan {name}...")
