import argparse
import json
import sys
from pathlib import Path


def register_agent_consumption_commands(subparsers) -> None:
    parser = subparsers.add_parser(
        "agent-consumption",
        help="Agent consumption operations (Required Reading & Trace Validation)"
    )
    subparsers_ac = parser.add_subparsers(
        dest="agent_consumption_cmd", required=True, help="Agent consumption commands"
    )

    # required command
    req_parser = subparsers_ac.add_parser(
        "required", help="Generate a Required Reading Result"
    )
    req_parser.add_argument("--task-profile", required=True, help="Task profile (e.g., pr_review)")
    req_parser.add_argument("--available-roles", help="Comma-separated list of available roles")
    req_parser.add_argument("--available-roles-file", help="Path to JSON file containing available roles")
    req_parser.add_argument("--out", "--output", dest="out", help="Output path for the result JSON")

    # preflight command
    pre_parser = subparsers_ac.add_parser(
        "preflight",
        help="Resolve required reading and emit an answer-compliance template",
    )
    pre_parser.add_argument("--task-profile", required=True, help="Task profile (e.g., pr_review)")
    pre_parser.add_argument("--available-roles", help="Comma-separated list of available roles")
    pre_parser.add_argument("--available-roles-file", help="Path to JSON file containing available roles")
    pre_parser.add_argument("--bundle-manifest", help="Path to a bundle manifest to derive available roles")
    pre_parser.add_argument("--answer-compliance", help="Optional Answer Compliance JSON to validate")
    pre_parser.add_argument("--strict", action="store_true", help="Treat 'warn' status as exit code 1")
    pre_parser.add_argument("--out", "--output", dest="out", help="Output path for the preflight JSON")

    # validate-trace command
    val_parser = subparsers_ac.add_parser(
        "validate-trace", help="Compare Required Reading Result with Answer Compliance"
    )
    val_parser.add_argument("--required-reading", required=True, help="Path to Required Reading Result JSON")
    val_parser.add_argument("--answer-compliance", required=True, help="Path to Answer Compliance JSON")
    val_parser.add_argument("--available-roles", help="Comma-separated list of available roles")
    val_parser.add_argument("--available-roles-file", help="Path to JSON file containing available roles")
    val_parser.add_argument("--strict", action="store_true", help="Treat 'warn' status as exit code 1")
    val_parser.add_argument("--out", "--output", dest="out", help="Output path for the trace JSON")


class AgentConsumptionCliError(Exception):
    """User-facing CLI input/output error."""


