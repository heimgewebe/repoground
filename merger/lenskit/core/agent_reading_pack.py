"""
Agent Reading Pack Producer for the ``agent_reading_pack`` artifact role.

Produces ``<stem>.agent_reading_pack.md`` — a compact, deterministic Markdown
document that an LLM agent reads FIRST to understand a Lenskit bundle:

  * which artifact is authoritative for what (reading policy / artifact roles),
  * how to run full-text search and resolve byte/line ranges and citations,
  * which source files map to which canonical_md byte/line ranges,
  * the bundle's own output-health verdict,
  * what is explicitly absent (epistemic emptiness).

Governance: the pack is ``authority=navigation_index`` / ``canonicality=derived``.
It is NAVIGATION, NOT TRUTH. The only source of truth is ``canonical_md``;
every claim must be verified against the canonical bytes.

Design contract (mirrors core/citation_map.py):
  * pure functions for model-building and rendering; IO isolated to the producer,
  * SHA256 of the truth-anchoring artifacts (canonical_md, chunk_index) is verified
    against the manifest — a mismatch is a hard failure (no lying pack),
  * diagnostic/derived inputs (output_health, citation_map) only warn on mismatch,
  * atomic write, no partial output on failure,
  * deterministic body: derived purely from the manifest and the artifacts it
    references (bundle ``created_at`` is used, never a fresh clock read).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .citation_map import byte_range_to_line_range, normalize_canonical_range
from .claim_evidence_diagnostics import (
    claim_absence_reason_detail,
    claim_absence_reason_from_manifest,
)
from .check_view import compact_check_projection
from .constants import ArtifactRole
from .path_security import resolve_secure_path

PRODUCED_BY = "agent_reading_pack_producer/v1"
PACK_VERSION = "v1.1"
TOP_CHUNK_SPAN_LIMIT = 30

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNC_RE = re.compile(r"^\\\\")

_MANIFEST_SUFFIX = ".bundle.manifest.json"
_OUTPUT_SUFFIX = ".agent_reading_pack.md"

# Roles whose presence/integrity the pack relies on for truthful navigation.
_CANONICAL_MD = ArtifactRole.CANONICAL_MD.value
_CHUNK_INDEX = ArtifactRole.CHUNK_INDEX_JSONL.value
_DUMP_INDEX = ArtifactRole.DUMP_INDEX_JSON.value
_SQLITE_INDEX = ArtifactRole.SQLITE_INDEX.value
_OUTPUT_HEALTH = ArtifactRole.OUTPUT_HEALTH.value
_CITATION_MAP = ArtifactRole.CITATION_MAP_JSONL.value
_CLAIM_EVIDENCE_MAP = ArtifactRole.CLAIM_EVIDENCE_MAP_JSON.value
_SELF_ROLE = ArtifactRole.AGENT_READING_PACK.value
_AGENT_ENTRY_MANIFEST = ArtifactRole.AGENT_ENTRY_MANIFEST.value
_EXPORT_SAFETY_REPORT = "export_safety_report"
_SNAPSHOT_PLAN_JSON = "snapshot_plan_json"
_LENS_CARD_ROLES = ("lens_cards_jsonl", "lens_card_jsonl", "lens_cards")
_CONCEPT_CARD_ROLES = ("concept_cards_jsonl", "concept_card_jsonl", "concept_cards")
_PR_DELTA_CARD_ROLES = ("pr_delta_cards_jsonl", "pr_delta_card_jsonl", "pr_delta_cards")
_RELATION_CARD_ROLES = ("relation_cards_jsonl", "relation_card_jsonl", "relation_cards")
_SYMBOL_INDEX_ROLES = ("python_symbol_index_json", "python_symbol_index")
_CALL_GRAPH_ROLES = ("python_call_graph_json", "python_call_graph")


class AgentReadingPackError(Exception):
    pass


# ---------------------------------------------------------------------------
# Path / hash helpers (mirror citation_map.py conventions)
# ---------------------------------------------------------------------------

def _normalize_relative_path(raw: str, label: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{label}: path must be a string")
    if raw.startswith("/"):
        raise ValueError(f"{label}: absolute paths are forbidden")
    if _UNC_RE.match(raw):
        raise ValueError(f"{label}: UNC paths are forbidden")
    if raw.startswith("\\"):
        raise ValueError(f"{label}: Windows rooted paths are forbidden")
    if _WINDOWS_DRIVE_RE.match(raw):
        raise ValueError(f"{label}: Windows drive-prefixed paths are forbidden")
    parts = raw.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(f"{label}: path traversal ('..') is forbidden")
    normalized = [p for p in parts if p not in ("", ".")]
    if not normalized:
        raise ValueError(f"{label}: path must not be empty")
    return "/".join(normalized)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(65536), b""):
            h.update(buf)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_path = Path(tmp_file.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _first_nonempty_str(*values: Any) -> Optional[str]:
    for v in values:
        if isinstance(v, str) and v:
            return v
    return None


# ---------------------------------------------------------------------------
# Pure model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ArtifactView:
    role: str
    path: str
    authority: Optional[str]
    canonicality: Optional[str]
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TopFile:
    path: str
    repo_id: Optional[str]
    chunk_count: int
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class HealthSummary:
    present: bool
    verdict: Optional[str] = None
    chunk_count: Optional[int] = None
    sqlite_row_count: Optional[int] = None
    fts_content_non_empty: Optional[bool] = None
    range_ref_resolution_status: Optional[str] = None
    error_count: int = 0
    warning_count: int = 0


@dataclass(frozen=True, slots=True)
class PackModel:
    run_id: str
    created_at: Optional[str]
    generator_name: Optional[str]
    generator_version: Optional[str]
    redaction: Optional[bool]
    fts5_bm25: Optional[bool]
    artifacts: Tuple[ArtifactView, ...]
    health: HealthSummary
    top_files: Tuple[TopFile, ...]
    top_chunk_spans_status: str
    top_chunk_spans_reason: Optional[str]
    indexed_chunk_count: int
    repo_ids: Tuple[str, ...]
    bundle_manifest_path: str
    canonical_md_path: Optional[str]
    chunk_index_path: Optional[str]
    dump_index_path: Optional[str]
    sqlite_index_path: Optional[str]
    citation_map_path: Optional[str]
    claim_evidence_map_path: Optional[str]
    claim_count: Optional[int]
    claim_evidence_ref_count: Optional[int]
    claim_requires_live_check_count: Optional[int]
    absent_notes: Tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Top-file aggregation (pure)
# ---------------------------------------------------------------------------

def compute_top_files(
    chunk_index_path: Path,
    canonical_md_bytes: bytes,
    canonical_md_rel: str,
    *,
    limit: int = TOP_CHUNK_SPAN_LIMIT,
) -> Tuple[List[TopFile], List[str], int]:
    """
    Aggregate chunk-index entries into per-source-file canonical spans.

    Returns ``(top_files, repo_ids, indexed_chunk_count)``.

    Only chunks whose canonical range targets ``canonical_md_rel`` contribute to
    a file's span; ``indexed_chunk_count`` counts every well-formed chunk object.
    Files are ranked by (chunk_count desc, span_bytes desc, repo asc, path asc)
    so the output is deterministic for identical inputs.
    """
    file_size = len(canonical_md_bytes)
    agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    repos: set[str] = set()
    indexed_chunk_count = 0

    with chunk_index_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(chunk, dict):
                continue
            indexed_chunk_count += 1

            # Derive repo_id from search_keys and chunk.repo independently so conflicts
            # within the fallback tier are also detected conservatively.
            search_keys = chunk.get("search_keys")
            search_repo_id = _first_nonempty_str(
                search_keys.get("repo_id") if isinstance(search_keys, dict) else None
            )
            chunk_repo_id = _first_nonempty_str(chunk.get("repo"))
            for _cand in (search_repo_id, chunk_repo_id):
                if _cand:
                    repos.add(_cand)
            if search_repo_id and chunk_repo_id and search_repo_id != chunk_repo_id:
                fallback_repo_id = None  # conflicting fallback sources — conservative
            else:
                fallback_repo_id = _first_nonempty_str(search_repo_id, chunk_repo_id)

            norm_range = normalize_canonical_range(chunk)
            if norm_range is None:
                continue

            # Prefer canonical_range.repo_id over search_keys/chunk.repo for TopFile attribution;
            # on conflict, omit rather than silently assert a potentially wrong affiliation.
            range_repo_id = _first_nonempty_str(
                norm_range.get("repo_id") if isinstance(norm_range, dict) else None
            )
            if range_repo_id:
                repos.add(range_repo_id)

            if range_repo_id and fallback_repo_id and range_repo_id != fallback_repo_id:
                repo_id = None  # conflicting sources — conservative
            else:
                repo_id = _first_nonempty_str(range_repo_id, fallback_repo_id)
            raw_fp = norm_range.get("file_path", "")
            try:
                norm_fp = _normalize_relative_path(raw_fp, "range.file_path")
            except ValueError:
                continue
            if norm_fp != canonical_md_rel:
                continue

            start_byte = norm_range.get("start_byte")
            end_byte = norm_range.get("end_byte")
            if isinstance(start_byte, bool) or isinstance(end_byte, bool):
                continue
            if not isinstance(start_byte, int) or not isinstance(end_byte, int):
                continue
            if start_byte < 0 or end_byte <= start_byte or end_byte > file_size:
                continue

            src_path = _first_nonempty_str(chunk.get("path")) or "<unknown>"
            key = (repo_id or "", src_path)
            entry = agg.get(key)
            if entry is None:
                agg[key] = {
                    "repo_id": repo_id,
                    "path": src_path,
                    "count": 1,
                    "start": start_byte,
                    "end": end_byte,
                }
            else:
                entry["count"] += 1
                entry["start"] = min(entry["start"], start_byte)
                entry["end"] = max(entry["end"], end_byte)

    top: List[TopFile] = []
    for entry in agg.values():
        start_line, end_line = byte_range_to_line_range(
            canonical_md_bytes, entry["start"], entry["end"]
        )
        top.append(
            TopFile(
                path=entry["path"],
                repo_id=entry["repo_id"],
                chunk_count=entry["count"],
                start_byte=entry["start"],
                end_byte=entry["end"],
                start_line=start_line,
                end_line=end_line,
            )
        )

    top.sort(
        key=lambda t: (
            -t.chunk_count,
            -(t.end_byte - t.start_byte),
            t.repo_id or "",
            t.path,
        )
    )
    return top[:limit], sorted(repos), indexed_chunk_count


def summarize_health(health_doc: Dict[str, Any]) -> HealthSummary:
    """Build a HealthSummary from a parsed output_health.json document."""
    raw_checks = health_doc.get("checks")
    checks = compact_check_projection(health_doc) if isinstance(raw_checks, dict) else {}
    errors = health_doc.get("errors")
    warnings = health_doc.get("warnings")
    return HealthSummary(
        present=True,
        verdict=health_doc.get("verdict") if isinstance(health_doc.get("verdict"), str) else None,
        chunk_count=checks.get("chunk_count"),
        sqlite_row_count=checks.get("sqlite_row_count"),
        fts_content_non_empty=checks.get("fts_content_non_empty"),
        range_ref_resolution_status=checks.get("range_ref_resolution_status"),
        error_count=len(errors) if isinstance(errors, list) else 0,
        warning_count=len(warnings) if isinstance(warnings, list) else 0,
    )


# ---------------------------------------------------------------------------
# Rendering (pure)
# ---------------------------------------------------------------------------

def _md_cell(value: Any) -> str:
    if value is None:
        return "—"
    text = str(value)
    if text.strip() == "":
        return "—"
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _yn(value: Optional[bool]) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def _artifact_by_role(model: PackModel, role: str) -> Optional[ArtifactView]:
    for artifact in model.artifacts:
        if artifact.role == role:
            return artifact
    return None


def _artifacts_by_roles(model: PackModel, roles: Tuple[str, ...]) -> Tuple[ArtifactView, ...]:
    role_set = set(roles)
    return tuple(artifact for artifact in model.artifacts if artifact.role in role_set)


def _append_artifact_bullet(lines: List[str], artifact: ArtifactView) -> None:
    lines.append(
        "- `{role}`: `{path}` "
        "(authority=`{authority}`, canonicality=`{canonicality}`, sha256=`{sha}`)".format(
            role=_md_cell(artifact.role),
            path=_md_cell(artifact.path),
            authority=_md_cell(artifact.authority),
            canonicality=_md_cell(artifact.canonicality),
            sha=_md_cell(artifact.sha256[:12]),
        )
    )


_ROLE_GUIDE = {
    _CANONICAL_MD: "the ONLY source of truth — read exact bytes/lines from here",
    _CHUNK_INDEX: "retrieval index: byte/line ranges per chunk for precise navigation",
    _DUMP_INDEX: "navigation index of dumped files (resolve range refs against this)",
    _SQLITE_INDEX: "runtime cache: FTS5 full-text search over chunk content",
    _OUTPUT_HEALTH: "diagnostic self-test: trust the bundle only if verdict=pass",
    _CITATION_MAP: "stable citation_id → canonical byte/line range mapping",
    _CLAIM_EVIDENCE_MAP: "claim → declared evidence_refs map (navigation/evidence index, not truth)",
    _AGENT_ENTRY_MANIFEST: "machine-readable agent front door (navigation index, not truth)",
    "index_sidecar_json": "navigation index sidecar (repolens-agent contract)",
    "derived_manifest_json": "registry of derived artifacts",
    "graph_index_json": "import/entry-point graph for graph-aware retrieval",
    "retrieval_eval_json": "diagnostic retrieval-quality evaluation",
    "architecture_summary": "diagnostic high-level architecture snapshot",
    "delta_json": "diagnostic change delta vs a prior run",
    "concept_cards_jsonl": "Concept Card navigation index over explicit task concepts, dependencies, failures and queries",
    "relation_cards_jsonl": "Relation Card navigation index over supported local import edges",
    "python_symbol_index_json": "Python AST symbol navigation index; static parse only, not runtime truth",
    "python_call_graph_json": "Python AST call-site navigation index; only safe static resolutions, not runtime truth",
}


def _append_call_graph_section(lines: List[str], model: PackModel) -> None:
    lines.append("## CALL_GRAPH_INDEX")
    artifacts = _artifacts_by_roles(model, _CALL_GRAPH_ROLES)
    if artifacts:
        for artifact in artifacts:
            _append_artifact_bullet(lines, artifact)
        lines.append(
            "- MCP: `find_references` lists bounded S0/S1 call sites; `get_callers` "
            "selects one exact target symbol and returns only S1 callers; `get_callees` "
            "selects one exact caller symbol and separates S1 targets from unresolved S0 sites."
        )
    else:
        lines.append("- No bundle-registered Python Call Graph artifact is present in this manifest.")
    lines.append(
        "- Call Graph records are static AST call sites. S1 means one unique local target "
        "under the modelled lexical bindings; shadowed, ambiguous, dynamic, foreign or "
        "unindexed calls remain explicit S0 evidence."
    )
    lines.append(
        "- does_not_establish: complete call graph, runtime reachability, dynamic "
        "dispatch resolution, dependency completeness, transitive import resolution, "
        "import success, test sufficiency, review completeness or merge readiness."
    )
    lines.append("")


def render_agent_reading_pack(model: PackModel) -> str:
    lines: List[str] = []
    lines.append(
        f"<!-- ARTIFACT:{_SELF_ROLE} VERSION:{PACK_VERSION} "
        "AUTHORITY:navigation_index CANONICALITY:derived -->"
    )
    lines.append("# Agent Reading Pack")
    lines.append("")
    lines.append(
        "> **NAVIGATION, NOT TRUTH.** This document is a *derived* navigation aid "
        "(`authority=navigation_index`, `canonicality=derived`). The only source of "
        "truth is `canonical_md`. Treat every statement here as a pointer to verify "
        "against the canonical bytes, never as evidence on its own."
    )
    lines.append("")

    # ── BUNDLE_IDENTITY ──────────────────────────────────────────────────
    lines.append("## BUNDLE_IDENTITY")
    lines.append(f"- run_id: `{model.run_id}`")
    lines.append(f"- created_at: {model.created_at or 'unknown'}")
    gen = " ".join(p for p in (model.generator_name, model.generator_version) if p) or "unknown"
    lines.append(f"- generator: {gen}")
    lines.append(f"- redaction: {_yn(model.redaction)}")
    lines.append(f"- fts5_bm25: {_yn(model.fts5_bm25)}")
    lines.append(f"- indexed_chunks: {model.indexed_chunk_count}")
    if model.repo_ids:
        lines.append(f"- repos: {', '.join(model.repo_ids)}")
    lines.append("")

    # ── READING_POLICY ───────────────────────────────────────────────────
    lines.append("## READING_POLICY")
    lines.append(
        "Authorities rank what an artifact may assert: `canonical_content` > "
        "`navigation_index`/`retrieval_index` > `diagnostic_signal`/`runtime_cache`. "
        "Use derived artifacts to *find* content, then read it from `canonical_md`."
    )
    lines.append("")
    present_roles = [a.role for a in model.artifacts]
    for role in present_roles:
        guide = _ROLE_GUIDE.get(role, "see artifact role table below")
        lines.append(f"- `{role}` — {guide}")
    lines.append("")

    # ── REQUIRED_READING_BY_TASK ─────────────────────────────────────────
    lines.append("## REQUIRED_READING_BY_TASK")
    lines.append(
        "Choose the task profile that matches the claim. Required artifacts are "
        "profile-specific; sidecars remain navigation or diagnosis, not content truth."
    )
    lines.append("| task_profile | required | recommended | insufficient |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(
        "| `basic_repo_question` | `agent_reading_pack`, `canonical_md` | "
        "`citation_map_jsonl` when making specific cited claims | "
        "sidecar-only claims without canonical verification |"
    )
    lines.append(
        "| `pr_review` | `agent_reading_pack`, `canonical_md`, `citation_map_jsonl`, "
        "`post_emit_health` | `claim_evidence_map_json` when roadmap/status claims are "
        "involved; `bundle_surface_validation` when bundle/surface claims are involved | "
        "only reading `canonical_md` linearly; relying on a health pass as review completeness |"
    )
    lines.append(
        "| `roadmap_status_claim` | `agent_reading_pack`, `canonical_md`, "
        "`claim_evidence_map_json` | `citation_map_jsonl` | roadmap status without the "
        "Claim Evidence Map or a canonical check |"
    )
    lines.append(
        "| `artifact_surface_review` | `bundle_manifest`, `post_emit_health`, "
        "`bundle_surface_validation`, `canonical_md` | `output_health` | "
        "`output_health` alone; any health pass treated as claim truth |"
    )
    lines.append(
        "| `retrieval_quality_review` | `retrieval_eval_json`, `chunk_index_jsonl`, "
        "`sqlite_index`, `canonical_md` | `docs/retrieval/*` | impressionistic retrieval "
        "claims without metrics |"
    )
    lines.append(
        "| `security_export_review` | `agent_reading_pack`, `canonical_md`, "
        "`export_safety_report`, `post_emit_health` | `agent_entry_manifest`, "
        "`bundle_surface_validation`, `output_health` | export decision without "
        "export_safety_report; treating export_safety_report as secret absence |"
    )
    lines.append("")

    # ── WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT ───────────────────────────
    lines.append("## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT")
    lines.append(
        "`canonical_md` contains the content truth, but some tasks require sidecars to "
        "locate, validate or diagnose the relevant evidence surface."
    )
    lines.append("Additional role-appropriate artifacts are needed for:")
    lines.append("- PR review with evidence requirements.")
    lines.append("- Roadmap or status claims.")
    lines.append("- Bundle or surface health assessment.")
    lines.append("- Retrieval quality assessment.")
    lines.append("- Citation or range readiness claims.")
    lines.append("- Claims about present or missing sidecars.")
    lines.append("- Claims about artifact authority, canonicality or risk class.")
    lines.append("")

    # ── SIDECAR_USAGE_RULES ──────────────────────────────────────────────
    lines.append("## SIDECAR_USAGE_RULES")
    lines.append("- Sidecars are navigation, diagnostic signals, indexes or caches; they are not content truth.")
    lines.append("- Content claims must resolve back to `canonical_md`, the only content truth.")
    lines.append("- `citation_map_jsonl` maps stable citation IDs to canonical ranges.")
    lines.append("- `claim_evidence_map_json` is an evidence-navigation index, not truth.")
    lines.append("- `post_emit_health` is post-emit surface diagnosis, not repo understanding.")
    lines.append("- `bundle_surface_validation` is surface coherence validation, not claim truth.")
    lines.append(
        "- `output_health` is a pre-/emit diagnostic signal and must not be read as "
        "forensic readiness."
    )
    lines.append("- `sqlite_index` is runtime cache/search support, not authority.")
    lines.append(
        "- `retrieval_eval_json` is a diagnostic retrieval-quality signal; for "
        "retrieval quality reviews inspect its `miss_taxonomy` to see why expected "
        "targets were missed. Miss taxonomy is diagnostic only and does not prove "
        "retrieval completeness, target absence in the repository, semantic "
        "irrelevance, claim truth or repo understanding."
    )
    lines.append("")


    # ── AGENT_ENTRY_MANIFEST ─────────────────────────────────────────────
    lines.append("## AGENT_ENTRY_MANIFEST")
    entry_manifest = _artifact_by_role(model, _AGENT_ENTRY_MANIFEST)
    if entry_manifest is not None:
        _append_artifact_bullet(lines, entry_manifest)
        lines.append(
            "- role: machine-readable front door for agents; navigation only, not content truth."
        )
    else:
        lines.append(
            "- `agent_entry_manifest` is not visible in this Reading Pack's manifest snapshot. "
            "For finalized bundles, inspect the final `bundle_manifest.artifacts` for "
            "role=`agent_entry_manifest`."
        )
        lines.append(
            "- reason: this pack may be emitted before the Agent Entry Manifest to avoid "
            "circular hash claims. Absence here is not evidence that the final bundle lacks it."
        )
    lines.append(
        "- does_not_establish: repo understanding, answer correctness, all relevant "
        "context use, forensic readiness or claim truth."
    )
    lines.append("")

    # ── AGENT_CONSUMPTION_CONTRACTS ─────────────────────────────────────
    lines.append("## AGENT_CONSUMPTION_CONTRACTS")
    lines.append(
        "Known machine-readable agent-consumption surfaces. These are accountability "
        "and navigation aids; they do not prove actual reading or understanding."
    )
    lines.append("- `required-reading-protocol.v1`: task profile → required/recommended roles.")
    lines.append("- `answer-compliance.v1`: answer-side declaration of artifacts, ranges and non-claims.")
    lines.append("- `agent-consumption-trace.v1`: comparison of required reading and declared consumption.")
    lines.append(
        "- CLI: `python3 -m merger.lenskit.cli.main agent-consumption required "
        "--task-profile <profile> ...`"
    )
    lines.append("- CLI: `python3 -m merger.lenskit.cli.main agent-consumption preflight --task-profile <profile> ...`")
    lines.append(
        "- CLI: `python3 -m merger.lenskit.cli.main agent-consumption validate-trace ...`"
    )
    lines.append(
        "- does_not_establish: actual_reading_proven, answer_correct, repo_understood, "
        "all_relevant_context_used or claims_true."
    )
    lines.append("")

    # ── EXPORT_SAFETY_REPORT ────────────────────────────────────────────
    lines.append("## EXPORT_SAFETY_REPORT")
    export_safety = _artifact_by_role(model, _EXPORT_SAFETY_REPORT)
    if export_safety is not None:
        _append_artifact_bullet(lines, export_safety)
    else:
        lines.append(
            "- No bundle-registered `export_safety_report` artifact is present in this manifest."
        )
    lines.append(
        "- Inspect report fields `profile`, `status`, `redaction_required`, "
        "`redaction_observed`, `post_emit_health_status`, and `agent_export_gate_status`."
    )
    lines.append(
        "- Export-safety reports are diagnostic policy checks. They do not prove "
        "secret absence, PII absence, public-share safety, repo understanding or forensic readiness."
    )
    lines.append("")

    # ── SNAPSHOT_PLAN_REPORT ─────────────────────────────────────────────
    lines.append("## SNAPSHOT_PLAN_REPORT")
    snapshot_plan = _artifact_by_role(model, _SNAPSHOT_PLAN_JSON)
    if snapshot_plan is not None:
        _append_artifact_bullet(lines, snapshot_plan)
    else:
        lines.append("- No bundle-registered `snapshot_plan_json` artifact is present in this manifest.")
    lines.append(
        "- Snapshot Plan reports describe how RepoBrief selected the snapshot profile "
        "and output mode. They do not prove repo understanding, correctness, "
        "completeness, safety, test sufficiency or forensic readiness."
    )
    lines.append("")

    # ── LENS_CARD_INDEX ─────────────────────────────────────────────────
    lines.append("## LENS_CARD_INDEX")
    lens_card_artifacts = _artifacts_by_roles(model, _LENS_CARD_ROLES)
    if lens_card_artifacts:
        for artifact in lens_card_artifacts:
            _append_artifact_bullet(lines, artifact)
    else:
        lines.append(
            "- No bundle-registered Lens Card artifact is present in this manifest."
        )
    lines.append(
        "- Lens Cards, when present, are path navigation units derived from Primary "
        "Lens and Facet data. They do not prove truth, impact, safety, coverage or review completeness."
    )
    lines.append("")


    # ── CONCEPT_CARD_INDEX ───────────────────────────────────────────────
    lines.append("## CONCEPT_CARD_INDEX")
    concept_card_artifacts = _artifacts_by_roles(model, _CONCEPT_CARD_ROLES)
    if concept_card_artifacts:
        for artifact in concept_card_artifacts:
            _append_artifact_bullet(lines, artifact)
    else:
        lines.append(
            "- No bundle-registered Concept Card artifact is present in this manifest."
        )
    lines.append(
        "- Concept Cards, when present, are deterministic task-navigation cards "
        "derived from explicit registry specs. They do not prove truth, completeness, "
        "semantic importance, review priority, runtime dependency, causality, "
        "security assessment or change impact."
    )
    lines.append("")

    # ── PR_DELTA_CARD_INDEX ─────────────────────────────────────────────
    lines.append("## PR_DELTA_CARD_INDEX")
    pr_delta_card_artifacts = _artifacts_by_roles(model, _PR_DELTA_CARD_ROLES)
    if pr_delta_card_artifacts:
        for artifact in pr_delta_card_artifacts:
            _append_artifact_bullet(lines, artifact)
    else:
        lines.append(
            "- No bundle-registered PR Delta Card artifact is present in this manifest."
        )
    if _artifact_by_role(model, "delta_json") is not None:
        lines.append(
            "- `delta_json` is present; it is the source diagnostic surface, not a card index."
        )
    lines.append(
        "- PR Delta Cards, when present, describe file-level navigation deltas only. "
        "They do not prove review findings, breakage, safety or required fixes."
    )
    lines.append("")

    # ── RELATION_CARD_INDEX ─────────────────────────────────────────────
    lines.append("## RELATION_CARD_INDEX")
    relation_card_artifacts = _artifacts_by_roles(model, _RELATION_CARD_ROLES)
    if relation_card_artifacts:
        for artifact in relation_card_artifacts:
            _append_artifact_bullet(lines, artifact)
    else:
        lines.append(
            "- No bundle-registered Relation Card artifact is present in this manifest."
        )
    lines.append(
        "- Relation Cards, when present, expose formal or heuristic links. They do "
        "not prove impact, causality, test sufficiency, runtime behavior or regression absence."
    )
    lines.append("")

    # ── SYMBOL_INDEX ────────────────────────────────────────────────────
    lines.append("## SYMBOL_INDEX")
    symbol_index_artifacts = _artifacts_by_roles(model, _SYMBOL_INDEX_ROLES)
    if symbol_index_artifacts:
        for artifact in symbol_index_artifacts:
            _append_artifact_bullet(lines, artifact)
        lines.append(
            "- CLI: `python3 -m merger.lenskit.cli.main repobrief symbol search "
            "--bundle-manifest <manifest> --q <name>`"
        )
    else:
        lines.append("- No bundle-registered Python Symbol Index artifact is present in this manifest.")
    lines.append(
        "- Symbol Index records are parsed from Python AST without importing or executing "
        "target code. They are navigation hints only."
    )
    lines.append(
        "- does_not_establish: call graph completeness, dependency completeness, import "
        "success, runtime behavior, test sufficiency, review impact or merge readiness."
    )
    lines.append("")

    _append_call_graph_section(lines, model)

    # ── GRAPH_DIAGNOSTICS ───────────────────────────────────────────────
    lines.append("## GRAPH_DIAGNOSTICS")
    graph_roles = (
        ArtifactRole.ARCHITECTURE_GRAPH_JSON.value,
        ArtifactRole.ENTRYPOINTS_JSON.value,
        ArtifactRole.GRAPH_INDEX_JSON.value,
    )
    graph_artifacts = _artifacts_by_roles(model, graph_roles)
    if graph_artifacts:
        for artifact in graph_artifacts:
            _append_artifact_bullet(lines, artifact)
    else:
        lines.append("- No graph diagnostic artifacts are present in this manifest.")
    lines.append(
        "- Graph artifacts are diagnostic/navigation surfaces. They do not prove "
        "runtime call reachability, architecture completeness, dependency causality or change impact."
    )
    lines.append("")

    # ── RETRIEVAL_DIAGNOSTICS ───────────────────────────────────────────
    lines.append("## RETRIEVAL_DIAGNOSTICS")
    retrieval_roles = (_CHUNK_INDEX, _SQLITE_INDEX, ArtifactRole.RETRIEVAL_EVAL_JSON.value)
    retrieval_artifacts = _artifacts_by_roles(model, retrieval_roles)
    if retrieval_artifacts:
        for artifact in retrieval_artifacts:
            _append_artifact_bullet(lines, artifact)
    else:
        lines.append("- No retrieval diagnostic artifacts are present in this manifest.")
    lines.append(
        "- Inspect `retrieval_eval_json` and `miss_taxonomy` when reviewing retrieval quality. "
        "A retrieval diagnostic does not prove relevant content is absent or semantically irrelevant."
    )
    lines.append("")

    # ── WHAT_THIS_DOES_NOT_PROVE ────────────────────────────────────────
    lines.append("## WHAT_THIS_DOES_NOT_PROVE")
    lines.append("This Reading Pack v2 index surface does not prove:")
    lines.append("- `truth`")
    lines.append("- `repo_understood`")
    lines.append("- `answer_correct`")
    lines.append("- `answer_safe_without_citations`")
    lines.append("- `all_relevant_context_used`")
    lines.append("- `test_sufficiency`")
    lines.append("- `runtime_behavior`")
    lines.append("- `regression_absence`")
    lines.append("- `forensic_ready`")
    lines.append("")
    # ── LENS_CARD_GUIDANCE ───────────────────────────────────────────────
    lines.append("## LENS_CARD_GUIDANCE")
    lines.append(
        "Lens Cards, when available, are optional derived navigation indexes "
        "(`authority=navigation_index`, `canonicality=derived`)."
    )
    lines.append(
        "They project the existing Primary Lens and Facet Model for a repo path; "
        "they do not introduce a new Primary Lens or Facet taxonomy."
    )
    lines.append(
        "Lens Cards do not replace `canonical_md`, which remains the only content truth."
    )
    lines.append(
        "A Lens Card does not prove truth, repo understanding, review completeness, "
        "test sufficiency, runtime correctness, regression absence, safety or "
        "change impact."
    )
    lines.append(
        "When `lens_cards_jsonl` is present in the bundle manifest, treat it as "
        "a path-navigation artifact only; it still does not replace canonical reads."
    )
    lines.append("")

    # ── AGENT_CONSUMPTION_CONTRACT ───────────────────────────────────────
    lines.append("## AGENT_CONSUMPTION_CONTRACT")
    lines.append(
        "Agent-consumption surfaces are navigation and accountability aids. "
        "They do not replace `canonical_md`."
    )
    lines.append("Use them when present:")
    lines.append(
        "- `agent_entry_manifest` / `lenskit.agent_entry_manifest`: "
        "machine-readable bundle entrypoint."
    )
    lines.append(
        "- `required_reading_protocol` / `lenskit.required_reading_protocol`: "
        "task-profile-specific required reading."
    )
    lines.append(
        "- `agent_consumption_trace` / `lenskit.agent_consumption_trace`: "
        "machine-readable declaration of consumed artifacts, ranges, and citations."
    )
    lines.append(
        "- `answer_compliance` / `ANSWER_COMPLIANCE_CHECKLIST`: answer-side "
        "obligations and non-claims; declaration only, not proof of actual reading."
    )
    lines.append(
        "- `export_safety_report` / `lenskit.export_safety_report`: "
        "export diagnostic only."
    )
    lines.append(
        "- `snapshot_plan_json` / `repobrief.snapshot_plan`: snapshot planning "
        "diagnostic only; it records profile/output-mode decisions and does not "
        "prove correctness, completeness or safety."
    )
    lines.append(
        "This does not establish `repo_understood`, `answer_safe_without_citations`, "
        "`claims_true`, `all_relevant_context_used`, `secret_absence`, `pii_absence`, "
        "or `forensic_ready`."
    )
    lines.append("`canonical_md` remains the only content truth.")
    lines.append(
        "Sidecars remain navigation, diagnostics, index, evidence, or cache."
    )
    lines.append(
        "Health passes do not prove repo understanding, answer safety, test "
        "sufficiency, runtime correctness, regression absence, or forensic readiness."
    )
    lines.append("")

    # ── ANSWER_COMPLIANCE_CHECKLIST ──────────────────────────────────────
    lines.append("## ANSWER_COMPLIANCE_CHECKLIST")
    lines.append("```text")
    lines.append("Lenskit consumption:")
    lines.append("- task_profile:")
    lines.append("- required_artifacts_checked:")
    lines.append("- sidecars_used:")
    lines.append("- canonical_ranges_or_citations_used:")
    lines.append("- sidecars_not_used_and_why:")
    lines.append("- epistemic_gaps:")
    lines.append("- does_not_establish:")
    lines.append("```")
    lines.append(
        "This checklist is a declaration aid, not proof that the agent actually read or "
        "understood the artifacts."
    )
    lines.append("")

    # ── DO_NOT_CLAIM ─────────────────────────────────────────────────────
    lines.append("## DO_NOT_CLAIM")
    lines.append("The Agent Reading Pack, health reports, surface validation and sidecars do not prove:")
    lines.append("- `repo_understood` — navigation or a health pass does not prove repo understanding.")
    lines.append("- `claims_true` — indexes and surface checks do not prove content claims true.")
    lines.append(
        "- `answer_safe_without_citations` — artifact presence does not make citations unnecessary."
    )
    lines.append("- `test_sufficiency` — located tests do not prove sufficient coverage.")
    lines.append("- `runtime_correctness` — static artifacts do not prove runtime behavior.")
    lines.append("- `review_complete` — reading guidance or health passes do not complete a review.")
    lines.append(
        "- `change_impact` — relation or path proximity alone does not prove change impact."
    )
    lines.append("- `forensic_ready` — diagnostic passes do not establish forensic readiness.")
    lines.append("- `all_relevant_context_used` — sidecar use does not prove complete context use.")
    lines.append("- `regression_absence` — these artifacts do not prove that regressions are absent.")
    lines.append("")

    # ── ARTIFACT_ROLES ───────────────────────────────────────────────────
    lines.append("## ARTIFACT_ROLES")
    lines.append("| role | authority | canonicality | bytes | sha256 | path |")
    lines.append("| --- | --- | --- | ---: | --- | --- |")
    for a in model.artifacts:
        lines.append(
            "| {role} | {auth} | {canon} | {bytes} | `{sha}` | `{path}` |".format(
                role=_md_cell(a.role),
                auth=_md_cell(a.authority),
                canon=_md_cell(a.canonicality),
                bytes=a.bytes,
                sha=_md_cell(a.sha256[:12]),
                path=_md_cell(a.path),
            )
        )
    lines.append("")

    # ── OUTPUT_HEALTH_SUMMARY ────────────────────────────────────────────
    lines.append("## OUTPUT_HEALTH_SUMMARY")
    if model.health.present:
        h = model.health
        lines.append(f"- verdict: **{h.verdict or 'unknown'}**")
        lines.append(f"- chunk_count: {h.chunk_count if h.chunk_count is not None else 'unknown'}")
        lines.append(
            f"- sqlite_row_count: {h.sqlite_row_count if h.sqlite_row_count is not None else 'unknown'}"
        )
        lines.append(f"- fts_content_non_empty: {_yn(h.fts_content_non_empty)}")
        lines.append(f"- range_ref_resolution_status: {h.range_ref_resolution_status or 'unknown'}")
        lines.append(f"- errors: {h.error_count}, warnings: {h.warning_count}")
        lines.append(
            "- note: `agent_pack_present` in `output_health` may read `skipped` — "
            "health is computed before this pack is emitted (v1)."
        )
    else:
        lines.append("- _No `output_health` artifact present; bundle is self-unverified._")
    lines.append("")

    # ── HOW_TO_SEARCH ────────────────────────────────────────────────────
    lines.append("## HOW_TO_SEARCH")
    if model.sqlite_index_path:
        lines.append("Full-text search (FTS5/BM25):")
        lines.append("```bash")
        lines.append(
            "python3 -m merger.lenskit.cli.main query "
            f'--index "{model.sqlite_index_path}" --q "<terms>" --emit json'
        )
        lines.append("```")
    else:
        lines.append("- No verified `sqlite_index` available: full-text search is unavailable for this bundle.")
    lines.append("Resolve a byte/line range to exact text (against this bundle manifest):")
    lines.append("```bash")
    lines.append(
        "python3 -m merger.lenskit.cli.main range get "
        f'--manifest "{model.bundle_manifest_path}" --ref <range_ref.json> --format json'
    )
    lines.append("```")
    if model.citation_map_path:
        lines.append(
            f"Stable citations: each line of `{model.citation_map_path}` maps a "
            "`citation_id` to a `canonical_range` (file_path/start_byte/end_byte/"
            "start_line/end_line/content_sha256) inside `canonical_md`."
        )
    lines.append("")

    # ── CLAIM_EVIDENCE_MAP_SUMMARY ───────────────────────────────────────
    lines.append("## CLAIM_EVIDENCE_MAP_SUMMARY")
    if (
        model.claim_evidence_map_path
        and model.claim_count is not None
        and model.claim_evidence_ref_count is not None
        and model.claim_requires_live_check_count is not None
    ):
        lines.append(f"- artifact: `{model.claim_evidence_map_path}`")
        lines.append(f"- claims: {model.claim_count}")
        lines.append(f"- evidence_refs: {model.claim_evidence_ref_count}")
        lines.append(f"- requires_live_check: {model.claim_requires_live_check_count}")
        lines.append(
            "- note: Claim Evidence Map is navigation/evidence index, not truth."
        )
        lines.append(
            "- does_not_establish: truth, sufficiency, causality, completeness."
        )
    else:
        lines.append("- _No verified `claim_evidence_map_json` artifact present._")
    lines.append("")

    # ── TOP_CHUNK_SPANS ──────────────────────────────────────────────────
    lines.append(f"## TOP_CHUNK_SPANS (top {TOP_CHUNK_SPAN_LIMIT} by chunk coverage)")
    lines.append(
        "```json\n"
        "{\n"
        '  "artifact": "agent_reading_pack",\n'
        '  "applies_to": "TOP_CHUNK_SPANS",\n'
        '  "authority": "navigation_index",\n'
        '  "canonicality": "derived",\n'
        '  "risk_class": "navigation",\n'
        '  "may_cite": false,\n'
        '  "must_resolve_to": "role_specific_authority",\n'
        '  "does_not_prove": [\n'
        '    "semantic_importance",\n'
        '    "architecture_truth",\n'
        '    "complete_context"\n'
        "  ]\n"
        "}\n"
        "```"
    )
    lines.append(f"- status: `{model.top_chunk_spans_status}`")
    if model.top_chunk_spans_reason:
        lines.append(f"- reason_code: `{model.top_chunk_spans_reason}`")
    if model.top_files:
        lines.append(
            "Largest aggregated canonical spans by chunk coverage. Navigation aid only; "
            "not an importance ranking. Canonical spans point into `canonical_md`; use "
            "them to read or cite a file's content precisely. `bytes` is `[start_byte, end_byte)`."
        )
        lines.append("| file | repo | chunks | bytes | lines |")
        lines.append("| --- | --- | ---: | --- | --- |")
        for t in model.top_files:
            lines.append(
                "| `{path}` | {repo} | {chunks} | [{sb}, {eb}) | {sl}–{el} |".format(
                    path=_md_cell(t.path),
                    repo=_md_cell(t.repo_id),
                    chunks=t.chunk_count,
                    sb=t.start_byte,
                    eb=t.end_byte,
                    sl=t.start_line,
                    el=t.end_line,
                )
            )
    else:
        lines.append(
            "- _No canonical file spans available; this is an explicit "
            "`not_applicable` surface with a machine-readable reason_code above._"
        )
    lines.append("")

    # ── EPISTEMIC_EMPTINESS ──────────────────────────────────────────────
    lines.append("## EPISTEMIC_EMPTINESS")
    if model.absent_notes:
        for note in model.absent_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- No expected artifacts are missing from this bundle.")
    lines.append("")

    lines.append(f"<!-- produced_by:{PRODUCED_BY} -->")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# IO adapter
# ---------------------------------------------------------------------------

def _fail_report(
    production_run_id: str,
    manifest_path_str: str,
    errors: List[str],
    *,
    bundle_run_id: Any = None,
    error_kind: str = "production_error",
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "status": "fail",
        "error_kind": error_kind,
        "bundle_manifest_path": manifest_path_str,
        "bundle_run_id": bundle_run_id,
        "production_run_id": production_run_id,
        "canonical_md_sha256": None,
        "chunk_index_sha256": None,
        "output_path": None,
        "output_sha256": None,
        "output_bytes": None,
        "artifact_role_count": 0,
        "top_file_count": 0,
        "indexed_chunk_count": 0,
        "health_verdict": None,
        "errors": errors,
        "warnings": warnings or [],
    }


def _remove_stale_output(output_path: Optional[Path], protected: set[Path]) -> Optional[str]:
    if output_path is None:
        return None
    try:
        resolved = output_path.resolve()
    except OSError:
        return None
    if resolved in protected:
        return None
    try:
        output_path.unlink(missing_ok=True)
        return None
    except OSError as e:
        return f"Could not remove stale output {str(output_path)!r}: {e}"


def _verify_referenced_artifact(
    entry: Dict[str, Any],
    manifest_dir: Path,
    label: str,
    *,
    hard: bool,
    errors: List[str],
    warnings: List[str],
) -> Optional[Tuple[Path, str]]:
    """Resolve, existence-check and SHA-verify a manifest artifact entry.

    Returns ``(abs_path, actual_sha256)`` on success, else ``None`` (appending to
    ``errors`` when ``hard`` is True, otherwise to ``warnings``).
    """
    sink = errors if hard else warnings
    raw = entry.get("path", "")
    try:
        rel = _normalize_relative_path(raw, f"{label}.path")
    except ValueError as e:
        sink.append(f"{label}: {e}")
        return None
    try:
        abs_path = resolve_secure_path(manifest_dir, rel)
    except ValueError as e:
        sink.append(f"{label}: unsafe path: {e}")
        return None
    if not abs_path.exists() or not abs_path.is_file():
        sink.append(f"{label}: file not found: {rel}")
        return None
    try:
        actual = _sha256_file(abs_path)
    except OSError as e:
        sink.append(f"{label}: cannot read file: {e}")
        return None
    manifest_sha = entry.get("sha256")
    if not isinstance(manifest_sha, str) or not _SHA256_RE.fullmatch(manifest_sha):
        # A truth anchor without a verifiable expected hash is a missing check,
        # not a neutral state. Hard roles fail; soft roles warn and are skipped.
        sink.append(f"{label}: missing or invalid sha256 in manifest")
        return None
    if actual != manifest_sha:
        sink.append(
            f"{label}: sha256 mismatch (manifest={manifest_sha[:12]} actual={actual[:12]})"
        )
        return None
    return abs_path, actual


def produce_agent_reading_pack(  # lenskit:requires-authority=canonical_content
    manifest_path_str: str,
    output_path_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Produce ``<stem>.agent_reading_pack.md`` from a bundle manifest.

    Returns a structured report dict. The Markdown is written adjacent to the
    manifest unless ``output_path_str`` is given. Truth-anchoring artifacts
    (canonical_md, chunk_index) are SHA-verified against the manifest; a mismatch
    fails production. Diagnostic inputs (output_health, citation_map) only warn.
    """
    production_run_id = str(uuid.uuid4())
    errors: List[str] = []
    warnings: List[str] = []

    manifest_path = Path(manifest_path_str)
    if not manifest_path.is_absolute():
        manifest_path = Path.cwd() / manifest_path
    manifest_path = manifest_path.resolve()
    manifest_path_str = str(manifest_path)

    output_path: Optional[Path] = None
    if output_path_str:
        p = Path(output_path_str)
        output_path = p if p.is_absolute() else Path.cwd() / p
    elif manifest_path.name.endswith(_MANIFEST_SUFFIX):
        stem = manifest_path.name[: -len(_MANIFEST_SUFFIX)]
        output_path = manifest_path.parent / (stem + _OUTPUT_SUFFIX)

    output_is_explicit = output_path_str is not None
    protected: set[Path] = {manifest_path}

    if not manifest_path.exists() or not manifest_path.is_file():
        # Input error before any manifest load: never mutate existing outputs.
        return _fail_report(
            production_run_id,
            manifest_path_str,
            [f"Manifest not found or not a file: {manifest_path}"],
            error_kind="path_read_error",
        )

    manifest_dir = manifest_path.parent
    try:
        manifest = load_manifest(manifest_path)
    except (json.JSONDecodeError, OSError) as e:
        # Input error before any manifest load: never mutate existing outputs.
        return _fail_report(
            production_run_id,
            manifest_path_str,
            [f"Cannot load manifest: {e}"],
            error_kind="path_read_error",
        )

    bundle_run_id = manifest.get("run_id")
    if not isinstance(bundle_run_id, str) or not bundle_run_id:
        _s = _remove_stale_output(output_path, protected) if not output_is_explicit else None
        return _fail_report(
            production_run_id,
            manifest_path_str,
            [f"Manifest 'run_id' is missing or empty: {bundle_run_id!r}"] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
        )

    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        _s = _remove_stale_output(output_path, protected) if not output_is_explicit else None
        return _fail_report(
            production_run_id,
            manifest_path_str,
            ["Manifest 'artifacts' must be a list"] + ([_s] if _s else []),
            bundle_run_id=bundle_run_id,
        )

    # Build the artifact-role view, skipping the pack's own role so re-runs never
    # list a previous pack as bundle content. While iterating, collect every
    # non-self artifact path into `protected` so an explicit --output can never
    # overwrite a manifest-listed input — even one that is not part of the
    # verification set or that fails soft verification. _SELF_ROLE stays excluded
    # so idempotent regeneration over a final manifest still works.
    by_role: Dict[str, Dict[str, Any]] = {}
    artifact_views: List[ArtifactView] = []
    for a in raw_artifacts:
        if not isinstance(a, dict):
            continue
        role = a.get("role")
        if not isinstance(role, str) or role == _SELF_ROLE:
            continue
        raw_path = a.get("path")
        if isinstance(raw_path, str):
            try:
                rel = _normalize_relative_path(raw_path, f"{role}.path")
                protected.add(resolve_secure_path(manifest_dir, rel))
            except ValueError:
                # Role-specific verification still reports hard/soft errors for
                # malformed paths where relevant; tolerate them here.
                pass
        by_role.setdefault(role, a)
        artifact_views.append(
            ArtifactView(
                role=role,
                path=str(a.get("path", "")),
                authority=a.get("authority") if isinstance(a.get("authority"), str) else None,
                canonicality=a.get("canonicality") if isinstance(a.get("canonicality"), str) else None,
                bytes=a.get("bytes") if isinstance(a.get("bytes"), int) else 0,
                sha256=_first_nonempty_str(a.get("sha256")) or "",
            )
        )
    artifact_views.sort(key=lambda v: (v.role, v.path))

    # --- verify truth-anchoring artifacts (hard) and diagnostics (soft) ---
    canonical_md_path: Optional[Path] = None
    canonical_md_sha: Optional[str] = None
    if _CANONICAL_MD in by_role:
        res = _verify_referenced_artifact(
            by_role[_CANONICAL_MD], manifest_dir, "canonical_md",
            hard=True, errors=errors, warnings=warnings,
        )
        if res:
            canonical_md_path, canonical_md_sha = res
            protected.add(canonical_md_path)

    chunk_index_path: Optional[Path] = None
    chunk_index_sha: Optional[str] = None
    if _CHUNK_INDEX in by_role:
        res = _verify_referenced_artifact(
            by_role[_CHUNK_INDEX], manifest_dir, "chunk_index_jsonl",
            hard=True, errors=errors, warnings=warnings,
        )
        if res:
            chunk_index_path, chunk_index_sha = res
            protected.add(chunk_index_path)

    verified_soft_paths: Dict[str, str] = {}

    health: HealthSummary = HealthSummary(present=False)  # lenskit:authority=diagnostic_signal
    claim_count: Optional[int] = None
    claim_evidence_ref_count: Optional[int] = None
    claim_requires_live_check_count: Optional[int] = None
    if _OUTPUT_HEALTH in by_role:
        res = _verify_referenced_artifact(
            by_role[_OUTPUT_HEALTH], manifest_dir, "output_health",
            hard=False, errors=errors, warnings=warnings,
        )
        if res:
            try:
                health = summarize_health(load_manifest(res[0]))
            except (json.JSONDecodeError, OSError) as e:
                warnings.append(f"output_health: cannot parse ({e})")

    for soft_role, label in (
        (_CITATION_MAP, "citation_map_jsonl"),
        (_CLAIM_EVIDENCE_MAP, "claim_evidence_map_json"),
        (_DUMP_INDEX, "dump_index_json"),
        (_SQLITE_INDEX, "sqlite_index"),
    ):
        if soft_role in by_role:
            res = _verify_referenced_artifact(
                by_role[soft_role], manifest_dir, label,
                hard=False, errors=errors, warnings=warnings,
            )
            if res:
                protected.add(res[0])
                verified_soft_paths[soft_role] = str(by_role[soft_role].get("path"))
                if soft_role == _CLAIM_EVIDENCE_MAP:
                    try:
                        claim_doc = load_manifest(res[0])
                    except (json.JSONDecodeError, OSError) as e:
                        warnings.append(f"claim_evidence_map_json: cannot parse ({e})")
                        verified_soft_paths.pop(_CLAIM_EVIDENCE_MAP, None)
                    else:
                        claims = claim_doc.get("claims") if isinstance(claim_doc, dict) else None
                        if isinstance(claims, list):
                            claim_count = len(claims)
                            claim_evidence_ref_count = 0
                            claim_requires_live_check_count = 0
                            for claim in claims:
                                if not isinstance(claim, dict):
                                    continue
                                refs = claim.get("evidence_refs")
                                if isinstance(refs, list):
                                    claim_evidence_ref_count += len(refs)
                                if claim.get("requires_live_check") is True:
                                    claim_requires_live_check_count += 1
                        else:
                            warnings.append(
                                "claim_evidence_map_json: missing or invalid 'claims' list"
                            )
                            verified_soft_paths.pop(_CLAIM_EVIDENCE_MAP, None)

    if errors:
        _s = _remove_stale_output(output_path, protected) if not output_is_explicit else None
        if _s:
            errors.append(_s)
        return _fail_report(
            production_run_id, manifest_path_str, errors,
            bundle_run_id=bundle_run_id, warnings=warnings,
        )

    # --- top files (needs canonical_md bytes + chunk index) ---
    top_files: List[TopFile] = []
    top_chunk_spans_status = "not_applicable"
    top_chunk_spans_reason: Optional[str] = "top_chunk_spans_missing_required_inputs"
    repo_ids: List[str] = []
    indexed_chunk_count = 0
    absent_notes: List[str] = []
    claim_absence_reason = claim_absence_reason_from_manifest(manifest)

    if canonical_md_path is not None and chunk_index_path is not None:
        try:
            canonical_md_bytes = canonical_md_path.read_bytes()
            canonical_md_rel = _normalize_relative_path(
                by_role[_CANONICAL_MD].get("path", ""), "canonical_md.path"
            )
            top_files, repo_ids, indexed_chunk_count = compute_top_files(
                chunk_index_path, canonical_md_bytes, canonical_md_rel
            )
            if top_files:
                top_chunk_spans_status = "available"
                top_chunk_spans_reason = None
            else:
                top_chunk_spans_reason = "top_chunk_spans_no_canonical_chunk_ranges"
        except (OSError, ValueError) as e:
            return _fail_report(
                production_run_id, manifest_path_str,
                [f"Cannot compute top files: {e}"],
                bundle_run_id=bundle_run_id, error_kind="path_read_error",
                warnings=warnings,
            )

    # --- epistemic emptiness notes ---
    if _CANONICAL_MD not in by_role:
        absent_notes.append("`canonical_md` is absent: no canonical source of truth in this bundle.")
    if _CHUNK_INDEX not in by_role:
        absent_notes.append("`chunk_index_jsonl` is absent: no precise range navigation available.")
    if _SQLITE_INDEX not in by_role:
        absent_notes.append("`sqlite_index` is absent: full-text search is unavailable.")
    elif _SQLITE_INDEX not in verified_soft_paths:
        absent_notes.append(
            "`sqlite_index` is present but failed verification; full-text search command suppressed."
        )
    if _CITATION_MAP not in by_role:
        absent_notes.append("`citation_map_jsonl` is absent: no stable citation_id mapping.")
    elif _CITATION_MAP not in verified_soft_paths:
        absent_notes.append(
            "`citation_map_jsonl` is present but failed verification; citation guidance suppressed."
        )
    if _CLAIM_EVIDENCE_MAP not in by_role:
        reason_detail = claim_absence_reason_detail(claim_absence_reason)
        reason_suffix = (
            f" reason={claim_absence_reason} ({reason_detail})."
            if claim_absence_reason is not None
            else ""
        )
        absent_notes.append(
            "`claim_evidence_map_json` is absent: claim→evidence navigation index not available."
            + reason_suffix
        )
        absent_notes.append(
            "`claim_evidence_map` is absent in this bundle; claim→evidence navigation remains explicitly unavailable."
        )
    elif _CLAIM_EVIDENCE_MAP not in verified_soft_paths:
        absent_notes.append(
            "`claim_evidence_map_json` is present but failed verification or parsing; claim-evidence summary suppressed."
        )
    if _OUTPUT_HEALTH not in by_role:
        absent_notes.append("`output_health` is absent: bundle integrity is self-unverified.")
    elif not health.present:
        absent_notes.append(
            "`output_health` is present but failed verification or parsing; health summary suppressed."
        )

    generator = manifest.get("generator") if isinstance(manifest.get("generator"), dict) else {}
    capabilities = manifest.get("capabilities") if isinstance(manifest.get("capabilities"), dict) else {}

    # Render a usable manifest path in the range command: use the filename only when
    # the pack and the manifest are co-located; otherwise render the absolute path so
    # a reader can resolve the range command from wherever the pack file was placed.
    if output_path is not None and output_path.parent.resolve() == manifest_path.parent.resolve():
        bundle_manifest_for_pack = manifest_path.name
    else:
        bundle_manifest_for_pack = str(manifest_path)

    model = PackModel(
        run_id=bundle_run_id,
        created_at=manifest.get("created_at") if isinstance(manifest.get("created_at"), str) else None,
        generator_name=generator.get("name") if isinstance(generator.get("name"), str) else None,
        generator_version=generator.get("version") if isinstance(generator.get("version"), str) else None,
        redaction=capabilities.get("redaction") if isinstance(capabilities.get("redaction"), bool) else None,
        fts5_bm25=capabilities.get("fts5_bm25") if isinstance(capabilities.get("fts5_bm25"), bool) else None,
        artifacts=tuple(artifact_views),
        health=health,
        top_files=tuple(top_files),
        top_chunk_spans_status=top_chunk_spans_status,
        top_chunk_spans_reason=top_chunk_spans_reason,
        indexed_chunk_count=indexed_chunk_count,
        repo_ids=tuple(repo_ids),
        bundle_manifest_path=bundle_manifest_for_pack,
        canonical_md_path=str(by_role[_CANONICAL_MD].get("path")) if _CANONICAL_MD in by_role else None,
        chunk_index_path=str(by_role[_CHUNK_INDEX].get("path")) if _CHUNK_INDEX in by_role else None,
        dump_index_path=verified_soft_paths.get(_DUMP_INDEX),
        sqlite_index_path=verified_soft_paths.get(_SQLITE_INDEX),
        citation_map_path=verified_soft_paths.get(_CITATION_MAP),
        claim_evidence_map_path=verified_soft_paths.get(_CLAIM_EVIDENCE_MAP),
        claim_count=claim_count,
        claim_evidence_ref_count=claim_evidence_ref_count,
        claim_requires_live_check_count=claim_requires_live_check_count,
        absent_notes=tuple(absent_notes),
    )

    body = render_agent_reading_pack(model)
    body_bytes = body.encode("utf-8")

    # --- output path safety ---
    if output_path is None:
        return _fail_report(
            production_run_id, manifest_path_str,
            [
                f"Cannot derive safe output path: manifest filename {manifest_path.name!r} "
                f"does not end with '{_MANIFEST_SUFFIX}'. Pass --output explicitly."
            ],
            bundle_run_id=bundle_run_id, warnings=warnings,
        )
    if output_path.resolve() in protected:
        return _fail_report(
            production_run_id, manifest_path_str,
            [
                f"Output path {str(output_path)!r} collides with an input artifact. "
                "Pass --output to specify a safe destination."
            ],
            bundle_run_id=bundle_run_id, warnings=warnings,
        )

    try:
        _write_bytes_atomic(output_path, body_bytes)
    except OSError as e:
        return _fail_report(
            production_run_id, manifest_path_str,
            [f"Cannot write output: {e}"],
            bundle_run_id=bundle_run_id, error_kind="path_read_error",
            warnings=warnings,
        )

    return {
        "status": "ok",
        "error_kind": "ok",
        "bundle_manifest_path": manifest_path_str,
        "bundle_run_id": bundle_run_id,
        "production_run_id": production_run_id,
        "canonical_md_sha256": canonical_md_sha,
        "chunk_index_sha256": chunk_index_sha,
        "output_path": str(output_path),
        "output_sha256": _sha256_bytes(body_bytes),
        "output_bytes": len(body_bytes),
        "artifact_role_count": len(artifact_views),
        "top_file_count": len(top_files),
        "indexed_chunk_count": indexed_chunk_count,
        "health_verdict": health.verdict,
        "errors": errors,
        "warnings": warnings,
    }
