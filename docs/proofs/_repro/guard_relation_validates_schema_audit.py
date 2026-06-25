#!/usr/bin/env python3
"""Derive the fixed-snapshot ``validates_schema`` report from reviewed flows."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

AUDIT = "guard-relation-cards-v1b-validates-schema-audit.json"


class AuditError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


@dataclass(frozen=True)
class Flow:
    source_path: str
    relation_owner_symbol: str
    relation_call_line: int
    engine_owner_symbol: str
    engine_call_line: int
    schema_path: str
    schema_fragment: str | None
    activation_condition: str
    target_scope: str
    schema_binding_origin: str
    resolved_engine: str
    validator_draft: str
    format_checker_mode: str
    dependency_requirement: str
    missing_dependency_outcome: str
    schema_requirement: str
    missing_schema_outcome: str
    meta_guard_present: bool
    schema_path_definition_line: int | None
    schema_load_line: int | None


@dataclass(frozen=True)
class MetaFlow:
    source_path: str
    engine_owner_symbol: str
    engine_call_line: int
    schema_path: str
    followed_by_instance_validation: bool
    schema_binding_verification: str


def parse_rows(names: list[str], rows: list[list[Any]], kind: type) -> tuple:
    require(names == [item.name for item in fields(kind)], f"field mismatch: {names}")
    records = []
    for number, row in enumerate(rows):
        require(len(row) == len(names), f"row {number} has {len(row)} fields")
        records.append(kind(**dict(zip(names, row, strict=True))))
    return tuple(records)


def direct(flow: Flow) -> bool:
    return (
        flow.relation_owner_symbol == flow.engine_owner_symbol
        and flow.relation_call_line == flow.engine_call_line
    )


def semantic_key(flow: Flow) -> tuple[str, ...]:
    return (
        flow.source_path,
        flow.relation_owner_symbol,
        flow.engine_owner_symbol,
        flow.schema_path,
        flow.schema_fragment or "",
        flow.activation_condition,
        flow.target_scope,
    )


def snapshot_key(flow: Flow) -> tuple[str, ...]:
    return (
        flow.source_path,
        flow.relation_owner_symbol,
        str(flow.relation_call_line),
        flow.engine_owner_symbol,
        str(flow.engine_call_line),
        flow.schema_path,
        flow.schema_fragment or "",
        flow.activation_condition,
        flow.target_scope,
    )


def flow_id(base_sha: str, flow: Flow) -> str:
    return hashlib.sha256(
        "|".join((base_sha, *snapshot_key(flow))).encode("utf-8")
    ).hexdigest()


def axis(flows: tuple[Flow, ...], name: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(flow, name)) for flow in flows).items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    args = parser.parse_args()
    manifest_path = Path(args.manifest) if args.manifest else (
        Path(__file__).resolve().parent.parent / AUDIT
    )
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    manual_keys = (
        "base_sha",
        "declared_scanner_grammar",
        "flow_fields",
        "inventory_path_count",
        "inventory_sha256",
        "limitations",
        "meta_flow_fields",
        "reviewed_flows",
        "reviewed_meta_flows",
        "text_only_non_validator_files",
    )
    manual = {key: source[key] for key in manual_keys}
    require(args.base_sha == manual["base_sha"], "base mismatch")
    flows = parse_rows(manual["flow_fields"], manual["reviewed_flows"], Flow)
    meta = parse_rows(manual["meta_flow_fields"], manual["reviewed_meta_flows"], MetaFlow)
    accepted = tuple(sorted(
        (flow for flow in flows if flow.target_scope == "in_repo"),
        key=snapshot_key,
    ))
    external = tuple(sorted(
        (flow for flow in flows if flow.target_scope != "in_repo"),
        key=snapshot_key,
    ))
    require(len(accepted) == 24 and len(external) == 1, "flow cardinality")
    require(len({snapshot_key(flow) for flow in accepted}) == 24, "snapshot keys")
    require(len({flow_id(args.base_sha, flow) for flow in accepted}) == 24, "flow ids")
    require(len(meta) == 6, "meta flow cardinality")

    axes = {
        "engine_invocation": dict(sorted(Counter(
            "direct" if direct(flow) else "delegated" for flow in accepted
        ).items())),
        **{
            name: axis(accepted, name)
            for name in (
                "activation_condition",
                "dependency_requirement",
                "format_checker_mode",
                "missing_dependency_outcome",
                "missing_schema_outcome",
                "resolved_engine",
                "schema_binding_origin",
                "schema_requirement",
                "target_scope",
                "validator_draft",
            )
        },
    }
    require(axes["engine_invocation"] == {"delegated": 2, "direct": 22}, "invocation")
    require(axes["schema_requirement"] == {"optional": 3, "required": 21}, "schema requirement")
    require(
        axes["activation_condition"]
        == {
            'range_ref_version != "2"': 1,
            'range_ref_version == "2"': 1,
            "unconditional": 22,
        },
        "activation condition",
    )

    report = {
        **manual,
        "axis_counts": axes,
        "identity_model": {
            "semantic_flow_key_fields": [
                "source_path",
                "relation_owner_symbol",
                "engine_owner_symbol",
                "schema_path",
                "schema_fragment",
                "activation_condition",
                "target_scope",
            ],
            "snapshot_callsite_key_fields": [
                "source_path",
                "relation_owner_symbol",
                "relation_call_line",
                "engine_owner_symbol",
                "engine_call_line",
                "schema_path",
                "schema_fragment",
                "activation_condition",
                "target_scope",
            ],
            "snapshot_flow_id": "sha256(base_sha + snapshot_callsite_key)",
            "stability_boundary": "snapshot-local; line changes alter the snapshot key",
        },
        "meta_validation": {
            "engine_callsite_count": len({
                (flow.source_path, flow.engine_owner_symbol, flow.engine_call_line)
                for flow in meta
            }),
            "schema_binding_verification": "manual_source_review",
            "schema_flow_count": len(meta),
        },
        "relation_counts": {
            "accepted_modules": len({flow.source_path for flow in accepted}),
            "accepted_schema_targets": len({flow.schema_path for flow in accepted}),
            "callsite_flows": len(accepted),
            "external_or_not_accepted_flows": len(external),
            "snapshot_callsite_keys": len({snapshot_key(flow) for flow in accepted}),
            "snapshot_flow_ids": len({flow_id(args.base_sha, flow) for flow in accepted}),
            "unique_engine_callsites_including_external": len({
                (flow.source_path, flow.engine_owner_symbol, flow.engine_call_line)
                for flow in flows
            }),
            "unique_module_schema_targets": len({
                (flow.source_path, flow.schema_path) for flow in accepted
            }),
            "unique_semantic_flow_keys": len({semantic_key(flow) for flow in accepted}),
        },
        "schema_coverage": {
            "total_schema_files": 54,
            "with_accepted_in_repo_relation": 18,
            "without_accepted_in_repo_relation": 36,
        },
    }
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"OK wrote {args.output} ({len(accepted)} accepted flows)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
