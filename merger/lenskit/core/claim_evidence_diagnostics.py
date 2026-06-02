from typing import Any, Dict, Optional
from .constants import (
    CLAIM_EVIDENCE_MAP_ABSENCE_REASON_LINK_KEY,
    CLAIM_EVIDENCE_MAP_ABSENCE_REASONS,
    CLAIM_EVIDENCE_MAP_ABSENCE_REASON_MESSAGES,
)

def claim_absence_reason_from_manifest(manifest: Dict[str, Any]) -> Optional[str]:
    links = manifest.get("links")
    if not isinstance(links, dict):
        return None
    raw = links.get(CLAIM_EVIDENCE_MAP_ABSENCE_REASON_LINK_KEY)
    if isinstance(raw, str) and raw in CLAIM_EVIDENCE_MAP_ABSENCE_REASONS:
        return raw
    return None

def claim_absence_reason_detail(reason: Optional[str]) -> str:
    return CLAIM_EVIDENCE_MAP_ABSENCE_REASON_MESSAGES.get(reason, "reason unavailable")
