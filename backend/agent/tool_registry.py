from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from .permissions import PermissionLevel

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    permission: PermissionLevel = PermissionLevel.LOW
    timeout: float = 30
    def schema(self) -> dict[str, Any]:
        return {"type":"function", "function":{"name":self.name,"description":self.description,"parameters":self.parameters}}

class ToolRegistry:
    def __init__(self): self._tools: dict[str, Tool] = {}
    def register(self, tool: Tool) -> None: self._tools[tool.name] = tool
    def get(self, name: str) -> Tool | None: return self._tools.get(name)
    def schemas(self) -> list[dict[str, Any]]: return [tool.schema() for tool in self._tools.values()]
    def list(self) -> list[dict[str, str]]:
        return [{"name":t.name,"description":t.description,"permission":t.permission} for t in self._tools.values()]
