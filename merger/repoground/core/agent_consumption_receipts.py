"""Trusted tool-read receipts for agent-consumption evidence.

This module mints and validates data-sparing observation receipts that bind one
access event to exactly:

* a task identity
* a repository commit
* an artifact role
* an immutable artifact identity (path + sha256 + byte count)

Receipts never store artifact content. Answer text, free-form self-declarations
and untrusted issuers cannot mint observed evidence. A valid receipt is only a
binding record: it does not establish semantic reading, relevance, correctness
or truth.

Retention / redaction / deletion (documented contract):

* policy: ``ephemeral_comparison_input`` — operator-controlled retention only
* content_retained: always false
* redaction: metadata_only (role, path, digests, sizes, binding ids)
* deletion: safe_at_any_time — absence becomes missing/unavailable evidence
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

KIND = "lenskit.agent_tool_read_receipt"
VERSION = "1.0"

TRUSTED_WRAPPER_ISSUER_ID = "repoground.agent_consumption.tool_read_wrapper"
TRUSTED_GATEWAY_ISSUER_ID = "repoground.agent_consumption.tool_gateway"

TRUSTED_ISSUERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("trusted_wrapper", TRUSTED_WRAPPER_ISSUER_ID),
        ("tool_gateway", TRUSTED_GATEWAY_ISSUER_ID),
    }
)

DOES_NOT_ESTABLISH: tuple[str, ...] = (
    "semantic_reading",
    "relevance_to_answer",
    "answer_correct",
    "claims_true",
    "repo_understood",
    "all_relevant_context_used",
    "runtime_interception",
    "mandatory_wrapper_adoption",
)

RETENTION: dict[str, Any] = {
    "policy": "ephemeral_comparison_input",
    "content_retained": False,
    "redaction": "metadata_only",
    "deletion": "safe_at_any_time",
}

MAX_TASK_ID_LEN = 128
MAX_ROLE_LEN = 128
MAX_PATH_LEN = 512
MAX_EVENT_ID_LEN = 128
MAX_ISSUER_ID_LEN = 128
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_RECEIPT_JSON_BYTES = 8 * 1024

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_ISSUER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._@+/-]+$")
_OBSERVED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$"
)

# Fail-closed content / secret surface. Presence of these keys rejects minting
# and validation: receipts are metadata-only.
_FORBIDDEN_KEYS = frozenset(
    {
        "content",
        "body",
        "text",
        "raw",
        "source_text",
        "source_content",
        "payload",
        "blob",
        "data",
        "file_bytes",
        "bytes_content",
        "secret",
        "secrets",
        "token",
        "password",
        "api_key",
        "private_key",
        "authorization",
    }
)

_SECRET_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH) )?PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S{6,}"),
)


class ToolReadReceiptError(ValueError):
    """Receipt minting or validation failed closed."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _reject_forbidden_keys(mapping: Mapping[str, Any], *, label: str) -> None:
    bad = sorted(k for k in mapping if k in _FORBIDDEN_KEYS or not isinstance(k, str))
    if bad:
        raise ToolReadReceiptError(
            f"{label} contains forbidden or non-string keys: {', '.join(map(str, bad))}"
        )
    for key, value in mapping.items():
        if isinstance(value, Mapping):
            _reject_forbidden_keys(value, label=f"{label}.{key}")


def _reject_secrets(text: str, *, label: str) -> None:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise ToolReadReceiptError(
                f"{label} fails closed: secret-like material is not allowed in receipts"
            )


def _require_str(
    value: Any,
    *,
    label: str,
    pattern: re.Pattern[str],
    max_len: int,
    min_len: int = 1,
) -> str:
    if not isinstance(value, str):
        raise ToolReadReceiptError(f"{label} must be a string")
    if len(value) < min_len or len(value) > max_len:
        raise ToolReadReceiptError(f"{label} length out of bounds")
    if pattern.fullmatch(value) is None:
        raise ToolReadReceiptError(f"{label} has an invalid shape")
    _reject_secrets(value, label=label)
    return value


