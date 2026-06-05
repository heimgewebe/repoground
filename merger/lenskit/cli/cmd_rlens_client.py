"""rLens HTTP CLI client. No new runtime dependencies."""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional, Tuple

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_SSE_TIMEOUT_SECONDS = 300

# Profile config keys allowed at the profile level. Tokens or secrets are
# deliberately not part of this set — secrets must come from env (RLENS_TOKEN
# or a profile-named token_env) or from --token, never from a repo-tracked or
# config file.
_PROFILE_ALLOWED_KEYS = frozenset({"base_url", "token_env"})
_PROFILE_FORBIDDEN_KEYS = frozenset({"token", "rlens_token", "secret"})


def _validate_profile_config(data: Any, path: pathlib.Path) -> dict:
    if not isinstance(data, dict):
        raise ValueError(f"Profile config root must be a JSON object ({path})")
    profiles = data.get("profiles")
    if profiles is not None and not isinstance(profiles, dict):
        raise ValueError(f"Profile config 'profiles' must be a JSON object ({path})")
    default_profile = data.get("default_profile")
    if default_profile is not None and not isinstance(default_profile, str):
        raise ValueError(f"Profile config 'default_profile' must be a string ({path})")

    for name, profile in (profiles or {}).items():
        if not isinstance(profile, dict):
            raise ValueError(f"Profile {name!r} must be a JSON object")
        forbidden = _PROFILE_FORBIDDEN_KEYS.intersection(profile.keys())
        if forbidden:
            raise ValueError(
                f"Profile {name!r} contains forbidden key(s) {sorted(forbidden)}; "
                "secrets must come from env (token_env) or --token, never from config"
            )
        unknown = set(profile.keys()) - _PROFILE_ALLOWED_KEYS
        if unknown:
            raise ValueError(
                f"Profile {name!r} has unknown key(s) {sorted(unknown)}; "
                f"allowed: {sorted(_PROFILE_ALLOWED_KEYS)}"
            )
        base_url = profile.get("base_url")
        if base_url is not None and not isinstance(base_url, str):
            raise ValueError(f"Profile {name!r} 'base_url' must be a string")
        if isinstance(base_url, str):
            parsed = urllib.parse.urlparse(base_url)
            scheme = parsed.scheme.lower()
            if scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(
                    f"Profile {name!r} 'base_url' must be an absolute "
                    "http:// or https:// URL"
                )
        token_env = profile.get("token_env")
        if token_env is not None and not isinstance(token_env, str):
            raise ValueError(f"Profile {name!r} 'token_env' must be a string")
    return data


def _profile_config_path() -> pathlib.Path:
    explicit = os.environ.get("LENSKIT_RLENS_PROFILES")
    if explicit:
        return pathlib.Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg).expanduser() if xdg else pathlib.Path.home() / ".config"
    return base / "lenskit" / "rlens-profiles.json"


