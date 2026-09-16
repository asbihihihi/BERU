from enum import StrEnum

class PermissionLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class PermissionManager:
    def requires_confirmation(self, level: PermissionLevel) -> bool:
        return level == PermissionLevel.HIGH
