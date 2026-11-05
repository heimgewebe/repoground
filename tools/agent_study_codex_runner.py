#!/usr/bin/env python3
"""Read-only Codex JSONL adapter for RepoGround's existing three-arm study CLI.

This is one external JSON-stdio runner, not a new benchmark service. All Codex
events are preserved in a private trace; usage is copied only from turn.completed.
No model result, cost, citation, tool time, or quality grade is manufactured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

MCP_TOOLS = (
    "bundle_discover", "snapshot_status", "ask_context", "query_existing_index",
    "range_get", "grounding_verify", "live_freshness", "find_symbol",
    "find_references", "get_callers", "get_callees",
    "get_structure_neighborhood", "get_flake_relation_evidence",
)
TOOL_NAMES = {
    "git": ["codex_git_command"],
    "file": ["codex_file_command"],
    # MCP resource reads are a Codex client operation, not a server tools/list entry.
    "repoground": ["repoground_" + tool for tool in MCP_TOOLS]
    + ["repoground_read_mcp_resource"],
}
AGENT_VERSION = "codex-study-prompt-v3"
PROVIDER = "openai-codex-cli"
SOURCE_SEARCH_TOOLS = frozenset({
    "repoground_ask_context", "repoground_query_existing_index",
})
MAX_TRACE_BYTES = 32 * 1024 * 1024
MAX_TOOL_CALLS = 160
MODEL_TIMEOUT = 290
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,200}\Z")
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _exec(argv: list[str], *, cwd: Path | None = None) -> str:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=45, check=False)
    if p.returncode != 0:
        raise RuntimeError("source/runner command failed: " + argv[0])
    return p.stdout.decode("utf-8").strip()


def _private_dir(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("private study directory may not be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("study state directory unavailable")


def _open_private_create(path: Path) -> Any:
    if path.is_symlink():
        raise ValueError("refusing symlink output")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "wb")


def _create_once(path: Path, content: bytes) -> None:
    with _open_private_create(path) as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _config(path: Path) -> dict[str, Any]:
    cfg = _read_json(path)
    if set(cfg) != {
        "codex_bin", "mcp_python", "mcp_script",
        "source_roots", "workspaces_root", "trace_root",
    }:
        raise ValueError("runner configuration must have exact known fields")
    for key in ("codex_bin", "mcp_python", "mcp_script", "workspaces_root", "trace_root"):
        if not isinstance(cfg[key], str) or not Path(cfg[key]).is_absolute():
            raise ValueError("runner configuration needs absolute paths")
    roots = cfg["source_roots"]
    if not isinstance(roots, dict) or not roots:
        raise ValueError("source_roots required")
    if any(not isinstance(k, str) or not isinstance(v, str)
           or not Path(v).is_absolute() for k, v in roots.items()):
        raise ValueError("source_roots require absolute paths")
    for key in ("codex_bin", "mcp_python", "mcp_script"):
        if not Path(cfg[key]).is_file():
            raise ValueError("runner executable/script unavailable: " + key)
    return cfg


def _mcp_implementation_digest(mcp_script: str) -> tuple[str, int]:
    """Bind importable MCP implementation sources, not just its thin launcher.

    Deployed releases have no .git directory: use a source-content digest
    rather than inventing a Git SHA. Exclude test/fixture-only Python modules.
    """
    launcher = Path(mcp_script).resolve(strict=True)
    root = launcher.parents[1]
    paths: list[Path] = []
    for relative in ("merger/repoground", "repoground"):
        package = root / relative
        if package.is_dir():
            paths.extend(
                file for file in package.rglob("*.py")
                if not {"tests", "fixtures", "__pycache__"}.intersection(file.relative_to(root).parts)
            )
    if not paths or len(paths) > 2000:
        raise ValueError("MCP implementation source inventory unavailable or oversized")
    hasher = hashlib.sha256()
    for source in sorted(paths, key=lambda file: file.relative_to(root).as_posix()):
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("MCP implementation source unsafe")
        hasher.update(
            source.relative_to(root).as_posix().encode("utf-8")
            + b"\x00" + hashlib.sha256(source.read_bytes()).digest()
        )
    return hasher.hexdigest(), len(paths)


def _fingerprint(cfg: dict[str, Any]) -> dict[str, Any]:
    cli = _exec([cfg["codex_bin"], "--version"]).replace(" ", "-").strip()
    if not cli or len(cli) > 120:
        raise ValueError("unbounded Codex CLI version")
    script_sha = _digest(Path(__file__).read_bytes())
    mcp_sha = _digest(Path(cfg["mcp_script"]).read_bytes())
    implementation_sha, implementation_count = _mcp_implementation_digest(cfg["mcp_script"])
    return {
        "runner_version": "codex-jsonl-study-v1-" + script_sha[:16] + "-" + cli,
        "tool_contract": "codex-study-readonly-v1-mcp-" + mcp_sha[:12] + "-impl-" + implementation_sha[:16],
        "agent_version": AGENT_VERSION,
        "tool_names": TOOL_NAMES,
        "provider": PROVIDER,
        "codex_version": cli,
        "runner_script_sha256": script_sha,
        "mcp_script_sha256": mcp_sha,
        "mcp_implementation_sha256": implementation_sha,
        "mcp_implementation_source_count": implementation_count,
    }


def _validate_request_identity(req: dict[str, Any]) -> None:
    if req.get("kind") != "repoground.agent_study_request" or req.get("version") != "1.0":
        raise ValueError("study request kind/version mismatch")
    if not isinstance(req.get("request_id"), str) or not ID.fullmatch(req["request_id"]):
        raise ValueError("invalid request id")
    if not isinstance(req.get("workspace_id"), str) or not ID.fullmatch(req["workspace_id"]):
        raise ValueError("invalid workspace id")
    if req.get("condition") not in ("git_only", "repoground_mandatory", "repoground_selective"):
        raise ValueError("unknown study arm")
    if not isinstance(req.get("repositories"), dict) or not req["repositories"]:
        raise ValueError("frozen repository set missing")
    if not isinstance(req.get("question"), str) or not req["question"]:
        raise ValueError("study question missing")
    historical = req.get("citation_commits", {})
    if not isinstance(historical, dict):
        raise ValueError("historical citation scope must be a mapping")
    for repo, commits in historical.items():
        if (repo not in req["repositories"] or not isinstance(commits, list)
                or not 0 < len(commits) <= 8
                or any(not isinstance(rev, str) or not HEX40.fullmatch(rev)
                       or rev == req["repositories"][repo].get("commit")
                       for rev in commits) or len(commits) != len(set(commits))):
            raise ValueError("historical citation commits are not bounded")


def _validate_request_profile(req: dict[str, Any], fingerprint: dict[str, Any]) -> None:
    run = req.get("runner")
    ctx = req.get("execution_context")
    if not isinstance(run, dict) or not isinstance(ctx, dict):
        raise ValueError("runner and execution_context required")
    if run.get("provider") != PROVIDER or run.get("runner_version") != fingerprint["runner_version"]:
        raise ValueError("runner executable or version drift")
    if not isinstance(run.get("model"), str) or not run["model"]:
        raise ValueError("exact model identifier missing")
    if run.get("sampling") != {"model_reasoning_effort": "medium"}:
        raise ValueError("unsupported Codex sampling configuration")
    if ctx.get("agent_version") != AGENT_VERSION or ctx.get("tool_contract") != fingerprint["tool_contract"]:
        raise ValueError("agent/tool contract drift")
    if ctx.get("cache_policy") != "controlled" or not isinstance(ctx.get("host_class"), str):
        raise ValueError("cache/host profile mismatch")


def _validate_request_tools(req: dict[str, Any]) -> None:
    requested_tools = TOOL_NAMES["git"] + TOOL_NAMES["file"]
    if req["condition"] != "git_only":
        requested_tools += TOOL_NAMES["repoground"]
    if req.get("tools_allowed") != sorted(requested_tools):
        raise ValueError("tool inventory does not match actual runner contract")
    if req.get("git_file_tool_names") != sorted(TOOL_NAMES["git"] + TOOL_NAMES["file"]):
        raise ValueError("Git/file tool inventory drift")
    expected_rg = [] if req["condition"] == "git_only" else sorted(TOOL_NAMES["repoground"])
    if req.get("repoground_tool_names") != expected_rg:
        raise ValueError("RepoGround tool inventory drift")
    if (req.get("repoground") is None) != (req["condition"] == "git_only"):
        raise ValueError("baseline/treatment snapshot access mismatch")
    if req.get("isolation") != {
        "fresh_session": True, "fresh_workspace": True,
        "no_prior_arm_transcripts": True, "disable_unlisted_plugins": True,
    }:
        raise ValueError("required isolation flags absent")


def _validate_request(req: dict[str, Any], fingerprint: dict[str, Any]) -> None:
    _validate_request_identity(req)
    _validate_request_profile(req, fingerprint)
    _validate_request_tools(req)

def _prepare_sources(req: dict[str, Any], cfg: dict[str, Any]) -> tuple[Path, dict[str, Path]]:
    root = Path(cfg["workspaces_root"])
    _private_dir(root)
    workspace = root / req["workspace_id"]
    workspace.mkdir(mode=0o700, exist_ok=False)
    repositories = workspace / "repos"
    repositories.mkdir(mode=0o700)
    result: dict[str, Path] = {}
    for name, bound in req["repositories"].items():
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,60}", name):
            raise ValueError("unsafe repository identifier")
        if not isinstance(bound, dict) or not HEX40.fullmatch(str(bound.get("commit", ""))):
            raise ValueError("frozen SHA missing")
        if name not in cfg["source_roots"]:
            raise ValueError("no registered source root for " + name)
        source = Path(cfg["source_roots"][name]).resolve(strict=True)
        if _exec(["git", "-C", str(source), "rev-parse", "--show-toplevel"]) != str(source):
            raise ValueError("registered source root is not canonical checkout")
        origin = _exec(["git", "-C", str(source), "remote", "get-url", "origin"])
        slug = str(bound.get("slug", ""))
        if not origin.rstrip("/").removesuffix(".git").endswith("/" + slug) and not origin.removesuffix(".git").endswith(":" + slug):
            raise ValueError("registered source remote does not match frozen repository")
        _exec(["git", "-C", str(source), "cat-file", "-e", bound["commit"] + "^{commit}"])
        dest = repositories / name
        _exec(["git", "clone", "--quiet", "--shared", "--no-checkout", "--", str(source), str(dest)])
        _exec(["git", "-C", str(dest), "checkout", "--quiet", "--detach", bound["commit"]])
        _exec(["git", "-C", str(dest), "remote", "set-url", "origin", origin])
        if _exec(["git", "-C", str(dest), "rev-parse", "HEAD"]) != bound["commit"]:
            raise ValueError("cloned source revision drift")
        if _exec(["git", "-C", str(dest), "status", "--porcelain", "--untracked-files=normal"]):
            raise ValueError("frozen source clone not clean")
        result[name] = dest
    return workspace, result


def _manifest_evidence(req: dict[str, Any], sources: dict[str, Path]) -> dict[str, dict[str, Any]]:
    evidence = {}
    for name, bound in (req.get("repoground") or {}).items():
        path = Path(bound["manifest_path"])
        if path.is_symlink() or not path.is_file() or _digest(path.read_bytes()) != bound["manifest_sha256"]:
            raise ValueError("published bundle SHA drift")
        manifest = _read_json(path)
        generator = manifest.get("generator", {}).get("runtime", {})
        provenance = manifest.get("snapshot_provenance", {}).get("repositories", [])
        links = manifest.get("links", {})
        if not isinstance(provenance, list) or len(provenance) != 1:
            raise ValueError("bundle source ambiguity")
        observed = provenance[0]
        health_path = path.parent / links.get("post_emit_health_path", "")
        if (
            generator.get("git_commit") != bound["generator_commit"]
            or generator.get("git_dirty") is not False
            or observed.get("git_commit") != bound["source_commit"]
            or observed.get("git_dirty") is not False
            or observed.get("provenance_status") != "present"
            or links.get("agent_export_gate_status") != "pass"
            or links.get("bundle_surface_validation_status") != "pass"
            or not health_path.is_file() or health_path.is_symlink()
            or _read_json(health_path).get("status") != "pass"
            or _exec(["git", "-C", str(sources[name]), "rev-parse", "HEAD"]) != bound["source_commit"]
        ):
            raise ValueError("bundle health/source/generated revision mismatch")
        evidence[name] = {
            "repo": name, "source_commit": bound["source_commit"],
            "generator_commit": bound["generator_commit"],
            "manifest_sha256": bound["manifest_sha256"],
            "observed_status": "available",
            "freshness": "pinned_exact",
            # Internal only: never copy a host path into the provider receipt.
            "_manifest_path": str(path),
        }
    return evidence


def _pin_bundle_sibling(
    source: Path, original: Path, directory: Path,
    post_name: str, expected_sha: str,
) -> None:
    if source.is_dir() and not source.is_symlink():
        return  # Generation metadata is not a manifest role.
    if source.is_symlink() or not source.is_file():
        raise ValueError("source bundle contains unsafe entry")
    if source == original:
        return
    if source.parent == original.parent and source.name == post_name:
        # Preserve the health attestation's original publication path, but
        # also hash-bind its private copy to exactly the pinned manifest bytes.
        post = _read_json(source)
        if post.get("bundle_manifest_sha256") not in (None, expected_sha):
            raise ValueError("source post-health SHA conflicts with frozen manifest")
        post["bundle_manifest_sha256"] = expected_sha
        _create_once(directory / post_name, _json_bytes(post) + b"\n")
        return
    # Published bundles reject extra hardlinks (notably output_health).
    # Always use an independent private inode, including on the same filesystem.
    destination = directory / source.name
    with source.open("rb") as reader, _open_private_create(destination) as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())


def _pin_nested_artifacts(
    original: Path, directory: Path, manifest_doc: dict[str, Any],
    post_name: str, expected_sha: str,
) -> None:
    """Mirror manifest-declared nested roles; reject traversal and symlinks."""
    artifacts = manifest_doc.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("manifest artifacts not an array")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise ValueError("manifest artifact path invalid")
        relative = artifact["path"]
        if (
            relative.startswith("/") or "\\" in relative
            or any(part in ("", ".", "..") for part in relative.split("/"))
        ):
            raise ValueError("unsafe manifest artifact relative path")
        parts = relative.split("/")
        if len(parts) == 1:
            continue  # Top-level files have already been mirrored.
        src_dir = original.parent
        for segment in parts[:-1]:
            src_dir = src_dir / segment
            if src_dir.is_symlink() or not src_dir.is_dir():
                raise ValueError("nested manifest artifact parent unsafe")
        target_dir = directory.joinpath(*parts[:-1])
        target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if target_dir.is_symlink():
            raise ValueError("nested manifest artifact destination unsafe")
        _pin_bundle_sibling(
            src_dir / parts[-1], original, target_dir, post_name, expected_sha,
        )


def _pin_bundle_manifest(bound: dict[str, Any], directory: Path) -> Path:
    original = Path(bound["manifest_path"])
    if original.is_symlink() or not original.is_file():
        raise ValueError("source manifest is not an ordinary file")
    raw = original.read_bytes()
    if _digest(raw) != bound["manifest_sha256"]:
        raise ValueError("source manifest changed before private pin")
    manifest_doc = json.loads(raw)
    post_name = manifest_doc.get("links", {}).get("post_emit_health_path")
    if not isinstance(post_name, str) or Path(post_name).name != post_name:
        raise ValueError("source bundle post-emit health name invalid")
    directory.mkdir(mode=0o700, exist_ok=False)
    for source in original.parent.iterdir():
        _pin_bundle_sibling(source, original, directory, post_name, bound["manifest_sha256"])
    _pin_nested_artifacts(original, directory, manifest_doc, post_name, bound["manifest_sha256"])
    manifest = directory / original.name
    _create_once(manifest, raw)
    manifest.chmod(0o400)
    if _digest(manifest.read_bytes()) != bound["manifest_sha256"]:
        raise ValueError("private manifest digest mismatch")
    return manifest


def _pin_snapshot_manifests(
    req: dict[str, Any], root: Path,
) -> dict[str, Path]:
    """Pin exact manifest bytes outside publisher and agent workspace.

    The producer can atomically replace its source manifest without changing
    any consumer-visible bytes used by the private MCP server.
    """
    manifests = req.get("repoground") or {}
    if not manifests:
        return {}
    root.mkdir(mode=0o700, exist_ok=False)
    return {
        repo: _pin_bundle_manifest(bound, root / repo)
        for repo, bound in sorted(manifests.items())
    }



def _assert_pinned_manifests(
    request: dict[str, Any], pinned: dict[str, Path],
) -> None:
    if set(pinned) != set(request.get("repoground") or {}):
        raise ValueError("private manifest inventory mismatch")
    for repo, manifest in pinned.items():
        if manifest.is_symlink() or _digest(manifest.read_bytes()) != request["repoground"][repo]["manifest_sha256"]:
            raise ValueError("private manifest changed while MCP was running")


def _private_manifest_evidence(
    evidence: dict[str, dict[str, Any]], pinned: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    """Resolve resource proofs against the private copies used by Codex."""
    if set(evidence) != set(pinned):
        raise ValueError("private manifest inventory mismatch")
    return {
        repo: {
            **bound,
            "_publisher_manifest_path": bound["_manifest_path"],
            "_manifest_path": str(pinned[repo]),
        }
        for repo, bound in evidence.items()
    }


def _output_schema() -> dict[str, Any]:
    path = {"type": "object", "properties": {
        "repo": {"type": "string"}, "path": {"type": "string"},
    }, "required": ["repo", "path"], "additionalProperties": False}
    citation = {"type": "object", "properties": {
        "repo": {"type": "string"}, "path": {"type": "string"},
        "commit": {"type": "string"}, "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
    }, "required": ["repo", "path", "commit", "start_line", "end_line"],
        "additionalProperties": False}
    return {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["answer", "abstain", "unavailable"]},
            "reported_paths": {"type": "array", "items": path},
            "citations": {"type": "array", "items": citation},
            "asserted_sufficient_evidence": {"type": "boolean"},
            "explanation": {"type": "string"},
        },
        "required": ["outcome", "reported_paths", "citations", "asserted_sufficient_evidence", "explanation"],
        "additionalProperties": False,
    }


def _prompt(req: dict[str, Any]) -> str:
    lines = [
        "Du bearbeitest eine kontrollierte, ausschließlich lesende Coding-Agenten-Aufgabe.",
        "Die eingefrorenen Git-Repositories stehen unter repos/REPO. Verwende nur diese.",
        "Prüfe Belege direkt an den jeweils angegebenen Git-Commits.",
        "Keine Bearbeitung, kein Netzwerkabruf, keine ungeprüften Behauptungen.",
        "Antworte nur mit dem vorgegebenen strukturierten JSON.",
        "reported_paths und citations benutzen Repo-Kürzel und zum Repository relative Pfade.",
        "Zitate müssen konkrete, tatsächlich gelesene Zeilen des eingefrorenen Commits tragen.",
        "Ergänze explanation: eine inhaltliche, quellengestützte Begründung (24 bis 8000 Zeichen).",
        "Erkläre auch bei abstain/unavailable, welche Evidenz fehlt; erfinde keine Fakten.",
        "Wenn eine Behauptung nicht belegbar ist, verwende abstain oder unavailable.",
    ]
    if req.get("repositories"):
        lines.append(
            "Zulässige Repo-Kürzel für reported_paths und citations: "
            + ", ".join(sorted(req["repositories"])) + "."
        )
    for repo, commits in sorted(req.get("citation_commits", {}).items()):
        lines.append(
            "Zusätzlich zulässige historische Zitatrevisionen für "
            + repo + ": " + ", ".join(commits)
        )
    if req["condition"] == "repoground_mandatory":
        lines.append(
            "Diese Bedingung verlangt mindestens eine erfolgreiche inhaltliche "
            "RepoGround-Suche (repoground_ask_context oder "
            "repoground_query_existing_index) und anschließend mindestens einen "
            "erfolgreichen repoground_range_get auf einen kanonischen Quellbereich "
            "mit überprüftem SHA-256. repoground_bundle_discover allein genügt nicht."
        )
    elif req["condition"] == "repoground_selective":
        lines.append("RepoGround-MCP ist verfügbar, aber freiwillig; null RepoGround-Aufrufe sind ausdrücklich erlaubt.")
    else:
        lines.append("RepoGround ist in dieser Kontrollbedingung nicht verfügbar; benutze Git und normale Dateisuche.")
    return "\n".join(lines) + "\n\nAUFGABE (in allen drei Armen bytegleich):\n" + req["question"]


def _codex_argv(req: dict[str, Any], cfg: dict[str, Any],
                workspace: Path, sources: dict[str, Path],
                pinned: dict[str, Path] | None = None) -> list[str]:
    schema_path = workspace / "answer.schema.json"
    _create_once(schema_path, _json_bytes(_output_schema()) + b"\n")
    argv = [
        cfg["codex_bin"], "exec", "--sandbox", "read-only",
        "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
        "--disable", "apps", "--disable", "plugins",
        "--json", "--output-schema", str(schema_path),
        "--model", req["runner"]["model"],
        "-c", 'model_reasoning_effort="medium"',
    ]
    for name, bound in sorted((req.get("repoground") or {}).items()):
        server = "study_" + name.replace("-", "_")
        mcp_argv = [
            cfg["mcp_script"], "--bundle-root", str((pinned or {}).get(name, bound["manifest_path"])),
            "--repo-root", str(sources[name]),
        ]
        argv += [
            "-c", "mcp_servers." + server + ".command=" + json.dumps(cfg["mcp_python"]),
            "-c", "mcp_servers." + server + ".enabled=true",
            "-c", "mcp_servers." + server + ".required=true",
            "-c", "mcp_servers." + server + ".args=" + json.dumps(mcp_argv, separators=(",", ":")),
            # An allowlist also excludes future server tools not in the frozen
            # study contract; disabling just one known extra would not.
            "-c", "mcp_servers." + server + ".enabled_tools=" + json.dumps(list(MCP_TOOLS)),
        ]
    argv.append(_prompt(req))
    return argv


def _record_codex_event(events: list[tuple[dict[str, Any], float]], line: bytes) -> None:
    if not line.strip():
        return
    event = json.loads(line)
    if not isinstance(event, dict):
        raise ValueError("Codex event not an object")
    events.append((event, time.monotonic()))


def _collect_codex_stream(
    process: subprocess.Popen[bytes], start: float, trace_file: Any,
) -> tuple[bytes, list[tuple[dict[str, Any], float]], bool]:
    """Capture real bytes plus local event arrival timestamps without guesses."""
    assert process.stdout is not None
    chunks: list[bytes] = []
    events: list[tuple[dict[str, Any], float]] = []
    buffer = b""
    size = 0
    timed_out = False
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = MODEL_TIMEOUT - (time.monotonic() - start)
            if remaining <= 0:
                timed_out = True
                break
            selected = selector.select(min(1.0, remaining))
            if not selected:
                if process.poll() is not None:
                    selected = selector.select(0.1)
                    if not selected:
                        break
                else:
                    continue
            fragment = os.read(process.stdout.fileno(), 65536)
            if not fragment:
                break
            if size + len(fragment) > MAX_TRACE_BYTES:
                trace_file.write(fragment[:max(0, MAX_TRACE_BYTES - size)])
                raise ValueError("Codex trace over maximum byte budget")
            trace_file.write(fragment)
            size += len(fragment)
            chunks.append(fragment)
            buffer += fragment
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                _record_codex_event(events, line)
        if not timed_out:
            _record_codex_event(events, buffer)
    finally:
        selector.close()
        process.stdout.close()
    return b"".join(chunks), events, timed_out


def _capture(argv: list[str], cwd: Path, stderr_path: Path, trace_path: Path) -> tuple[bytes, list[tuple[dict[str, Any], float]], int, bool, datetime, datetime, int]:
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        env.pop(key, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    with _open_private_create(stderr_path) as error_log, _open_private_create(trace_path) as raw_file:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=error_log,
                                   start_new_session=True)
        try:
            raw, events, timed_out = _collect_codex_stream(process, start, raw_file)
        except (OSError, ValueError, json.JSONDecodeError):
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            raise
        finally:
            # Own the raw evidence before any JSON validation can fail.
            raw_file.flush()
            os.fsync(raw_file.fileno())
        if timed_out:
            os.killpg(process.pid, signal.SIGKILL)
        code = process.wait(timeout=15)
    ended_at = datetime.now(timezone.utc)
    duration_ms = round((time.monotonic() - start) * 1000)
    return raw, events, code, timed_out, started_at, ended_at, duration_ms

def _mcp_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    result = item.get("result")
    if not isinstance(result, dict):
        return None
    structured = result.get("structured_content")
    if isinstance(structured, dict):
        return structured
    for part in result.get("content", []):
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            try:
                value = json.loads(part["text"])
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return None


def _builtin_empty_mcp(item: dict[str, Any]) -> bool:
    if item.get("server") != "codex":
        return False
    expected = {
        "list_mcp_resources": {"resources": []},
        "list_mcp_resource_templates": {"resourceTemplates": []},
    }
    tool = item.get("tool")
    payload = _mcp_payload(item)
    return tool in expected and payload == expected[tool]


def _shell_bundle_access(
    item: dict[str, Any], expected: dict[str, dict[str, Any]],
    workspace: Path | None,
) -> list[dict[str, str]]:
    """Classify shell commands that name an exact bound bundle location.

    Exact runtime paths avoid treating ordinary checked-out source text that
    merely discusses RepoGround or pinned bundles as evidence consumption.
    This is trace classification, not a claim of same-UID shell isolation.
    """
    command = str(item.get("command") or "")
    observed = command + "\n" + str(item.get("aggregated_output") or "")
    accesses: list[dict[str, str]] = []
    for repo, evidence in sorted(expected.items()):
        for key, location in (
            ("private_pin", evidence.get("_manifest_path")),
            ("publisher", evidence.get("_publisher_manifest_path")),
        ):
            if not isinstance(location, str):
                continue
            manifest = Path(location)
            candidates = {str(manifest), str(manifest.parent)}
            if workspace is not None:
                for path in (manifest, manifest.parent):
                    try:
                        relative = path.relative_to(workspace)
                    except ValueError:
                        continue
                    if relative.parts:
                        candidates.add(relative.as_posix())
            if any(candidate and candidate in observed for candidate in candidates):
                accesses.append({
                    "repo": repo, "target": key,
                    "classification": "observed_bound_bundle_shell_access",
                })
                break
    return accesses


def _command_tool_receipt(
    item: dict[str, Any], sequence: int, duration_ms: int,
    expected: dict[str, dict[str, Any]] | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    command = str(item.get("command") or "")
    name = "codex_git_command" if re.search(r"\bgit\b", command) else "codex_file_command"
    successful = item.get("status") == "completed" and item.get("exit_code") == 0
    receipt = {
        "sequence": sequence, "name": name,
        "status": "success" if successful else "failed",
        "duration_ms": duration_ms, "input_bytes": len(command.encode("utf-8")),
        "output_bytes": len(str(item.get("aggregated_output") or "").encode("utf-8")),
    }
    accesses = _shell_bundle_access(item, expected or {}, workspace)
    if accesses:
        receipt["repoground_data_access"] = accesses
    return receipt


def _mcp_evidence_available(tool: str, payload: Any) -> bool:
    """Treat a successfully observed read according to its actual MCP contract."""
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    if tool == "ask_context":
        pack = payload.get("context_pack")
        availability = pack.get("availability") if isinstance(pack, dict) else None
        return (
            status == "ok" and isinstance(availability, dict)
            and availability.get("status") == "available"
        )
    if tool == "grounding_verify":
        return status == "pass"
    if tool == "live_freshness":
        return status == "fresh"
    if tool == "get_flake_relation_evidence":
        evidence = payload.get("evidence")
        return (
            isinstance(evidence, dict)
            and evidence.get("status") in ("ok", "partial")
            and isinstance(evidence.get("relations"), list)
            and isinstance(evidence.get("gaps"), list)
            and isinstance(payload.get("pack_sha256"), str)
            and HEX64.fullmatch(payload["pack_sha256"]) is not None
            and isinstance(payload.get("source_commit"), str)
            and HEX40.fullmatch(payload["source_commit"]) is not None
        )
    return status == "available"


def _read_bounded_regular_file(path: Path, limit: int) -> bytes | None:
    """Read one non-symlink regular file through its checked descriptor."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                return None
            raw = handle.read(limit + 1)
        if len(raw) != info.st_size:
            return None
        return raw
    except OSError:
        return None


