from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
import uuid
import hashlib
import json
from datetime import datetime, timezone

def calculate_job_hash(req: "JobRequest", hub_resolved: str, version: str) -> str:
    """
    Calculates a deterministic hash for the job parameters to ensure idempotency.
    Includes 'version' to ensure reproducibility across software updates.
    """
    # Normalize extras
    extras_list = sorted([x.strip().lower() for x in (req.extras or "").split(",") if x.strip()])
    extras_str = ",".join(extras_list)

    # Normalize path_filter (None vs "")
    path_filter = req.path_filter.strip() if isinstance(req.path_filter, str) else None
    if path_filter == "":
        path_filter = None

    # Normalize repos
    repos_list = sorted(req.repos) if req.repos else ["__ALL__"]

    # Normalize extensions
    ext_list = sorted(req.extensions) if req.extensions else []

    # Normalize include_paths
    inc_paths = None
    if req.include_paths is not None:
        stripped_paths = [p.strip() for p in req.include_paths]
        if any(p in (".", "") for p in stripped_paths):
            inc_paths = None
        else:
            inc_paths = sorted(set(stripped_paths))

    # Normalize include_paths_by_repo
    inc_paths_repo = None
    if req.include_paths_by_repo is not None:
        inc_paths_repo = {}
        for r, paths in req.include_paths_by_repo.items():
            if paths is None:
                inc_paths_repo[r] = None
            else:
                stripped_repo_paths = [p.strip() for p in paths]
                if not req.strict_include_paths_by_repo and any(p in (".", "") for p in stripped_repo_paths):
                    # Legacy behavior: if not strict, treat "." or "" as None (All)
                    inc_paths_repo[r] = None
                else:
                    inc_paths_repo[r] = sorted(set(stripped_repo_paths))

    # Construct signature dict
    sig = {
        "lenskit_version": version,
        "hub": hub_resolved, # Use resolved hub path!
        "repos": repos_list,
        "level": req.level,
        "mode": req.mode,
        "max_bytes": req.max_bytes,
        "split_size": req.split_size,
        "plan_only": req.plan_only,
        "code_only": req.code_only,
        "extensions": ext_list,
        "path_filter": path_filter,
        "extras": extras_str,
        "json_sidecar": req.json_sidecar,
        "meta_density": req.meta_density,
        "include_paths": inc_paths,
        "include_paths_by_repo": inc_paths_repo,
        "strict_include_paths_by_repo": req.strict_include_paths_by_repo,
        # New fields v2.4
        "output_mode": req.output_mode,
        "redact_secrets": req.redact_secrets,
        "include_hidden": req.include_hidden,
        # Effective pre-pull changes the meaning of a job: a fast-forwarded tree
        # can produce a different dump than the stale one. plan_only never mutates
        # repos, so plan_only/pre_pull=True hashes like plan_only/pre_pull=False.
        "pre_pull": req.pre_pull and not req.plan_only,
        # Merges dir excluded from content hash:
        # Same content, different output path = same logical job.
        # Client must check returned artifact for actual path.
    }

    # Serialize and hash
    sig_str = json.dumps(sig, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(sig_str.encode("utf-8")).hexdigest()

class JobRequest(BaseModel):
    hub: Optional[str] = None
    merges_dir: Optional[str] = None # Output directory override
    repos: Optional[List[str]] = None  # None/empty = all
    level: Literal["overview", "summary", "dev", "max"] = "dev"
    mode: Literal["gesamt", "pro-repo"] = "gesamt"
    max_bytes: Optional[str] = "0"  # human size string or "0"
    split_size: Optional[str] = "25MB"
    plan_only: bool = False
    code_only: bool = False
    extensions: Optional[List[str]] = None
    path_filter: Optional[str] = None
    include_paths: Optional[List[str]] = None # Relative paths to include (whitelist)
    include_paths_by_repo: Optional[Dict[str, Optional[List[str]]]] = None
    strict_include_paths_by_repo: bool = False # If True, missing keys in include_paths_by_repo trigger hard fail (400)
    # Default: Minimal (Agent-fokussiert). Nur Sidecars.
    # Aligning with repolens.py logic to prevent drift.
    extras: Optional[str] = "json_sidecar,augment_sidecar"
    meta_density: Literal["min", "standard", "full", "auto"] = Field(
        default="auto",
        description="Controls the density of metadata (headers, file_meta blocks) in the report. 'auto' switches to 'standard' if filters are active."
    )
    json_sidecar: bool = True  # Default true for service
    force_new: bool = False
    # Bounded repo-sync mutation: fast-forward-only fetch/merge of each selected
    # local repo before the scan. Default on; disable for a pure read of the
    # current on-disk state. See docs/service-api.md (Mutation Boundary).
    pre_pull: bool = Field(
        default=True,
        description="Fast-forward-only fetch/merge before scan (bounded repo-sync mutation). Blocks on dirty or diverged repos.",
    )
    # v2.4 Parity Features
    output_mode: Literal["archive", "retrieval", "dual"] = "dual"
    redact_secrets: bool = False
    include_hidden: bool = Field(default=True, description="Whether to include hidden files/directories (starting with .)")

class AtlasEffective(BaseModel):
    max_depth: int
    max_entries: int
    exclude_globs: List[str]

class AtlasRequest(BaseModel):
    # The new formal root model for internal use:
    root_kind: Literal["preset", "token", "abs_path"]
    root_value: Optional[str] = None
    root_token: Optional[str] = None
    inventory_strict: bool = True
    scan_mode: Literal["inventory", "topology", "content", "workspace"] = "inventory"

    # Deprecated legacy fields:
    # These fields are no longer mapped or respected by the `resolve_atlas_root`
    # server logic. They remain temporarily in the schema as inert compatibility
    # remnants during the request-shape transition. Requests lacking the canonical
    # `root_kind` will fail validation (422) regardless of these fields.
    root_id: Optional[str] = None
    root: Optional[str] = None

    max_depth: int = 6
    max_entries: int = 200000
    exclude_globs: Optional[List[str]] = None
    sample_files: bool = False
    no_default_excludes: bool = False
    # max_file_size: Limit in bytes for files included in the scan.
    # null indicates unlimited size. >0 limits size.
    max_file_size: Optional[int] = Field(default=50 * 1024 * 1024, description="Max file size in bytes. Null for unlimited.")

class AtlasArtifact(BaseModel):
    """Projection of an Atlas scan artifact for the API layer.

    Status vocabulary (unified across CLI and API)
    -----------------------------------------------
    - ``"running"``  — scan is in progress
    - ``"complete"`` — scan finished successfully (terminal)
    - ``"failed"``   — scan terminated with an error (terminal)

    Note: the CLI path persists status in the SQLite registry while the
    API path persists status in the JSON artifact file.  Both paths use
    the **same three status values** above.  See ``atlas/lifecycle.py``
    for the shared lifecycle executor that guarantees deterministic
    finalization.

    ``is_stalled`` is a **derived diagnostic flag** — it is NOT a status
    class.  It is computed on-the-fly from ``last_progress_at`` (>60 s
    without update) and never persisted.  UI consumers can use it to warn
    about potentially hung scans without introducing a fourth status value.
    """
    id: str
    status: Literal["running", "complete", "failed"] = "complete"
    created_at: str
    hub: str
    root_scanned: str
    paths: Dict[str, str] # {"json": "...", "md": "..."}
    stats: Dict[str, Any] # Summary stats (total_* = final result, *_seen = in-progress counters)
    effective: Optional[AtlasEffective] = None # Effective parameters (max_depth, etc)
    error: Optional[str] = None # Generic error message if failed
    is_stalled: bool = False  # Derived diagnostic: True when status == "running" but no progress for >60s

class Artifact(BaseModel):
    id: str
    job_id: str
    hub: str
    repos: List[str]
    created_at: str
    paths: Dict[str, str]  # e.g. {"md": "...", "json": "...", "part2": "..."}
    params: JobRequest # Effective parameters used for generation (normalized)
    merges_dir: Optional[str] = None # Effective absolute path to output directory

class Job(BaseModel):
    id: str
    # 'canceling' = user requested cancel, runner hasn't stopped yet
    # 'canceled' = final state
    status: Literal["queued", "running", "succeeded", "failed", "canceling", "canceled"]
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    request: JobRequest
    hub_resolved: Optional[str] = None
    content_hash: Optional[str] = None
    logs: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    artifact_ids: List[str] = Field(default_factory=list)
    error: Optional[str] = None

    @classmethod
    def create(cls, request: JobRequest, content_hash: Optional[str] = None) -> "Job":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            id=str(uuid.uuid4()),
            status="queued",
            created_at=now,
            request=request,
            content_hash=content_hash,
            logs=[],
            warnings=[],
            artifact_ids=[]
        )

