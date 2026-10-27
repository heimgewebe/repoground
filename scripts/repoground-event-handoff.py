#!/usr/bin/env python3
"""Bounded, explicit RepoGround Git/CI event-to-evidence publisher entrypoint.

An existing authorized scheduler/publisher calls this executable with events.
Nothing is registered to run automatically, and a read command never invokes it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Support direct script execution from anywhere without a new Python package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from merger.repoground.core.event_handoff import (  # noqa: E402
    EventInputError,
    _check_event,
    MAX_EVENT_BYTES,
    publish_event,
    read_event_receipt,
)

MAX_BATCH_EVENTS = 16


def _read_event_cli(args: argparse.Namespace) -> int:
    """A consumer path with no Git execution, lock, snapshot or outbox writes."""
    try:
        result = read_event_receipt(
            outbox_root=args.outbox_root, event_key=args.read_event_key,
        )
    except (EventInputError, OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "available" else 2


def _load_cli_events(
    args: argparse.Namespace, parser: argparse.ArgumentParser,
) -> list[dict]:
    """Reject the entire malformed batch before the first write-side event."""
    if args.repo_root is None:
        parser.error("--repo-root required for publishing events")
    if not 1 <= args.max_events <= MAX_BATCH_EVENTS:
        parser.error("max-events must be between 1 and 16")
    path = Path(args.event_file)
    if path.is_symlink() or not path.is_file():
        parser.error("event-file must be an existing regular file, not a symlink")
    if path.stat().st_size > MAX_BATCH_EVENTS * (MAX_EVENT_BYTES + 1):
        parser.error("event-file exceeds bounded event payload size")
    data = path.read_text(encoding="utf-8")
    if args.format == "json":
        event = json.loads(data)
        if not isinstance(event, dict):
            raise EventInputError("single event must be a JSON object")
        events = [event]
    else:
        lines = [line for line in data.splitlines() if line.strip()]
        if len(lines) > args.max_events:
            raise EventInputError("bounded_batch_limit")
        events = [json.loads(line) for line in lines]
    if not events or len(events) > args.max_events:
        raise EventInputError("bounded_batch_limit")
    return [_check_event(event) for event in events]


def _publish_cli_events(args: argparse.Namespace, events: list[dict]) -> int:
    results = []
    for event in events:
        outcome = publish_event(
            event=event, repo_root=args.repo_root, outbox_root=args.outbox_root,
            bundle_manifest=args.bundle_manifest,
            context_budget_tokens=args.budget_tokens,
        )
        results.append({
            "status": outcome["status"],
            "event_key": outcome.get("event_key"),
            "receipt_path": outcome.get("receipt_path"),
            "reason": outcome.get("reason"),
        })
    summary = {
        "kind": "repoground.publisher_event_handoff_batch",
        "version": 1, "count": len(results),
        "published": sum(row["status"] == "published" for row in results),
        "deduplicated": sum(row["status"] == "deduplicated" for row in results),
        "blocked": sum(row["status"] == "blocked" for row in results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 2 if summary["blocked"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publisher-only, bounded, idempotent Git/CI event evidence handoff",
    )
    parser.add_argument("--repo-root", help="Required only for authorized event publication")
    parser.add_argument("--outbox-root", required=True)
    parser.add_argument("--bundle-manifest", help="Existing published bundle, never refresh")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--event-file", help="UTF-8 JSON object or bounded JSONL (write-side)")
    operation.add_argument("--read-event-key", help="SHA-256 event receipt key (read-only)")
    parser.add_argument("--format", choices=("json", "jsonl"), default="json")
    parser.add_argument("--max-events", type=int, default=16)
    parser.add_argument("--budget-tokens", type=int, default=1200)
    args = parser.parse_args(argv)

    if args.read_event_key is not None:
        return _read_event_cli(args)
    try:
        events = _load_cli_events(args, parser)
        return _publish_cli_events(args, events)
    except (EventInputError, UnicodeError, OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())