def _flake_pinned_manifest(
    expected: dict[str, Any],
) -> tuple[Path, dict[str, Any]] | None:
    """Verify a private frozen manifest's original bytes and physical path."""
    manifest_name = expected.get("_manifest_path")
    if not isinstance(manifest_name, str):
        return None
    manifest_path = Path(manifest_name)
    try:
        if (
            not manifest_path.is_absolute()
            or any(part in (".", "..") for part in manifest_path.parts)
            or manifest_path.resolve(strict=True) != manifest_path
        ):
            return None
        pin_root = manifest_path.parent
        if pin_root.is_symlink() or pin_root.resolve(strict=True) != pin_root:
            return None
    except OSError:
        return None
    manifest_bytes = _read_bounded_regular_file(manifest_path, 4 * 1024 * 1024)
    if manifest_bytes is None or _digest(manifest_bytes) != expected.get("manifest_sha256"):
        return None
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    return pin_root, manifest


def _flake_pack_private_artifact(
    expected: dict[str, Any],
) -> tuple[bytes, str] | None:
    """Read one strictly bound artifact from an immutable private manifest."""
    pinned = _flake_pinned_manifest(expected)
    if pinned is None:
        return None
    pin_root, manifest = pinned
    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
    roles = [
        row for row in (artifacts if isinstance(artifacts, list) else [])
        if isinstance(row, dict) and row.get("role") == "flake_relation_evidence_json"
    ]
    if len(roles) != 1:
        return None
    role = roles[0]
    relative = role.get("path")
    declared_sha = role.get("sha256")
    declared_bytes = role.get("bytes")
    if (
        not isinstance(relative, str) or not relative or relative.startswith("/")
        or "\\" in relative or "\x00" in relative
        or any(part in ("", ".", "..") for part in relative.split("/"))
        or not isinstance(declared_sha, str) or HEX64.fullmatch(declared_sha) is None
        or type(declared_bytes) is not int or not 0 < declared_bytes <= 2 * 1024 * 1024
    ):
        return None
    artifact_path = pin_root.joinpath(*relative.split("/"))
    try:
        if (
            artifact_path.resolve(strict=True) != artifact_path
            or not artifact_path.is_relative_to(pin_root)
        ):
            return None
    except OSError:
        return None
    artifact_bytes = _read_bounded_regular_file(artifact_path, 2 * 1024 * 1024)
    if (
        artifact_bytes is None or len(artifact_bytes) != declared_bytes
        or _digest(artifact_bytes) != declared_sha
    ):
        return None
    return artifact_bytes, declared_sha


