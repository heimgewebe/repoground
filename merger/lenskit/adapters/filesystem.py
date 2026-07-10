from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from fastapi import HTTPException
from dataclasses import dataclass
import os

from .security import (
    AccessDeniedError,
    SecurityViolationError,
    get_security_config,
)

@dataclass(frozen=True)
class TrustedPath:
    path: Path

def list_allowed_roots(hub: Optional[Path], merges_dir: Optional[Path]) -> List[Dict[str, Any]]:
    sec = get_security_config()
    roots: List[Dict[str, Any]] = []
    if hub:
        roots.append({"id": "hub", "path": str(hub.resolve())})
    if merges_dir:
        roots.append({"id": "merges", "path": str(merges_dir.resolve())})
    if sec.sensitive_fs_access:
        try:
            # The "system" preset maps to the service user's home directory.
            # It is present only when init_service granted sensitive filesystem
            # access (loopback + bearer auth). Validation failures omit only
            # this optional root; ordinary Hub/Merges roots remain available.
            sys_root = Path.home().resolve()
            sec.validate_path(sys_root)
            roots.append({"id": "system", "path": str(sys_root)})
        except (SecurityViolationError, OSError, RuntimeError):
            # `system` is optional; its failure must not hide explicit Hub/Merges roots.
            pass
    return roots

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))

def _token_secret() -> bytes:
    s = os.getenv("RLENS_FS_TOKEN_SECRET") or os.getenv("RLENS_TOKEN") or ""
    if not s:
        raise HTTPException(status_code=500, detail="FS token secret not configured")
    return s.encode("utf-8")

def issue_fs_token(abs_path: Path, ttl_seconds: int = 1200) -> str:
    payload = {
        "p": str(abs_path),
        "exp": int(time.time()) + int(ttl_seconds),
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_token_secret(), body, hashlib.sha256).digest()
    return f"{_b64url(body)}.{_b64url(sig)}"

def _parse_fs_token(token: str) -> Tuple[Path, int]:
    try:
        body_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token")

    body = _b64url_decode(body_b64)
    sig = _b64url_decode(sig_b64)
    expected = hmac.new(_token_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=403, detail="Invalid token signature")

    try:
        payload = json.loads(body.decode("utf-8"))
        raw_p = payload.get("p")
        exp = int(payload["exp"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    if not isinstance(raw_p, str) or not raw_p.strip():
        raise HTTPException(status_code=400, detail="Invalid token path")
    if len(raw_p) > 4096:
        raise HTTPException(status_code=400, detail="Invalid token path length")
    if "\x00" in raw_p:
        raise HTTPException(status_code=400, detail="Invalid token path")

    if int(time.time()) > exp:
        raise HTTPException(status_code=403, detail="Token expired")

    sec = get_security_config()
    p = Path(raw_p)
    resolved = sec.validate_path(p)
    return resolved, exp

def resolve_fs_token(token: str) -> Path:
    p, _exp = _parse_fs_token(token)
    return p

def resolve_fs_path(hub: Optional[Path], merges_dir: Optional[Path], root_id: Optional[str] = None, rel_path: Optional[str] = None, token: Optional[str] = None) -> TrustedPath:
    if token is not None:
        return TrustedPath(resolve_fs_token(token))

    if root_id is not None:
        root_map: Dict[str, Optional[Path]] = {
            "hub": hub,
            "merges": merges_dir,
            "system": Path.home().resolve(),
        }
        base = root_map.get(root_id)
        if base is None:
            raise HTTPException(status_code=400, detail="Unknown root id")

        sec = get_security_config()
        if root_id == "system" and not sec.sensitive_fs_access:
            raise AccessDeniedError("System root requires loopback plus bearer authentication")
        # validate base
        base_resolved = sec.validate_path(base.resolve())

        rel = (rel_path or "").strip()
        if rel in ("", ".", "/"):
            return TrustedPath(base_resolved)

        raise HTTPException(status_code=400, detail="Use token navigation for subpaths")

    raise HTTPException(status_code=400, detail="Invalid fs request")
