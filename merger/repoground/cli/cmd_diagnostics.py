"""Explicit, bounded diagnostic surfaces for optional RepoGround capabilities.

These commands turn previously test-only modules into real opt-in product surfaces.
They do not run during normal indexing, querying, service or merge flows.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

_MAX_JSON_BYTES = 8 * 1024 * 1024


def _read_json(
    path_value: str,
    *,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    path = Path(path_value).expanduser()
    before_open = path.lstat()
    if stat.S_ISLNK(before_open.st_mode):
        raise ValueError(f"refusing symbolic-link input: {path}")
    if not stat.S_ISREG(before_open.st_mode):
        raise ValueError(f"input must be a regular file: {path}")
    if before_open.st_size > _MAX_JSON_BYTES:
        raise ValueError(
            f"input exceeds {_MAX_JSON_BYTES} bytes: {path} ({before_open.st_size} bytes)"
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        after_open = os.fstat(descriptor)
        if not stat.S_ISREG(after_open.st_mode):
            raise ValueError(f"input must remain a regular file while opening: {path}")
        if (before_open.st_dev, before_open.st_ino) != (
            after_open.st_dev,
            after_open.st_ino,
        ):
            raise ValueError(f"input changed while opening: {path}")
        if after_open.st_size > _MAX_JSON_BYTES:
            raise ValueError(
                f"input exceeds {_MAX_JSON_BYTES} bytes: {path} ({after_open.st_size} bytes)"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(_MAX_JSON_BYTES + 1)
    finally:
        os.close(descriptor)

    if len(payload) > _MAX_JSON_BYTES:
        raise ValueError(f"input exceeds {_MAX_JSON_BYTES} bytes while reading: {path}")
    value = json.loads(payload.decode("utf-8"))
    if expected_type is not None and not isinstance(value, expected_type):
        expected_name = (
            ", ".join(item.__name__ for item in expected_type)
            if isinstance(expected_type, tuple)
            else expected_type.__name__
        )
        raise ValueError(f"input must contain JSON {expected_name}: {path}")
    return value


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _build_diagnostics_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repoground diagnostics",
        description="Run explicit, read-only or locally projected diagnostic operations",
    )
    operations = parser.add_subparsers(
        dest="diagnostics_command",
        required=True,
        help="Diagnostic operation",
    )

    answer_delta = operations.add_parser(
        "answer-delta",
        help="Revalidate declared answer citations against a newer bundle",
    )
    answer_delta.add_argument("--old-declaration", required=True)
    answer_delta.add_argument("--new-bundle-manifest", required=True)
    answer_delta.add_argument("--new-citation-map")

    history_lens = operations.add_parser(
        "history-lens",
        help="Project bounded history records without claiming repository truth",
    )
    history_lens.add_argument("--records", required=True)
    history_lens.add_argument(
        "--profile",
        choices=["disabled", "summary", "full"],
        default="summary",
    )
    history_lens.add_argument("--include-author-metadata", action="store_true")

    memory_build = operations.add_parser(
        "memory-build",
        help="Build a citation-bound memory record that requires recall revalidation",
    )
    memory_build.add_argument("--claim-text", required=True)
    memory_build.add_argument("--citations", required=True)
    memory_build.add_argument("--snapshot-stem", required=True)
    memory_build.add_argument("--snapshot-hash", required=True)
    memory_build.add_argument("--freshness-status", required=True)
    memory_build.add_argument("--stored-at")
    memory_build.add_argument("--metadata")

    memory_check = operations.add_parser(
        "memory-check",
        help="Revalidate a citation-bound memory record before reuse",
    )
    memory_check.add_argument("--memory-record", required=True)
    memory_check.add_argument("--current-citations", required=True)
    memory_check.add_argument("--current-snapshot-hash")
    memory_check.add_argument("--current-freshness-status")

    audit_plan = operations.add_parser(
        "audit-plan",
        help="Select a bounded deterministic set of diagnostic audit lanes",
    )
    audit_plan.add_argument("--changed-path", action="append", default=[])
    audit_plan.add_argument("--paths-file")
    audit_plan.add_argument("--review-query", default="")
    audit_plan.add_argument("--max-lanes", type=int, default=6)

    audit_findings = operations.add_parser(
        "audit-findings",
        help="Bind audit candidates to revisions, lanes and resolvable citations",
    )
    audit_findings.add_argument("--plan", required=True)
    audit_findings.add_argument("--candidates", required=True)
    audit_findings.add_argument("--reviewed-revision", required=True)
    audit_findings.add_argument("--current-revision", required=True)
    audit_findings.add_argument("--citation-ids", required=True)
    audit_findings.add_argument("--verification-records")

    eval_report = operations.add_parser(
        "eval-report",
        help="Explain retrieval misses without changing evaluation metrics",
    )
    eval_report.add_argument("--eval-results", required=True)
    eval_report.add_argument("--index")
    eval_report.add_argument("--canonical")
    eval_report.add_argument("--citation")

    return parser


def register_diagnostics_commands(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "diagnostics",
        help="Run explicit, read-only or locally projected diagnostic operations",
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        dest="diagnostics_help",
    )
    parser.add_argument("diagnostics_args", nargs=argparse.REMAINDER)


def _run_answer_delta(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.core.answer_grounding_delta import (
        check_answer_grounding_delta,
    )

    declaration = _read_json(args.old_declaration, expected_type=dict)
    return check_answer_grounding_delta(
        declaration,
        new_bundle_manifest=args.new_bundle_manifest,
        new_citation_map=args.new_citation_map,
    )


def _run_history_lens(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.core.history_lens import build_history_lens

    records = _read_json(args.records, expected_type=list)
    return build_history_lens(
        records,
        profile=args.profile,
        include_author_metadata=args.include_author_metadata,
    )


def _run_memory_build(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.core.memory import build_memory_record

    citations = _read_json(args.citations, expected_type=list)
    metadata = _read_json(args.metadata, expected_type=dict) if args.metadata else None
    return build_memory_record(
        claim_text=args.claim_text,
        citations=citations,
        snapshot_stem=args.snapshot_stem,
        snapshot_hash=args.snapshot_hash,
        freshness_status=args.freshness_status,
        stored_at=args.stored_at,
        metadata=metadata,
    )


def _run_memory_check(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.core.memory import check_memory_recall

    record = _read_json(args.memory_record, expected_type=dict)
    citations = _read_json(args.current_citations, expected_type=(dict, list))
    return check_memory_recall(
        record,
        current_citations=citations,
        current_snapshot_hash=args.current_snapshot_hash,
        current_freshness_status=args.current_freshness_status,
    )


def _run_audit_plan(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.retrieval.audit_lane import plan_audit_lanes

    paths = list(args.changed_path)
    if args.paths_file:
        paths.extend(_read_json(args.paths_file, expected_type=list))
    return plan_audit_lanes(
        paths,
        review_query=args.review_query,
        max_lanes=args.max_lanes,
    )


def _run_audit_findings(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.retrieval.audit_finding import adapt_audit_findings

    plan = _read_json(args.plan, expected_type=dict)
    candidates = _read_json(args.candidates, expected_type=list)
    citation_ids = _read_json(args.citation_ids, expected_type=list)
    verification_records = (
        _read_json(args.verification_records, expected_type=list)
        if args.verification_records
        else []
    )
    return adapt_audit_findings(
        plan,
        candidates,
        reviewed_revision=args.reviewed_revision,
        current_revision=args.current_revision,
        resolvable_citation_ids=citation_ids,
        verification_records=verification_records,
    )


def _run_eval_report(args: argparse.Namespace) -> dict[str, Any]:
    from merger.repoground.retrieval.eval_diagnostics_integration import (
        integrate_diagnostics_with_eval_results,
    )

    eval_results = _read_json(args.eval_results, expected_type=dict)
    return integrate_diagnostics_with_eval_results(
        eval_results,
        index_path=Path(args.index) if args.index else None,
        canonical_path=Path(args.canonical) if args.canonical else None,
        citation_path=Path(args.citation) if args.citation else None,
    )


def run_diagnostics(args: argparse.Namespace) -> int:
    raw_args = ["--help"] if args.diagnostics_help else args.diagnostics_args
    operation_args = _build_diagnostics_parser().parse_args(raw_args)
    handlers = {
        "answer-delta": _run_answer_delta,
        "history-lens": _run_history_lens,
        "memory-build": _run_memory_build,
        "memory-check": _run_memory_check,
        "audit-plan": _run_audit_plan,
        "audit-findings": _run_audit_findings,
        "eval-report": _run_eval_report,
    }
    try:
        result = handlers[operation_args.diagnostics_command](operation_args)
    except (
        KeyError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    _emit(result)
    return 0