def _flake_pack_content_proof(
    payload: Any, expected: dict[str, Any],
) -> dict[str, str] | None:
    """Bind structured Flake output to actual bytes in the private frozen pin."""
    pack_fields = {
        "kind", "version", "source_repo", "source_commit", "target_pins",
        "evidence", "read_contract", "pack_sha256",
    }
    envelope_fields = {"status", "manifest_sha256", "does_not_establish"}
    if (
        not isinstance(payload, dict) or set(payload) != pack_fields | envelope_fields
        or payload.get("status") != "available"
        or payload.get("manifest_sha256") != expected.get("manifest_sha256")
        or payload.get("source_commit") != expected.get("source_commit")
        or payload.get("does_not_establish") != [
            "runtime_dependency", "active_generation", "running_service",
            "complete_change_impact",
        ]
    ):
        return None
    pinned = _flake_pack_private_artifact(expected)
    if pinned is None:
        return None
    artifact_bytes, declared_sha = pinned
    try:
        artifact_pack = json.loads(artifact_bytes)
        returned_pack = {key: payload[key] for key in pack_fields}
        evidence = artifact_pack.get("evidence") if isinstance(artifact_pack, dict) else None
        if (
            not isinstance(artifact_pack, dict) or set(artifact_pack) != pack_fields
            or artifact_pack != returned_pack
            or not isinstance(artifact_pack.get("pack_sha256"), str)
            or HEX64.fullmatch(artifact_pack["pack_sha256"]) is None
            or _digest(_json_bytes({
                key: value for key, value in artifact_pack.items()
                if key != "pack_sha256"
            })) != artifact_pack["pack_sha256"]
            or not isinstance(evidence, dict)
            or not isinstance(evidence.get("evidence_sha256"), str)
            or HEX64.fullmatch(evidence["evidence_sha256"]) is None
            or _digest(_json_bytes({
                key: value for key, value in evidence.items()
                if key != "evidence_sha256"
            })) != evidence["evidence_sha256"]
        ):
            return None
    except (KeyError, TypeError, UnicodeError, ValueError):
        return None
    return {
        "resource_role": "flake_relation_evidence_json",
        "resource_content_sha256": declared_sha,
    }

