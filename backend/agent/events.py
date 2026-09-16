from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

@dataclass
class Event:
    type: str
    data: dict[str, Any]
    def payload(self) -> dict[str, Any]:
        return {"type": self.type, "timestamp": datetime.now(timezone.utc).isoformat(), **self.data}
