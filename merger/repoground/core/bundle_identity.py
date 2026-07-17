"""Versioned RepoGround bundle-manifest identity handling."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

CANONICAL_BUNDLE_KIND = "repoground.bundle.manifest"
CANONICAL_BUNDLE_VERSION = "2.0"
LEGACY_BUNDLE_KIND = "repolens.bundle.manifest"
LEGACY_BUNDLE_VERSION = "1.0"


def bundle_identity(document: Mapping[str, Any]) -> str | None:
    """Return ``canonical`` or ``legacy`` for an exact, non-contradictory identity.

    Canonical RepoGround manifests must always declare version ``2.0``. The
    legacy kind may omit ``version`` because bounded 2.x readers and fixtures
    historically accepted that shape; a present legacy version must still be
    exactly ``1.0``.
    """
    kind = document.get("kind")
    version = document.get("version")
    if kind == CANONICAL_BUNDLE_KIND and version == CANONICAL_BUNDLE_VERSION:
        return "canonical"
    if kind == LEGACY_BUNDLE_KIND and version in {None, LEGACY_BUNDLE_VERSION}:
        return "legacy"
    return None


def is_bundle_manifest(document: object) -> bool:
    return isinstance(document, Mapping) and bundle_identity(document) is not None


def bundle_schema_path(document: Mapping[str, Any]) -> Path:
    identity = bundle_identity(document)
    if identity is None:
        raise ValueError("unsupported or contradictory bundle manifest identity")
    filename = "bundle-manifest.v2.schema.json" if identity == "canonical" else "bundle-manifest.v1.schema.json"
    return Path(__file__).resolve().parent.parent / "contracts" / filename
