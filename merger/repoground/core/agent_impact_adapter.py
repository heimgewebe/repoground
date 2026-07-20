"""Read-only RepoGround adapter for agent impact/edit context.

The adapter subclasses the protocol-neutral RepoGround adapter and composes only
integrity-checked bundle reads. It neither creates snapshots nor mutates source,
Git, tests, pull requests or memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from merger.repoground.core.agent_impact_context import build_agent_impact_context
from merger.repoground.core.agent_impact_refinement import (
    refine_agent_impact_context,
)
from merger.repoground.core.readonly_adapter import (
    RepoGroundReadonlyAdapter,
    RepoGroundReadonlyAdapterError,
)

MAX_RELATION_CARDS = 10_000
_CORE_JSON_CONTRACTS = {
    "architecture_graph_json": ("lenskit.architecture.graph", "nodes", "edges"),
    "python_symbol_index_json": ("lenskit.python_symbol_index", "symbols"),
    "python_call_graph_json": ("lenskit.python_call_graph", "calls"),
    "entrypoints_json": ("lenskit.entrypoints", "entrypoints"),
}


@dataclass(frozen=True)
class _SourceResponses:
    graph: dict[str, Any]
    symbols: dict[str, Any]
    call_graph: dict[str, Any]
    entrypoints: dict[str, Any]
    cards: dict[str, Any]


def _json_document(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("content_json")
    return value if isinstance(value, dict) else {}


def _jsonl_documents(
    response: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    text = response.get("content_text")
    if not isinstance(text, str):
        return [], []
    documents: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if len(documents) >= MAX_RELATION_CARDS:
            errors.append("relation_cards_scan_truncated")
            break
        line = raw.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"invalid_json_line:{line_number}")
            continue
        if isinstance(value, dict):
            documents.append(value)
        else:
            errors.append(f"non_object_json_line:{line_number}")
    return documents, errors


def _artifact_status(role: str, response: dict[str, Any]) -> dict[str, Any]:
    artifact = response.get("artifact")
    return {
        "source": role,
        "status": response.get("status", "missing"),
        "error_code": response.get("error_code"),
        "bytes": artifact.get("bytes") if isinstance(artifact, dict) else None,
        "sha256": artifact.get("sha256") if isinstance(artifact, dict) else None,
    }


def _json_parse_status(response: dict[str, Any]) -> str:
    text = response.get("content_text")
    if not isinstance(text, str):
        return "invalid_json"
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return "invalid_json"
    return "invalid_schema"


def _core_json_status(role: str, response: dict[str, Any]) -> dict[str, Any]:
    status = _artifact_status(role, response)
    if status["status"] != "available":
        return status
    document = response.get("content_json")
    if not isinstance(document, dict):
        failure = _json_parse_status(response)
        status.update({"status": failure, "error_code": failure})
        return status
    expected_kind, *array_fields = _CORE_JSON_CONTRACTS[role]
    valid_identity = (
        document.get("kind") == expected_kind
        and document.get("version") == "1.0"
    )
    valid_arrays = all(
        isinstance(document.get(field), list) for field in array_fields
    )
    if not valid_identity or not valid_arrays:
        status.update(
            {
                "status": "invalid_schema",
                "error_code": "core_artifact_contract_invalid",
            }
        )
    return status


def _target_query(target_path: Any, target_symbol: Any, changed_paths: Any) -> str:
    parts: list[str] = []
    if isinstance(target_symbol, str) and target_symbol.strip():
        parts.append(target_symbol.strip())
    if isinstance(target_path, str) and target_path.strip():
        parts.append(target_path.strip())
    if isinstance(changed_paths, list):
        parts.extend(
            value.strip()
            for value in changed_paths
            if isinstance(value, str) and value.strip()
        )
    return " ".join(dict.fromkeys(parts))


def _query_limit(max_items: Any) -> int:
    valid = (
        isinstance(max_items, int)
        and not isinstance(max_items, bool)
        and 1 <= max_items <= 200
    )
    return int(max_items) if valid else 25


class RepoGroundAgentImpactAdapter(RepoGroundReadonlyAdapter):
    """Expose a bounded impact/edit context over registered snapshots."""

    def _impact_sources(self, snapshot_id: str) -> _SourceResponses:
        return _SourceResponses(
            graph=self.artifact_get(snapshot_id, "architecture_graph_json"),
            symbols=self.artifact_get(snapshot_id, "python_symbol_index_json"),
            call_graph=self.artifact_get(snapshot_id, "python_call_graph_json"),
            entrypoints=self.artifact_get(snapshot_id, "entrypoints_json"),
            cards=self.artifact_get(snapshot_id, "relation_cards_jsonl"),
        )

    def _impact_query(
        self,
        snapshot_id: str,
        *,
        query: str,
        max_items: Any,
        include_query_context: bool,
    ) -> dict[str, Any]:
        if not include_query_context or not query:
            return {}
        return self.query_existing_index(
            snapshot_id,
            query,
            k=_query_limit(max_items),
            resolve_evidence=True,
            project_sources=True,
        )

    @staticmethod
    def _source_statuses(
        sources: _SourceResponses,
        query_response: dict[str, Any],
    ) -> list[dict[str, Any]]:
        statuses = [
            _core_json_status("architecture_graph_json", sources.graph),
            _core_json_status("python_symbol_index_json", sources.symbols),
            _core_json_status("entrypoints_json", sources.entrypoints),
            _artifact_status("relation_cards_jsonl", sources.cards),
        ]
        call_graph_status = _core_json_status(
            "python_call_graph_json",
            sources.call_graph,
        )
        if call_graph_status.get("status") != "missing":
            statuses.append(call_graph_status)
        if query_response:
            statuses.append(
                {
                    "source": "sqlite_index",
                    "status": query_response.get("status"),
                    "error_code": query_response.get("error_code"),
                }
            )
        return statuses

    def agent_impact_context(
        self,
        snapshot_id: Any,
        *,
        target_path: Any = None,
        target_symbol: Any = None,
        changed_paths: Any = None,
        mode: Any = "impact",
        max_items: Any = 25,
        include_query_context: Any = True,
    ) -> dict[str, Any]:
        registration = self._registration(snapshot_id)
        if not isinstance(include_query_context, bool):
            return self._invalid(
                "agent_impact_context",
                "include_query_context must be a boolean",
                snapshot_id=registration.snapshot_id,
            )

        sources = self._impact_sources(registration.snapshot_id)
        cards, card_errors = _jsonl_documents(sources.cards)
        query = _target_query(target_path, target_symbol, changed_paths)
        item_limit = _query_limit(max_items)
        query_response = self._impact_query(
            registration.snapshot_id,
            query=query,
            max_items=item_limit,
            include_query_context=include_query_context,
        )
        result = build_agent_impact_context(
            target_path=target_path,
            target_symbol=target_symbol,
            changed_paths=changed_paths,
            mode=mode,
            max_items=max_items,
            architecture_graph=_json_document(sources.graph),
            symbol_index=_json_document(sources.symbols),
            python_call_graph=_json_document(sources.call_graph),
            entrypoints=_json_document(sources.entrypoints),
            relation_cards=cards,
            query_context=query_response,
            source_statuses=self._source_statuses(sources, query_response),
        )
        result = refine_agent_impact_context(
            result,
            query_response,
            max_items=item_limit,
        )
        result.update(
            {
                "action": "agent_impact_context",
                "snapshot_id": registration.snapshot_id,
                "bundle_manifest": str(registration.manifest),
                "snapshot": self.snapshot_status(
                    registration.snapshot_id
                ).get("snapshot"),
                "query": query,
                "relation_card_parse_errors": card_errors,
            }
        )
        return result

    def dispatch(self, request: Any) -> dict[str, Any]:
        if (
            isinstance(request, dict)
            and request.get("action") == "agent_impact_context"
        ):
            try:
                return self.agent_impact_context(
                    request.get("snapshot_id"),
                    target_path=request.get("target_path"),
                    target_symbol=request.get("target_symbol"),
                    changed_paths=request.get("changed_paths"),
                    mode=request.get("mode", "impact"),
                    max_items=request.get("max_items", 25),
                    include_query_context=request.get(
                        "include_query_context",
                        True,
                    ),
                )
            except (RepoGroundReadonlyAdapterError, TypeError, ValueError) as exc:
                return self._invalid(
                    "agent_impact_context",
                    str(exc),
                    snapshot_id=request.get("snapshot_id"),
                )
        return super().dispatch(request)


__all__ = ["RepoGroundAgentImpactAdapter"]
