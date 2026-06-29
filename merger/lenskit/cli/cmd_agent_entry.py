import argparse
import json
import sys
from pathlib import Path


def register_agent_entry_commands(subparsers) -> None:
    parser = subparsers.add_parser(
        "agent-entry",
        help="Agent entry manifest operations",
    )
    agent_entry_subparsers = parser.add_subparsers(
        dest="agent_entry_cmd", required=True, help="Agent entry commands"
    )

    manifest_parser = agent_entry_subparsers.add_parser(
        "manifest",
        help="Build an Agent Entry Manifest from a bundle manifest",
    )
    manifest_parser.add_argument(
        "--bundle-manifest",
        required=True,
        help="Path to bundle-manifest.v1 JSON",
    )
    manifest_parser.add_argument(
        "--out",
        "--output",
        dest="out",
        help="Output path for the manifest JSON. Without --out, JSON is written to stdout only.",
    )


class AgentEntryCliError(Exception):
    """User-facing CLI input/output error."""


def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentEntryCliError(f"Invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise AgentEntryCliError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AgentEntryCliError(f"Expected JSON object in {path}.")
    return data


def _write_json_or_stdout(payload: dict, out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if out is None:
        sys.stdout.write(text)
        return
    try:
        out.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise AgentEntryCliError(f"Could not write to {out}: {exc}") from exc


def run_agent_entry_manifest(args: argparse.Namespace) -> int:
    from merger.lenskit.core.agent_entry_manifest import build_agent_entry_manifest

    try:
        bundle_manifest_path = Path(args.bundle_manifest)
        bundle_manifest = _read_json_object(bundle_manifest_path)
        payload = build_agent_entry_manifest(bundle_manifest)
        out_path = Path(args.out) if args.out else None
        _write_json_or_stdout(payload, out_path)
        return 0
    except AgentEntryCliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: unexpected failure: {exc}", file=sys.stderr)
        return 2


def run_agent_entry(args: argparse.Namespace) -> int:
    if args.agent_entry_cmd == "manifest":
        return run_agent_entry_manifest(args)
    return 2
