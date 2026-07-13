"""Validate benchmark runner evidence without trusting the runner."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from merger.lenskit.core.agent_benchmark_common import (
    MAX_JSON_BYTES,
    RECEIPT_KIND,
    VERSION,
    list_value,
    mapping_value,
    sha256_bytes,
    sha256_json,
)


def _validate_identity(
    request: Mapping[str, Any], receipt: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if receipt.get("kind") != RECEIPT_KIND or receipt.get("version") != VERSION:
        errors.append("receipt kind/version mismatch")
    if receipt.get("request_id") != request.get("request_id"):
        errors.append("receipt request_id does not match request")
    if receipt.get("request_sha256") != sha256_json(request):
        errors.append("receipt request_sha256 does not match request")
    return errors


def _validate_provider(
    request: Mapping[str, Any], receipt: Mapping[str, Any]
) -> list[str]:
    expected = mapping_value(request.get("runner"))
    actual = mapping_value(receipt.get("provider"))
    errors: list[str] = []
    if actual.get("name") != expected.get("provider"):
        errors.append("receipt provider does not match request")
    if actual.get("model") != expected.get("model"):
        errors.append("receipt model does not match request")
    if mapping_value(actual.get("sampling")) != mapping_value(expected.get("sampling")):
        errors.append("receipt sampling settings do not match request")
    if actual.get("token_source") != "provider_reported":
        errors.append("receipt tokens are not provider-reported")
    return errors


def _validate_tokens(
    request: Mapping[str, Any], receipt: Mapping[str, Any]
) -> list[str]:
    budgets = mapping_value(request.get("budgets"))
    provider = mapping_value(receipt.get("provider"))
    errors: list[str] = []
    for field in ("input_tokens", "output_tokens"):
        value = provider.get(field)
        if not isinstance(value, int) or value < 0:
            errors.append(f"receipt {field} is invalid")
        elif value > int(budgets.get(field, -1)):
            errors.append(f"receipt exceeds {field} budget")
    return errors


def _validate_duration(
    request: Mapping[str, Any], receipt: Mapping[str, Any]
) -> list[str]:
    duration = receipt.get("duration_ms")
    if not isinstance(duration, int) or duration < 0:
        return ["receipt duration_ms is invalid"]
    wall_seconds = int(mapping_value(request.get("budgets")).get("wall_seconds", 0))
    if duration > wall_seconds * 1000:
        return ["receipt exceeds wall-clock budget"]
    return []


def _call_sizes(call: Mapping[str, Any]) -> tuple[int, int, list[str]]:
    errors: list[str] = []
    input_bytes = call.get("input_bytes")
    output_bytes = call.get("output_bytes")
    if not isinstance(input_bytes, int) or input_bytes < 0:
        errors.append("tool-call input_bytes is invalid")
        input_bytes = 0
    if not isinstance(output_bytes, int) or output_bytes < 0:
        errors.append("tool-call output_bytes is invalid")
        output_bytes = 0
    return input_bytes, output_bytes, errors


def _validate_tool_calls(
    request: Mapping[str, Any], receipt: Mapping[str, Any]
) -> list[str]:
    budgets = mapping_value(request.get("budgets"))
    allowed = set(list_value(request.get("allowed_tools")))
    calls = list_value(receipt.get("tool_calls"))
    errors: list[str] = []
    if len(calls) > int(budgets.get("max_tool_calls", -1)):
        errors.append("receipt exceeds tool-call budget")
    total_input = 0
    total_output = 0
    for expected_sequence, raw_call in enumerate(calls, start=1):
        call = mapping_value(raw_call)
        if call.get("sequence") != expected_sequence:
            errors.append("tool-call sequence is not contiguous")
        if call.get("name") not in allowed:
            errors.append(f"disallowed tool call: {call.get('name')!r}")
        input_bytes, output_bytes, size_errors = _call_sizes(call)
        total_input += input_bytes
        total_output += output_bytes
        errors.extend(size_errors)
    if total_input > int(budgets.get("max_tool_input_bytes", -1)):
        errors.append("receipt exceeds tool-input byte budget")
    if total_output > int(budgets.get("max_tool_output_bytes", -1)):
        errors.append("receipt exceeds tool-output byte budget")
    return errors


def _resolve_artifact(path: str, root: Path) -> Path | None:
    candidate = (root / path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _inline_transcript(transcript: Mapping[str, Any]) -> tuple[bytes | None, list[str]]:
    inline = transcript.get("inline")
    if not isinstance(inline, str) or transcript.get("artifact") is not None:
        return None, ["inline transcript storage is inconsistent"]
    transcript_bytes = inline.encode("utf-8")
    if not transcript_bytes:
        return None, ["transcript must not be empty"]
    if len(transcript_bytes) > MAX_JSON_BYTES:
        return None, ["transcript exceeds configured limit"]
    return transcript_bytes, []


def _artifact_transcript(
    transcript: Mapping[str, Any], transcript_root: str | Path | None
) -> tuple[bytes | None, list[str]]:
    artifact = transcript.get("artifact")
    if not isinstance(artifact, str) or transcript.get("inline") is not None:
        return None, ["artifact transcript storage is inconsistent"]
    if transcript_root is None:
        return None, ["artifact transcript requires transcript_root"]
    resolved = _resolve_artifact(artifact, Path(transcript_root).expanduser())
    if resolved is None or not resolved.is_file():
        return None, ["transcript artifact is missing or outside transcript_root"]
    try:
        with resolved.open("rb") as handle:
            transcript_bytes = handle.read(MAX_JSON_BYTES + 1)
    except OSError:
        return None, ["transcript artifact could not be read"]
    if not transcript_bytes:
        return None, ["transcript must not be empty"]
    if len(transcript_bytes) > MAX_JSON_BYTES:
        return None, ["transcript exceeds configured limit"]
    return transcript_bytes, []


def _validate_transcript(
    receipt: Mapping[str, Any], transcript_root: str | Path | None
) -> list[str]:
    transcript = mapping_value(receipt.get("transcript"))
    storage = transcript.get("storage")
    if storage == "inline":
        content, errors = _inline_transcript(transcript)
    elif storage == "artifact":
        content, errors = _artifact_transcript(transcript, transcript_root)
    else:
        return ["transcript storage is invalid"]
    if content is None:
        return errors
    if transcript.get("bytes") != len(content):
        errors.append("transcript byte count mismatch")
    if transcript.get("sha256") != sha256_bytes(content):
        errors.append("transcript SHA-256 mismatch")
    return errors


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _validate_timestamps(receipt: Mapping[str, Any]) -> list[str]:
    started = _parse_timestamp(receipt.get("started_at"))
    ended = _parse_timestamp(receipt.get("ended_at"))
    errors: list[str] = []
    if started is None:
        errors.append("receipt started_at is not a timezone-aware date-time")
    if ended is None:
        errors.append("receipt ended_at is not a timezone-aware date-time")
    if started is not None and ended is not None and ended < started:
        errors.append("receipt ended_at precedes started_at")
    return errors


def _validate_status(receipt: Mapping[str, Any]) -> list[str]:
    status = receipt.get("status")
    exit_code = receipt.get("exit_code")
    error = receipt.get("error")
    if status not in {"success", "failed", "timeout", "invalid"}:
        return ["receipt status is invalid"]
    if status == "success" and (exit_code != 0 or error is not None):
        return ["successful receipt must have exit_code 0 and no error"]
    if status in {"failed", "timeout", "invalid"} and not isinstance(error, Mapping):
        return ["non-success receipt requires structured error evidence"]
    return []


def validate_receipt(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    transcript_root: str | Path | None = None,
) -> list[str]:
    """Validate identity, budget, tool policy and transcript evidence."""

    errors = _validate_identity(request, receipt)
    errors.extend(_validate_provider(request, receipt))
    errors.extend(_validate_tokens(request, receipt))
    errors.extend(_validate_timestamps(receipt))
    errors.extend(_validate_duration(request, receipt))
    errors.extend(_validate_tool_calls(request, receipt))
    errors.extend(_validate_transcript(receipt, transcript_root))
    errors.extend(_validate_status(receipt))
    return errors


__all__ = ["validate_receipt"]
