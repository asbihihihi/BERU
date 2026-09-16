import asyncio
from backend.agent.permissions import PermissionLevel, PermissionManager
from backend.agent.tool_registry import Tool, ToolRegistry
from backend.agent.memory import Memory

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
