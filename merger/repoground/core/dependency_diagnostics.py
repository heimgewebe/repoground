from __future__ import annotations

from typing import Any

JSONSCHEMA_EFFECT_AVAILABLE = "full_validation_available"
JSONSCHEMA_EFFECT_DEGRADED = "validation_degraded"

def jsonschema_dependency(
    *,
    available: bool,
    required_for: list[str],
) -> dict[str, Any]:
    return {
        "jsonschema": {
            "available": available,
            "required_for": required_for,
            "effect": (
                JSONSCHEMA_EFFECT_AVAILABLE
                if available
                else JSONSCHEMA_EFFECT_DEGRADED
            ),
        }
    }