def _load_profile_config(path: pathlib.Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Profile config unreadable ({path}): {e}") from None
    return _validate_profile_config(data, path)


def _is_profile_explicitly_requested(args: argparse.Namespace) -> bool:
    name = getattr(args, "leaf_profile", None) or getattr(args, "profile", None)
    env_name = os.environ.get("RLENS_PROFILE") or None
    return bool(name or env_name)


def _ensure_profile_config_valid_if_present(args: argparse.Namespace) -> None:
    _ = args
    path = _profile_config_path()
    if path.exists():
        _load_profile_config(path)


def _select_profile(args: argparse.Namespace) -> Optional[Tuple[str, dict]]:
    """Return (name, profile_dict) or None if no profile selected.

    Raises ValueError for explicit-but-broken selections so callers can map to
    config_error exit code.
    """
    name = getattr(args, "leaf_profile", None) or getattr(args, "profile", None)
    env_name = os.environ.get("RLENS_PROFILE") or None
    explicit_request = bool(name or env_name)
    if not name:
        name = env_name

    path = _profile_config_path()
    if not path.exists():
        if explicit_request:
            raise ValueError(
                f"Profile {name!r} requested but config not found at {path}"
            )
        return None

    data = _load_profile_config(path)
    profiles = data.get("profiles") or {}
    if not name:
        default_name = data.get("default_profile")
        if not default_name:
            return None
        name = default_name

    if name not in profiles:
        raise ValueError(f"Profile {name!r} not found in {path}")
    profile = profiles[name]
    return name, profile


def _resolve_base_url(args: argparse.Namespace) -> str:
    base_url = getattr(args, "leaf_base_url", None) or getattr(args, "base_url", None)
    profile: Optional[Tuple[str, dict]] = None
    if _is_profile_explicitly_requested(args):
        profile = _select_profile(args)
    if not base_url:
        base_url = os.environ.get("RLENS_BASE_URL")
    if not base_url:
        if profile is None:
            profile = _select_profile(args)
        if profile is not None:
            base_url = profile[1].get("base_url")
    base = base_url if base_url else DEFAULT_BASE_URL
    parsed = urllib.parse.urlparse(base)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Base URL config must be an absolute http:// or https:// URL")
    return base.rstrip("/")


def _resolve_token(args: argparse.Namespace) -> Optional[str]:
    token = getattr(args, "leaf_token", None) or getattr(args, "token", None)
    if token:
        return token
    env_token = os.environ.get("RLENS_TOKEN")
    if env_token:
        return env_token
    profile = _select_profile(args)
    if profile is not None:
        token_env = profile[1].get("token_env")
        if token_env:
            return os.environ.get(token_env) or None
    return None


def _is_json_output(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "leaf_json", False) or getattr(args, "json", False))


def _redact(text: str, token: Optional[str]) -> str:
    safe_text = text
    if token and token in text:
        safe_text = safe_text.replace(token, "[REDACTED]")
    safe_text = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", safe_text, flags=re.IGNORECASE)
    return safe_text


def _exit_error(
    args: argparse.Namespace,
    error_kind: str,
    message: str,
    token: Optional[str] = None,
) -> int:
    safe_msg = _redact(message, token)
    if _is_json_output(args):
        print(json.dumps({"status": "error", "error_kind": error_kind, "message": safe_msg}))
    else:
        print(f"Error ({error_kind}): {safe_msg}", file=sys.stderr)
    return 1


def _exit_config_error(
    args: argparse.Namespace,
    message: str,
    token: Optional[str] = None,
) -> int:
    safe_msg = _redact(message, token)
    if _is_json_output(args):
        print(json.dumps({"status": "error", "error_kind": "config_error", "message": safe_msg}))
    else:
        print(f"Error (config_error): {safe_msg}", file=sys.stderr)
    return 2


def _fetch_json(url: str, token: Optional[str], timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body)


def _post_json(
    url: str,
    token: Optional[str],
    payload: Optional[dict] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    data = b""
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body)


def _post_json_with_errors(
    args: argparse.Namespace,
    url: str,
    token: Optional[str],
    payload: Optional[dict] = None,
) -> Tuple[Optional[Any], Optional[int]]:
    try:
        return _post_json(url, token, payload), None
    except urllib.error.HTTPError as e:
        return None, _exit_error(args, "remote_error", f"HTTP {e.code}: {e.reason}", token)
    except urllib.error.URLError as e:
        return None, _exit_error(args, "remote_error", f"Connection error: {e.reason}", token)
    except json.JSONDecodeError as e:
        return None, _exit_error(args, "parse_error", f"Invalid JSON response: {e}", token)
    except (ValueError, TimeoutError, OSError) as e:
        return None, _exit_error(args, "remote_error", f"Request failed: {e}", token)


def _fetch_json_with_errors(
    args: argparse.Namespace, url: str, token: Optional[str]
) -> Tuple[Optional[Any], Optional[int]]:
    try:
        return _fetch_json(url, token), None
    except urllib.error.HTTPError as e:
        return None, _exit_error(args, "remote_error", f"HTTP {e.code}: {e.reason}", token)
    except urllib.error.URLError as e:
        return None, _exit_error(args, "remote_error", f"Connection error: {e.reason}", token)
    except json.JSONDecodeError as e:
        return None, _exit_error(args, "parse_error", f"Invalid JSON response: {e}", token)
    except (ValueError, TimeoutError, OSError) as e:
        return None, _exit_error(args, "remote_error", f"Request failed: {e}", token)


