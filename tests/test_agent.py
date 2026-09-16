import asyncio
from backend.agent.permissions import PermissionLevel, PermissionManager
from backend.agent.tool_registry import Tool, ToolRegistry
from backend.agent.memory import Memory
from backend.agent.core import AgentCore


class ContextLLM:
    provider = "test"
    model = "test-model"

    def __init__(self):
        self.requests = []

    async def chat(self, messages, tools=None):
        self.requests.append(messages)
        return {"role": "assistant", "content": "Siap."}

def test_registry_and_permissions():
    registry=ToolRegistry()
    async def handler(a): return {"ok":True}
    registry.register(Tool("sample","Sample",{"type":"object"},handler,PermissionLevel.HIGH))
    assert registry.get("sample") is not None
    assert PermissionManager().requires_confirmation(PermissionLevel.HIGH)
    assert not PermissionManager().requires_confirmation(PermissionLevel.LOW)

def test_memory(tmp_path):
    memory=Memory(tmp_path/"memory.db"); memory.save("language","Indonesian")
    assert memory.list()[0]["value"] == "Indonesian"
    assert memory.delete("language")


def test_agent_keeps_bounded_session_context():
    llm = ContextLLM()
    agent = AgentCore(llm, ToolRegistry(), PermissionManager())
    history = []

    async def emit(*_):
        pass

    asyncio.run(agent.run("Cari file PDF", emit, history=history))
    asyncio.run(agent.run("Buka yang kedua", emit, history=history))

    assert any(message.get("content") == "Cari file PDF" for message in llm.requests[1])
    assert len(history) == 4


def test_agent_executes_selected_live_tool_and_returns_final_answer():
    class ToolLLM(ContextLLM):
        async def chat(self, messages, tools=None):
            self.requests.append(messages)
            if len(self.requests) == 1:
                return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_current_time", "arguments": {}}}]}
            return {"role": "assistant", "content": "Sekarang pukul 10.00 WIB."}

    llm = ToolLLM()
    registry = ToolRegistry()
    called = []

    async def current_time(_):
        called.append(True)
        return {"time": "10:00", "timezone": "Asia/Jakarta"}

    registry.register(Tool("get_current_time", "Waktu saat ini", {"type": "object"}, current_time))
    agent = AgentCore(llm, registry, PermissionManager())

    async def emit(*_):
        pass

    answer = asyncio.run(agent.run("Jam berapa sekarang?", emit))
    assert called == [True]
    assert answer == "Sekarang pukul 10.00 WIB."


def test_agent_streams_final_answer_after_tool_result():
    class StreamLLM(ContextLLM):
        async def chat(self, messages, tools=None):
            return {"role": "assistant", "tool_calls": [{"function": {"name": "get_current_time", "arguments": {}}}]}

        async def chat_stream(self, messages, tools=None):
            yield "Sekarang "
            yield "pukul 10.00 WIB."

    registry = ToolRegistry()

    async def current_time(_):
        return {"time": "10:00"}

    registry.register(Tool("get_current_time", "Waktu", {"type": "object"}, current_time))
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    answer = asyncio.run(AgentCore(StreamLLM(), registry, PermissionManager()).run("Jam berapa?", emit))
    assert answer == "Sekarang pukul 10.00 WIB."
    assert [data["delta"] for kind, data in events if kind == "message_delta"] == ["Sekarang ", "pukul 10.00 WIB."]