def _mcp_range_get_content_sha256(item: dict[str, Any], payload: Any) -> str | None:
    """Bind one actual MCP source byte read to its unchanged canonical range ref."""
    if not isinstance(payload, dict) or payload.get("status") != "available":
        return None
    args = item.get("arguments")
    ref = args.get("range_ref") if isinstance(args, dict) else None
    result = payload.get("result")
    resolved = result.get("range") if isinstance(result, dict) else None
    if not isinstance(ref, dict) or ref.get("artifact_role") != "canonical_md":
        return None
    if not isinstance(resolved, dict) or result.get("status") != "available":
        return None
    version = ref.get("range_ref_version")
    if version == "2":
        # v2 separates the whole artifact's identity from extracted bytes.
        whole_sha = ref.get("content_sha256")
        if not isinstance(whole_sha, str) or HEX64.fullmatch(whole_sha) is None:
            return None
        expected = ref.get("range_content_sha256")
    elif version is None:
        # The original v1 range reference binds its selected bytes here.
        expected = ref.get("content_sha256")
    else:
        return None
    observed = resolved.get("sha256")
    count = resolved.get("bytes")
    text = resolved.get("text")
    if (
        not isinstance(expected, str) or HEX64.fullmatch(expected) is None
        or observed != expected or type(count) is not int or count <= 0
        or not isinstance(text, str) or len(text.encode("utf-8")) != count
        or hashlib.sha256(text.encode("utf-8")).hexdigest() != expected
    ):
        return None
    return observed


