"""Read-only audit for active RepoGround naming aliases."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MAX_CONFIG_BYTES = 1024 * 1024
MAX_CMDLINE_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_FINDINGS = 500

FORMER_PRODUCT_TERMS: tuple[str, ...] = (
    "repo" + "brief",
    "lens" + "kit",
    "repo" + "lens",
    "r" + "lens",
)
FORMER_SERVICE_UNIT = "r" + "lens" + ".service"

SOURCE_ROOTS = ("merger/repoground", "repoground", "scripts", "tests")
SOURCE_SUFFIXES = {".py", ".sh", ".js", ".html"}

PROMPT_EXECUTABLES = frozenset({"agy", "chatgpt", "claude", "cline", "codex"})
PROMPT_ARGUMENT_FLAGS = frozenset(
    {
        "--prompt",
        "-p",
        "--system-prompt",
        "--append-system-prompt",
        "--message",
        "--instructions",
    }
)
CONFIG_VALUE_KEYS = frozenset(
    {
        "args",
        "argv",
        "bundle_root",
        "command",
        "env",
        "environment",
        "executable",
        "module",
        "path",
        "program",
        "root",
        "unit",
        "uri",
        "url",
    }
)

# These are executable aliases or runtime locations. Versioned kind/schema values
# are deliberately not listed: they remain exact persisted-data contracts.
def _active_alias_patterns() -> dict[str, tuple[str, ...]]:
    old_cache_prefix = ("lens" + "kit_repo" + "brief").upper()
    old_profile_var = ("lens" + "kit_repo" + "ground_profiles").upper()
    old_ui_global = "__" + ("r" + "lens").upper() + "_UI_VERSION__"
    old_service_dir = "." + "r" + "lens-service"
    old_snapshot_dir = "." + "r" + "lens-source-snapshots"
    old_state = ".repo" + "Lens-state.json"
    old_pr_root = ".repo" + "lens/pr-schau"
    return {
        "former-cache-environment": (
            old_cache_prefix + "_CACHE_VALIDATION",
            old_cache_prefix + "_STRICT_CACHE_HASH",
        ),
        "former-profile-environment": (old_profile_var,),
        "former-runtime-storage": (
            old_service_dir,
            old_snapshot_dir,
            old_state,
            old_pr_root,
            "rlens-job-",
        ),
        "former-ui-global": (old_ui_global,),
        "former-python-symbol": (
            "_load_repo" + "lens_extractor_module",
            "find_repo" + "lens_dirs",
            "run_r" + "lens_fixture",
            "run_repo" + "lens_fixture",
        ),
        "former-command-alias": (
            "repo" + "brief-mcp-stdio.py",
            "r" + "lens-client",
        ),
        "former-generator-name": (
            '"name": "r' + 'lens"',
            '"name": "repo' + 'lens"',
            '"name": "lens' + 'kit"',
        ),
    }

ACTIVE_ALIAS_PATTERNS = _active_alias_patterns()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _matched_active_aliases(text: str) -> list[str]:
    return sorted(
        category
        for category, patterns in ACTIVE_ALIAS_PATTERNS.items()
        if any(pattern in text for pattern in patterns)
    )


def _external_alias_patterns() -> dict[str, tuple[str, ...]]:
    old_cache_prefix = ("lens" + "kit_repo" + "brief").upper()
    old_profile_var = ("lens" + "kit_repo" + "ground_profiles").upper()
    return {
        "former-command-alias": (
            "repo" + "brief-mcp-stdio.py",
            "r" + "lens-client",
            "r" + "lens-launcher.sh",
        ),
        "former-resource-scheme": ("repo" + "brief://",),
        "former-environment": (
            old_cache_prefix + "_CACHE_VALIDATION",
            old_cache_prefix + "_STRICT_CACHE_HASH",
            old_profile_var,
            ("r" + "lens_").upper(),
            ("repo" + "lens_").upper(),
            ("r" + "b_").upper(),
        ),
        "former-runtime-storage": (
            "." + "r" + "lens-service",
            "." + "r" + "lens-source-snapshots",
            "r" + "lens-job-",
            ".repo" + "Lens-state.json",
            ".repo" + "lens/pr-schau",
            "/.local/state/" + "repobrief-publish/",
            "/logs/" + "repobrief-publish",
            "." + "rb-prune-quarantine",
        ),
        "former-service-unit": (FORMER_SERVICE_UNIT,),
        "former-python-module": ("merger." + "lens" + "kit",),
        "former-repository-path": ("/repos/" + "lens" + "kit",),
        "former-bundle-storage": (
            "/.local/share/" + "repo" + "brief/",
            "lens" + "kit-briefs",
        ),
        "former-ui-global": (
            "__" + ("r" + "lens").upper() + "_UI_VERSION__",
        ),
    }


EXTERNAL_ALIAS_PATTERNS = _external_alias_patterns()


def _matched_external_names(text: str) -> list[str]:
    lowered = text.casefold()
    return sorted(
        term for term in FORMER_PRODUCT_TERMS if term.casefold() in lowered
    )


def _matched_external_aliases(text: str) -> list[str]:
    return sorted(
        category
        for category, patterns in EXTERNAL_ALIAS_PATTERNS.items()
        if any(pattern in text for pattern in patterns)
    )


def _is_prompt_process(argv: list[str]) -> bool:
    for token in argv[:3]:
        name = Path(token).name.casefold()
        stem = Path(name).stem
        if name in PROMPT_EXECUTABLES or stem in PROMPT_EXECUTABLES:
            return True
    return False


def _matched_process_aliases(argv: list[str]) -> list[str]:
    matches: set[str] = set()
    former_command = "repo" + "brief"
    prompt_process = _is_prompt_process(argv)
    skip_next_as_prompt = False
    for token in argv:
        if skip_next_as_prompt:
            skip_next_as_prompt = False
            continue
        if prompt_process and token in PROMPT_ARGUMENT_FLAGS:
            skip_next_as_prompt = True
            continue
        if prompt_process and any(
            token.startswith(flag + "=") for flag in PROMPT_ARGUMENT_FLAGS
        ):
            continue
        # A long argument containing whitespace is commonly an agent prompt or
        # explanatory text. It is not an executable command, URI, env assignment
        # or path token and therefore must not block a live cutover.
        if prompt_process and any(character.isspace() for character in token):
            continue
        if token == former_command:
            matches.add("former-command-alias")
        matches.update(_matched_external_aliases(token))
        basename = Path(token).name
        if basename == former_command:
            matches.add("former-command-alias")
        matches.update(_matched_external_aliases(basename))
    return sorted(matches)


def _config_string_aliases(value: str, *, command_value: bool = False) -> set[str]:
    matches = set(_matched_external_aliases(value))
    if command_value and value == "repo" + "brief":
        matches.add("former-command-alias")
    return matches


def _json_config_aliases(
    payload: Any,
    *,
    semantic_context: bool = False,
) -> set[str]:
    matches: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            matches.update(_matched_external_aliases(key_text))
            child_semantic = semantic_context or key_text.casefold() in CONFIG_VALUE_KEYS
            if child_semantic and isinstance(value, str):
                matches.update(
                    _config_string_aliases(
                        value,
                        command_value=key_text.casefold() == "command",
                    )
                )
            elif isinstance(value, (dict, list)):
                matches.update(
                    _json_config_aliases(
                        value,
                        semantic_context=child_semantic,
                    )
                )
    elif isinstance(payload, list):
        for item in payload:
            if semantic_context and isinstance(item, str):
                matches.update(_config_string_aliases(item))
            elif isinstance(item, (dict, list)):
                matches.update(
                    _json_config_aliases(
                        item,
                        semantic_context=semantic_context,
                    )
                )
    return matches


def _line_config_aliases(text: str) -> set[str]:
    matches: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        separator = "=" if "=" in line else ":" if ":" in line else ""
        if not separator:
            continue
        key, value = line.split(separator, 1)
        key = key.strip().strip("\"'")
        value = value.strip().strip("\"'")
        matches.update(_matched_external_aliases(key))
        if key.casefold() in CONFIG_VALUE_KEYS:
            matches.update(
                _config_string_aliases(
                    value,
                    command_value=key.casefold() == "command",
                )
            )
    return matches


def _matched_config_aliases(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        matches = _line_config_aliases(text)
    else:
        matches = _json_config_aliases(payload)
    return sorted(matches)


def scan_processes(proc_root: str | Path = "/proc") -> list[dict[str, Any]]:
    """Return redacted findings for running commands using former names."""
    root = Path(proc_root)
    findings: list[dict[str, Any]] = []
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return findings
    observer_pid = os.getpid()
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == observer_pid:
            continue
        try:
            with (entry / "cmdline").open("rb") as handle:
                raw = handle.read(MAX_CMDLINE_BYTES + 1)
        except OSError:
            continue
        if not raw or len(raw) > MAX_CMDLINE_BYTES:
            continue
        argv = [
            token.decode("utf-8", errors="replace")
            for token in raw.split(b"\0")
            if token
        ]
        matches = _matched_process_aliases(argv)
        if matches:
            findings.append(
                {
                    "pid": int(entry.name),
                    "executable": Path(argv[0]).name,
                    "matched_aliases": matches,
                    "matched_names": _matched_external_names(" ".join(argv)),
                    "argv_sha256": _sha256(raw),
                }
            )
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def scan_configs(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Hash configs and report former active names without returning contents."""
    findings: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        try:
            with path.open("rb") as handle:
                data = handle.read(MAX_CONFIG_BYTES + 1)
        except OSError as exc:
            findings.append({
                "path": str(path), "status": "unavailable",
                "reason": type(exc).__name__,
                "matched_aliases": [], "matched_names": [],
            })
            continue
        if len(data) > MAX_CONFIG_BYTES:
            findings.append({
                "path": str(path), "status": "blocked",
                "reason": "config_too_large", "max_bytes": MAX_CONFIG_BYTES,
                "matched_aliases": [], "matched_names": [],
            })
            continue
        decoded = data.decode("utf-8", errors="replace")
        aliases = _matched_config_aliases(decoded)
        findings.append({
            "path": str(path), "status": "scanned", "bytes": len(data),
            "sha256": _sha256(data),
            "matched_aliases": aliases,
            "matched_names": _matched_external_names(decoded) if aliases else [],
        })
    return findings


