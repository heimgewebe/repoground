#!/usr/bin/env python3
"""S3 bounded Nixer source/build/generation/runtime observation; never a rebuild.

This probe reads Git objects, Nix Store metadata, systemd and one localhost
HTTP endpoint. It never fetches, switches generations or changes services.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from merger.repoground.core.flake_input_relations import flake_revision_relations

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_STORE = re.compile(r"/nix/store/[a-z0-9]{32}-[A-Za-z0-9._+-]+\Z")
_FILES = ("server.py", "evidence.py", "image_pin.py")
_KIND = "repoground.nixer-runtime-provenance"
_ENDPOINT = "http://127.0.0.1:18187/mcp"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _cmd(*argv: str) -> bytes:
    completed = subprocess.run(
        argv, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"read-only probe failed: {argv[0]} {argv[1]} (exit {completed.returncode})")
    if len(completed.stdout) > 250_000:
        raise RuntimeError("read-only probe output exceeds bound")
    return completed.stdout


def _git_blob(repo: Path, sha: str, filename: str) -> bytes:
    if not _SHA.fullmatch(sha) or filename not in _FILES:
        raise ValueError("only full Git SHAs and known source filenames are supported")
    return _cmd("git", "-C", str(repo), "show", f"{sha}:{filename}")


def compare_source_contents(
    store_source_bytes: dict[str, bytes],
    git_blob_reader: Callable[[str, str], bytes],
    older_commit: str,
    declared_commit: str,
) -> dict[str, Any]:
    """Compare content without promoting a matching blob set to a unique Git origin."""
    matches: dict[str, Any] = {}
    for filename in _FILES:
        store_bytes = store_source_bytes.get(filename)
        if store_bytes is None:
            matches[filename] = {"status": "unavailable"}
            continue
        row: dict[str, Any] = {
            "status": "observed", "store_sha256": _sha256(store_bytes),
            "match_older": None, "match_declared": None,
        }
        for commit, key in ((older_commit, "match_older"), (declared_commit, "match_declared")):
            try:
                git_bytes = git_blob_reader(commit, filename)
            except (OSError, RuntimeError, ValueError):
                continue
            row[key] = _sha256(git_bytes) == row["store_sha256"]
            row["git_sha256_" + key.removeprefix("match_")] = _sha256(git_bytes)
        matches[filename] = row
    return matches


def _derivation_sources(drv: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    phase = drv.get("env", {}).get("installPhase", "")
    if not isinstance(phase, str):
        return result
    # The derivation uses literal "cp /nix/store/ID-name.py .../name.py".
    for src in re.findall(r"(?m)\bcp\s+(/nix/store/[a-z0-9]{32}-(?:server|evidence|image_pin)\.py)\s+", phase):
        filename = Path(src).name.split("-", 1)[-1]
        if filename in _FILES and filename not in result:
            result[filename] = src
    return result


def _http_observation() -> dict[str, Any]:
    request = urllib.request.Request(_ENDPOINT, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return {"http_status": response.status, "http_responded": True}
    except urllib.error.HTTPError as exc:
        # A 4xx from a live MCP server is HTTP reachability, *not* an MCP handshake.
        return {"http_status": exc.code, "http_responded": True}
    except (OSError, TimeoutError) as exc:
        return {"http_status": None, "http_responded": False, "gap": type(exc).__name__}


def _mcp_request(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """Perform one bounded read-only stateless MCP JSON-RPC call on localhost."""
    request = urllib.request.Request(
        _ENDPOINT,
        data=_canonical({
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
        }),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        content_type = response.headers.get("Content-Type", "")
        payload = response.read(65_537)
        if len(payload) > 65_536:
            raise RuntimeError("MCP response exceeds bounded size")
    if "text/event-stream" in content_type:
        records = [line[6:] for line in payload.decode().splitlines()
                   if line.startswith("data: ")]
        if len(records) != 1:
            raise RuntimeError("unexpected MCP event frame count")
        result = json.loads(records[0])
    elif "application/json" in content_type:
        result = json.loads(payload)
    else:
        raise RuntimeError("unexpected MCP response type")
    if result.get("jsonrpc") != "2.0" or result.get("id") != request_id or "error" in result:
        raise RuntimeError("invalid MCP JSON-RPC response")
    return result["result"]


def _mcp_observation() -> dict[str, Any]:
    """Read-only initialize and real nixer_status tool call; no runtime mutation."""
    try:
        initialize = _mcp_request(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {},
             "clientInfo": {"name": "repoground-s3-probe", "version": "1"}},
            1,
        )
        initialized = (
            initialize.get("serverInfo", {}).get("name") == "Nixer"
            and isinstance(initialize.get("protocolVersion"), str)
        )
        if not initialized:
            return {"protocol_handshake_verified": False, "tool_call_verified": False,
                    "gap": "unexpected_server_identity"}
        status = _mcp_request("tools/call", {"name": "nixer_status", "arguments": {}}, 2)
        result = status.get("structuredContent", {})
        good = (
            status.get("isError") is False
            and isinstance(result, dict)
            and result.get("identity") == "nixer-nix-specialist-v0"
            and result.get("service") == "Nixer"
            and result.get("backend", {}).get("ready") is True
        )
        return {
            "protocol_handshake_verified": True,
            "protocol_version": initialize["protocolVersion"],
            "server_name": initialize["serverInfo"]["name"],
            "tool_call_verified": good,
            "tool_name": "nixer_status",
            "tool_payload_sha256": _sha256(_canonical(result)) if good else None,
        }
    except (OSError, ValueError, KeyError, RuntimeError, TypeError) as exc:
        return {"protocol_handshake_verified": False, "tool_call_verified": False,
                "gap": type(exc).__name__}


def _tcp_listener_inodes(proc_tcp_text: str) -> set[str]:
    """Exact IPv4 listeners for 127.0.0.1:18187, including the wildcard bind."""
    result: set[str] = set()
    for line in proc_tcp_text.splitlines()[1:]:
        cols = line.split()
        if len(cols) < 10 or cols[3] != "0A":
            continue
        address_port = cols[1].split(":", 1)
        if (
            len(address_port) == 2
            and address_port[0] in {"0100007F", "00000000"}
            and address_port[1].upper() == "470B"
        ):
            result.add(cols[9])
    return result


def _mainpid_listener(pid: int, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    """Bind the IPv4 MCP listening socket to the observed systemd MainPID.

    A successful MCP response from an unrelated listener is not process proof.
    A shared/ambiguous port or inaccessible procfs remains unverified.
    """
    if pid <= 0:
        return {"verified": False, "reason": "main_pid_missing"}
    try:
        listeners = _tcp_listener_inodes((proc_root / str(pid) / "net/tcp").read_text())
        if len(listeners) != 1:
            return {"verified": False, "reason": "listener_missing_or_ambiguous"}
        inode = next(iter(listeners))
        for fd in (proc_root / str(pid) / "fd").iterdir():
            try:
                target = fd.readlink().as_posix()
            except OSError:
                continue
            if target == f"socket:[{inode}]":
                return {"verified": True, "socket_inode_sha256": _sha256(inode.encode())}
        return {"verified": False, "reason": "main_pid_does_not_own_listener"}
    except (OSError, ValueError) as exc:
        return {"verified": False, "reason": type(exc).__name__}


def _unit_state(unit: str) -> dict[str, str]:
    out = _cmd("systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState",
               "-p", "MainPID", "-p", "ExecStart", "-p", "ControlGroup")
    rows = {}
    for line in out.decode().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rows[k] = v
    return rows


def _store_output_from_execstart(execstart: str) -> str | None:
    match = re.search(r"\bpath=(/nix/store/[a-z0-9]{32}-[^ ;]+/bin/nixer)\b", execstart)
    if match is None:
        return None
    output = match.group(1).rsplit("/bin/nixer", 1)[0]
    return output if _STORE.fullmatch(output) else None


def _append_edge(edges: list[dict[str, Any]], relation: str, status: str,
                 reference: str | None = None, detail: str | None = None) -> None:
    row = {"relation": relation, "status": status}
    if reference is not None:
        row["evidence_ref"] = reference
    if detail is not None:
        row["detail"] = detail
    edges.append(row)


def _record_listener_ownership(
    edges: list[dict[str, Any]], gaps: list[str],
    before: dict[str, Any], after: dict[str, Any],
) -> bool:
    bound = before.get("verified") is True and before == after
    _append_edge(
        edges, "observed_process_to_endpoint_listener",
        "verified" if bound else "unverified",
        before.get("socket_inode_sha256"),
    )
    if not bound:
        gaps.append("nixer_mcp_listener_ownership_unverified")
    return bound


def _mcp_process_attribution(
    mcp_verified: bool, http_responded: bool, gaps: list[str] | None = None,
) -> str:
    """Socket ownership never implies identity of a TCP request handler."""
    if mcp_verified:
        if gaps is not None:
            gaps.append("mcp_request_handler_pid_not_proven")
        return "unattributed_mcp_response"
    return "http_reachable_only" if http_responded else "unverified"


def _source_comparison(
    drv_record: dict[str, Any],
    nixer_repo: Path,
    older_commit: str,
    declared_commit: str,
    edges: list[dict[str, Any]],
    gaps: list[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    source_paths = _derivation_sources(drv_record)
    source_bytes = {name: Path(file).read_bytes() for name, file in source_paths.items()}
    comparison = compare_source_contents(
        source_bytes, lambda commit, name: _git_blob(nixer_repo, commit, name),
        older_commit, declared_commit,
    )
    all_older = all(comparison[name].get("match_older") is True for name in _FILES)
    all_declared = all(comparison[name].get("match_declared") is True for name in _FILES)
    digest = _sha256(_canonical(comparison))
    _append_edge(edges, "older_git_sources_content_to_build_derivation",
                 "verified_content_equivalence" if all_older else "unverified", digest)
    declared_conflict = any(
        comparison[name].get("match_declared") is False for name in _FILES
    )
    _append_edge(edges, "declared_git_sources_content_to_build_derivation",
                 "verified_content_equivalence" if all_declared
                 else "source_content_mismatch" if declared_conflict else "unverified",
                 digest)
    if not all_older:
        gaps.append("older_git_source_content_not_fully_verified")
    if any(comparison[name].get("match_declared") is False for name in _FILES):
        gaps.append("declared_git_source_content_does_not_match_running_build")
    elif not all_declared:
        gaps.append("declared_git_source_content_unavailable")
    return source_paths, comparison


def build_report(
    heim_pc_repo: Path, heim_pc_commit: str, nixer_repo: Path,
    older_commit: str, declared_commit: str,
) -> dict[str, Any]:
    if any(not _SHA.fullmatch(x) for x in (heim_pc_commit, older_commit, declared_commit)):
        raise ValueError("source commits must be full lowercase Git SHAs")

    observed_at = datetime.now(timezone.utc).isoformat()
    gaps: list[str] = []
    edges: list[dict[str, Any]] = []
    input_proof = flake_revision_relations(
        heim_pc_repo, heim_pc_commit, source_repo="heimgewebe/heim-pc",
        targets={"heimgewebe/nixer": (nixer_repo, declared_commit)},
    )
    declared = any(
        x["relation_type"] == "flake_pinned_input"
        and x["target"]["repo_id"] == "heimgewebe/nixer"
        and x["target"]["commit"] == declared_commit
        for x in input_proof["relations"]
    )
    _append_edge(edges, "heim_pc_git_flake_to_declared_nixer_git_pin",
                 "verified" if declared else "unverified", input_proof["evidence_sha256"])
    gaps.extend("source_flake:" + s for s in input_proof["gaps"])

    generation = Path("/run/current-system").resolve(strict=True).as_posix()
    system_profile = Path("/nix/var/nix/profiles/system").resolve(strict=True).as_posix()
    unit_link = Path("/etc/systemd/system/nixer-headless.service").resolve(strict=True).as_posix()
    unit = _unit_state("nixer-headless.service")
    output = _store_output_from_execstart(unit.get("ExecStart", ""))
    if output is None:
        raise RuntimeError("effective nixer-headless ExecStart package is not identified")
    _append_edge(edges, "active_generation_to_system_profile",
                 "verified" if generation == system_profile else "mismatch", generation)
    why = _cmd("nix", "why-depends", "/run/current-system", output).decode()
    closure_verified = generation in why and output in why and unit_link.rsplit("/", 1)[0] in why
    _append_edge(edges, "activated_generation_to_nixer_unit_and_output",
                 "verified" if closure_verified else "unverified",
                 _sha256(why.encode()))
    if not closure_verified:
        gaps.append("nix_closure_dependency_chain_unverified")

    derivation = _cmd("nix-store", "-q", "--deriver", output).decode().strip()
    if not derivation.endswith(".drv") or not derivation.startswith("/nix/store/"):
        raise RuntimeError("no valid Nix deriver for running package")
    drv_doc = json.loads(_cmd("nix", "derivation", "show", derivation).decode())
    objects = drv_doc.get("derivations", drv_doc)
    drv_record = next(iter(objects.values())) if isinstance(objects, dict) and len(objects) == 1 else None
    if not isinstance(drv_record, dict):
        raise RuntimeError("Nix derivation JSON shape is unexpected")
    declared_output = drv_record.get("env", {}).get("out")
    derivative_verified = declared_output == output
    _append_edge(edges, "nix_derivation_to_store_output",
                 "verified" if derivative_verified else "mismatch", derivation)
    if not derivative_verified:
        gaps.append("derivation_output_mismatch")
    source_paths, comparison = _source_comparison(
        drv_record, nixer_repo, older_commit, declared_commit, edges, gaps,
    )

    pid = int(unit.get("MainPID", "0"))
    proc_cmdline = Path(f"/proc/{pid}/cmdline").read_bytes() if pid > 0 else b""
    proc_cgroup = Path(f"/proc/{pid}/cgroup").read_text() if pid > 0 else ""
    proc_exe = Path(f"/proc/{pid}/exe").resolve().as_posix() if pid > 0 else None
    unit_running = (
        unit.get("ActiveState") == "active" and pid > 0
        and output.encode() in proc_cmdline and "nixer-headless.service" in proc_cgroup
    )
    _append_edge(edges, "effective_systemd_unit_to_observed_process",
                 "verified" if unit_running else "unverified",
                 _sha256(proc_cmdline + proc_cgroup.encode()))
    if not unit_running:
        gaps.append("effective_unit_to_process_unverified")
    listener_before = _mainpid_listener(pid) if unit_running else {
        "verified": False, "reason": "unit_process_unverified",
    }
    http = _http_observation()
    mcp = _mcp_observation() if unit_running and http["http_responded"] else {
        "protocol_handshake_verified": False, "tool_call_verified": False,
        "gap": "endpoint_not_observed",
    }
    listener_after = _mainpid_listener(pid) if unit_running else {
        "verified": False, "reason": "unit_process_unverified",
    }
    listener_bound = _record_listener_ownership(
        edges, gaps, listener_before, listener_after,
    )
    _append_edge(
        edges, "mcp_endpoint_to_nixer_status",
        "verified" if mcp["tool_call_verified"] else "unverified",
        mcp.get("tool_payload_sha256") or _ENDPOINT,
    )
    # Holding the listener socket does not identify the process accepting the
    # request. Keep MCP success distinct from precise process attribution.
    _append_edge(
        edges, "observed_process_to_mcp_nixer_status",
        _mcp_process_attribution(
            mcp["tool_call_verified"], unit_running and http["http_responded"], gaps,
        ),
        mcp.get("tool_payload_sha256") or _ENDPOINT,
        "MCP response handler PID not established",
    )
    if not http["http_responded"]:
        gaps.append("endpoint_http_unreachable")
    if not mcp["tool_call_verified"]:
        gaps.append("mcp_initialize_or_tool_call_not_proven")
    gaps.append("full_nix_flake_source_to_derivation_identity_not_proven")

    result: dict[str, Any] = {
        "kind": _KIND, "version": "1", "observed_at_utc": observed_at,
        "source": {
            "heim_pc_commit": heim_pc_commit, "declared_nixer_commit": declared_commit,
            "content_comparison_older_nixer_commit": older_commit,
            "s1_evidence_sha256": input_proof["evidence_sha256"],
        },
        "nix": {
            "active_generation": generation, "system_profile": system_profile,
            "effective_unit_store_path": unit_link, "nixer_store_output": output,
            "nixer_derivation": derivation,
            "derivation_json_sha256": _sha256(_canonical(drv_doc)),
            "nixer_source_store_paths": source_paths,
            "why_depends_sha256": _sha256(why.encode()),
        },
        "systemd": {
            "unit": "nixer-headless.service", "active_state": unit.get("ActiveState"),
            "main_pid": pid, "cgroup": unit.get("ControlGroup"),
            "exec_start": unit.get("ExecStart"), "process_exe": proc_exe,
            "process_cmdline_sha256": _sha256(proc_cmdline),
        },
        "source_file_matches": comparison,
        "endpoint": {
            "url": _ENDPOINT, **http, **mcp,
            "listener_ownership": {
                "verified": listener_bound,
                "before": listener_before, "after": listener_after,
            },
        },
        "edges": edges, "gaps": sorted(set(gaps)),
        "status": "partial" if gaps else "ok",
        "does_not_establish": [
            "unique_git_commit_from_equal_content", "current_git_pin_was_built",
            "exact_nix_flake_input_to_derivation_identity",
            "runtime_source_equal_to_declared_pin", "absence_of_other_processes",
            "mcp_request_handler_pid",
        ],
    }
    result["evidence_sha256"] = _sha256(_canonical(result))
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--heim-pc-repo", required=True, type=Path)
    p.add_argument("--heim-pc-commit", required=True)
    p.add_argument("--nixer-repo", required=True, type=Path)
    p.add_argument("--older-nixer-commit", required=True)
    p.add_argument("--declared-nixer-commit", required=True)
    args = p.parse_args()
    print(json.dumps(build_report(
        args.heim_pc_repo, args.heim_pc_commit, args.nixer_repo,
        args.older_nixer_commit, args.declared_nixer_commit,
    ), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())