def _add_common_options(
    parser: argparse.ArgumentParser,
    suppress_defaults: bool = False,
    dest_prefix: str = "",
) -> None:
    scalar_default = argparse.SUPPRESS if suppress_defaults else None
    flag_default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument(
        "--base-url",
        dest=f"{dest_prefix}base_url",
        default=scalar_default,
        help="rLens service base URL (overrides RLENS_BASE_URL; default: http://127.0.0.1:8787)",
    )
    parser.add_argument(
        "--token",
        dest=f"{dest_prefix}token",
        default=scalar_default,
        help="Bearer token (overrides RLENS_TOKEN env var)",
    )
    parser.add_argument(
        "--profile",
        dest=f"{dest_prefix}profile",
        default=scalar_default,
        help=(
            "Host profile name from rlens-profiles.json "
            "(overrides RLENS_PROFILE; --base-url/RLENS_BASE_URL take precedence)"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest=f"{dest_prefix}json",
        default=flag_default,
        help="Output raw JSON response",
    )


def register_rlens_client_commands(subparsers: argparse._SubParsersAction) -> None:
    client_parser = subparsers.add_parser(
        "rlens-client", help="Read-only rLens service client"
    )
    _add_common_options(client_parser)
    client_subparsers = client_parser.add_subparsers(
        dest="rlens_cmd", help="rLens client subcommands"
    )

    health_parser = client_subparsers.add_parser("health", help="Check service health")
    _add_common_options(health_parser, suppress_defaults=True, dest_prefix="leaf_")

    artifacts_parser = client_subparsers.add_parser("artifacts", help="List artifacts")
    _add_common_options(artifacts_parser, suppress_defaults=True, dest_prefix="leaf_")
    artifacts_parser.add_argument("--repo", default=None, help="Filter by repository name")

    latest_parser = client_subparsers.add_parser(
        "latest", help="Get latest artifact for a repository"
    )
    _add_common_options(latest_parser, suppress_defaults=True, dest_prefix="leaf_")
    latest_parser.add_argument("--repo", required=True, help="Repository name (required)")
    latest_parser.add_argument("--level", default="max", help="Level (default: max)")
    latest_parser.add_argument("--mode", default="gesamt", help="Mode (default: gesamt)")

    jobs_parser = client_subparsers.add_parser("jobs", help="List jobs")
    _add_common_options(jobs_parser, suppress_defaults=True, dest_prefix="leaf_")
    jobs_parser.add_argument("--status", default=None, help="Filter by job status")
    jobs_parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of jobs to return"
    )

    job_parser = client_subparsers.add_parser("job", help="Get job details by id")
    _add_common_options(job_parser, suppress_defaults=True, dest_prefix="leaf_")
    job_parser.add_argument("job_id", help="Job ID")

    run_parser = client_subparsers.add_parser(
        "run", help="Create or reuse an rLens bundle job"
    )
    _add_common_options(run_parser, suppress_defaults=True, dest_prefix="leaf_")
    run_parser.add_argument(
        "--repo",
        action="append",
        default=None,
        help="Repository name to include; repeat for multiple repos (omit for all)",
    )
    run_parser.add_argument("--hub", default=None, help="Hub path override")
    run_parser.add_argument("--merges-dir", default=None, help="Output directory override")
    run_parser.add_argument(
        "--level",
        choices=("overview", "summary", "dev", "max"),
        default="dev",
        help="Bundle level (default: dev, matching JobRequest)",
    )
    run_parser.add_argument(
        "--mode",
        choices=("gesamt", "pro-repo"),
        default="gesamt",
        help="Bundle mode (default: gesamt)",
    )
    run_parser.add_argument("--force-new", action="store_true", help="Do not reuse matching existing jobs")
    run_parser.add_argument("--plan-only", action="store_true", help="Plan only; do not write bundle artifacts")
    pre_pull_group = run_parser.add_mutually_exclusive_group()
    pre_pull_group.add_argument(
        "--pre-pull",
        dest="pre_pull",
        action="store_true",
        default=None,
        help="Fast-forward-only update before scanning (default: enabled unless --plan-only)",
    )
    pre_pull_group.add_argument(
        "--no-pre-pull",
        dest="pre_pull",
        action="store_false",
        help="Disable the fast-forward-only pre-pull; scan the current on-disk state as-is",
    )

    cancel_parser = client_subparsers.add_parser("cancel", help="Request job cancellation")
    _add_common_options(cancel_parser, suppress_defaults=True, dest_prefix="leaf_")
    cancel_parser.add_argument("job_id", help="Job ID")

    logs_parser = client_subparsers.add_parser(
        "logs", help="Stream job logs via SSE until event: end"
    )
    _add_common_options(logs_parser, suppress_defaults=True, dest_prefix="leaf_")
    logs_parser.add_argument("job_id", help="Job ID")
    logs_parser.add_argument(
        "--last-id",
        type=int,
        default=None,
        dest="last_id",
        help="Resume from this SSE event id (server clamps negatives to 0)",
    )
    logs_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Per-read timeout in seconds for the SSE stream "
            f"(default: {DEFAULT_SSE_TIMEOUT_SECONDS})"
        ),
    )

    profiles_parser = client_subparsers.add_parser(
        "profiles", help="List configured host profiles"
    )
    _add_common_options(profiles_parser, suppress_defaults=True, dest_prefix="leaf_")