def _iter_source_files(root: Path):
    for relative_root in SOURCE_ROOTS:
        scan_root = root / relative_root
        if not scan_root.is_dir():
            continue
        for path in sorted(scan_root.rglob("*")):
            if path.is_file() and path.suffix in SOURCE_SUFFIXES:
                yield path, path.relative_to(root).as_posix()


def _is_scannable_source(path: Path, relative: str) -> bool:
    if "/contracts/" in f"/{relative}/" or "/fixtures/" in f"/{relative}/":
        return False
    if relative == "merger/repoground/core/naming_audit.py":
        return False
    try:
        return path.stat().st_size <= MAX_SOURCE_BYTES
    except OSError:
        return False


def _read_source(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _executable_path_aliases(path: Path, relative: str) -> list[str]:
    if path.suffix not in {".py", ".sh"}:
        return []
    lowered = relative.casefold()
    terms = ("repolens", "rlens", "repobrief", "lenskit")
    return ["former-executable-path"] if any(term in lowered for term in terms) else []


def scan_repository(repo_root: str | Path) -> list[dict[str, Any]]:
    """Find executable alias mechanisms while ignoring versioned data IDs."""
    root = Path(repo_root).resolve()
    findings: list[dict[str, Any]] = []
    for path, relative in _iter_source_files(root):
        if not _is_scannable_source(path, relative):
            continue
        source = _read_source(path)
        if source is None:
            continue
        matches = _matched_active_aliases(source)
        matches.extend(_executable_path_aliases(path, relative))
        combined = sorted(set(matches))
        if combined:
            findings.append({"path": relative, "matched_aliases": combined})
        if len(findings) >= MAX_FINDINGS:
            break
    return findings


def service_state(unit: str) -> dict[str, Any]:
    command = [
        "systemctl", "--user", "show", unit, "--no-pager",
        "--property=LoadState", "--property=ActiveState",
        "--property=SubState", "--property=UnitFileState",
    ]
    try:
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"unit": unit, "status": "unavailable", "reason": type(exc).__name__}
    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value
    return {
        "unit": unit,
        "status": "observed" if result.returncode == 0 else "unavailable",
        "returncode": result.returncode,
        "properties": properties,
    }


def build_audit(
    *,
    config_paths: Iterable[str | Path] = (),
    proc_root: str | Path = "/proc",
    repo_root: str | Path | None = None,
    include_services: bool = True,
) -> dict[str, Any]:
    processes = scan_processes(proc_root)
    configs = scan_configs(config_paths)
    repository = scan_repository(repo_root) if repo_root is not None else []
    config_matches = [item for item in configs if item.get("matched_aliases")]
    active_aliases_zero = not processes and not config_matches and not repository
    services = (
        [service_state("repoground.service"), service_state(FORMER_SERVICE_UNIT)]
        if include_services else []
    )
    return {
        "schema": "repoground.naming_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "observer_pid": os.getpid(),
        "read_only": True,
        "raw_command_lines_included": False,
        "raw_config_contents_included": False,
        "active_aliases_zero": active_aliases_zero,
        "repository_alias_findings": repository,
        "process_findings": processes,
        "config_findings": configs,
        "service_states": services,
    }


def dumps_audit(audit: dict[str, Any]) -> str:
    return json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