def _mcp_resource_artifact_identity(
    suffix: str, manifest: dict[str, Any],
) -> tuple[str, Any, Any] | None:
    """Find one SHA-declared artifact matching an advertised resource role."""
    aliases = {"canonical": "canonical_md",
               "reading-pack": "agent_reading_pack",
               "health": "post_emit_health"}
    role = aliases.get(suffix)
    if suffix.startswith("artifact/"):
        role = suffix.removeprefix("artifact/")
    if not role or "/" in role or len(role) > 128:
        return None
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    matches = [a for a in artifacts if isinstance(a, dict)
               and a.get("role") == role]
    if len(matches) != 1:
        return None
    return role, matches[0].get("sha256"), matches[0].get("bytes")


def _mcp_resource_bound_identity(
    uri: str, evidence: dict[str, Any],
) -> tuple[str, str, int] | None:
    """Read the already-frozen manifest and bind its exact advertised role."""
    manifest_name = evidence.get("_manifest_path")
    if not isinstance(manifest_name, str):
        return None
    manifest_path = Path(manifest_name)
    if (
        not manifest_path.name.endswith(".bundle.manifest.json")
        or manifest_path.is_symlink() or not manifest_path.is_file()
        or manifest_path.stat().st_size > 4 * 1024 * 1024
    ):
        return None
    try:
        manifest_bytes = manifest_path.read_bytes()
        if _digest(manifest_bytes) != evidence.get("manifest_sha256"):
            return None
        manifest = json.loads(manifest_bytes)
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    stem = manifest_path.name.removesuffix(".bundle.manifest.json")
    prefix = "repoground://snapshot/" + stem + "/"
    if not uri.startswith(prefix):
        return None
    suffix = uri[len(prefix):]
    if suffix == "manifest":
        identity = "manifest", evidence["manifest_sha256"], len(manifest_bytes)
    else:
        identity = _mcp_resource_artifact_identity(suffix, manifest)
    if identity is None:
        return None
    role, digest, size = identity
    if (
        not isinstance(digest, str) or HEX64.fullmatch(digest) is None
        or type(size) is not int or size < 1 or size > 16 * 1024 * 1024
    ):
        return None
    return role, digest, size