def _cmd_health(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))
    url = f"{base_url}/api/health"
    data, error_code = _fetch_json_with_errors(args, url, token)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    print(f"status: {data.get('status', '?')}")
    if "version" in data:
        print(f"version: {data['version']}")
    if "server_version" in data:
        print(f"server_version: {data['server_version']}")
    if "hub" in data:
        print(f"hub: {data['hub']}")
    if "running_jobs" in data:
        print(f"running_jobs: {data['running_jobs']}")
    if "auth_enabled" in data:
        print(f"auth_enabled: {data['auth_enabled']}")
    return 0


def _cmd_artifacts(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))
    url = f"{base_url}/api/artifacts"
    if args.repo:
        url = f"{url}?{urllib.parse.urlencode({'repo': args.repo})}"
    data, error_code = _fetch_json_with_errors(args, url, token)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    items = data if isinstance(data, list) else []
    if not items:
        print("No artifacts found.")
        return 0
    for item in items:
        artifact_id = item.get("id", "?")
        repos = item.get("repos", item.get("repo", "?"))
        created_at = item.get("created_at", "?")
        paths = item.get("paths") or {}
        primary = None
        if isinstance(paths, dict):
            primary = paths.get("primary") or next(iter(paths.values()), None)
        line = f"  {artifact_id}  repos={repos}  created={created_at}"
        if primary:
            line += f"  path={primary}"
        print(line)
    return 0


def _cmd_latest(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))
    params = urllib.parse.urlencode({"repo": args.repo, "level": args.level, "mode": args.mode})
    url = f"{base_url}/api/artifacts/latest?{params}"
    data, error_code = _fetch_json_with_errors(args, url, token)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    print(f"id: {data.get('id', '?')}")
    print(f"repos: {data.get('repos', data.get('repo', '?'))}")
    print(f"created_at: {data.get('created_at', '?')}")
    paths = data.get("paths") or {}
    if isinstance(paths, dict):
        primary = paths.get("primary") or next(iter(paths.values()), None)
        if primary:
            print(f"path: {primary}")
    return 0


def _cmd_jobs(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))

    if args.limit is not None and args.limit < 1:
        return _exit_config_error(args, "--limit must be a positive integer", token)

    params: dict = {}
    if args.status:
        params["status"] = args.status
    if args.limit is not None:
        params["limit"] = args.limit

    url = f"{base_url}/api/jobs"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    data, error_code = _fetch_json_with_errors(args, url, token)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    items = data if isinstance(data, list) else []
    if not items:
        print("No jobs found.")
        return 0
    for item in items:
        job_id = item.get("id", "?")
        status = item.get("status", "?")
        created_at = item.get("created_at", "?")
        line = f"  {job_id}  status={status}  created={created_at}"
        print(line)
    return 0


