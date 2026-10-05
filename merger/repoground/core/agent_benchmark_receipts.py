"""Validate benchmark runner evidence without trusting the runner."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from merger.repoground.core.agent_benchmark_common import (
    AgentBenchmarkError,
    MAX_JSON_BYTES,
    RECEIPT_KIND,
    VERSION,
    list_value,
    mapping_value,
    sha256_bytes,
    sha256_json,
)
from merger.repoground.core.agent_benchmark_components import _load_bound_manifest


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


_REPOGROUND_MCP_EVIDENCE_TOOLS = {"ask_context", "grounding_verify", "live_freshness"}
_REPOGROUND_EVIDENCE_TOOLS = _REPOGROUND_MCP_EVIDENCE_TOOLS | {
    "repobrief_resource_read"
}
_FRESHNESS_STATUSES = {"fresh", "stale", "unknown", "not_comparable", "not_applicable"}
_GROUNDING_STATUSES = {"pass", "fail", "warn", "degraded", "not_applicable"}
_REPOGROUND_CALL_FIELDS = {
    "sequence",
    "tool",
    "freshness_status",
    "resolved_range_count",
    "context_bytes_used",
    "grounding_status",
}

_LIVE_RUNNER_CONTRACTS = {
    "grabowski-claude-code-live-v1": "claude",
    "grabowski-codex-cli-live-v1": "codex",
}
_REPOGROUND_MCP_SERVER_ALIASES = {"repobrief", "repoground"}
_CLAUDE_REPOGROUND_TOOLS = {
    f"mcp__{server}__{tool}": tool
    for server in _REPOGROUND_MCP_SERVER_ALIASES
    for tool in _REPOGROUND_MCP_EVIDENCE_TOOLS
}
_CLAUDE_RESOURCE_READ_TOOLS = {"ReadMcpResource", "ReadMcpResourceTool"}


def _is_commit(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(char in "0123456789abcdef" for char in value)
    )


def _jsonl_objects(content: bytes) -> tuple[list[Mapping[str, Any]] | None, list[str]]:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, ["receipt transcript is not UTF-8 JSONL"]
    objects: list[Mapping[str, Any]] = []
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return None, ["receipt transcript is not valid JSONL"]
        if not isinstance(value, Mapping):
            return None, ["receipt transcript JSONL entry must be an object"]
        objects.append(value)
    if not objects:
        return None, ["receipt transcript JSONL is empty"]
    return objects, []


def _json_mapping(value: Any) -> Mapping[str, Any] | None:
    decoded = value
    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except json.JSONDecodeError:
            return None
    return decoded if isinstance(decoded, Mapping) else None


def _structured_payload(value: Any) -> Mapping[str, Any] | None:
    decoded = _json_mapping(value)
    if decoded is None:
        return None
    nested = decoded.get("structuredContent")
    if not isinstance(nested, Mapping):
        nested = decoded.get("structured_content")
    if isinstance(nested, Mapping):
        return nested
    result = decoded.get("result")
    if isinstance(result, Mapping):
        nested = result.get("structuredContent")
        if not isinstance(nested, Mapping):
            nested = result.get("structured_content")
        if isinstance(nested, Mapping):
            return nested
    if decoded.get("kind") in {
        "repobrief.mcp.read_only_frontdoor",
        "repobrief.live_freshness",
    }:
        return decoded
    return None


def _decoded_repoground_payload(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    content = value.get("content")
    if isinstance(content, list):
        candidates = list(content)
    elif isinstance(content, (str, Mapping)):
        candidates = [content]
    else:
        return None
    for candidate in candidates:
        payload_source = (
            candidate.get("text")
            if isinstance(candidate, Mapping) and isinstance(candidate.get("text"), str)
            else candidate
        )
        payload = _structured_payload(payload_source)
        if payload is not None:
            return payload
    return None


def _decoded_resource_read_result(
    value: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    if "contents" in value and "_meta" in value:
        return value
    content = value.get("content")
    if isinstance(content, list):
        candidates = list(content)
    elif isinstance(content, (str, Mapping)):
        candidates = [content]
    else:
        return None
    for candidate in candidates:
        payload_source = (
            candidate.get("text")
            if isinstance(candidate, Mapping)
            and isinstance(candidate.get("text"), str)
            else candidate
        )
        decoded = _json_mapping(payload_source)
        if (
            isinstance(decoded, Mapping)
            and "contents" in decoded
            and "_meta" in decoded
        ):
            return decoded
    return None


def _live_snapshot_commit(
    freshness: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
) -> str | None:
    if (
        freshness.get("kind") != "repobrief.live_freshness"
        or freshness.get("version") != "v1"
        or freshness.get("status") not in _FRESHNESS_STATUSES
        or not isinstance(expected_manifest_path, str)
        or freshness.get("bundle_manifest") != expected_manifest_path
    ):
        return None
    snapshot = freshness.get("snapshot_provenance")
    if isinstance(snapshot, Mapping):
        commit = snapshot.get("git_commit")
        if _is_commit(commit) and commit == fallback_commit:
            return str(commit)
        return None
    if (
        freshness.get("status") == "not_comparable"
        and freshness.get("reason") == "repo_root_not_configured"
        and freshness.get("repo_root") is None
        and freshness.get("read_only_git_probe") is False
        and freshness.get("implicit_refresh") is False
        and snapshot is None
        and _is_commit(fallback_commit)
    ):
        return str(fallback_commit)
    if (
        freshness.get("status") == "unknown"
        and isinstance(freshness.get("reason"), str)
        and bool(freshness.get("reason"))
        and isinstance(freshness.get("repo_root"), str)
        and bool(freshness.get("repo_root"))
        and freshness.get("read_only_git_probe") is True
        and freshness.get("implicit_refresh") is False
        and snapshot is None
        and _is_commit(fallback_commit)
    ):
        return str(fallback_commit)
    return None


def _live_freshness_evidence(
    sequence: int,
    payload: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
) -> tuple[str, dict[str, Any]] | None:
    commit = _live_snapshot_commit(
        payload,
        fallback_commit=fallback_commit,
        expected_manifest_path=expected_manifest_path,
    )
    if commit is None:
        return None
    return commit, {
        "sequence": sequence,
        "tool": "live_freshness",
        "freshness_status": payload.get("status"),
        "resolved_range_count": None,
        "context_bytes_used": None,
        "grounding_status": None,
    }


def _frontdoor_header_matches(tool: str, payload: Mapping[str, Any]) -> bool:
    return bool(
        payload.get("kind") == "repobrief.mcp.read_only_frontdoor"
        and payload.get("version") == "v1"
        and payload.get("tool") == tool
    )


def _frontdoor_live_freshness_commit(
    payload: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
) -> str | None:
    freshness = payload.get("live_freshness")
    if not isinstance(freshness, Mapping):
        return None
    return _live_snapshot_commit(
        freshness,
        fallback_commit=fallback_commit,
        expected_manifest_path=expected_manifest_path,
    )


def _ask_context_binding(
    pack: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[Mapping[str, Any], str] | None:
    freshness = pack.get("freshness")
    snapshot_ref = pack.get("snapshot_ref")
    if not isinstance(freshness, Mapping) or not isinstance(snapshot_ref, Mapping):
        return None
    status = freshness.get("status")
    if (
        status not in _FRESHNESS_STATUSES
        or snapshot_ref.get("freshness_status") != status
        or not isinstance(expected_manifest_sha256, str)
        or snapshot_ref.get("manifest_sha256") != expected_manifest_sha256
    ):
        return None
    commit = snapshot_ref.get("git_commit")
    if _is_commit(commit):
        return freshness, str(commit)
    if commit is None and _is_commit(fallback_commit):
        return freshness, str(fallback_commit)
    return None


def _ask_context_evidence(
    sequence: int,
    payload: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[str, dict[str, Any]] | None:
    if not _frontdoor_header_matches("ask_context", payload):
        return None
    live_freshness = payload.get("live_freshness")
    live_commit = _frontdoor_live_freshness_commit(
        payload,
        fallback_commit=fallback_commit,
        expected_manifest_path=expected_manifest_path,
    )
    if (
        payload.get("status") != "ok"
        or not isinstance(live_freshness, Mapping)
        or live_commit is None
    ):
        return None
    pack = payload.get("context_pack")
    if (
        not isinstance(pack, Mapping)
        or pack.get("kind") != "repobrief.ask_context_pack"
        or pack.get("version") != "1.0"
    ):
        return None
    bound = _ask_context_binding(
        pack,
        fallback_commit=fallback_commit,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if bound is None:
        return None
    _pack_freshness, commit = bound
    if commit != live_commit:
        return None
    ranges = pack.get("resolved_ranges")
    budget = pack.get("budget")
    context_bytes = budget.get("context_bytes_used") if isinstance(budget, Mapping) else None
    if (
        not isinstance(ranges, list)
        or isinstance(context_bytes, bool)
        or not isinstance(context_bytes, int)
        or context_bytes < 0
    ):
        return None
    resolved_range_count = sum(
        1
        for item in ranges
        if isinstance(item, Mapping) and item.get("status") == "resolved"
    )
    return commit, {
        "sequence": sequence,
        "tool": "ask_context",
        "freshness_status": live_freshness.get("status"),
        "resolved_range_count": resolved_range_count,
        "context_bytes_used": context_bytes,
        "grounding_status": None,
    }


def _grounding_snapshot_commit(
    snapshot_ref: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_sha256: str | None,
) -> str | None:
    observed_manifest_sha256 = snapshot_ref.get("manifest_sha256")
    if (
        observed_manifest_sha256 is not None
        and observed_manifest_sha256 != expected_manifest_sha256
    ):
        return None
    raw_commit = snapshot_ref.get("git_commit")
    if _is_commit(raw_commit):
        return str(raw_commit) if raw_commit == fallback_commit else None
    if raw_commit is None and _is_commit(fallback_commit):
        return str(fallback_commit)
    return None


def _grounding_evidence(
    sequence: int,
    payload: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[str, dict[str, Any]] | None:
    if not _frontdoor_header_matches("grounding_verify", payload):
        return None
    if (
        _frontdoor_live_freshness_commit(
            payload,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
        )
        is None
    ):
        return None
    verdict = payload.get("verdict")
    if (
        not isinstance(verdict, Mapping)
        or verdict.get("kind") != "repobrief.answer_grounding_verdict"
        or verdict.get("version") != "1.0"
        or verdict.get("status") not in _GROUNDING_STATUSES
        or payload.get("status") != verdict.get("status")
    ):
        return None
    snapshot_ref = verdict.get("snapshot_ref")
    if not isinstance(snapshot_ref, Mapping):
        return None
    commit = _grounding_snapshot_commit(
        snapshot_ref,
        fallback_commit=fallback_commit,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if commit is None:
        return None
    raw_freshness = snapshot_ref.get("freshness_status")
    if raw_freshness is None:
        freshness_status = "not_applicable"
    elif raw_freshness in _FRESHNESS_STATUSES:
        freshness_status = str(raw_freshness)
    else:
        return None
    return commit, {
        "sequence": sequence,
        "tool": "grounding_verify",
        "freshness_status": freshness_status,
        "resolved_range_count": None,
        "context_bytes_used": None,
        "grounding_status": verdict.get("status"),
    }


def _resource_read_evidence(
    sequence: int,
    result: Mapping[str, Any],
    *,
    expected_uri: str | None,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
) -> tuple[str, dict[str, Any]] | None:
    decoded = _decoded_resource_read_result(result)
    if decoded is None:
        return None
    contents = decoded.get("contents")
    meta = decoded.get("_meta")
    if (
        not isinstance(expected_uri, str)
        or not expected_uri
        or not isinstance(contents, list)
        or len(contents) != 1
        or not isinstance(contents[0], Mapping)
        or contents[0].get("uri") != expected_uri
        or not isinstance(meta, Mapping)
    ):
        return None
    item = contents[0]
    text = item.get("text")
    mime_type = item.get("mimeType")
    repoground = meta.get("repoground")
    if (
        not isinstance(text, str)
        or not text
        or not isinstance(mime_type, str)
        or not mime_type
        or not isinstance(repoground, Mapping)
        or repoground.get("status") != "available"
        or repoground.get("implicitRefresh") is not False
        or not isinstance(repoground.get("snapshotContext"), Mapping)
        or not isinstance(repoground.get("identity"), Mapping)
    ):
        return None
    freshness = repoground.get("liveFreshness")
    if not isinstance(freshness, Mapping):
        return None
    commit = _live_snapshot_commit(
        freshness,
        fallback_commit=fallback_commit,
        expected_manifest_path=expected_manifest_path,
    )
    if commit is None:
        return None
    content_bytes = len(text.encode("utf-8"))
    if content_bytes <= 0:
        return None
    return commit, {
        "sequence": sequence,
        "tool": "repobrief_resource_read",
        "freshness_status": freshness.get("status"),
        "resolved_range_count": None,
        "context_bytes_used": content_bytes,
        "grounding_status": None,
    }


def _evidence_call_from_payload(
    tool: str,
    sequence: int,
    payload: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[str, dict[str, Any]] | None:
    if tool == "live_freshness":
        return _live_freshness_evidence(
            sequence,
            payload,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
        )
    if tool == "ask_context":
        return _ask_context_evidence(
            sequence,
            payload,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    if tool == "grounding_verify":
        return _grounding_evidence(
            sequence,
            payload,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    return None


def _evidence_document(
    request: Mapping[str, Any],
    calls: list[dict[str, Any]],
    commits: set[str],
) -> dict[str, Any] | None:
    if not calls or len(commits) != 1:
        return None
    return {
        "target_commit": str(mapping_value(request.get("repository")).get("commit", "")),
        "bundle_commit": next(iter(commits)),
        "calls": calls,
    }


def _claude_tool_blocks(
    events: list[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    uses: list[Mapping[str, Any]] = []
    results: dict[str, Mapping[str, Any]] = {}
    for event in events:
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(blocks, list):
            continue
        for raw in blocks:
            if not isinstance(raw, Mapping):
                continue
            if raw.get("type") == "tool_use" and raw.get("name") != "StructuredOutput":
                uses.append(raw)
            elif raw.get("type") == "tool_result" and isinstance(
                raw.get("tool_use_id"), str
            ):
                results[str(raw["tool_use_id"])] = raw
    return uses, results


def _claude_transcript_evidence(
    request: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    uses, results = _claude_tool_blocks(events)
    evidence_calls: list[dict[str, Any]] = []
    commits: set[str] = set()
    errors: list[str] = []
    for sequence, use in enumerate(uses, start=1):
        concrete = str(use.get("name", ""))
        tool = _CLAUDE_REPOGROUND_TOOLS.get(concrete)
        is_resource_read = concrete in _CLAUDE_RESOURCE_READ_TOOLS
        if tool is None and not is_resource_read:
            continue
        identifier = use.get("id")
        result = results.get(str(identifier)) if isinstance(identifier, str) else None
        if not isinstance(result, Mapping) or result.get("is_error") is True:
            continue
        normalized_tool = "repobrief_resource_read" if is_resource_read else str(tool)
        if is_resource_read:
            arguments = use.get("input")
            expected_uri = (
                arguments.get("uri") if isinstance(arguments, Mapping) else None
            )
            normalized = _resource_read_evidence(
                sequence,
                result,
                expected_uri=expected_uri,
                fallback_commit=fallback_commit,
                expected_manifest_path=expected_manifest_path,
            )
        else:
            payload = _decoded_repoground_payload(result)
            normalized = (
                _evidence_call_from_payload(
                    str(tool),
                    sequence,
                    payload,
                    fallback_commit=fallback_commit,
                    expected_manifest_path=expected_manifest_path,
                    expected_manifest_sha256=expected_manifest_sha256,
                )
                if isinstance(payload, Mapping)
                else None
            )
        if normalized is None:
            errors.append(
                "bound transcript successful RepoGround call could not be normalized: "
                f"sequence {sequence} ({normalized_tool})"
            )
            continue
        commit, call = normalized
        commits.add(commit)
        evidence_calls.append(call)
    return _evidence_document(request, evidence_calls, commits), errors


def _codex_resource_read_evidence(
    item: Mapping[str, Any],
    sequence: int,
    result: Mapping[str, Any],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
) -> tuple[str, dict[str, Any]] | None:
    arguments = item.get("arguments")
    if (
        not isinstance(arguments, Mapping)
        or arguments.get("action") != "read"
    ):
        return None
    return _resource_read_evidence(
        sequence,
        result,
        expected_uri=arguments.get("uri"),
        fallback_commit=fallback_commit,
        expected_manifest_path=expected_manifest_path,
    )


def _codex_item_evidence(
    item: Mapping[str, Any],
    sequence: int,
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[str, dict[str, Any]] | None:
    tool = item.get("tool")
    if (
        item.get("type") != "mcp_tool_call"
        or item.get("server") not in _REPOGROUND_MCP_SERVER_ALIASES
        or tool not in _REPOGROUND_EVIDENCE_TOOLS
        or item.get("status") != "completed"
        or item.get("error") is not None
    ):
        return None
    result = item.get("result")
    if not isinstance(result, Mapping):
        return None
    if tool == "repobrief_resource_read":
        return _codex_resource_read_evidence(
            item,
            sequence,
            result,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
        )
    payload = result.get("structured_content")
    if not isinstance(payload, Mapping):
        return None
    return _evidence_call_from_payload(
        str(tool),
        sequence,
        payload,
        fallback_commit=fallback_commit,
        expected_manifest_path=expected_manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def _codex_successful_repoground_item(item: Mapping[str, Any]) -> bool:
    return bool(
        item.get("type") == "mcp_tool_call"
        and item.get("server") in _REPOGROUND_MCP_SERVER_ALIASES
        and item.get("tool") in _REPOGROUND_EVIDENCE_TOOLS
        and item.get("status") == "completed"
        and item.get("error") is None
    )


def _codex_explicit_non_evidence_item(item: Mapping[str, Any]) -> bool:
    arguments = item.get("arguments")
    return bool(
        item.get("tool") == "repobrief_resource_read"
        and isinstance(arguments, Mapping)
        and arguments.get("action") == "list"
    )


def _codex_transcript_evidence(
    request: Mapping[str, Any],
    events: list[Mapping[str, Any]],
    *,
    fallback_commit: str | None,
    expected_manifest_path: str | None,
    expected_manifest_sha256: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    sequence = 0
    evidence_calls: list[dict[str, Any]] = []
    commits: set[str] = set()
    errors: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type in {"agent_message", "reasoning", "todo_list"}:
            continue
        if item_type not in {"command_execution", "mcp_tool_call"}:
            continue
        sequence += 1
        successful_repoground = _codex_successful_repoground_item(item)
        explicit_non_evidence = (
            successful_repoground and _codex_explicit_non_evidence_item(item)
        )
        normalized = _codex_item_evidence(
            item,
            sequence,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        if normalized is None:
            if successful_repoground and not explicit_non_evidence:
                errors.append(
                    "bound transcript successful RepoGround call could not be normalized: "
                    f"sequence {sequence} ({item.get('tool')})"
                )
            continue
        commit, call = normalized
        commits.add(commit)
        evidence_calls.append(call)
    return _evidence_document(request, evidence_calls, commits), errors


def _bound_transcript_evidence(
    request: Mapping[str, Any], content: bytes | None
) -> tuple[dict[str, Any] | None, list[str]]:
    contract = mapping_value(request.get("runner")).get("execution_contract")
    runner = _LIVE_RUNNER_CONTRACTS.get(str(contract))
    if runner is None:
        return None, []
    if content is None:
        return None, ["receipt RepoGround evidence requires readable bound transcript"]
    fallback_commit, manifest_errors = _bound_manifest_commit(request)
    if manifest_errors:
        return None, manifest_errors
    repobrief = mapping_value(request.get("repobrief"))
    expected_manifest_path = repobrief.get("manifest")
    expected_manifest_sha256 = repobrief.get("manifest_sha256")
    events, errors = _jsonl_objects(content)
    if events is None:
        return None, errors
    if runner == "claude":
        expected, parser_errors = _claude_transcript_evidence(
            request,
            events,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    else:
        expected, parser_errors = _codex_transcript_evidence(
            request,
            events,
            fallback_commit=fallback_commit,
            expected_manifest_path=expected_manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    return expected, parser_errors


def _bound_manifest_commit(
    request: Mapping[str, Any],
) -> tuple[str | None, list[str]]:
    runner = mapping_value(request.get("runner"))
    if not runner.get("execution_contract"):
        return None, []
    repository = mapping_value(request.get("repository"))
    repository_id = repository.get("id")
    if not isinstance(repository_id, str) or not repository_id:
        return None, ["receipt RepoGround manifest binding is invalid"]
    try:
        _path, manifest = _load_bound_manifest(
            mapping_value(request.get("repobrief")),
            repository_id=repository_id,
            label="benchmark RepoGround manifest",
        )
    except AgentBenchmarkError as exc:
        return None, [f"receipt RepoGround manifest binding is invalid: {exc}"]
    provenance = manifest.get("snapshot_provenance")
    repositories = (
        provenance.get("repositories") if isinstance(provenance, Mapping) else None
    )
    if (
        not isinstance(repositories, list)
        or len(repositories) != 1
        or not isinstance(repositories[0], Mapping)
    ):
        return None, ["receipt RepoGround manifest provenance is invalid"]
    commit = repositories[0].get("git_commit")
    if not _is_commit(commit):
        return None, ["receipt RepoGround manifest commit is invalid"]
    return str(commit), []


def _validate_ask_context_evidence(
    call: Mapping[str, Any], observed: Mapping[str, Any]
) -> list[str]:
    ranges = call.get("resolved_range_count")
    context_bytes = call.get("context_bytes_used")
    if (
        not isinstance(ranges, int)
        or isinstance(ranges, bool)
        or ranges < 0
        or not isinstance(context_bytes, int)
        or isinstance(context_bytes, bool)
        or context_bytes < 0
        or call.get("grounding_status") is not None
    ):
        return ["receipt RepoGround ask_context evidence is invalid"]
    output_bytes = observed.get("output_bytes")
    if (
        isinstance(output_bytes, int)
        and not isinstance(output_bytes, bool)
        and output_bytes >= 0
        and context_bytes > output_bytes
    ):
        return ["receipt RepoGround ask_context context bytes exceed bound tool output"]
    return []


def _validate_live_freshness_evidence(call: Mapping[str, Any]) -> list[str]:
    if (
        call.get("resolved_range_count") is not None
        or call.get("context_bytes_used") is not None
        or call.get("grounding_status") is not None
    ):
        return ["receipt RepoGround live_freshness evidence is invalid"]
    return []


def _validate_grounding_evidence(call: Mapping[str, Any]) -> list[str]:
    if (
        call.get("resolved_range_count") is not None
        or call.get("context_bytes_used") is not None
        or call.get("grounding_status") not in _GROUNDING_STATUSES
    ):
        return ["receipt RepoGround grounding_verify evidence is invalid"]
    return []


def _validate_resource_read_evidence(
    call: Mapping[str, Any], observed: Mapping[str, Any]
) -> list[str]:
    context_bytes = call.get("context_bytes_used")
    if (
        call.get("resolved_range_count") is not None
        or not isinstance(context_bytes, int)
        or isinstance(context_bytes, bool)
        or context_bytes <= 0
        or call.get("grounding_status") is not None
    ):
        return ["receipt RepoGround resource-read evidence is invalid"]
    output_bytes = observed.get("output_bytes")
    if (
        isinstance(output_bytes, int)
        and not isinstance(output_bytes, bool)
        and output_bytes >= 0
        and context_bytes > output_bytes
    ):
        return [
            "receipt RepoGround resource-read content bytes exceed bound tool output"
        ]
    return []


def _validate_repoground_call(
    call: Mapping[str, Any], observed: Mapping[str, Any] | None
) -> list[str]:
    tool = call.get("tool")
    if tool not in _REPOGROUND_EVIDENCE_TOOLS:
        return ["receipt RepoGround evidence tool is invalid"]
    if observed is None or observed.get("name") != tool:
        return ["receipt RepoGround evidence call does not match tool_calls"]
    if observed.get("status") != "success":
        return ["receipt RepoGround evidence may reference only successful tool calls"]
    errors: list[str] = []
    if call.get("freshness_status") not in _FRESHNESS_STATUSES:
        errors.append("receipt RepoGround evidence freshness_status is invalid")
    if tool == "ask_context":
        errors.extend(_validate_ask_context_evidence(call, observed))
    elif tool == "live_freshness":
        errors.extend(_validate_live_freshness_evidence(call))
    elif tool == "repobrief_resource_read":
        errors.extend(_validate_resource_read_evidence(call, observed))
    else:
        errors.extend(_validate_grounding_evidence(call))
    return errors


def _validate_repoground_header(
    request: Mapping[str, Any], evidence: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    target_commit = evidence.get("target_commit")
    bundle_commit = evidence.get("bundle_commit")
    expected_commit = mapping_value(request.get("repository")).get("commit")
    if target_commit != expected_commit:
        errors.append("receipt RepoGround evidence target_commit does not match request")
    if not _is_commit(bundle_commit):
        errors.append("receipt RepoGround evidence bundle_commit is invalid")
        return errors
    bound_commit, manifest_errors = _bound_manifest_commit(request)
    errors.extend(manifest_errors)
    if bound_commit is not None and bundle_commit != bound_commit:
        errors.append(
            "receipt RepoGround evidence bundle_commit does not match bound manifest"
        )
    return errors


def _validate_repoground_calls(
    receipt: Mapping[str, Any], evidence: Mapping[str, Any]
) -> list[str]:
    raw_calls = evidence.get("calls")
    if not isinstance(raw_calls, list):
        return ["receipt RepoGround evidence calls must be a list"]
    tool_calls = {
        mapping_value(call).get("sequence"): mapping_value(call)
        for call in list_value(receipt.get("tool_calls"))
    }
    errors: list[str] = []
    seen_sequences: set[int] = set()
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            errors.append("receipt RepoGround evidence call must be an object")
            continue
        call = raw
        if set(call) != _REPOGROUND_CALL_FIELDS:
            errors.append("receipt RepoGround evidence call fields mismatch")
            continue
        sequence = call.get("sequence")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or sequence in seen_sequences
        ):
            errors.append("receipt RepoGround evidence call sequence is invalid")
            continue
        seen_sequences.add(sequence)
        errors.extend(_validate_repoground_call(call, tool_calls.get(sequence)))
    return errors


def _has_successful_repoground_evidence_call(
    receipt: Mapping[str, Any],
) -> bool:
    return any(
        isinstance(raw_call, Mapping)
        and raw_call.get("name") in _REPOGROUND_MCP_EVIDENCE_TOOLS
        and raw_call.get("status") == "success"
        for raw_call in list_value(receipt.get("tool_calls"))
    )


def _validate_baseline_repoground_transcript(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    transcript_content: bytes | None,
) -> list[str]:
    if "repoground_evidence" in receipt:
        return ["baseline receipt must not contain RepoGround evidence"]
    contract = mapping_value(request.get("runner")).get("execution_contract")
    if str(contract) not in _LIVE_RUNNER_CONTRACTS:
        return []
    if not isinstance(request.get("component_delta"), Mapping):
        return []
    if not isinstance(request.get("repobrief"), Mapping):
        return []

    expected, transcript_errors = _bound_transcript_evidence(
        request, transcript_content
    )
    errors = list(transcript_errors)
    if expected is None:
        if (
            _has_successful_repoground_evidence_call(receipt)
            and not transcript_errors
        ):
            errors.append(
                "baseline RepoGround tool call is not supported by bound transcript"
            )
        return errors
    errors.extend(_validate_repoground_header(request, expected))
    errors.extend(_validate_repoground_calls(receipt, expected))
    return errors


def _validate_repoground_evidence(
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    transcript_content: bytes | None,
) -> list[str]:
    if request.get("condition") != "treatment":
        return _validate_baseline_repoground_transcript(
            request, receipt, transcript_content
        )
    contract = mapping_value(request.get("runner")).get("execution_contract")
    live_contract = str(contract) in _LIVE_RUNNER_CONTRACTS
    expected, transcript_errors = _bound_transcript_evidence(request, transcript_content)
    if "repoground_evidence" not in receipt:
        errors = list(transcript_errors)
        if live_contract and expected is not None:
            errors.append(
                "receipt RepoGround evidence is required by bound transcript"
            )
        elif (
            live_contract
            and _has_successful_repoground_evidence_call(receipt)
            and not transcript_errors
        ):
            errors.append(
                "receipt RepoGround tool call is not supported by bound transcript"
            )
        return errors
    evidence = receipt.get("repoground_evidence")
    if not isinstance(evidence, Mapping):
        return ["receipt RepoGround evidence must be an object"]
    if set(evidence) != {"target_commit", "bundle_commit", "calls"}:
        return ["receipt RepoGround evidence fields mismatch"]
    errors = _validate_repoground_header(request, evidence)
    errors.extend(_validate_repoground_calls(receipt, evidence))
    errors.extend(transcript_errors)
    if live_contract:
        if expected is None and not transcript_errors:
            errors.append(
                "receipt RepoGround evidence is not supported by bound transcript"
            )
        elif expected is not None and dict(evidence) != expected:
            errors.append("receipt RepoGround evidence does not match bound transcript")
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


def _transcript_content(
    receipt: Mapping[str, Any], transcript_root: str | Path | None
) -> tuple[bytes | None, list[str]]:
    transcript = mapping_value(receipt.get("transcript"))
    storage = transcript.get("storage")
    if storage == "inline":
        return _inline_transcript(transcript)
    if storage == "artifact":
        return _artifact_transcript(transcript, transcript_root)
    return None, ["transcript storage is invalid"]


def _validate_transcript(
    receipt: Mapping[str, Any],
    content: bytes | None,
    errors: list[str],
) -> list[str]:
    errors = list(errors)
    if content is None:
        return errors
    transcript = mapping_value(receipt.get("transcript"))
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

    transcript_content, transcript_errors = _transcript_content(
        receipt, transcript_root
    )
    errors = _validate_identity(request, receipt)
    errors.extend(_validate_provider(request, receipt))
    errors.extend(_validate_tokens(request, receipt))
    errors.extend(_validate_timestamps(receipt))
    errors.extend(_validate_duration(request, receipt))
    errors.extend(_validate_tool_calls(request, receipt))
    errors.extend(
        _validate_repoground_evidence(request, receipt, transcript_content)
    )
    errors.extend(_validate_transcript(receipt, transcript_content, transcript_errors))
    errors.extend(_validate_status(receipt))
    return errors


__all__ = ["validate_receipt"]