class PrescanRequest(BaseModel):
    repo: str # Repo name to scan
    max_depth: int = 10
    ignore_globs: Optional[List[str]] = None

class PrescanNode(BaseModel):
    path: str
    type: Literal["file", "dir"]
    size: Optional[int] = None
    children: Optional[List["PrescanNode"]] = None

try:
    PrescanNode.model_rebuild()
except AttributeError:
    # Fallback for Pydantic v1
    try:
        PrescanNode.update_forward_refs()
    except AttributeError:
        pass

class FederationQueryRequest(BaseModel):
    federation_index: str
    q: str
    k: int = 10
    repo: Optional[str] = None
    path: Optional[str] = None
    ext: Optional[str] = None
    layer: Optional[str] = None
    artifact_type: Optional[str] = None
    embedding_policy: Optional[str] = None
    explain: bool = False
    trace: bool = False
    build_context_bundle: bool = False
    output_profile: Optional[Literal["human_review", "agent_minimal", "ui_navigation", "lookup_minimal", "review_context"]] = None

class PrescanResponse(BaseModel):
    root: str
    tree: PrescanNode
    signature: str
    file_count: int
    total_bytes: int

class FSRoot(BaseModel):
    id: str
    path: str
    token: str

class FSRootsResponse(BaseModel):
    roots: List[FSRoot]

class QueryRequest(BaseModel):
    index_id: str
    q: str
    k: int = 10
    repo: Optional[str] = None
    path: Optional[str] = None
    ext: Optional[str] = None
    layer: Optional[str] = None
    artifact_type: Optional[str] = None
    output_profile: Optional[Literal["human_review", "agent_minimal", "ui_navigation", "lookup_minimal", "review_context"]] = None
    context_mode: Literal["exact", "block", "window", "file"] = "exact"
    context_window_lines: int = 0
    build_context_bundle: bool = False
    explain: bool = False
    trace: bool = False
    embedding_policy: Optional[str] = None
    graph_index: Optional[str] = None
    graph_weights: Optional[Dict[str, float]] = None
    stale_policy: Literal["fail", "warn", "ignore"] = "fail"
    test_penalty: float = 0.75
    overmatch_guard: bool = False


class ArtifactLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_type: Literal["query_trace", "context_bundle", "agent_query_session"]
    id: str = Field(min_length=1)


class TraceLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class ContextLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
