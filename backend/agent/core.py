import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .permissions import PermissionManager
from .tool_registry import ToolRegistry
from backend.llm.ollama_client import OllamaClient


EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


SYSTEM = """
Kamu adalah BERU, asisten AI desktop pribadi milik Asbi.

ATURAN UTAMA:
- SELALU jawab dalam Bahasa Indonesia.
- Jangan pernah menjawab dalam Bahasa Inggris kecuali Asbi secara eksplisit meminta Bahasa Inggris.
- Gunakan gaya bicara natural, santai, ramah, dan singkat.
- Jangan terdengar seperti robot atau customer service formal.
- Panggil pengguna dengan nama "Asbi" jika sesuai konteks.
- Untuk sapaan seperti "halo beru", "hai beru", atau "beru", jawab secara singkat dan natural.
- Jika pengguna hanya menyapa, jangan gunakan tool.
- Gunakan tools untuk mendapatkan fakta terkini atau melakukan tindakan di komputer.
- Jangan pernah mengklaim suatu tindakan berhasil jika hasil tool belum mengonfirmasi keberhasilannya.
- Prioritaskan jawaban yang pendek agar cepat dibacakan oleh suara.

CONTOH:
User: "halo beru"
BERU: "Hai Asbi, saya BERU. Mau ngapain hari ini?"

User: "hai beru"
BERU: "Hai Asbi! Ada yang bisa saya bantu?"

User: "beru"
BERU: "Iya, Asbi?"

User: "siapa kamu?"
BERU: "Saya BERU, asisten AI di laptopmu."

User: "buka chrome"
BERU: "Siap, saya buka Chrome."

Untuk membuka aplikasi, gunakan tool open_application. Parameter target boleh
berupa nama aplikasi manusia seperti "Chrome", "Discord", "File Explorer",
atau "Visual Studio Code"; tidak harus berupa nama file .exe.

Jika user meminta mencari file atau folder, gunakan find_file_or_folder. Jika
user meminta membuka folder, gunakan open_folder; jangan gunakan
open_application. Jika user meminta menutup, keluar, atau quit aplikasi,
gunakan close_application. Jangan mengklaim tindakan berhasil sebelum hasil
tool mengonfirmasinya. Bila found, opened, atau closed bernilai false, jelaskan
kegagalannya secara jujur, singkat, dan natural. Jangan mengarang alasan,
menyuruh restart laptop, atau menyuruh menghubungi pemilik komputer tanpa bukti
masalah sistem.

Sekali lagi: SELALU gunakan Bahasa Indonesia kecuali pengguna meminta bahasa lain.
"""


class AgentCore:
    def __init__(
        self,
        llm: OllamaClient,
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
    ) -> str:
        await emit(
            "agent_started",
            {"message": user_message},
        )

        await emit(
            "thinking",
            {"status": "Understanding request"},
        )

        messages = [
            {
                "role": "system",
                "content": SYSTEM,
            },
            {
                "role": "user",
                "content": user_message,
            },
        ]

        try:
            reply = await self.llm.chat(
                messages,
                self.tools.schemas(),
            )

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

                return answer

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
                            "status": "running",
                        },
                    )

                    try:
                        result = await asyncio.wait_for(
                            tool.handler(args),
                            tool.timeout,
                        )
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

                messages.extend(
                    [
                        reply,
                        {
                            "role": "tool",
                            "content": json.dumps(
                                result,
                                ensure_ascii=False,
                            ),
                        },
                    ]
                )

            await emit(
                "thinking",
                {"status": "Preparing response"},
            )

            final = await self.llm.chat(messages)

            answer = str(
                final.get("content") or "Tugas selesai."
            )

            await emit(
                "message_delta",
                {"delta": answer},
            )

            await emit(
                "message_complete",
                {"message": answer},
            )

            return answer

        except Exception as exc:
            await emit(
                "error",
                {
                    "message": (
                        "BERU tidak dapat menghubungi "
                        f"model: {exc}"
                    )
                },
            )

            return (
                "Maaf, model BERU sedang tidak tersedia."
            )

        finally:
            await emit(
                "agent_finished",
                {}
            )
