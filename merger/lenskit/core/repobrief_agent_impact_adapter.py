"""Read-only RepoBrief adapter for agent impact/edit context.

The adapter subclasses the protocol-neutral RepoBrief adapter and composes only
integrity-checked bundle reads. It neither creates snapshots nor mutates source,
Git, tests, pull requests or memory.
"""

from __future__ import annotations

import json
from typing import Any

from merger.lenskit.core.agent_impact_context import build_agent_impact_context
from merger.lenskit.core.repobrief_readonly_adapter import (
    RepoBriefReadonlyAdapter,
    RepoBriefReadonlyAdapterError,
)

MAX_RELATION_CARDS = 10_000


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


class RepoBriefAgentImpactAdapter(RepoBriefReadonlyAdapter):
    """Expose a bounded impact/edit context over registered snapshots."""

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

        graph_response = self.artifact_get(
            registration.snapshot_id,
            "architecture_graph_json",
        )
        symbol_response = self.artifact_get(
            registration.snapshot_id,
            "python_symbol_index_json",
        )
        entrypoint_response = self.artifact_get(
            registration.snapshot_id,
            "entrypoints_json",
        )
        cards_response = self.artifact_get(
            registration.snapshot_id,
            "relation_cards_jsonl",
        )

        relation_cards, relation_card_errors = _jsonl_documents(cards_response)
        query_response: dict[str, Any] = {}
        query = _target_query(target_path, target_symbol, changed_paths)
        query_limit = (
            max_items
            if isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and 1 <= max_items <= 200
            else 25
        )
        if include_query_context is True and query:
            query_response = self.query_existing_index(
                registration.snapshot_id,
                query,
                k=query_limit,
                resolve_evidence=True,
                project_sources=True,
            )
        elif include_query_context not in {True, False}:
            return self._invalid(
                "agent_impact_context",
                "include_query_context must be a boolean",
                snapshot_id=registration.snapshot_id,
            )

        snapshot_response = self.snapshot_status(registration.snapshot_id)
        statuses = [
            _artifact_status("architecture_graph_json", graph_response),
            _artifact_status("python_symbol_index_json", symbol_response),
            _artifact_status("entrypoints_json", entrypoint_response),
            _artifact_status("relation_cards_jsonl", cards_response),
        ]
        if query_response:
            statuses.append(
                {
                    "source": "sqlite_index",
                    "status": query_response.get("status"),
                    "error_code": query_response.get("error_code"),
                }
            )

        result = build_agent_impact_context(
            target_path=target_path,
            target_symbol=target_symbol,
            changed_paths=changed_paths,
            mode=mode,
            max_items=max_items,
            architecture_graph=_json_document(graph_response),
            symbol_index=_json_document(symbol_response),
            entrypoints=_json_document(entrypoint_response),
            relation_cards=relation_cards,
            query_context=query_response,
            source_statuses=statuses,
        )
        result.update(
            {
                "action": "agent_impact_context",
                "snapshot_id": registration.snapshot_id,
                "bundle_manifest": str(registration.manifest),
                "snapshot": snapshot_response.get("snapshot"),
                "query": query,
                "relation_card_parse_errors": relation_card_errors,
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
            except (RepoBriefReadonlyAdapterError, TypeError, ValueError) as exc:
                return self._invalid(
                    "agent_impact_context",
                    str(exc),
                    snapshot_id=request.get("snapshot_id"),
                )
        return super().dispatch(request)


__all__ = ["RepoBriefAgentImpactAdapter"]