def _normalize_identity(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ToolReadReceiptError("artifact_identity must be an object")
    _reject_forbidden_keys(raw, label="artifact_identity")
    path = _require_str(
        raw.get("path"), label="artifact_identity.path", pattern=_PATH_RE, max_len=MAX_PATH_LEN
    )
    digest = raw.get("sha256")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ToolReadReceiptError("artifact_identity.sha256 must be a lowercase hex SHA-256")
    size = raw.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_ARTIFACT_BYTES:
        raise ToolReadReceiptError("artifact_identity.bytes is out of bounds")
    identity = {"path": path, "sha256": digest, "bytes": size}
    if set(raw) - {"path", "sha256", "bytes"}:
        raise ToolReadReceiptError("artifact_identity has unexpected fields")
    return identity


def _normalize_issuer(raw: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ToolReadReceiptError("issuer must be an object")
    _reject_forbidden_keys(raw, label="issuer")
    kind = raw.get("kind")
    issuer_id = raw.get("id")
    if kind not in ("trusted_wrapper", "tool_gateway"):
        raise ToolReadReceiptError("issuer.kind must be trusted_wrapper or tool_gateway")
    issuer_id = _require_str(
        issuer_id,
        label="issuer.id",
        pattern=_ISSUER_ID_RE,
        max_len=MAX_ISSUER_ID_LEN,
    )
    if (kind, issuer_id) not in TRUSTED_ISSUERS:
        raise ToolReadReceiptError(
            f"issuer ({kind!r}, {issuer_id!r}) is not an allowlisted trusted source"
        )
    if set(raw) - {"kind", "id"}:
        raise ToolReadReceiptError("issuer has unexpected fields")
    return {"kind": kind, "id": issuer_id}


def binding_material(
    *,
    task_id: str,
    repo_commit: str,
    artifact_role: str,
    artifact_identity: Mapping[str, Any],
    access_event_id: str,
    issuer: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "access_event_id": access_event_id,
        "artifact_identity": {
            "bytes": artifact_identity["bytes"],
            "path": artifact_identity["path"],
            "sha256": artifact_identity["sha256"],
        },
        "artifact_role": artifact_role,
        "issuer": {"id": issuer["id"], "kind": issuer["kind"]},
        "kind": KIND,
        "repo_commit": repo_commit,
        "task_id": task_id,
        "version": VERSION,
    }


def compute_binding_sha256(
    *,
    task_id: str,
    repo_commit: str,
    artifact_role: str,
    artifact_identity: Mapping[str, Any],
    access_event_id: str,
    issuer: Mapping[str, str],
) -> str:
    return sha256_json(
        binding_material(
            task_id=task_id,
            repo_commit=repo_commit,
            artifact_role=artifact_role,
            artifact_identity=artifact_identity,
            access_event_id=access_event_id,
            issuer=issuer,
        )
    )


def _bounded_receipt_size(receipt: Mapping[str, Any]) -> None:
    encoded = canonical_json(receipt).encode("utf-8")
    if len(encoded) > MAX_RECEIPT_JSON_BYTES:
        raise ToolReadReceiptError(
            f"receipt exceeds {MAX_RECEIPT_JSON_BYTES} bytes after deterministic serialization"
        )


def mint_tool_read_receipt(
    *,
    task_id: str,
    repo_commit: str,
    artifact_role: str,
    artifact_identity: Mapping[str, Any],
    access_event_id: str,
    issuer: Mapping[str, str] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Mint one trusted receipt. Content is never accepted or stored."""
    task = _require_str(
        task_id, label="task_id", pattern=_TASK_ID_RE, max_len=MAX_TASK_ID_LEN
    )
    commit = _require_str(
        repo_commit, label="repo_commit", pattern=_COMMIT_RE, max_len=40, min_len=40
    )
    role = _require_str(
        artifact_role, label="artifact_role", pattern=_ROLE_RE, max_len=MAX_ROLE_LEN
    )
    event_id = _require_str(
        access_event_id,
        label="access_event_id",
        pattern=_EVENT_ID_RE,
        max_len=MAX_EVENT_ID_LEN,
        min_len=8,
    )
    identity = _normalize_identity(artifact_identity)
    issuer_obj = _normalize_issuer(
        issuer
        if issuer is not None
        else {"kind": "trusted_wrapper", "id": TRUSTED_WRAPPER_ISSUER_ID}
    )
    observed = observed_at if observed_at is not None else utc_now_iso()
    if not isinstance(observed, str) or _OBSERVED_AT_RE.fullmatch(observed) is None:
        raise ToolReadReceiptError("observed_at must be an ISO-8601 UTC timestamp ending with Z")

    binding = compute_binding_sha256(
        task_id=task,
        repo_commit=commit,
        artifact_role=role,
        artifact_identity=identity,
        access_event_id=event_id,
        issuer=issuer_obj,
    )
    receipt: dict[str, Any] = {
        "kind": KIND,
        "version": VERSION,
        "task_id": task,
        "repo_commit": commit,
        "artifact_role": role,
        "artifact_identity": identity,
        "access_event_id": event_id,
        "observed_at": observed,
        "issuer": issuer_obj,
        "binding_sha256": binding,
        "retention": dict(RETENTION),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    receipt["receipt_sha256"] = sha256_json(receipt)
    _bounded_receipt_size(receipt)
    return receipt


def validate_tool_read_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a receipt fail-closed and return a normalized copy."""
    if not isinstance(receipt, Mapping):
        raise ToolReadReceiptError("receipt must be an object")
    _reject_forbidden_keys(receipt, label="receipt")
    if receipt.get("kind") != KIND or receipt.get("version") != VERSION:
        raise ToolReadReceiptError("receipt kind/version mismatch")

    required = {
        "kind",
        "version",
        "task_id",
        "repo_commit",
        "artifact_role",
        "artifact_identity",
        "access_event_id",
        "observed_at",
        "issuer",
        "binding_sha256",
        "receipt_sha256",
        "retention",
        "does_not_establish",
    }
    extra = set(receipt) - required
    if extra:
        raise ToolReadReceiptError(
            f"receipt has unexpected fields: {', '.join(sorted(extra))}"
        )
    missing = required - set(receipt)
    if missing:
        raise ToolReadReceiptError(
            f"receipt missing fields: {', '.join(sorted(missing))}"
        )

    task = _require_str(
        receipt["task_id"], label="task_id", pattern=_TASK_ID_RE, max_len=MAX_TASK_ID_LEN
    )
    commit = _require_str(
        receipt["repo_commit"],
        label="repo_commit",
        pattern=_COMMIT_RE,
        max_len=40,
        min_len=40,
    )
    role = _require_str(
        receipt["artifact_role"],
        label="artifact_role",
        pattern=_ROLE_RE,
        max_len=MAX_ROLE_LEN,
    )
    event_id = _require_str(
        receipt["access_event_id"],
        label="access_event_id",
        pattern=_EVENT_ID_RE,
        max_len=MAX_EVENT_ID_LEN,
        min_len=8,
    )
    identity = _normalize_identity(receipt.get("artifact_identity"))
    issuer = _normalize_issuer(receipt.get("issuer"))
    observed = receipt.get("observed_at")
    if not isinstance(observed, str) or _OBSERVED_AT_RE.fullmatch(observed) is None:
        raise ToolReadReceiptError("observed_at must be an ISO-8601 UTC timestamp ending with Z")

    expected_binding = compute_binding_sha256(
        task_id=task,
        repo_commit=commit,
        artifact_role=role,
        artifact_identity=identity,
        access_event_id=event_id,
        issuer=issuer,
    )
    if receipt.get("binding_sha256") != expected_binding:
        raise ToolReadReceiptError("binding_sha256 does not match deterministic binding")

    retention = receipt.get("retention")
    if not isinstance(retention, Mapping) or dict(retention) != RETENTION:
        raise ToolReadReceiptError("retention policy is incomplete or altered")

    dne = receipt.get("does_not_establish")
    if not isinstance(dne, list) or set(dne) != set(DOES_NOT_ESTABLISH) or len(dne) != len(
        DOES_NOT_ESTABLISH
    ):
        raise ToolReadReceiptError("does_not_establish must match the fixed receipt boundary")

    without_digest = {
        "kind": KIND,
        "version": VERSION,
        "task_id": task,
        "repo_commit": commit,
        "artifact_role": role,
        "artifact_identity": identity,
        "access_event_id": event_id,
        "observed_at": observed,
        "issuer": issuer,
        "binding_sha256": expected_binding,
        "retention": dict(RETENTION),
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }
    expected_receipt_sha = sha256_json(without_digest)
    if receipt.get("receipt_sha256") != expected_receipt_sha:
        raise ToolReadReceiptError("receipt_sha256 does not match deterministic serialization")

    normalized = {**without_digest, "receipt_sha256": expected_receipt_sha}
    _bounded_receipt_size(normalized)
    return normalized


def identity_from_bytes(*, path: str, content: bytes) -> dict[str, Any]:
    """Derive identity metadata from bytes without retaining the content."""
    if not isinstance(content, (bytes, bytearray)):
        raise ToolReadReceiptError("content must be bytes for hashing only")
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ToolReadReceiptError("content exceeds maximum artifact size for hashing")
    return {
        "path": path,
        "sha256": sha256_bytes(bytes(content)),
        "bytes": len(content),
    }


class TrustedToolReadWrapper:
    """Allowlisted mint path for observed tool-read receipts.

    Callers pass path and content solely so the wrapper can hash identity
    metadata. Content is never stored on the receipt. Answer text and self-
    declarations have no mint path on this class.
    """

    issuer_kind = "trusted_wrapper"
    issuer_id = TRUSTED_WRAPPER_ISSUER_ID

    def observe_artifact_access(
        self,
        *,
        task_id: str,
        repo_commit: str,
        artifact_role: str,
        path: str,
        content: bytes,
        access_event_id: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        identity = identity_from_bytes(path=path, content=content)
        # Explicitly drop any reference to content after hashing.
        del content
        return mint_tool_read_receipt(
            task_id=task_id,
            repo_commit=repo_commit,
            artifact_role=artifact_role,
            artifact_identity=identity,
            access_event_id=access_event_id,
            issuer={"kind": self.issuer_kind, "id": self.issuer_id},
            observed_at=observed_at,
        )