def _cmd_job(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))

    url = f"{base_url}/api/jobs/{urllib.parse.quote(args.job_id, safe='')}"
    data, error_code = _fetch_json_with_errors(args, url, token)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    print(f"id: {data.get('id', '?')}")
    print(f"status: {data.get('status', '?')}")
    print(f"created_at: {data.get('created_at', '?')}")
    if data.get("started_at"):
        print(f"started_at: {data['started_at']}")
    if data.get("finished_at"):
        print(f"finished_at: {data['finished_at']}")
    if data.get("hub_resolved"):
        print(f"hub: {data['hub_resolved']}")
    artifact_ids = data.get("artifact_ids") or []
    if artifact_ids:
        print(f"artifacts: {', '.join(artifact_ids)}")
    if data.get("error"):
        print(f"error: {data['error']}")
    for warning in data.get("warnings") or []:
        print(f"warning: {warning}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    # plan_only never mutates local repos; an explicit --pre-pull contradicts it.
    # Reject before any network/config work so no HTTP request is made.
    if args.plan_only and args.pre_pull is True:
        return _exit_config_error(
            args, "--plan-only and --pre-pull are mutually exclusive (plan_only never mutates local repos)."
        )

    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))

    payload: dict = {
        "level": args.level,
        "mode": args.mode,
    }
    if args.repo:
        payload["repos"] = args.repo
    if args.hub:
        payload["hub"] = args.hub
    if args.merges_dir:
        payload["merges_dir"] = args.merges_dir
    if args.force_new:
        payload["force_new"] = True
    if args.plan_only:
        payload["plan_only"] = True
    # Effective pre_pull: explicit flag wins; otherwise default true unless plan_only.
    # Always sent explicitly so behavior is unambiguous and easy to assert in tests.
    effective_pre_pull = args.pre_pull
    if effective_pre_pull is None:
        effective_pre_pull = not args.plan_only
    payload["pre_pull"] = effective_pre_pull

    url = f"{base_url}/api/jobs"
    data, error_code = _post_json_with_errors(args, url, token, payload)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    print(f"id: {data.get('id', '?')}")
    print(f"status: {data.get('status', '?')}")
    repos = data.get("repos")
    if repos:
        if isinstance(repos, list):
            print(f"repos: {', '.join(str(repo) for repo in repos)}")
        else:
            print(f"repos: {repos}")
    if data.get("hub_resolved"):
        print(f"hub: {data['hub_resolved']}")
    return 0


def _cmd_cancel(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))

    url = f"{base_url}/api/jobs/{urllib.parse.quote(args.job_id, safe='')}/cancel"
    data, error_code = _post_json_with_errors(args, url, token, None)
    if error_code is not None:
        return error_code

    if _is_json_output(args):
        print(json.dumps(data, indent=2))
        return 0

    print(f"status: {data.get('status', '?')}")
    if data.get("message"):
        print(f"message: {data['message']}")
    return 0


def _strip_sse_value(value: str) -> str:
    # Per SSE spec, a single optional leading space after the colon is stripped.
    if value.startswith(" "):
        return value[1:]
    return value


def _dispatch_sse_event(
    event: dict, json_output: bool, token: Optional[str]
) -> Optional[int]:
    event_type = event.get("event")
    if event_type == "end":
        return 0

    data = _redact(event.get("data", ""), token)
    if json_output:
        payload: dict = {"data": data}
        if "id" in event:
            payload["id"] = event["id"]
        if event_type:
            payload["event"] = event_type
        print(json.dumps(payload), flush=True)
    else:
        print(data, flush=True)
    return None


