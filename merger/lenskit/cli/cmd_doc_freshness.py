"""CLI: ``lenskit doc-freshness`` — diagnostic doc-freshness verifier (v0).

Subcommands:

* ``inspect`` — verify the registry against the live tree and report drift.
  Exit 0 on pass, 1 on findings (warn/fail), 2 on a load/validation error.
  ``--strict`` escalates a confirmed stale drift in a *normative* doc to a
  failure (the per-entry enforcement promotion path).
* ``update`` — regenerate the human-readable view (``docs/_generated/
  doc-freshness.md``) and stamp ``last_verified`` for entries that verify.
  ``--write`` persists; without it, the command is a dry run.

Diagnostic-first: this is intentionally not wired as a blocking CI gate yet
(mirrors the artifact-drift-matrix rollout rule and the experimental AST lint).
"""
from __future__ import annotations

import argparse
import json
import sys


def register_doc_freshness_commands(subparsers) -> None:
    df_parser = subparsers.add_parser(
        "doc-freshness",
        help=(
            "Verify documentation claims against code/test/proof evidence "
            "(diagnostic; detects stale TODOs / roadmap drift)"
        ),
    )
    df_subparsers = df_parser.add_subparsers(
        dest="doc_freshness_cmd", required=True, help="Doc-freshness commands"
    )

    inspect_parser = df_subparsers.add_parser(
        "inspect",
        help="Verify the registry and report drift (exit 1 on findings).",
    )
    _add_common_args(inspect_parser)
    inspect_parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Escalate a confirmed stale drift in a normative doc to a failure "
            "(enforcement promotion path; default is diagnostic/tracked)."
        ),
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        dest="emit_json",
        help="Emit the machine-readable JSON report to stdout.",
    )

    update_parser = df_subparsers.add_parser(
        "update",
        help=(
            "Regenerate the generated view and stamp last_verified for verified "
            "entries (--write to persist)."
        ),
    )
    _add_common_args(update_parser)
    update_parser.add_argument(
        "--write",
        action="store_true",
        help="Persist changes (default is a dry run that prints what would change).",
    )
    update_parser.add_argument(
        "--no-stamp",
        action="store_true",
        help=(
            "Regenerate the generated view without updating last_verified "
            "(useful for deterministic CI sync checks)."
        ),
    )


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--registry",
        dest="registry",
        default=None,
        help="Path to the doc-freshness registry YAML (default: docs/doc-freshness-registry.yml).",
    )
    parser.add_argument(
        "--repo-root",
        dest="repo_root",
        default=None,
        help="Repo root used to resolve evidence (default: inferred from the package).",
    )


def _load_and_validate(args):
    """Return ``(data, repo_root, registry_path)`` or raise ValueError/OSError."""
    from pathlib import Path

    from merger.lenskit.core.doc_freshness import (
        default_registry_path,
        default_schema_path,
        load_registry,
        repo_root_from_here,
        validate_registry,
    )

    repo_root = (
        Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    )
    registry_path = (
        Path(args.registry).resolve()
        if args.registry
        else default_registry_path(repo_root)
    )
    if not registry_path.is_file():
        raise OSError(f"registry not found: {registry_path}")

    data = load_registry(registry_path)
    schema_errors = validate_registry(data, default_schema_path(repo_root))
    if schema_errors:
        raise ValueError(
            "registry violates doc-freshness-registry.v1 schema: "
            + "; ".join(schema_errors)
        )
    return data, repo_root, registry_path


def run_doc_freshness_inspect(args: argparse.Namespace) -> int:
    from merger.lenskit.core.doc_freshness import verify

    try:
        data, repo_root, _ = _load_and_validate(args)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    report = verify(data, repo_root, strict=getattr(args, "strict", False))

    if getattr(args, "emit_json", False):
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human_report(report)

    return 0 if report.status == "pass" else 1