def _read_json_any(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise AgentConsumptionCliError(f"Invalid JSON in {path}: {e}") from e
    except OSError as e:
        raise AgentConsumptionCliError(f"Could not read {path}: {e}") from e


def _read_json_object(path: Path) -> dict:
    data = _read_json_any(path)
    if not isinstance(data, dict):
        raise AgentConsumptionCliError(f"Expected JSON object in {path}.")
    return data


def _write_json_or_stdout(payload: dict, out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if out is None:
        sys.stdout.write(text + "\n")
    else:
        try:
            out.write_text(text + "\n", encoding="utf-8")
        except OSError as e:
            raise AgentConsumptionCliError(f"Could not write to {out}: {e}") from e


def _parse_roles_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {r.strip() for r in value.split(",") if r.strip()}


def _load_roles_file(path: Path | None) -> set[str]:
    if path is None:
        return set()
    data = _read_json_any(path)
    if isinstance(data, list):
        roles = data
    elif isinstance(data, dict) and isinstance(data.get("available_roles"), list):
        roles = data["available_roles"]
    else:
        raise AgentConsumptionCliError(
            f"Invalid available roles file {path}: expected a JSON array "
            "or an object with an available_roles array."
        )
    return {str(x).strip() for x in roles if str(x).strip()}


def _collect_available_roles(csv_value: str | None, roles_file: Path | None) -> set[str]:
    roles = _parse_roles_csv(csv_value)
    roles |= _load_roles_file(roles_file)
    return roles


def _load_roles_from_bundle_manifest(path: Path | None) -> set[str]:
    if path is None:
        return set()
    data = _read_json_object(path)
    roles: set[str] = set()
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        raise AgentConsumptionCliError(
            f"Invalid bundle manifest {path}: expected artifacts array."
        )
    for artifact in artifacts:
        if isinstance(artifact, dict) and isinstance(artifact.get("role"), str):
            roles.add(artifact["role"])

    # Some diagnostic sidecars are linked, not registered as artifacts.  Make
    # them available for required-reading/preflight without pretending they are
    # bundle artifacts.
    links = data.get("links") or {}
    if isinstance(links, dict):
        if links.get("post_emit_health_path"):
            roles.add("post_emit_health")
        if links.get("bundle_surface_validation_path"):
            roles.add("bundle_surface_validation")
    return roles


def _require_keys(data: dict, keys: set[str], *, label: str) -> None:
    missing = sorted(keys - set(data))
    if missing:
        raise AgentConsumptionCliError(
            f"{label} missing required keys: {', '.join(missing)}"
        )


def _exit_for_status(status: str, *, strict: bool = False) -> int:
    if status == "pass":
        return 0
    if status == "warn":
        return 1 if strict else 0
    if status in ("fail", "not_applicable"):
        return 1
    return 2


def _answer_compliance_template(task_profile: str, artifacts: list[str]) -> dict:
    from merger.lenskit.core.agent_consumption_validate import DOES_NOT_ESTABLISH

    return {
        "task_profile": task_profile,
        "declared_artifacts": sorted(artifacts),
        "declared_citations": [],
        "declared_ranges": [],
        "epistemic_gaps": [],
        "unread_required_artifacts": [],
        "unread_recommended_artifacts": [],
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }


def _preflight_status(required_status: str, trace_status: str | None) -> str:
    if trace_status is not None:
        return trace_status
    return required_status


def run_agent_consumption_preflight(args: argparse.Namespace) -> int:
    from merger.lenskit.core.agent_consumption_validate import validate_agent_consumption
    from merger.lenskit.core.required_reading import (
        default_required_reading_protocol,
        resolve_required_reading,
    )

    try:
        roles_file_path = (
            Path(args.available_roles_file) if args.available_roles_file else None
        )
        manifest_path = Path(args.bundle_manifest) if args.bundle_manifest else None
        available_roles = _collect_available_roles(args.available_roles, roles_file_path)
        available_roles |= _load_roles_from_bundle_manifest(manifest_path)

        protocol = default_required_reading_protocol()
        required = resolve_required_reading(
            protocol, available_roles, args.task_profile
        )

        template_artifacts = sorted(
            set(required.get("available_required") or [])
            | set(required.get("available_recommended") or [])
        )
        if not template_artifacts:
            template_artifacts = sorted(set(required.get("required") or []))
        template = _answer_compliance_template(args.task_profile, template_artifacts)

        trace = None
        if args.answer_compliance:
            ac_data = _read_json_object(Path(args.answer_compliance))
            _require_keys(
                ac_data, {"task_profile", "declared_artifacts", "does_not_establish"},
                label="Answer compliance",
            )
            trace = validate_agent_consumption(
                required, ac_data, available_roles=available_roles
            )

        status = _preflight_status(
            required.get("status", "unknown"),
            trace.get("status") if isinstance(trace, dict) else None,
        )
        payload = {
            "kind": "lenskit.agent_consumption_preflight",
            "version": "1.0",
            "task_profile": args.task_profile,
            "status": status,
            "available_roles": sorted(available_roles),
            "required_reading": required,
            "answer_compliance_template": template,
            "agent_consumption_trace": trace,
            "does_not_establish": [
                "actual_reading_proven",
                "answer_correct",
                "repo_understood",
                "all_relevant_context_used",
                "claims_true",
                "test_sufficiency",
                "regression_absence",
                "runtime_behavior",
                "forensic_ready",
            ],
        }

        out_path = Path(args.out) if args.out else None
        _write_json_or_stdout(payload, out_path)
        return _exit_for_status(status, strict=args.strict)
    except AgentConsumptionCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: unexpected failure: {e}", file=sys.stderr)
        return 2


def run_agent_consumption_required(args: argparse.Namespace) -> int:
    from merger.lenskit.core.required_reading import (
        default_required_reading_protocol,
        resolve_required_reading,
    )

    try:
        roles_file_path = (
            Path(args.available_roles_file) if args.available_roles_file else None
        )
        available_roles = _collect_available_roles(args.available_roles, roles_file_path)

        protocol = default_required_reading_protocol()
        result = resolve_required_reading(
            protocol, available_roles, args.task_profile
        )

        out_path = Path(args.out) if args.out else None
        _write_json_or_stdout(result, out_path)

        return _exit_for_status(result.get("status", "unknown"))
    except AgentConsumptionCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: unexpected failure: {e}", file=sys.stderr)
        return 2


def run_agent_consumption_validate_trace(args: argparse.Namespace) -> int:
    from merger.lenskit.core.agent_consumption_validate import validate_agent_consumption

    try:
        rr_path = Path(args.required_reading)
        ac_path = Path(args.answer_compliance)

        rr_data = _read_json_object(rr_path)
        ac_data = _read_json_object(ac_path)

        _require_keys(
            rr_data, {"task_profile", "required", "recommended", "status"},
            label="Required reading"
        )
        _require_keys(
            ac_data, {"task_profile", "declared_artifacts", "does_not_establish"},
            label="Answer compliance"
        )

        roles_file_path = (
            Path(args.available_roles_file) if args.available_roles_file else None
        )
        available_roles = _collect_available_roles(args.available_roles, roles_file_path)

        explicit_roles = (
            args.available_roles is not None
            or args.available_roles_file is not None
        )
        available_roles_arg = available_roles if explicit_roles else None

        trace = validate_agent_consumption(
            rr_data, ac_data, available_roles=available_roles_arg
        )

        out_path = Path(args.out) if args.out else None
        _write_json_or_stdout(trace, out_path)

        return _exit_for_status(trace.get("status", "unknown"), strict=args.strict)
    except AgentConsumptionCliError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: unexpected failure: {e}", file=sys.stderr)
        return 2


def run_agent_consumption(args: argparse.Namespace) -> int:
    if args.agent_consumption_cmd == "required":
        return run_agent_consumption_required(args)
    if args.agent_consumption_cmd == "preflight":
        return run_agent_consumption_preflight(args)
    if args.agent_consumption_cmd == "validate-trace":
        return run_agent_consumption_validate_trace(args)
    return 2