def _mcp_resource_read_proof(
    item: dict[str, Any], payload: Any, evidence: dict[str, Any],
) -> dict[str, Any] | None:
    """Admit only a client resources/read response matching pinned bytes."""
    args = item.get("arguments")
    if not isinstance(args, dict) or set(args) != {"server", "uri"}:
        return None
    if args["server"] != item.get("server") or not isinstance(args["uri"], str):
        return None
    uri = args["uri"]
    identity = _mcp_resource_bound_identity(uri, evidence)
    if identity is None:
        return None
    role, expected_sha, expected_bytes = identity
    if (
        not isinstance(payload, dict)
        or payload.get("server") != item.get("server")
        or payload.get("uri") != uri
        or not isinstance(payload.get("contents"), list)
        or len(payload["contents"]) != 1
    ):
        return None
    content = payload["contents"][0]
    if (
        not isinstance(content, dict) or content.get("uri") != uri
        or not isinstance(content.get("text"), str)
    ):
        return None
    data = content["text"].encode("utf-8")
    if len(data) != expected_bytes or _digest(data) != expected_sha:
        return None
    return {"resource_role": role, "resource_content_sha256": expected_sha}


def _mcp_tool_receipt(
    item: dict[str, Any], sequence: int, duration_ms: int,
    expected: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    server = item.get("server")
    name = "repoground_" + str(item.get("tool"))
    repo = str(server).removeprefix("study_").replace("_", "-")
    if server != "study_" + repo.replace("-", "_") or repo not in expected:
        raise ValueError("unregistered or forbidden MCP server observed")
    if name not in TOOL_NAMES["repoground"]:
        raise ValueError("unregistered RepoGround MCP tool observed")
    payload = _mcp_payload(item)
    result = item.get("result")
    range_sha = (
        _mcp_range_get_content_sha256(item, payload)
        if item.get("tool") == "range_get" else None
    )
    resource_proof = (
        _mcp_resource_read_proof(item, payload, expected[repo])
        if item.get("tool") == "read_mcp_resource" else None
    )
    flake_proof = (
        _flake_pack_content_proof(payload, expected[repo])
        if item.get("tool") == "get_flake_relation_evidence" else None
    )
    successful = (
        item.get("status") == "completed" and not item.get("error")
        and not (isinstance(result, dict) and result.get("isError") is True)
        and (
            resource_proof is not None if item.get("tool") == "read_mcp_resource"
            else _mcp_evidence_available(str(item.get("tool")), payload)
        )
        and (item.get("tool") != "range_get" or range_sha is not None)
        and (
            item.get("tool") != "get_flake_relation_evidence"
            or flake_proof is not None
        )
    )
    call = {
        "sequence": sequence, "name": name,
        "status": "success" if successful else "failed",
        "duration_ms": duration_ms,
        "input_bytes": len(_json_bytes(item.get("arguments"))),
        "output_bytes": len(_json_bytes(item.get("result"))),
    }
    if successful:
        # The exact health-checked manifest was bound before the actual MCP
        # response; do not confuse pinned_exact with mutable HEAD freshness.
        # Do not leak the internal pinned host path into durable receipts.
        call["repoground_evidence"] = {
            k: v for k, v in expected[repo].items() if not k.startswith("_")
        }
        if range_sha is not None:
            call["source_content_sha256"] = range_sha
        if resource_proof is not None:
            call.update(resource_proof)
        if flake_proof is not None:
            call.update(flake_proof)
    return call


def _mandatory_source_intervention(calls: list[dict[str, Any]]) -> bool:
    """Discovery does not count: observe search followed by verified source bytes."""
    searches = [
        call["sequence"] for call in calls
        if call["name"] in SOURCE_SEARCH_TOOLS and call["status"] == "success"
    ]
    return bool(searches) and any(
        call["name"] == "repoground_range_get"
        and call["status"] == "success"
        and isinstance(call.get("source_content_sha256"), str)
        and HEX64.fullmatch(call["source_content_sha256"]) is not None
        and call["sequence"] > min(searches)
        for call in calls
    )


def _failed_unknown_client_discovery(item: dict[str, Any]) -> bool:
    """A failed Codex resources/list probe supplied no server evidence.

    A wrong server name is a client diagnostic, never a successful resource
    retrieval. Admit only the exact observed no-result error envelope.
    """
    server = item.get("server")
    arguments = item.get("arguments")
    error = item.get("error")
    return (
        item.get("type") == "mcp_tool_call"
        and item.get("tool") == "list_mcp_resources"
        and item.get("status") == "failed"
        and item.get("result") is None
        and isinstance(server, str) and bool(server)
        and isinstance(arguments, dict) and arguments == {"server": server}
        and isinstance(error, dict) and set(error) == {"message"}
        and error["message"] == (
            "resources/list failed: unknown MCP server '" + server + "'"
        )
    )


def _measured_tool_item(
    item: dict[str, Any], *, baseline: bool = False,
) -> bool:
    if item.get("type") not in ("command_execution", "mcp_tool_call"):
        return False
    if item.get("type") == "mcp_tool_call" and item.get("server") == "codex":
        # Built-in discovery is metadata, not a RepoGround retrieval. In the
        # Git-only control arm it must be empty and successful; a nonempty
        # listing would reveal an undeclared source and contaminate the trial.
        if item.get("tool") in ("list_mcp_resources", "list_mcp_resource_templates"):
            if baseline and (
                item.get("status") != "completed" or item.get("error")
                or not _builtin_empty_mcp(item)
            ):
                raise ValueError("nonempty or failed MCP discovery in git_only")
            return False
    if _failed_unknown_client_discovery(item):
        # The original provider JSONL retains the failed probe; it did not
        # expose a registered tool or source bytes, so it cannot taint a valid
        # answer or count as a successful RepoGround retrieval.
        return False
    return True


def _tool_receipts(events: list[tuple[dict[str, Any], float]],
                   expected: dict[str, dict[str, Any]],
                   workspace: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    starts: dict[str, float] = {}
    calls: list[dict[str, Any]] = []
    last_answer = ""
    for event, timestamp in events:
        typ = event.get("type")
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if typ == "item.started" and isinstance(item_id, str):
            starts[item_id] = timestamp
        if typ != "item.completed":
            continue
        if item.get("type") == "agent_message":
            last_answer = str(item.get("text") or "")
            continue
        if not _measured_tool_item(item, baseline=not expected):
            continue
        if not isinstance(item_id, str) or item_id not in starts:
            raise ValueError("unmeasured tool start/end pair")
        duration = round((timestamp - starts[item_id]) * 1000)
        if item["type"] == "command_execution":
            call = _command_tool_receipt(
                item, len(calls) + 1, duration, expected, workspace,
            )
        else:
            call = _mcp_tool_receipt(item, len(calls) + 1, duration, expected)
        calls.append(call)
        if len(calls) > MAX_TOOL_CALLS:
            raise ValueError("too many observed tool calls")
    return calls, last_answer


def _repoground_data_use(
    calls: list[dict[str, Any]], *, treatment: bool,
) -> dict[str, Any]:
    """Report byte-verified content reads and path exposure separately."""
    mcp_calls = [call for call in calls if call["name"].startswith("repoground_")]

    def verified_content_read(call: dict[str, Any]) -> bool:
        digest_field = {
            "repoground_range_get": "source_content_sha256",
            "repoground_read_mcp_resource": "resource_content_sha256",
            "repoground_get_flake_relation_evidence": "resource_content_sha256",
        }.get(call.get("name"))
        digest = call.get(digest_field) if digest_field is not None else None
        return (
            call.get("status") == "success"
            and isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None
        )

    mcp_reads = [call for call in mcp_calls if verified_content_read(call)]
    shell_accesses = sum(
        len(call.get("repoground_data_access", [])) for call in calls
    )
    channels = []
    if mcp_reads:
        channels.append("mcp")
    if shell_accesses:
        channels.append("shell")
    return {
        "classification": (
            "observed_repoground_data_use" if mcp_reads
            else "observed_bound_bundle_path_exposure" if shell_accesses
            else "no_bound_repoground_data_use_observed"
        ),
        "observed_channels": channels,
        "mcp_call_count": len(mcp_calls),
        "verified_mcp_read_count": len(mcp_reads),
        "shell_bundle_access_count": shell_accesses,
        "zero_mcp_calls_proves_zero_repoground_data_use": False,
        "causal_attribution": (
            "not_established_same_uid_shell_not_os_isolated" if treatment
            else "runner_exposed_no_mcp_or_private_bundle_pin"
        ),
    }

def _valid_answer_path(raw: Any, repositories: dict[str, Any]) -> bool:
    if not isinstance(raw, dict) or set(raw) != {"repo", "path"}:
        return False
    repo, path = raw["repo"], raw["path"]
    return (
        isinstance(repo, str) and repo in repositories
        and isinstance(path, str) and 0 < len(path) <= 400
        and path == PurePosixPath(path).as_posix()
        and not path.startswith(("/", "-", "\\"))
        and "\\" not in path
        and all(part not in (".", "..", "") for part in path.split("/"))
        and not any(ord(char) < 32 for char in path)
    )


def _valid_answer_citation(
    raw: Any, repositories: dict[str, Any],
    citation_commits: dict[str, list[str]] | None = None,
) -> bool:
    if not isinstance(raw, dict) or set(raw) != {
        "repo", "path", "commit", "start_line", "end_line",
    }:
        return False
    if not _valid_answer_path({"repo": raw["repo"], "path": raw["path"]}, repositories):
        return False
    repo, commit = raw["repo"], raw["commit"]
    start, end = raw["start_line"], raw["end_line"]
    allowed = {repositories[repo].get("commit")}
    allowed.update((citation_commits or {}).get(repo, []))
    return (
        isinstance(commit, str) and commit in allowed
        and type(start) is int and type(end) is int and start >= 1 and end >= start
    )


def _answer(
    text: str, repositories: dict[str, Any],
    citation_commits: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Preserve every invalid model answer in raw trace, never mark it successful."""
    fallback = {
        "outcome": "unavailable", "reported_paths": [], "citations": [],
        "asserted_sufficient_evidence": False, "explanation": "",
    }
    try:
        answer = json.loads(text)
    except ValueError:
        return fallback, False
    if not isinstance(answer, dict) or set(answer) != {
        "outcome", "reported_paths", "citations", "asserted_sufficient_evidence",
        "explanation",
    }:
        return fallback, False
    if (answer["outcome"] not in ("answer", "abstain", "unavailable")
            or type(answer["asserted_sufficient_evidence"]) is not bool
            or not isinstance(answer["reported_paths"], list)
            or not isinstance(answer["citations"], list)
            or not isinstance(answer["explanation"], str)
            or not 24 <= len(answer["explanation"]) <= 8000
            or not answer["explanation"].strip()
            or any(ord(c) < 32 and c not in "\n\t" for c in answer["explanation"])):
        return fallback, False
    seen_paths: set[tuple[str, str]] = set()
    for raw in answer["reported_paths"]:
        if not _valid_answer_path(raw, repositories):
            return fallback, False
        key = raw["repo"], raw["path"]
        if key in seen_paths:
            return fallback, False
        seen_paths.add(key)
    seen_citations: set[tuple[str, str, str, int, int]] = set()
    for raw in answer["citations"]:
        if not _valid_answer_citation(raw, repositories, citation_commits):
            return fallback, False
        key = (raw["repo"], raw["path"], raw["commit"], raw["start_line"], raw["end_line"])
        if key in seen_citations:
            return fallback, False
        seen_citations.add(key)
    return answer, True

def _usage(events: list[tuple[dict[str, Any], float]]) -> dict[str, Any] | None:
    uses = [event.get("usage") for event, _at in events if event.get("type") == "turn.completed"]
    if not uses or not isinstance(uses[-1], dict):
        return None
    use = uses[-1]
    values = (use.get("input_tokens"), use.get("output_tokens"))
    if any(type(v) is not int or v < 0 for v in values):
        return None
    cached = use.get("cached_input_tokens")
    if cached is not None and (type(cached) is not int or not 0 <= cached <= values[0]):
        return None
    return {
        "source": "provider_reported", "input_tokens": values[0],
        "output_tokens": values[1], "cached_input_tokens": cached,
    }


def run(req: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    fingerprint = _fingerprint(cfg)
    _validate_request(req, fingerprint)
    workspace, sources = _prepare_sources(req, cfg)
    manifest_evidence = _manifest_evidence(req, sources)
    trace_root = Path(cfg["trace_root"])
    _private_dir(trace_root)
    trace_path = trace_root / (req["request_id"] + ".jsonl")
    stderr_path = trace_root / (req["request_id"] + ".stderr.txt")
    if trace_path.exists() or stderr_path.exists():
        raise ValueError("refusing prior trial trace or stderr")
    pin_root = trace_root / (req["request_id"] + ".pinned-bundles")
    if pin_root.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("private bundle pins must be outside agent workspace")
    pinned = _pin_snapshot_manifests(req, pin_root)
    argv = _codex_argv(req, cfg, workspace, sources, pinned)
    raw, events, exitcode, timeout, started, ended, duration = _capture(
        argv, workspace, stderr_path, trace_path,
    )
    if not raw or not events:
        raise RuntimeError("no actual Codex JSONL events")
    _assert_pinned_manifests(req, pinned)
    manifest_evidence = _private_manifest_evidence(manifest_evidence, pinned)
    usage = _usage(events)
    if usage is None:
        # A missing provider receipt is not a claim of zero token consumption.
        raise RuntimeError("Codex never supplied valid provider usage")
    calls, final_answer = _tool_receipts(events, manifest_evidence, workspace)
    data_use = _repoground_data_use(calls, treatment=bool(req.get("repoground")))
    answer, parsed = _answer(final_answer, req["repositories"], req.get("citation_commits"))
    statuses = [e.get("type") for e, _at in events]
    intervention_used = _mandatory_source_intervention(calls)
    shell_contaminated = data_use["shell_bundle_access_count"] > 0
    success = (
        exitcode == 0 and not timeout and "turn.completed" in statuses
        and parsed
        and (req["condition"] != "repoground_mandatory" or intervention_used)
        and not shell_contaminated
    )
    error = None if success else {"class": (
        "shell_bundle_data_contamination" if shell_contaminated
        else "timeout" if timeout else "missing_mandatory_source_intervention"
        if req["condition"] == "repoground_mandatory" and not intervention_used
        else "invalid_agent_answer" if not parsed else "provider_failed"
    )}
    return {
        "kind": "repoground.agent_study_receipt", "version": "1.0",
        "request_id": req["request_id"], "request_sha256": _digest(_json_bytes(req)),
        "condition": req["condition"], "session_id": req["session_id"],
        "workspace_id": req["workspace_id"], "runner": req["runner"],
        "execution_context": req["execution_context"],
        "status": "success" if success else "failed" if shell_contaminated
        else "timeout" if timeout else "failed",
        "started_at": started.isoformat(), "ended_at": ended.isoformat(),
        "duration_ms": duration, "usage": usage, "tool_calls": calls,
        "repoground_data_use": data_use,
        "answer": answer,
        "trace": {"path": trace_path.name, "bytes": len(raw), "sha256": _digest(raw)},
        "billed_cost": None, "resources": None, "error": error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real Codex JSON-stdio RepoGround study adapter")
    parser.add_argument("--config", required=True)
    parser.add_argument("--fingerprint", action="store_true")
    args = parser.parse_args(argv)
    try:
        cfg = _config(Path(args.config))
        if args.fingerprint:
            print(json.dumps(_fingerprint(cfg), ensure_ascii=False, sort_keys=True))
            return 0
        req = json.load(sys.stdin)
        if not isinstance(req, dict):
            raise ValueError("expected one JSON study request")
        print(json.dumps(run(req, cfg), ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # No phantom receipt is emitted on failure. The parent study CLI
        # durably records the attempt and retains any actual raw trace.
        print(type(exc).__name__ + ": " + str(exc)[:350], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
