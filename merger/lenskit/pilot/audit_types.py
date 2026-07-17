"""Shared value types for the isolated audit pilot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class AuditPilotError(RuntimeError):
    """Raised when the pilot cannot proceed within its safety contract."""


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Validated identity and citation registry for one bundle generation."""

    root: Path
    manifest: Path
    manifest_sha256: str
    run_id: str
    reviewed_revision: str
    citation_ids: frozenset[str]


@dataclass(frozen=True)
class CommandResult:
    """Bounded result returned by an injected or real container command runner."""

    returncode: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float