def run_doc_freshness_update(args: argparse.Namespace) -> int:
    from datetime import date

    from merger.lenskit.core.doc_freshness import (
        default_generated_view_path,
        render_markdown,
        restamp_last_verified,
        verified_entry_ids,
        verify,
    )

    try:
        data, repo_root, registry_path = _load_and_validate(args)
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    report = verify(data, repo_root, strict=False)
    stamp = not bool(getattr(args, "no_stamp", False))
    today = date.today().isoformat()

    # Stamp last_verified for entries whose state is OK (never for findings).
    ok_ids = verified_entry_ids(report)
    registry_text = registry_path.read_text(encoding="utf-8")
    stamp_updates = {eid: today for eid in ok_ids} if stamp else {}
    new_registry_text, changed_ids = restamp_last_verified(registry_text, stamp_updates)
    registry_changed = new_registry_text != registry_text

    # Regenerate the human-readable view from the verified registry. Use the
    # restamped data so the view's last_verified column is consistent.
    stamped_data = _restamp_data(data, ok_ids, today) if stamp else data
    # Deterministic "generated_at": derived from the data (max last_verified),
    # NOT wall-clock, so regeneration is a pure function of the registry + tree
    # and a CI "regenerate & git-diff" check does not flap across days.
    generated_at = _max_last_verified(stamped_data)
    view_text = render_markdown(stamped_data, report, generated_at) + "\n"
    view_path = default_generated_view_path(repo_root)
    view_changed = (
        not view_path.is_file()
        or view_path.read_text(encoding="utf-8") != view_text
    )

    print(f"doc-freshness update — status: {report.status.upper()}")
    print(f"  verified entries (stampable): {len(ok_ids)}")
    print(f"  registry last_verified to change: {len(changed_ids)} {changed_ids or ''}")
    if not stamp:
        print("  stamping disabled (--no-stamp)")
    print(f"  generated view: {'WOULD CHANGE' if view_changed else 'up to date'} ({view_path})")
    if report.findings:
        print(
            f"  NOTE: {len(report.findings)} finding(s) NOT stamped "
            "(their declared state is contradicted by evidence)."
        )

    if not getattr(args, "write", False):
        print("\n(dry run — pass --write to persist)")
        return 0

    if registry_changed:
        registry_path.write_text(new_registry_text, encoding="utf-8")
        print(f"  wrote {registry_path}")
    if view_changed:
        view_path.parent.mkdir(parents=True, exist_ok=True)
        view_path.write_text(view_text, encoding="utf-8")
        print(f"  wrote {view_path}")
    if not registry_changed and not view_changed:
        print("  nothing to write (already current)")
    return 0


def _max_last_verified(data: dict) -> str:
    dates = [
        e.get("last_verified")
        for e in data.get("entries", [])
        if e.get("last_verified")
    ]
    return max(dates) if dates else "—"


def _restamp_data(data: dict, ok_ids, today: str) -> dict:
    import copy

    clone = copy.deepcopy(data)
    ok = set(ok_ids)
    for entry in clone.get("entries", []):
        if entry.get("id") in ok:
            entry["last_verified"] = today
    return clone


def _print_human_report(report) -> None:
    print(f"Doc-Freshness (diagnostic v0): {report.status.upper()}")
    print(f"  entries_scanned:  {report.entries_scanned}")
    print(f"  findings:         {len(report.findings)} (errors {report.error_count}, warnings {report.warning_count})")
    print(f"  stale (tracked):  {len(report.stale_confirmed)}")

    findings = report.findings
    if findings:
        print(f"\nFindings ({len(findings)}):")
        for r in sorted(findings, key=lambda x: (x.severity, x.entry_id)):
            print(f"  [{r.severity}] {r.entry_id} ({r.classification}) — {r.doc}")
            print(f"        {r.message}")

    if report.stale_confirmed:
        print(f"\nKnown drift, declared & tracked (NOT suppressed) ({len(report.stale_confirmed)}):")
        for r in report.stale_confirmed:
            print(f"  [{r.declared_status}] {r.entry_id} — {r.doc}")
            print(f"        {r.message}")

    print(
        "\n  NOTE: diagnostic verifier — a pass does NOT prove the docs are "
        "complete or correct, only that no tracked claim contradicts its "
        "declared evidence. Not a blocking CI gate (use --strict to preview "
        "normative-doc enforcement)."
    )