def _cmd_logs(args: argparse.Namespace) -> int:
    try:
        _ensure_profile_config_valid_if_present(args)
        token = _resolve_token(args)
        base_url = _resolve_base_url(args)
    except ValueError as e:
        return _exit_config_error(args, str(e))

    params: dict = {}
    if args.last_id is not None:
        params["last_id"] = args.last_id

    url = f"{base_url}/api/jobs/{urllib.parse.quote(args.job_id, safe='')}/logs"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "text/event-stream")

    timeout = args.timeout if args.timeout is not None else DEFAULT_SSE_TIMEOUT_SECONDS
    if timeout <= 0:
        return _exit_config_error(args, "--timeout must be greater than 0", token)

    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return _exit_error(args, "remote_error", f"HTTP {e.code}: {e.reason}", token)
    except urllib.error.URLError as e:
        return _exit_error(args, "remote_error", f"Connection error: {e.reason}", token)
    except (ValueError, TimeoutError, OSError) as e:
        return _exit_error(args, "remote_error", f"Request failed: {e}", token)

    json_output = _is_json_output(args)

    try:
        current_event: dict = {}
        for raw_line in response:
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace")
            else:
                line = raw_line
            line = line.rstrip("\r\n")

            if line == "":
                if current_event:
                    rc = _dispatch_sse_event(current_event, json_output, token)
                    current_event = {}
                    if rc is not None:
                        return rc
                continue

            if line.startswith(":"):
                continue

            field, sep, value = line.partition(":")
            if not sep:
                continue
            value = _strip_sse_value(value)

            if field == "data":
                if "data" in current_event:
                    current_event["data"] += "\n" + value
                else:
                    current_event["data"] = value
            elif field in ("id", "event"):
                current_event[field] = value
            # Other field names are ignored per SSE spec.

        if current_event:
            rc = _dispatch_sse_event(current_event, json_output, token)
            if rc is not None:
                return rc
        return 0
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return _exit_error(args, "remote_error", f"Stream error: {e}", token)
    finally:
        try:
            response.close()
        except Exception:
            pass


def _cmd_profiles(args: argparse.Namespace) -> int:
    path = _profile_config_path()
    json_output = _is_json_output(args)

    if not path.exists():
        if json_output:
            print(json.dumps({
                "config_path": str(path),
                "exists": False,
                "default_profile": None,
                "profiles": {},
            }, indent=2))
        else:
            print(f"No profile config at {path}")
        return 0

    try:
        data = _load_profile_config(path)
    except ValueError as e:
        return _exit_config_error(args, str(e))

    profiles_raw = data.get("profiles") or {}
    default_profile = data.get("default_profile")

    # Build a redacted view: only base_url and token_env name (never token values).
    safe_profiles: dict = {}
    for name, profile in profiles_raw.items():
        if not isinstance(profile, dict):
            continue
        entry: dict = {}
        if isinstance(profile.get("base_url"), str):
            entry["base_url"] = profile["base_url"]
        if isinstance(profile.get("token_env"), str):
            entry["token_env"] = profile["token_env"]
        safe_profiles[name] = entry

    if json_output:
        print(json.dumps({
            "config_path": str(path),
            "exists": True,
            "default_profile": default_profile if isinstance(default_profile, str) else None,
            "profiles": safe_profiles,
        }, indent=2))
        return 0

    print(f"config: {path}")
    if default_profile:
        print(f"default: {default_profile}")
    if not safe_profiles:
        print("No profiles defined.")
        return 0
    for name, entry in safe_profiles.items():
        marker = " (default)" if name == default_profile else ""
        base = entry.get("base_url", "?")
        line = f"  {name}{marker}  base_url={base}"
        if "token_env" in entry:
            line += f"  token_env={entry['token_env']}"
        print(line)
    return 0


def run_rlens_client(args: argparse.Namespace) -> int:
    if not hasattr(args, "rlens_cmd") or args.rlens_cmd is None:
        print("Usage: lenskit rlens-client <subcommand>", file=sys.stderr)
        print(
            "Subcommands: health, artifacts, latest, jobs, job, run, cancel, logs, profiles",
            file=sys.stderr,
        )
        return 2
    if args.rlens_cmd == "health":
        return _cmd_health(args)
    if args.rlens_cmd == "artifacts":
        return _cmd_artifacts(args)
    if args.rlens_cmd == "latest":
        return _cmd_latest(args)
    if args.rlens_cmd == "jobs":
        return _cmd_jobs(args)
    if args.rlens_cmd == "job":
        return _cmd_job(args)
    if args.rlens_cmd == "run":
        return _cmd_run(args)
    if args.rlens_cmd == "cancel":
        return _cmd_cancel(args)
    if args.rlens_cmd == "logs":
        return _cmd_logs(args)
    if args.rlens_cmd == "profiles":
        return _cmd_profiles(args)
    print(f"Unknown rlens-client subcommand: {args.rlens_cmd!r}", file=sys.stderr)
    return 2
