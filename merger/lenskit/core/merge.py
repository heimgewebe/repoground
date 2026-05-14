from __future__ import annotations
# -*- coding: utf-8 -*-

"""
merge_core – Core functions for repoLens (v2.4 Standard).
Implements AI-friendly formatting, tagging, and strict Pflichtenheft structure.
"""

import os
import sys
import json
import hashlib
import datetime
import re
import unicodedata
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any, Iterator, NamedTuple, Set
from dataclasses import dataclass, asdict

from . import lenses
from .constants import ArtifactRole
from . import clock
from .chunker import Chunker
from .redactor import Redactor
from .range_resolver import build_explicit_range_ref
from . import __core_version__ as CORE_VERSION

try:
    import yaml  # PyYAML
except Exception:  # pragma: no cover
    yaml = None


_NON_ALNUM = re.compile(r"[^a-z0-9]+")

EPISTEMIC_HUMILITY_WARNING = "⚠️ **Hinweis:** Dieses Profil/Filter erlaubt keine Aussagen über das Nicht-Vorhandensein von Dateien im Repository. Fehlende Einträge bedeuten lediglich „nicht im Ausschnitt enthalten“."

def _slug_token(s: str) -> str:
    """Deterministic ASCII token suitable for heading ids across renderers."""

    # Normalize to NFC to ensure consistent handling of diacritics
    # (e.g. ü as single char vs u+umlaut) before regex stripping
    s = unicodedata.normalize("NFC", s)
    s = s.lower()
    s = s.replace("/", "-").replace(".", "-")
    s = _NON_ALNUM.sub("-", s).strip("-")
    return s


READING_POLICY_BANNER = (
    "**READING POLICY (verbindlich):**\n"
    "- Dieses Markdown ist die kanonische Quelle und vollständig zu lesen.\n"
    "- Die JSON-Datei ist nur Index/Metadaten/Einstieg und enthält NICHT die volle Information.\n"
    "\n"
)


@dataclass(frozen=True)
class NavStyle:
    """
    Controls how much navigation noise is emitted into the report.
    - emit_search_markers: show '§§ token' lines for fallback search
    """

    emit_search_markers: bool = False


def _heading_block(level: int, token: str, title: Optional[str] = None, nav: Optional[NavStyle] = None) -> List[str]:
    """
    Return heading lines with stable token-based ids and optional title.

    Many Markdown renderers (especially on iOS) fail to emit heading IDs, and
    some ignore the `{#id}` syntax. To maximize compatibility for links like
    `#manifest` or `#file-tools-...`, we emit an explicit HTML anchor before the
    tokenized heading. This keeps links working when either heading IDs *or*
    HTML anchors are supported by the renderer.
    """

    # NOTE:
    # - Some renderers do not generate heading IDs.
    # - Some renderers strip HTML anchors.
    # We therefore provide three layers:
    #   (1) visible search marker: "§§ <token>" (works even if links are dead)
    #   (2) HTML anchor: <a id="token"></a> (works if HTML allowed)
    #   (3) tokenized heading: "## token" (works if heading IDs generated)
    nav = nav or NavStyle()
    lines: List[str] = []
    if nav.emit_search_markers:
        lines.append(f"§§ {token}")

    # Correction for readable headers (Spec v2.4):
    # Instead of "## token", we use "## Title" if available, keeping the anchor for linking.
    # Option A (Conservative): Separate anchor line + Markdown heading.

    # Validation/Sanitization:
    # If token is safe (alphanumeric + . _ : -), use it directly.
    # Otherwise, fallback to _slug_token to ensure valid HTML ID.
    if re.fullmatch(r"[A-Za-z0-9._:-]+", token):
        safe_token = token
    else:
        safe_token = _slug_token(token)

    lines.append(f'<a id="{safe_token}"></a>')

    if title:
        lines.append("#" * level + " " + title)
    else:
        # Note: If no title is provided, we use safe_token (sanitized) as the visible text.
        # This ensures the visible heading matches the anchor ID for consistency,
        # even if the original token contained unsafe characters.
        lines.append("#" * level + " " + safe_token)

    lines.append("")
    return lines

# --- Configuration & Heuristics ---

SPEC_VERSION = "2.4"
MERGES_DIR_NAME = "merges"
PR_SCHAU_DIR = Path(".repolens") / "pr-schau"

# Formale Contract-Deklaration für alle repoLens-Reports.
# Name/Version können von nachgelagerten Tools verwendet werden,
# um das Format eindeutig zu erkennen.
MERGE_CONTRACT_NAME = "repolens-report"
MERGE_CONTRACT_VERSION = SPEC_VERSION

# Ab v2.3+: 0 = "kein Limit pro Datei".
# max_file_bytes wirkt nur noch als optionales Soft-Limit / Hint,
# nicht mehr als harte Abschneide-Grenze. Große Dateien werden
# vollständig gelesen und nur über die Split-Logik in Parts verteilt.
DEFAULT_MAX_BYTES = 0

def _debug_log_func(debug: "DebugCollector", level: str):
    """
    Map configured severity levels to DebugCollector methods.
    If misconfigured, warn once (per call) and fall back to warn.
    """
    lvl = (level or "warn").strip().lower()
    if lvl in ("warn", "warning"):
        return debug.warn
    if lvl in ("error", "err"):
        return getattr(debug, "error", debug.warn)
    if lvl in ("info",):
        return getattr(debug, "info", debug.warn)

    # Misconfiguration: make it visible, then fall back.
    debug.warn(
        "debug-config-invalid",
        "merge_core",
        f"Unbekannter severity-level '{level}'. Erlaubt: info|warn|error. Fallback: warn.",
    )
    return debug.warn

# Debug-Config (erweitert für v2.4)
@dataclass
class DebugConfig:
    """
    Zentralisiert Debug- und Validierungs-Einstellungen.
    Ermöglicht spätere Erweiterung (Severity-Levels, neue Tags) ohne API-Break.
    """
    allowed_categories: Set[str]
    allowed_tags: Set[str]
    code_only_categories: Set[str]

    # Severity levels for checks (extensions)
    unknown_category_level: str = "warn"
    unknown_tag_level: str = "warn"

    @classmethod
    def defaults(cls) -> "DebugConfig":
        return cls(
            allowed_categories={"source", "test", "doc", "config", "contract", "other"},
            allowed_tags={
                "ai-context", "runbook", "lockfile", "script", "ci",
                "adr", "feed", "wgx-profile"
            },
            code_only_categories={"source", "test", "config", "contract"}
        )

DEBUG_CONFIG = DebugConfig.defaults()

AGENT_CONTRACT_NAME = "repolens-agent"
AGENT_CONTRACT_VERSION = "v2"

# Module-level registries so tests can import them without calling write_reports_v2.
# write_reports_v2 references these via local aliases (CONTRACT_REGISTRY / AUTHORITY_REGISTRY).
ARTIFACT_CONTRACT_REGISTRY = {
    ArtifactRole.INDEX_SIDECAR_JSON: {"id": AGENT_CONTRACT_NAME, "version": AGENT_CONTRACT_VERSION},
    ArtifactRole.RETRIEVAL_EVAL_JSON: {"id": "retrieval-eval", "version": "v1"},
    ArtifactRole.GRAPH_INDEX_JSON: {"id": "architecture.graph_index", "version": "v1"},
    ArtifactRole.PR_DELTA_JSON: {"id": "pr-schau-delta", "version": "1.0"},
    ArtifactRole.CITATION_MAP_JSONL: {"id": "citation-map", "version": "v1"},
}

ARTIFACT_AUTHORITY_REGISTRY = {
    ArtifactRole.CANONICAL_MD: {
        "authority": "canonical_content",
        "canonicality": "content_source",
        "regenerable": True,
        "staleness_sensitive": False,
    },
    ArtifactRole.INDEX_SIDECAR_JSON: {
        "authority": "navigation_index",
        "canonicality": "index_only",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.DUMP_INDEX_JSON: {
        "authority": "navigation_index",
        "canonicality": "index_only",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.DERIVED_MANIFEST_JSON: {
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.CHUNK_INDEX_JSONL: {
        "authority": "retrieval_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.SQLITE_INDEX: {
        "authority": "runtime_cache",
        "canonicality": "cache",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.RETRIEVAL_EVAL_JSON: {
        "authority": "diagnostic_signal",
        "canonicality": "diagnostic",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.OUTPUT_HEALTH: {
        "authority": "diagnostic_signal",
        "canonicality": "diagnostic",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.GRAPH_INDEX_JSON: {
        "authority": "retrieval_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True,
    },
    ArtifactRole.CITATION_MAP_JSONL: {
        "authority": "navigation_index",
        "canonicality": "derived",
        "regenerable": True,
        "staleness_sensitive": True,
    },
}

# Delta Report configuration
MAX_DELTA_FILES = 10  # Maximum number of files to show in each delta section

# Directories to ignore
SKIP_DIRS = {
    ".git",
    ".idea",
    "node_modules",
    ".svelte-kit",
    ".next",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".DS_Store",
    ".mypy_cache",
    "coverage",
}

# Top-level roots to skip in auto-discovery
SKIP_ROOTS = {
    MERGES_DIR_NAME,
    "merge",
    "output",
    "out",
}

# Individual files to ignore
SKIP_FILES = {
    ".DS_Store",
    "thumbs.db",
}

# Extensions considered text (broadened)
TEXT_EXTENSIONS = {
    ".md", ".txt", ".rst", ".py", ".rs", ".ts", ".tsx", ".js", ".jsx",
    ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".zsh", ".fish", ".dockerfile", "dockerfile",
    ".svelte", ".css", ".scss", ".html", ".htm", ".xml", ".csv", ".log",
    ".lock", ".bats", ".properties", ".gradle", ".groovy", ".kt", ".kts",
    ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rb", ".php", ".pl",
    ".lua", ".sql", ".bat", ".cmd", ".ps1", ".make", "makefile", "justfile",
    ".tf", ".hcl", ".gitignore", ".gitattributes", ".editorconfig", ".cs",
    ".swift", ".adoc", ".ai-context"
}


def _stable_file_id(fi: "FileInfo") -> str:
    """
    Stable across runs as long as repo + rel-path stay the same.
    Avoids relying on Markdown heading anchors or renderer-specific IDs.
    """

    repo = (
        getattr(fi, "root_label", None)
        or getattr(fi, "repo", None)
        or getattr(fi, "repo_name", None)
        or ""
    )
    path = str(
        getattr(fi, "rel_path", None)
        or getattr(fi, "path", None)
        or getattr(fi, "abs_path", None)
        or ""
    )

    # Normalize paths to NFC to ensure stable IDs across platforms (macOS vs Linux)
    repo = unicodedata.normalize("NFC", repo)
    path = unicodedata.normalize("NFC", path)

    raw = f"{repo}:{path}".encode("utf-8", errors="ignore")
    # Updated in v2.4 (PR1) to include FILE: prefix
    return "FILE:f_" + hashlib.sha1(raw).hexdigest()[:12]


def resolve_canonical_md(md_parts: List[Path]) -> Optional[Path]:
    """
    Returns the canonical markdown artifact from a list of markdown parts.
    By contract, only the first part is fully bundle-backed.
    """
    return md_parts[0] if md_parts else None


def _line_for_byte(data: bytes, byte_offset: int) -> int:
    """Return the 1-based line number of the byte at byte_offset in data.

    Counts the number of newlines in data before byte_offset and adds 1.
    For an exclusive end_byte, pass max(start_byte, end_byte - 1) to get
    the line of the last byte in the range without underflowing empty chunks.
    """
    return data.count(b"\n", 0, byte_offset) + 1

def _validate_agent_json_dict(d: Dict[str, Any], allow_empty_primary: bool = False) -> None:
    """
    Minimal, dependency-free validation. Purpose: prevent "success but nothing usable".
    (Full JSON-Schema validation can be added later; this is the hard safety belt.)
    """

    if not isinstance(d, dict):
        raise ValueError("agent-json: top-level is not an object")
    meta = d.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("agent-json: missing/invalid meta")
    if meta.get("contract") != AGENT_CONTRACT_NAME:
        raise ValueError(f"agent-json: meta.contract must be {AGENT_CONTRACT_NAME}")
    if meta.get("contract_version") != AGENT_CONTRACT_VERSION:
        raise ValueError(
            f"agent-json: meta.contract_version must be {AGENT_CONTRACT_VERSION}"
        )
    artifacts = d.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("agent-json: missing/invalid artifacts")
    if "index_json" not in artifacts:
        raise ValueError("agent-json: artifacts.index_json missing")
    if not allow_empty_primary and not artifacts.get("index_json"):
        raise ValueError("agent-json: artifacts.index_json missing")
    files = d.get("files")
    if not isinstance(files, list):
        raise ValueError("agent-json: missing/invalid files[]")


# --- Debug-Kollektor -------------------------------------------------------

class DebugItem(NamedTuple):
    level: str   # "info", "warn", "error"
    code: str    # z. B. "tag-unknown"
    context: str # kurzer Pfad oder Repo-Name
    message: str # Menschentext


@dataclass
class ExtrasConfig:
    health: bool = False
    organism_index: bool = False
    fleet_panorama: bool = False
    augment_sidecar: bool = False
    delta_reports: bool = False
    heatmap: bool = False
    json_sidecar: bool = False  # NEW: Enable JSON sidecar output

    @classmethod
    def none(cls):
        return cls()

    @classmethod
    def from_csv(cls, csv_str: str) -> Tuple["ExtrasConfig", List[str]]:
        """
        Parses a comma-separated string of extras keys and returns a populated ExtrasConfig object
        along with a list of warning messages (e.g. deprecations or unknown keys).
        """
        config = cls()
        warnings = []

        if not csv_str or csv_str.strip().lower() == "none":
            return config, warnings

        items = [x.strip().lower() for x in csv_str.split(",") if x.strip()]

        for item in items:
            if item == "ai_heatmap":
                warnings.append("Deprecated: 'ai_heatmap' is now 'heatmap'. Please update your config.")
                item = "heatmap"

            if hasattr(config, item):
                setattr(config, item, True)
            else:
                warnings.append(f"Unknown extra '{item}' ignored.")

        return config, warnings


class DebugCollector:
    """Sammelt Debug-Infos für optionale Report-Sektionen."""

    def __init__(self) -> None:
        self._items: List[DebugItem] = []

    @property
    def items(self) -> List[DebugItem]:
        return list(self._items)

    def info(self, code: str, context: str, msg: str) -> None:
        self._items.append(DebugItem("info", code, context, msg))

    def warn(self, code: str, context: str, msg: str) -> None:
        self._items.append(DebugItem("warn", code, context, msg))

    def error(self, code: str, context: str, msg: str) -> None:
        self._items.append(DebugItem("error", code, context, msg))

    def has_items(self) -> bool:
        return bool(self._items)

    def render_markdown(self) -> str:
        """Erzeugt eine optionale ## Debug-Sektion als Markdown-Tabelle."""
        if not self._items:
            return ""
        lines: List[str] = []
        lines.append("<!-- @debug:start -->")
        lines.append("## Debug")
        lines.append("")
        lines.append("| Level | Code | Kontext | Hinweis |")
        lines.append("|-------|------|---------|---------|")
        for it in self._items:
            lines.append(
                f"| {it.level} | `{it.code}` | `{it.context}` | {it.message} |"
            )
        lines.append("")
        lines.append("<!-- @debug:end -->")
        lines.append("")
        return "\n".join(lines)


@dataclass
class MergeArtifacts:
    """
    Result object for write_reports_v2() containing all generated artifacts.
    Makes it explicit which artifact is the primary (JSON or Markdown).
    """
    index_json: Optional[Path] = None
    canonical_md: Optional[Path] = None
    chunk_index: Optional[Path] = None
    md_parts: List[Path] = None
    dump_index: Optional[Path] = None
    sqlite_index: Optional[Path] = None
    retrieval_eval: Optional[Path] = None
    derived_manifest: Optional[Path] = None
    bundle_manifest: Optional[Path] = None
    output_health: Optional[Path] = None
    other: List[Path] = None

    def __post_init__(self):
        if self.md_parts is None:
            self.md_parts = []
        if self.other is None:
            self.other = []

    def get_all_paths(self) -> List[Path]:
        """Return all paths in deterministic order: primary first, then others."""
        paths = []

        # Primary / Navigation
        if self.index_json:
            paths.append(self.index_json)
        if self.canonical_md and self.canonical_md not in paths:
            paths.append(self.canonical_md)
        if self.chunk_index:
            paths.append(self.chunk_index)
        if self.dump_index:
            paths.append(self.dump_index)

        # Derived
        if self.derived_manifest:
            paths.append(self.derived_manifest)
        if self.sqlite_index:
            paths.append(self.sqlite_index)
        if self.retrieval_eval:
            paths.append(self.retrieval_eval)
        if self.output_health:
            paths.append(self.output_health)
        if self.bundle_manifest:
            paths.append(self.bundle_manifest)

        for p in self.md_parts:
            if p not in paths:
                paths.append(p)
        for p in self.other:
            if p not in paths:
                paths.append(p)
        return paths

    def get_sqlite_index(self) -> Optional[Path]:
        if self.sqlite_index:
            return self.sqlite_index
        # Fallback
        return next((p for p in self.get_all_paths() if p.name.endswith(".index.sqlite")), None)

    def get_retrieval_eval(self) -> Optional[Path]:
        if self.retrieval_eval:
            return self.retrieval_eval
        # Fallback
        return next((p for p in self.get_all_paths() if p.name.endswith(".retrieval_eval.json")), None)

    def get_derived_manifest(self) -> Optional[Path]:
        if self.derived_manifest:
            return self.derived_manifest
        # Fallback
        return next((p for p in self.get_all_paths() if p.name.endswith(".derived_index.json")), None)

    def get_primary_path(self) -> Optional[Path]:
        """Return the primary artifact path (JSON if exists, otherwise Markdown)."""
        return self.index_json or self.canonical_md


@dataclass
class RepoHealth:
    """Health status for a single repository."""
    repo_name: str
    status: str  # "ok", "warn", "critical"
    total_files: int
    category_counts: Dict[str, int]
    has_readme: bool
    has_wgx_profile: bool
    has_ci_workflows: bool
    has_contracts: bool
    has_ai_context: bool
    wgx_profile_expected: Optional[bool]  # True/False if declared, else None
    unknown_category_ratio: float
    unknown_categories: List[str]
    unknown_tags: List[str]
    warnings: List[str]
    recommendations: List[str]
    meta_sync_status: str = "unknown"  # "ok"|"warn"|"unknown"
    meta_sync: Optional[Dict[str, Any]] = None


class HealthCollector:
    """Collects health checks for repositories (Stage 1: Repo Doctor)."""

    def __init__(self, hub_path: Optional[Path] = None) -> None:
        self._repo_health: Dict[str, RepoHealth] = {}
        self.hub_path = hub_path
        self.fleet_snapshot = self._read_fleet_snapshot()
        self.fleet_snapshot_outdated = self._is_fleet_snapshot_outdated(self.fleet_snapshot)

    def _parse_dt(self, s: str) -> Optional[datetime.datetime]:
        # Accept "Z" timestamps and full ISO
        try:
            if s.endswith("Z"):
                return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
            # fromisoformat handles offsets like +00:00
            return datetime.datetime.fromisoformat(s)
        except Exception:
            return None

    def _is_fleet_snapshot_outdated(self, snap: Optional[Dict[str, Any]]) -> bool:
        if not snap or not isinstance(snap, dict):
            return False
        try:
            validity = snap.get("validity") if isinstance(snap.get("validity"), dict) else {}
            ttl_hours = validity.get("ttl_hours")
            if not isinstance(ttl_hours, int) or ttl_hours < 1:
                return False
            gen = snap.get("generated_at")
            if not isinstance(gen, str) or not gen.strip():
                return False
            dt = self._parse_dt(gen.strip())
            if not dt:
                return True
            now = clock.now_utc()
            # normalize naive datetimes to UTC to avoid crashes
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return (now - dt) > datetime.timedelta(hours=ttl_hours)
        except Exception:
            # Safer to assume outdated/invalid than fresh if parsing fails
            return True

    def _read_fleet_snapshot(self) -> Optional[Dict[str, Any]]:
        """Reads .gewebe/cache/fleet.snapshot.json if available."""
        if not self.hub_path:
            return None
        try:
            p = self.hub_path / ".gewebe/cache/fleet.snapshot.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to read fleet snapshot: {e}\n")
        return None

    def _pick_ai_context_paths(self, files: List["FileInfo"]) -> List[Path]:
        """
        Return candidate .ai-context.yml paths, preferring repo-root (shortest rel_path).
        Deterministic ordering prevents 'first file wins' randomness.
        """
        candidates: List[Tuple[int, str, Path]] = []
        for f in files:
            rp = str(getattr(f, "rel_path", ""))
            name = getattr(getattr(f, "rel_path", None), "name", "")
            if name == ".ai-context.yml" or rp.endswith("/.ai-context.yml") or rp.endswith(".ai-context.yml"):
                ap = getattr(f, "abs_path", None)
                if ap:
                    depth = rp.count("/")  # root file tends to have smallest depth
                    candidates.append((depth, rp, Path(ap)))
        candidates.sort(key=lambda t: (t[0], t[1]))
        return [p for _, __, p in candidates]

    def _read_sync_report(self, repo_root: Optional[Path]) -> Optional[Dict[str, Any]]:
        """Reads .gewebe/out/sync.report.json if available."""
        if not repo_root:
            return None
        try:
            p = repo_root / ".gewebe/out/sync.report.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to read sync report: {e}\n")
        return None

    def _eval_sync_status(self, report: Optional[Dict[str, Any]]) -> str:
        """Evaluates meta sync status: ok|warn|unknown."""
        if not report:
            return "unknown"

        # Immediate error check (Patch 1)
        if report.get("status") == "error":
            return "warn"

        # Safe access to fields
        summary = report.get("summary", {})
        mode = report.get("mode", "unknown")

        err_count = summary.get("error", 0)
        blocked_count = summary.get("blocked", 0)
        add_count = summary.get("add", 0)
        update_count = summary.get("update", 0)

        # Summary error check
        if err_count > 0:
            return "warn"

        if mode == "dry_run":
             # Pending changes in dry_run are a warning (not synced yet)
             if add_count > 0 or update_count > 0 or blocked_count > 0:
                 return "warn"
             return "ok" # Clean dry run means sync is up to date

        if mode == "apply":
            if blocked_count > 0:
                return "warn"
            # If applied successfully (error=0, blocked=0), status is ok.
            return "ok"

        return "unknown"

    def _read_wgx_profile_expected(self, files: List["FileInfo"], root_label: str) -> Optional[bool]:
        """
        Reads `profile_expected` from fleet snapshot (primary truth).
        """
        # T5: Fleet-Erwartungen nur aus fleet.snapshot.json
        if self.fleet_snapshot:
            repos = self.fleet_snapshot.get("data", {}).get("repos", {})
            repo_data = repos.get(root_label)
            if repo_data:
                wgx = repo_data.get("wgx") if isinstance(repo_data.get("wgx"), dict) else {}
                return wgx.get("profile_expected")
            # If repo not in snapshot, we assume unknown (None)
            return None

        # Fallback to local (deprecated by T5 but safe to keep as secondary?
        # T5 says "Fleet-Erwartungen ... NUR aus fleet.snapshot.json")
        # So we should probably return None if snapshot missing, or maybe
        # we check if we should strictly follow "NUR" (ONLY).
        # "wenn Snapshot fehlt/älter: WARN ... statt CRITICAL." implies we know it's missing.
        return None

    def analyze_repo(self, root_label: str, files: List["FileInfo"]) -> RepoHealth:
        """Analyze health of a single repository."""
        # Check if repo is known to fleet snapshot (completeness check)
        is_known_to_snapshot = True
        if self.fleet_snapshot:
            repos = self.fleet_snapshot.get("data", {}).get("repos", {})
            if root_label not in repos:
                is_known_to_snapshot = False

        # Try to determine repo root
        repo_root: Optional[Path] = None

        # Strategy A: Deterministic from Hub (Preferred)
        if self.hub_path:
            candidate = self.hub_path / root_label
            if candidate.exists() and candidate.is_dir():
                repo_root = candidate

        # Strategy B: Reconstruction from files (Fallback)
        if not repo_root and files:
            try:
                # Robust reconstruction: take abs path of first file, walk up by len(rel_path.parts) - 1
                f0 = files[0]
                if f0.abs_path and f0.rel_path:
                    # e.g. /a/b/c/d/file.txt, rel=d/file.txt -> len(parts)=2.
                    # parents[0] = /a/b/c/d
                    # parents[1] = /a/b/c <-- repo root
                    # Index should be len(f0.rel_path.parts) - 1
                    # Ensure index is within bounds of parents
                    idx = len(f0.rel_path.parts) - 1
                    if idx < len(f0.abs_path.parents):
                        repo_root = f0.abs_path.parents[idx]
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to reconstruct repo root: {e}\n")

        # Count files per category
        category_counts: Dict[str, int] = {}
        for fi in files:
            cat = fi.category or "other"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Check for key files
        has_readme = any(f.rel_path.name.lower() == "readme.md" for f in files)
        has_wgx_profile = any(
            ".wgx" in f.rel_path.parts and str(f.rel_path).endswith("profile.yml")
            for f in files
        )
        wgx_profile_expected = self._read_wgx_profile_expected(files, root_label)
        has_ci_workflows = any("ci" in (f.tags or []) for f in files)
        # 4. Contracts (heuristic extended: contracts/ OR **/*.schema.json)
        def is_contract(f):
            if f.category == "contract":
                return True
            rel = str(getattr(f, "rel_path", "")).lower()
            if rel.endswith(".schema.json"):
                return True
            return False

        has_contracts = any(is_contract(f) for f in files)
        # Enhanced AI context detection: check tags and file paths (cached to avoid repeated conversions)
        has_ai_context = False
        for f in files:
            if "ai-context" in (f.tags or []):
                has_ai_context = True
                break
            path_lower = str(f.rel_path).lower()
            if "ai-context" in path_lower or path_lower.endswith(".ai-context.yml") or "ai-context" in f.rel_path.parts:
                has_ai_context = True
                break

        # Check for unknown categories/tags
        unknown_categories = []
        unknown_tags = []
        unknown_cat_count = 0
        other_count = 0

        for fi in files:
            cat = fi.category or "other"
            if cat not in DEBUG_CONFIG.allowed_categories:
                if cat not in unknown_categories:
                    unknown_categories.append(cat)
                unknown_cat_count += 1
            if cat == "other":
                other_count += 1

            for tag in fi.tags or []:
                if tag not in DEBUG_CONFIG.allowed_tags:
                    if tag not in unknown_tags:
                        unknown_tags.append(tag)

        unknown_category_ratio = 0.0
        if len(files) > 0:
            unknown_category_ratio = unknown_cat_count / len(files)

        # Generate warnings and recommendations
        warnings = []
        recommendations = []

        if not is_known_to_snapshot:
            # We don't add a per-repo warning to avoid spam if the user requested "incomplete snapshot warning".
            # But the requirement says: "Snapshot incomplete (unknown repos: X)" global warning.
            # So we track it via a flag on RepoHealth or just count it globally.
            # Let's add an info-level warning here so it is visible in the per-repo details if desired?
            # User said: "optional pro repo: unknown_to_snapshot als Info/Warn (nicht als CRITICAL)."
            warnings.append("Repo unknown to fleet snapshot")
            # We do NOT mark this as CRITICAL, only warn/info.

        if not has_readme:
            warnings.append("No README.md found")
            recommendations.append("Add README.md for better AI/human navigation")

        # WGX profile policy:
        # - If explicitly NOT expected -> do not warn.
        # - If expected -> warn.
        # - If unknown (e.g. no snapshot) -> do NOT warn about profile itself, but we warned about snapshot.
        if not has_wgx_profile:
            if wgx_profile_expected is True:
                warnings.append("No .wgx/profile.yml found (expected by fleet snapshot)")
                recommendations.append("Create .wgx/profile.yml for Fleet conformance")
            elif wgx_profile_expected is None:
                # If unknown, we don't warn about missing profile, because we don't know if it is required.
                # (Strict logic T3/T5).
                pass

        if not has_ci_workflows:
            warnings.append("No CI workflows found")
            recommendations.append("Add .github/workflows for CI/CD")

        if not has_contracts:
            warnings.append("No contracts found")
            recommendations.append("Consider adding contract schemas")

        if not has_ai_context:
            warnings.append("No AI context files found")
            recommendations.append("Add .ai-context.yml files for better AI understanding")

        if unknown_categories:
            warnings.append(f"Unknown categories: {', '.join(unknown_categories)}")

        if unknown_tags:
            warnings.append(f"Unknown tags: {', '.join(unknown_tags)}")

        # Meta Sync Check
        meta_sync = self._read_sync_report(repo_root)
        meta_sync_status = self._eval_sync_status(meta_sync)

        if meta_sync_status == "warn":
             warnings.append("Meta Sync Issues (see details)")
             # We assume recommendation is handled by sync tool report

        # Determine overall status
        if len(warnings) >= 4:
            status = "critical"
        elif len(warnings) >= 2:
            status = "warn"
        else:
            status = "ok"

        health = RepoHealth(
            repo_name=root_label,
            status=status,
            total_files=len(files),
            category_counts=category_counts,
            has_readme=has_readme,
            has_wgx_profile=has_wgx_profile,
            has_ci_workflows=has_ci_workflows,
            has_contracts=has_contracts,
            has_ai_context=has_ai_context,
            wgx_profile_expected=wgx_profile_expected,
            unknown_category_ratio=unknown_category_ratio,
            unknown_categories=unknown_categories,
            unknown_tags=unknown_tags,
            warnings=warnings,
            recommendations=recommendations,
            meta_sync_status=meta_sync_status,
            meta_sync=meta_sync,
        )

        # Optional enrichment (keeps compatibility if RepoHealth doesn't define it)
        try:
            health.other_count = other_count
        except AttributeError:
            pass

        self._repo_health[root_label] = health
        return health

    def get_all_health(self) -> List[RepoHealth]:
        """Get all repo health reports."""
        return list(self._repo_health.values())

    def render_markdown(self) -> str:
        """Render health report as markdown."""
        if not self._repo_health:
            return ""

        lines: List[str] = []
        lines.append("<!-- @health:start -->")
        lines.append("## 🩺 Repo Health")
        lines.append("")

        # 1. Repo Feindynamiken (Global)
        no_ci = sum(1 for h in self._repo_health.values() if not h.has_ci_workflows)
        no_contracts = sum(1 for h in self._repo_health.values() if not h.has_contracts)
        # Only count missing WGX profile as a "problem" if expected is True or unknown.
        no_wgx = sum(
            1 for h in self._repo_health.values()
            if (not h.has_wgx_profile) and (h.wgx_profile_expected is not False)
        )

        # Snapshot Warn Global: missing OR outdated OR incomplete
        snapshot_missing = not self.fleet_snapshot
        snapshot_outdated = bool(self.fleet_snapshot_outdated)

        # Check for incomplete snapshot (repos present locally but not in snapshot)
        unknown_repos_count = 0
        if self.fleet_snapshot:
            snapshot_repos = self.fleet_snapshot.get("data", {}).get("repos", {})
            for h in self._repo_health.values():
                if h.repo_name not in snapshot_repos:
                    unknown_repos_count += 1

        if no_ci > 0 or no_contracts > 0 or no_wgx > 0 or snapshot_missing or snapshot_outdated or unknown_repos_count > 0:
            lines.append("### ⚔ Repo Feindynamiken (Global Risks)")
            lines.append("")
            if snapshot_missing:
                lines.append("- ⚠️ **Fleet Snapshot missing** – policy checks skipped or may be inaccurate.")
            elif snapshot_outdated:
                lines.append("- ⚠️ **Fleet Snapshot outdated (TTL exceeded)** – policy checks skipped or may be inaccurate.")

            if unknown_repos_count > 0:
                lines.append(f"- ⚠️ **Snapshot incomplete** – {unknown_repos_count} repositories unknown to fleet snapshot.")

            if no_ci > 0:
                lines.append(f"- {no_ci} Repos ohne CI-Workflows")
            if no_contracts > 0:
                lines.append(f"- {no_contracts} Repos ohne Contracts")
            if no_wgx > 0:
                lines.append(f"- {no_wgx} Repos ohne WGX-Profil")
            lines.append("")

        # 2. Per-Repo Report
        for health in sorted(self._repo_health.values(), key=lambda h: h.repo_name):
            # Status emoji
            status_emoji = {
                "ok": "✅",
                "warn": "⚠️",
                "critical": "🔴",
            }.get(health.status, "❓")

            lines.append(f"### {status_emoji} `{health.repo_name}` – {health.status.upper()}")
            lines.append("")
            lines.append(f"- **Total Files:** {health.total_files}")

            # Category breakdown
            if health.category_counts:
                cat_parts = [f"{cat}={count}" for cat, count in sorted(health.category_counts.items())]
                lines.append(f"- **Categories:** {', '.join(cat_parts)}")

            # Key indicators
            indicators = []
            indicators.append(f"README: {'yes' if health.has_readme else 'no'}")
            indicators.append(f"WGX Profile: {'yes' if health.has_wgx_profile else 'no'}")
            if health.wgx_profile_expected is True:
                indicators.append("WGX Expected: yes")
            elif health.wgx_profile_expected is False:
                indicators.append("WGX Expected: no")
            else:
                indicators.append("WGX Expected: unknown")
            indicators.append(f"CI: {'yes' if health.has_ci_workflows else 'no'}")
            indicators.append(f"Contracts: {'yes' if health.has_contracts else 'no'}")
            indicators.append(f"AI Context: {'yes' if health.has_ai_context else 'no'}")
            lines.append(f"- **Indicators:** {', '.join(indicators)}")

            # Meta Sync
            if health.meta_sync:
                ms = health.meta_sync
                summ = ms.get("summary", {})
                mode = ms.get("mode", "?")
                sync_detail = f"mode={mode} add={summ.get('add',0)} upd={summ.get('update',0)} blk={summ.get('blocked',0)} err={summ.get('error',0)}"
                lines.append(f"- **Meta Sync:** {health.meta_sync_status} ({sync_detail})")
            else:
                 lines.append("- **Meta Sync:** unknown")

            # Feindynamik-Scanner (Risiken)
            risks = []
            if not health.has_contracts:
                risks.append("❌ Keine Contracts gefunden → Änderungen nicht formal prüfbar.")
            else:
                risks.append("✅ Contracts vorhanden")

            if not health.has_ci_workflows:
                risks.append("❌ Keine CI-Workflows → Keine automatische Qualitätssicherung.")
            else:
                risks.append("✅ CI-Workflows vorhanden")

            if not health.has_wgx_profile:
                risks.append("❌ Kein WGX-Profil → Organismus kennt Standard-Jobs nicht.")
            else:
                risks.append("✅ WGX-Profil vorhanden")

            lines.append("")
            lines.append("**Risiko-Check (Feindynamik):**")
            for r in risks:
                lines.append(f"- {r}")

            # Warnings (Standard)
            if health.warnings:
                lines.append("")
                lines.append("**Detailed Warnings:**")
                for warning in health.warnings:
                    lines.append(f"  - {warning}")

            # Recommendations
            if health.recommendations:
                lines.append("")
                lines.append("**Recommendations:**")
                for rec in health.recommendations:
                    lines.append(f"  - {rec}")

            lines.append("")

        lines.append("<!-- @health:end -->")
        lines.append("")
        return "\n".join(lines)


class HeatmapCollector:
    """
    Identifies code hotspots and complexity clusters.
    """
    def __init__(self, files: List["FileInfo"]):
        self.files = files

    def render_markdown(self) -> str:
        if not self.files:
            return ""

        lines = []
        lines.append("<!-- @heatmap:start -->")
        lines.append("## 🔥 AI Heatmap – Code Hotspots")
        lines.append("")

        # 1. Top Files (Size & Complexity proxy)
        # Filter for relevant categories
        relevant = [f for f in self.files if f.category in ("source", "config", "contract", "test")]
        # Sort by size desc
        top_files = sorted(relevant, key=lambda f: f.size, reverse=True)[:5]

        lines.append("### Top-Level Hotspots (Files by Size)")
        for i, f in enumerate(top_files, 1):
            lines.append(f"{i}. `{f.rel_path}`")
            lines.append(f"   - Size: {human_size(f.size)}")
            lines.append(f"   - Category: {f.category}")
            if f.tags:
                lines.append(f"   - Tags: {', '.join(f.tags)}")
            lines.append("")

        # 2. Top Folders
        folder_stats = {}
        for f in self.files:
            parent = f.rel_path.parent
            if parent == Path("."):
                continue
            path_str = str(parent)
            if path_str not in folder_stats:
                folder_stats[path_str] = {"count": 0, "size": 0}
            folder_stats[path_str]["count"] += 1
            folder_stats[path_str]["size"] += f.size

        # Sort by size
        sorted_folders = sorted(folder_stats.items(), key=lambda x: x[1]["size"], reverse=True)[:5]

        lines.append("### Top Folder Hotspots")
        for path, stats in sorted_folders:
            lines.append(f"- `{path}/` → {stats['count']} Files, {human_size(stats['size'])}")

        lines.append("")
        lines.append("<!-- @heatmap:end -->")
        lines.append("")
        return "\n".join(lines)


def _build_extras_meta(extras: "ExtrasConfig", num_repos: int) -> Dict[str, bool]:
    """
    Hilfsfunktion: baut den extras-Block für den @meta-Contract.
    Alle Flags werden explizit gesetzt, um Konsistenz zu gewährleisten.

    Args:
        extras: ExtrasConfig mit den gewünschten Extras
        num_repos: Anzahl der Repos im Merge (für Fleet Panorama - muss explizit übergeben werden)
    """
    return {
        "health": extras.health,
        "organism_index": extras.organism_index,
        "fleet_panorama": extras.fleet_panorama and num_repos > 1,
        "augment_sidecar": extras.augment_sidecar,
        "delta_reports": extras.delta_reports,
        "json_sidecar": extras.json_sidecar,
        "heatmap": extras.heatmap,
    }


def _build_augment_meta(sources: List[Path]) -> Optional[Dict[str, Any]]:
    """
    Nutzt dieselbe Logik wie der Augment-Block, um das Sidecar im Meta zu verlinken.
    """
    sidecar = _find_augment_file_for_sources(sources)
    return {"sidecar": sidecar.name} if sidecar else None


def _render_fleet_panorama(sources: List[Path], files: List["FileInfo"]) -> Optional[str]:
    """
    Render the Fleet Panorama block.
    Only shown if:
      - extras.fleet_panorama is true
      - more than one repo is being merged
    """
    if len(sources) < 2:
        return None

    # Group files per repo
    grouped: Dict[str, List["FileInfo"]] = {}
    for fi in files:
        grouped.setdefault(fi.root_label, []).append(fi)

    lines: List[str] = []
    lines.append("<!-- @fleet-panorama:start -->")
    lines.append("## 🛰 Fleet Panorama")
    lines.append("")

    # Summary header
    total_files = sum(len(v) for v in grouped.values())
    total_bytes = sum(f.size for f in files)
    lines.append(f"**Summary:** {len(grouped)} repos, {total_bytes} bytes, {total_files} files")
    lines.append("")

    # Per-repo details
    for repo, repo_files in grouped.items():
        repo_bytes = sum(f.size for f in repo_files)
        lines.append(f"### `{repo}`")
        lines.append(f"- Files: {len(repo_files)}")
        lines.append(f"- Size: {repo_bytes} bytes")
        lines.append("")

    lines.append("<!-- @fleet-panorama:end -->")
    return "\n".join(lines) + "\n"


def _find_augment_file_for_sources(sources: List[Path]) -> Optional[Path]:
    """
    Locate an augment sidecar YAML file for the given sources.
    Convention: {repo_name}_augment.yml either in the repo root or its parent.
    """
    for source in sources:
        try:
            # Try in the repo directory itself
            candidate = source / f"{source.name}_augment.yml"
            if candidate.exists():
                return candidate

            # Try in parent directory
            candidate_parent = source.parent / f"{source.name}_augment.yml"
            if candidate_parent.exists():
                return candidate_parent
        except (OSError, PermissionError):
            # If we cannot access this source, skip it
            continue
    return None


def _render_augment_block(sources: List[Path], meta_density: str = "full") -> str:
    """
    Render the Augment Intelligence block based on an augment sidecar, if present.
    The expected structure matches tools_augment.yml (augment.hotspots, suggestions, risks, dependencies, priorities, context).
    """
    augment_path = _find_augment_file_for_sources(sources)
    if not augment_path:
        return ""

    # yaml is optional; if not available, render a basic block
    try:
        yaml  # type: ignore[name-defined]
    except NameError:
        lines = []
        lines.append("<!-- @augment:start -->")
        lines.append("## 🧩 Augment Intelligence")
        lines.append("")
        lines.append(f"**Sidecar:** `{augment_path.name}`")
        lines.append("")
        lines.append("_Hinweis: PyYAML nicht verfügbar – Details aus dem Sidecar können nicht automatisch geparst werden._")
        lines.append("")
        lines.append("<!-- @augment:end -->")
        lines.append("")
        return "\n".join(lines)

    try:
        raw = augment_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""

    try:
        data = yaml.safe_load(raw)  # type: ignore[name-defined]
    except Exception as e:
        # If the augment file is malformed, log error and do not break the merge
        sys.stderr.write(f"Warning: Failed to parse augment sidecar {augment_path}: {e}\n")
        return ""

    if not isinstance(data, dict):
        return ""

    augment = data.get("augment") or {}
    if not isinstance(augment, dict):
        return ""

    lines: List[str] = []
    lines.append("<!-- @augment:start -->")
    lines.append("## 🧩 Augment Intelligence")
    lines.append("")
    lines.append(f"**Sidecar:** `{augment_path.name}`")
    lines.append("")

    hotspots = augment.get("hotspots") or []
    if isinstance(hotspots, list) and hotspots and meta_density != "min":
        lines.append("### Hotspots")
        for hs in hotspots:
            if not isinstance(hs, dict):
                continue
            path = hs.get("path") or "?"
            reason = hs.get("reason") or ""
            severity = hs.get("severity") or ""
            line_range = hs.get("lines")
            details = []
            if severity:
                details.append(f"Severity: {severity}")
            if line_range:
                details.append(f"Lines: {line_range}")
            suffix = f" ({'; '.join(details)})" if details else ""
            if reason:
                lines.append(f"- `{path}` – {reason}{suffix}")
            else:
                lines.append(f"- `{path}`{suffix}")
        lines.append("")

    suggestions = augment.get("suggestions") or []
    if isinstance(suggestions, list) and suggestions:
        lines.append("### Suggestions")
        for s in suggestions:
            if isinstance(s, str):
                lines.append(f"- {s}")
        lines.append("")

    risks = augment.get("risks") or []
    if isinstance(risks, list) and risks:
        lines.append("### Risks")
        for r in risks:
            if isinstance(r, str):
                lines.append(f"- {r}")
        lines.append("")

    dependencies = augment.get("dependencies") or []
    if isinstance(dependencies, list) and dependencies:
        lines.append("### Dependencies")
        for dep in dependencies:
            if not isinstance(dep, dict):
                continue
            name = dep.get("name") or "unknown"
            required = dep.get("required")
            purpose = dep.get("purpose") or ""
            req_txt = ""
            if isinstance(required, bool):
                req_txt = "required" if required else "optional"
            parts = [name]
            if req_txt:
                parts.append(f"({req_txt})")
            if purpose:
                parts.append(f"– {purpose}")
            lines.append(f"- {' '.join(parts)}")
        lines.append("")

    priorities = augment.get("priorities") or []
    if isinstance(priorities, list) and priorities:
        lines.append("### Priorities")
        for pr in priorities:
            if not isinstance(pr, dict):
                continue
            prio = pr.get("priority")
            task = pr.get("task") or ""
            status = pr.get("status") or ""
            head = f"P{prio}: {task}" if prio is not None else task
            if status:
                lines.append(f"- {head} ({status})")
            else:
                lines.append(f"- {head}")
        lines.append("")

    context = augment.get("context") or {}
    if isinstance(context, dict) and context:
        lines.append("### Context")
        for key, value in context.items():
            lines.append(f"- **{key}:** {value}")
        lines.append("")

    lines.append("<!-- @augment:end -->")
    lines.append("")
    return "\n".join(lines)


def run_debug_checks(file_infos: List["FileInfo"], debug: DebugCollector) -> None:
    """
    Leichte, rein lesende Debug-Checks auf Basis der FileInfos.
    Verändert keine Merge-Logik, liefert nur Hinweise.
    """
    # 1. Unbekannte Kategorien / Tags
    for fi in file_infos:
        ctx = f"{fi.root_label}/{fi.rel_path.as_posix()}"
        cat = fi.category or "other"

        if cat not in DEBUG_CONFIG.allowed_categories:
            # Use configured severity
            log_func = _debug_log_func(debug, DEBUG_CONFIG.unknown_category_level)
            log_func(
                "category-unknown",
                ctx,
                f"Unbekannte Kategorie '{cat}' – erwartet sind {sorted(DEBUG_CONFIG.allowed_categories)}.",
            )

        for tag in getattr(fi, "tags", []) or []:
            if tag not in DEBUG_CONFIG.allowed_tags:
                log_func = _debug_log_func(debug, DEBUG_CONFIG.unknown_tag_level)
                log_func(
                    "tag-unknown",
                    ctx,
                    f"Tag '{tag}' ist nicht im v2.4-Schema registriert.",
                )

    # 2. Fleet-/Heimgewebe-Checks pro Repo
    per_root: Dict[str, List["FileInfo"]] = {}
    for fi in file_infos:
        per_root.setdefault(fi.root_label, []).append(fi)

    for root, fis in per_root.items():
        # README-Check
        if not any(f.rel_path.name.lower() == "readme.md" for f in fis):
            debug.info(
                "repo-no-readme",
                root,
                "README.md fehlt – Repo ist für KIs schwerer einzuordnen.",
            )
        # WGX-Profil-Check
        if not any(
            ".wgx" in f.rel_path.parts and str(f.rel_path).endswith("profile.yml")
            for f in fis
        ):
            debug.info(
                "repo-no-wgx-profile",
                root,
                "`.wgx/profile.yml` nicht gefunden – Repo ist nicht vollständig Fleet-konform.",
            )


# Directories considered "noise" (build artifacts etc.)
NOISY_DIRECTORIES = ("node_modules/", "dist/", "build/", "target/")

# Standard lockfile names
LOCKFILE_NAMES = {
    "Cargo.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
}

# Files typically considered configuration
CONFIG_FILENAMES = {
    "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml",
    "Cargo.toml", "Cargo.lock", "requirements.txt", "Pipfile", "Pipfile.lock",
    "poetry.lock", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Justfile", "Makefile", "toolchain.versions.yml", ".editorconfig",
    ".markdownlint.jsonc", ".markdownlint.yaml", ".yamllint", ".yamllint.yml",
    ".lychee.toml", ".vale.ini", ".pre-commit-config.yaml", ".gitignore",
    ".gitmodules", "tsconfig.json", "babel.config.js", "webpack.config.js",
    "rollup.config.js", "vite.config.js", "vite.config.ts", ".ai-context.yml"
}

# Large generated files or lockfiles that should be summarized in 'dev' profile
SUMMARIZE_FILES = {
    "package-lock.json", "pnpm-lock.yaml", "Cargo.lock", "yarn.lock", "Pipfile.lock", "poetry.lock"
}

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
SOURCE_EXTENSIONS = {
    ".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".svelte", ".c", ".cpp",
    ".h", ".hpp", ".go", ".java", ".cs", ".rb", ".php", ".swift", ".kt",
    ".sh", ".bash", ".pl", ".lua"
}

LANG_MAP = {
    "py": "python", "js": "javascript", "ts": "typescript", "html": "html", "css": "css",
    "scss": "scss", "sass": "sass", "json": "json", "xml": "xml", "yaml": "yaml", "yml": "yaml",
    "md": "markdown", "sh": "bash", "bat": "batch", "sql": "sql", "php": "php", "cpp": "cpp",
    "c": "c", "java": "java", "cs": "csharp", "go": "go", "rs": "rust", "rb": "ruby",
    "swift": "swift", "kt": "kotlin", "svelte": "svelte", "toml": "toml", "ini": "ini",
    "dockerfile": "dockerfile", "tf": "hcl", "hcl": "hcl", "bats": "bash", "pl": "perl", "lua": "lua",
    "ai-context": "yaml"
}

HUB_PATH_FILENAME = ".repolens-hub-path.txt"

# Constants
# Load Epistemic Charter from assets or fallback
_CHARTER_FALLBACK = """## Epistemic Reading Charter (Condensed)
**Status:** Normative | **Applied:** true | **Scope:** report_header

1. **Facts:** `full`/`snippet` = read. `meta` = unread/structure only.
2. **Constraint:** Strong claims only with `full` contact. `meta` requires hypothetical language.
3. **Duty:** If `risk_level != low`, explicitly flag uncertainty.
4. **Guard:** Do not simulate knowledge you don't have.

*Full Charter: merger/lenskit/assets/epistemic_reading_charter.md*
"""

# Semantische Use-Case-Beschreibung pro Profil.
# Wichtig: das ersetzt NICHT den Repo-Zweck (Declared Purpose),
# sondern ergänzt ihn um die Rolle des aktuellen Merges.
PROFILE_USECASE = {
    "overview": "Tools – Index",
    "summary": "Tools – Doku/Kontext",
    "dev": "Tools – Code/Review Snapshot",
    "machine-lean": "Tools – Machine-Lean",
    "max": "Tools – Vollsnapshot",
}

# Mandatory Repository Order for Multi-Repo Merges (v2.1 Spec)
REPO_ORDER = [
    "metarepo",
    "wgx",
    "hausKI",
    "hausKI-audio",
    "heimgeist",
    "chronik",
    "aussensensor",
    "semantAH",
    "leitstand",
    "heimlern",
    "tools",
    "weltgewebe",
    "vault-gewebe",
]

class FileInfo(object):
    """Container for file metadata."""
    __slots__ = (
        "root_label", "abs_path", "rel_path", "size", "is_text", "md5",
        "category", "tags", "ext", "skipped", "reason", "content",
        "inclusion_reason", "anchor", "anchor_alias", "roles", "lens"
    )

    def __init__(self, root_label, abs_path, rel_path, size, is_text, md5, category, tags, ext, skipped=False, reason=None, content=None, inclusion_reason="normal"):
        self.root_label = root_label
        self.abs_path = abs_path
        self.rel_path = rel_path
        self.size = size
        self.is_text = is_text
        self.md5 = md5
        self.category = category
        self.tags = tags
        self.ext = ext
        self.skipped = skipped
        self.reason = reason
        self.content = content
        self.inclusion_reason = inclusion_reason
        self.anchor = "" # Will be set during report generation
        self.anchor_alias = "" # Backwards-compatible anchor (without hash suffix)
        self.roles = None # Will be computed during report generation (None = unset)
        self.lens = None # Assigned during scan or later


# --- Utilities ---

def _hub_path_file(script_path: Path) -> Path:
    # liegt im repoLens-Skriptordner (neben repolens.py)
    return script_path.parent / HUB_PATH_FILENAME


def load_saved_hub_path(script_path: Path) -> Optional[Path]:
    f = _hub_path_file(script_path)
    try:
        if not f.is_file():
            return None
        raw = f.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        if p.is_dir():
            return p
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to load hub path from {f}: {e}\n")
        return None
    return None


def save_hub_path(script_path: Path, hub_dir: Path) -> bool:
    f = _hub_path_file(script_path)
    try:
        f.write_text(str(hub_dir.resolve()), encoding="utf-8")
        return True
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to save hub path to {f}: {e}\n")
        return False


def infer_repo_role(root_label: str, files: List["FileInfo"]) -> str:
    """
    Infers the high-level semantic role of the repository within the organism.
    """
    roles = []
    root = root_label.lower()

    # Name-based heuristics
    if "tool" in root or "merger" in root: roles.append("tooling")
    if "contract" in root or "schema" in root: roles.append("contracts")
    if "meta" in root: roles.append("governance")
    if "lern" in root: roles.append("education")
    if "geist" in root: roles.append("knowledge-base")
    if "haus" in root: roles.append("logic-core")
    if "sensor" in root: roles.append("ingestion")
    if "ui" in root or "app" in root or "leitstand" in root: roles.append("ui")
    if "wgx" in root: roles.append("fleet-management")

    # Content-based heuristics
    has_contracts = any(f.category == "contract" for f in files)

    if has_contracts and "contracts" not in roles:
        roles.append("contracts")

    if not roles:
        roles.append("service")

    return " / ".join(roles)


def summarize_repo(files: List["FileInfo"], included_count: int) -> Dict[str, Any]:
    """
    Build a compact stats dict for a repository.
    """
    total = len(files)
    text_files = sum(
        1
        for f in files
        if f.is_text and f.category in {"source", "doc", "config", "test", "contract"}
    )
    total_bytes = sum(f.size for f in files)

    return {
        "total": total,
        "text_files": text_files,
        "bytes": total_bytes,
        "included": included_count,
    }


def compute_file_roles(fi: "FileInfo") -> List[str]:
    """
    Compute semantic roles with a lean, high-signal heuristic.

    Only adds roles that meaningfully refine the category:
    - doc-essential: README-level docs
    - config: configuration/contract-style paths or config extensions
    - entrypoint: common entrypoint filenames
    - ai-context: AI/context-bearing paths or tags
    """
    roles: List[str] = []

    path_str = fi.rel_path.as_posix().lower()
    filename = fi.rel_path.name.lower()

    if fi.category == "doc" and "readme" in filename:
        roles.append("doc-essential")

    if "config" in path_str or filename.endswith((".yml", ".yaml", ".toml")):
        roles.append("config")

    if filename.startswith(("run_", "main", "index")):
        roles.append("entrypoint")

    if "ai" in path_str or "context" in path_str or "ai-context" in (fi.tags or []):
        roles.append("ai-context")

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for r in roles:
        if r not in seen:
            deduped.append(r)
            seen.add(r)

    return deduped


def build_hotspots(processed_files: List[Tuple["FileInfo", str]], limit: int = 8) -> List[str]:
    """
    Build a concise hotspot list for quick navigation.

    Focuses on included files and boosts likely entrypoints/configs.
    """
    candidates: List[Tuple[float, FileInfo]] = []

    for fi, status in processed_files:
        if status not in ("full", "truncated"):
            continue

        score = 0.0

        if "entrypoint" in fi.roles:
            score += 5.0
        if fi.category == "contract":
            score += 3.0
        if "ai-context" in (fi.tags or []):
            score += 2.5
        if "ci" in (fi.tags or []):
            score += 1.5
        if fi.category == "config":
            score += 1.0

        # Light size bias to surface substantial files without overwhelming the list
        score += min(fi.size / 1024.0, 50) / 50.0

        candidates.append((score, fi))

    if not candidates:
        return []

    candidates.sort(key=lambda item: (-item[0], -item[1].size, str(item[1].rel_path)))
    top = candidates[:limit]

    lines = ["### Hotspots (Einstiegspunkte)"]
    for _, fi in top:
        link = f"[`{fi.rel_path}`](#{fi.anchor})"
        role_hint = f"roles: {', '.join(fi.roles)}" if fi.roles else "roles: -"
        tag_hint = f"tags: {', '.join(fi.tags)}" if fi.tags else "tags: -"
        lines.append(
            f"- {link} — repo `{fi.root_label}`, {fi.category}; {role_hint}, {tag_hint}"
        )

    return lines


def describe_scope(files: List["FileInfo"]) -> str:
    """Build a human-readable scope string from the involved roots."""
    roots = sorted({fi.root_label for fi in files})
    if not roots:
        return "empty (no matching files)"
    if len(roots) == 1:
        return f"single repo `{roots[0]}`"

    preview = ", ".join(f"`{r}`" for r in roots[:5])
    if len(roots) > 5:
        preview += ", …"
    return f"{len(roots)} repos: {preview}"


def determine_inclusion_status(fi: "FileInfo", level: str, max_file_bytes: int) -> str:
    """
    Determine whether a file is included with content based on profile settings.
    Returns one of {"full", "meta-only", "omitted", "truncated"} (truncated unused today).
    """
    if not fi.is_text:
        return "omitted"

    tags = fi.tags or []

    if level == "overview":
        return "full" if is_priority_file(fi) else "meta-only"

    if level == "summary":
        if fi.category in ["doc", "config", "contract"] or "ci" in tags or "ai-context" in tags or "wgx-profile" in tags:
            return "full"
        if fi.category in ["source", "test"]:
            return "full" if is_priority_file(fi) else "meta-only"
        return "full" if is_priority_file(fi) else "meta-only"

    if level in ("dev", "machine-lean"):
        if "lockfile" in tags:
            return "meta-only" if fi.size > 20_000 else "full"
        if fi.category in ["source", "test", "config", "contract"] or "ci" in tags:
            return "full"
        if fi.category == "doc":
            return "full" if is_priority_file(fi) else "meta-only"
        return "meta-only"

    if level == "max":
        return "full"

    return "full" if fi.size <= max_file_bytes else "omitted"

def is_noise_file(fi: "FileInfo") -> bool:
    """
    Heuristik für 'Noise'-Dateien:
    - offensichtliche Lockfiles / Paketmanager-Artefakte
    - typische Build-/Vendor-Verzeichnisse
    ohne das Manifest-Schema zu verändern – nur das Included-Label wird erweitert.
    """
    try:
        path_str = str(fi.rel_path).replace("\\", "/").lower()
        name = fi.rel_path.name.lower()
    except Exception as e:
        sys.stderr.write(f"Warning: is_noise_file failed for {fi.rel_path}: {e}\n")
        return False

    noisy_dirs = (
        "node_modules/",
        "dist/",
        "build/",
        "target/",
        "venv/",
        ".venv/",
        "__pycache__/",
    )
    if any(seg in path_str for seg in noisy_dirs):
        return True

    lock_names = {
        "cargo.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "poetry.lock",
        "pipfile.lock",
        "composer.lock",
    }
    if name in lock_names or name.endswith(".lock"):
        return True

    tags_lower = {t.lower() for t in (fi.tags or [])}
    if "lockfile" in tags_lower or "deps" in tags_lower or "vendor" in tags_lower:
        return True

    return False

def detect_hub_dir(script_path: Path, arg_base_dir: Optional[str] = None) -> Path:
    if arg_base_dir:
        p = Path(arg_base_dir).expanduser()
        if p.is_dir():
            return p

    env_base = os.environ.get("REPOLENS_BASEDIR")
    if env_base:
        p = Path(env_base).expanduser()
        if p.is_dir():
            return p

    saved = load_saved_hub_path(script_path)
    if saved is not None:
        return saved

    # Pythonista local Documents fallback
    script_str = str(script_path)
    is_pythonista_like = (
        "Pythonista" in script_str
        or "/private/var/mobile/" in script_str
    )

    if is_pythonista_like:
        try:
            local_docs = Path.home() / "Documents"
            candidate = local_docs / "wc-hub"
            if candidate.is_dir():
                return candidate
        except OSError:
            pass

    raise FileNotFoundError(
        "Hub-Verzeichnis nicht gefunden. "
        "Gepruefte Quellen: explizites Argument, Environment-Variable, "
        "gespeicherter Pfad sowie - im Pythonista-Kontext - lokales Documents/wc-hub. "
        "Hinweis: Bei Pythonista/iCloud koennen Script und Hub in getrennten "
        "Speicherwelten liegen; in diesem Fall muss ein gueltiger Hub-Pfad "
        "explizit bereitgestellt werden."
    )


def get_merges_dir(hub: Path) -> Path:
    merges = hub / MERGES_DIR_NAME
    merges.mkdir(parents=True, exist_ok=True)
    return merges


def human_size(n: float) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} GB"


def is_probably_text(path: Path, size: int) -> bool:
    name = path.name.lower()
    base, ext = os.path.splitext(name)
    if ext in TEXT_EXTENSIONS or name in TEXT_EXTENSIONS:
        return True
    if size > 20 * 1024 * 1024:  # 20 MiB
        return False
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False
    if not chunk:
        return True
    if b"\x00" in chunk:
        return False
    return True


def _compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hash of a file using chunked reading for memory efficiency."""
    sha256 = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()
    except OSError:
        return "ERROR"


def compute_md5(path: Path, limit_bytes: Optional[int] = None) -> str:
    # MD5 is used for file integrity checking, not cryptographic security
    try:
        h = hashlib.md5(usedforsecurity=False)
    except TypeError:
        # Fallback for Python < 3.9
        h = hashlib.md5()  # nosec B303
    try:
        with path.open("rb") as f:
            remaining = limit_bytes
            while True:
                if remaining is None:
                    chunk = f.read(65536)
                else:
                    chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
        return h.hexdigest()
    except OSError as e:
        sys.stderr.write(f"Warning: MD5 computation failed for {path}: {e}\n")
        return "ERROR"


def lang_for(ext: str) -> str:
    return LANG_MAP.get(ext.lower().lstrip("."), "")


def get_repo_sort_index(repo_name: str) -> int:
    """Returns sort index for repo based on REPO_ORDER."""
    try:
        return REPO_ORDER.index(repo_name)
    except ValueError:
        return 999  # Put undefined repos at the end

def extract_purpose(repo_root: Path) -> str:
    """Safe purpose extraction from README or docs/intro.md. No guessing."""
    candidates = ["README.md", "README", "docs/intro.md"]
    for c in candidates:
        p = repo_root / c
        if p.exists():
            try:
                # Read text safely
                with p.open("r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read().strip()
                    # First paragraph is content until double newline
                    first = txt.split("\n\n")[0].strip()
                    # Markdown-Überschrift (#, ##, …) vorne abschneiden
                    first = first.lstrip("#").strip()
                    return first
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to extract purpose from {p}: {e}\n")
                return ""
    return ""

def get_declared_purpose(files: List[FileInfo]) -> str:
    # Deprecated in favor of extract_purpose for consistency with Spec v2.3 patch D logic
    # But kept as fallback or to support .ai-context which spec patch D didn't mention explicitly
    # but patch D implemented it as:
    # try: purpose = extract_purpose(sources[0]); ...
    return "(none)" # Handled in iter_report_blocks via extract_purpose


def classify_file_v2(rel_path: Path, ext: str) -> Tuple[str, List[str]]:
    """
    Returns (category, tags).
    Strict Pattern Matching based on v2.1 Spec.
    """
    # Optimization: Use tuple directly, don't convert to list
    parts = rel_path.parts
    name = rel_path.name.lower()
    tags = []

    # Tag Patterns - Strict match
    # KI-Kontext-Dateien
    if name.endswith(".ai-context.yml"):
        tags.append("ai-context")

    # CI-Workflows
    if ".github" in parts and "workflows" in parts and ext in [".yml", ".yaml"]:
        tags.append("ci")

    # Contracts:
    # Nur als Kategorie, nicht mehr als Tag – Spec sieht kein 'contract'-Tag vor.
    # (Die Zuordnung passiert weiter unten über die Category-Logik.)

    if "docs" in parts and "adr" in parts and ext == ".md":
        tags.append("adr")
    if name.startswith("runbook") and ext == ".md":
        tags.append("runbook")

    # Skripte: Shell und Python unter scripts/ oder bin/ als 'script' markieren
    if (("scripts" in parts) or ("bin" in parts)) and ext in (".sh", ".py"):
        tags.append("script")

    if "export" in parts and ext == ".jsonl":
        tags.append("feed")

    # Lockfiles (package-lock, Cargo.lock, pnpm-lock, etc.)
    if "lock" in name:
        tags.append("lockfile")

    # README: Spec-konform als KI-Kontext markieren, kein eigener 'readme'-Tag
    if name == "readme.md":
        tags.append("ai-context")

    # WGX-Profile
    if ".wgx" in parts and name.startswith("profile"):
        tags.append("wgx-profile")


    # Determine Category - Strict Logic
    # Category ∈ {source, test, doc, config, contract, other}
    category = "other"

    # Order matters: check more specific first
    if name in CONFIG_FILENAMES or "config" in parts or ".github" in parts or ".wgx" in parts or ext in [".toml", ".yaml", ".yml", ".json", ".lock"]:
         # Note: .json could be contract or config, check contract path
         if "contracts" in parts:
             category = "contract"
         else:
             category = "config"
    elif ext in DOC_EXTENSIONS or "docs" in parts:
        category = "doc"
    elif "contracts" in parts: # Fallback if not caught above
        category = "contract"
    elif "tests" in parts or "test" in parts or name.endswith("_test.py") or name.startswith("test_"):
        category = "test"
    elif ext in SOURCE_EXTENSIONS or "src" in parts or "crates" in parts or "scripts" in parts:
        category = "source"

    return category, tags


def _normalize_ext_list(ext_text: str) -> List[str]:
    if not ext_text:
        return []
    parts = [p.strip() for p in ext_text.split(",")]
    cleaned: List[str] = []
    for p in parts:
        if not p:
            continue
        if not p.startswith("."):
            p = "." + p
        cleaned.append(p.lower())
    return cleaned


# --- Repo Scan Logic ---

def is_critical_file(rel_path_str: str) -> bool:
    """
    Checks if a file is critical and should be force-included regardless of filters.
    Rules:
    - README.md (any case)
    - .ai-context.yml
    - .wgx/profile.yml
    - .github/workflows/*guard*
    """
    lower = rel_path_str.lower()
    if lower == "readme.md" or lower.endswith("/readme.md"):
        return True
    if lower == ".ai-context.yml" or lower.endswith("/.ai-context.yml"):
        return True
    if ".wgx/profile.yml" in lower:
        return True
    if ".github/workflows/" in lower and "guard" in lower:
        return True
    return False

def prescan_repo(repo_root: Path, max_depth: int = 10, ignore_globs: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Lightweight scan for structure visualization (Prescan).
    Returns a nested dict representing the tree.
    """
    repo_root = repo_root.resolve()
    root_label = repo_root.name

    # Build ignores
    ignore_set = set(SKIP_DIRS)
    import fnmatch

    # Simple tree structure: { "path": ".", "type": "dir", "children": [...] }
    # To build it, we traverse and collect nodes.
    # We can perform a recursive function.

    total_files = 0
    total_bytes = 0
    node_count = 0
    MAX_NODES = 50000

    def _is_ignored(name: str, relpath: str) -> bool:
        if name in ignore_set or name in SKIP_FILES:
            return True
        if name.startswith(".env") and name not in (".env.example", ".env.template", ".env.sample"):
            return True
        if ignore_globs:
            for g in ignore_globs:
                # User request: match against name (basename) OR relpath
                if fnmatch.fnmatch(name, g) or fnmatch.fnmatch(relpath, g):
                    return True
        return False

    def _walk(path: Path, depth: int) -> Dict[str, Any]:
        nonlocal total_files, total_bytes, node_count
        node_count += 1
        if node_count > MAX_NODES:
            # Hard abort signal
            raise RuntimeError(f"Prescan limit reached ({MAX_NODES} nodes). Repo too large.")

        rel_dir = path.relative_to(repo_root).as_posix() if path != repo_root else "."
        node = {
            "path": rel_dir,
            "type": "dir",
            "children": []
        }

        if depth > max_depth:
            return node

        try:
            # Sort for deterministic output
            with os.scandir(path) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            return node

        for entry in entries:
            name = entry.name
            full = path / name

            # Compute relpath for check
            # if rel_dir is ".", then relpath is name. Else rel_dir/name.
            child_rel = name if rel_dir == "." else f"{rel_dir}/{name}"

            if _is_ignored(name, child_rel):
                continue

            # Symlink Check (Security/Recursion)
            if entry.is_symlink():
                continue

            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            if entry.is_dir(follow_symlinks=False):
                 child_node = _walk(full, depth + 1)
                 node["children"].append(child_node)
            else:
                 # File
                 total_files += 1
                 node_count += 1
                 if node_count > MAX_NODES:
                     raise RuntimeError(f"Prescan limit reached ({MAX_NODES} nodes). Repo too large.")

                 total_bytes += st.st_size
                 file_node = {
                     "path": full.relative_to(repo_root).as_posix(),
                     "type": "file",
                     "size": st.st_size
                 }
                 node["children"].append(file_node)

        return node

    tree = _walk(repo_root, 0)

    # Compute a signature (hash of file paths + total bytes)
    # This helps detecting drift between prescan and merge.
    # Collect all file paths and sizes for signature
    sig_items = []

    def _collect_for_sig(node):
        if node["type"] == "file":
            # relpath:size
            sig_items.append(f"{node['path']}:{node.get('size', 0)}")
        if node.get("children"):
            for c in node["children"]:
                _collect_for_sig(c)

    _collect_for_sig(tree)
    sig_items.sort()

    sig_raw = "\n".join(sig_items)
    signature = hashlib.sha256(sig_raw.encode("utf-8")).hexdigest()

    return {
        "root": root_label,
        "tree": tree,
        "signature": signature,
        "file_count": total_files,
        "total_bytes": total_bytes
    }

def scan_repo(repo_root: Path, extensions: Optional[List[str]] = None, path_contains: Optional[str] = None, max_bytes: int = DEFAULT_MAX_BYTES, include_paths: Optional[List[str]] = None, calculate_md5: bool = True, include_hidden: bool = True) -> Dict[str, Any]:
    """
    Scans a repository and returns a summary dict with file info.

    calculate_md5:
        If False, skips all MD5 computation. Intended for plan-only / non-manifest
        operations where file integrity hashes are not required.
    include_hidden:
        If False, skips files and directories starting with '.' (unless explicitly whitelisted).
        Safe .env samples (.example/.template/.sample) are always included regardless of this flag.
    """
    repo_root = repo_root.resolve()
    root_label = repo_root.name
    files = []

    ext_filter = set(e.lower() for e in extensions) if extensions else None
    path_filter = path_contains.strip() if path_contains else None

    # Optimize include_paths check
    include_set = None
    include_prefixes = []

    # Normalize input: trim and filter empty
    # Handles:
    # - "src" -> "src"
    # - " ./src " -> "src"
    # - "." / "/" / "" -> None (ALL)
    # - [] -> [] (None selected)
    if include_paths is not None:
        normalized = []
        is_root_request = False

        for p in include_paths:
            if p is None: continue
            s = p.strip()

            # Explicit root indicators
            if s in (".", "/", ""):
                is_root_request = True
                continue

            # Remove leading ./ if present (common from UI/find)
            if s.startswith("./"):
                s = s[2:]

            # Check again if it became root (e.g. "./")
            if not s:
                is_root_request = True
                continue

            normalized.append(s)

        if is_root_request:
            include_paths = None
        else:
            include_paths = normalized

    if include_paths is not None:
        include_set = set(include_paths)
        # Store prefixes for directory matching optimization
        for p in include_paths:
            include_prefixes.append(p + "/")

    total_files = 0
    total_bytes = 0
    ext_hist: Dict[str, int] = {}

    root_str = str(repo_root)
    # Guardrail: Ensure root ends with separator for safe prefix checking
    root_guard = root_str if root_str.endswith(os.sep) else root_str + os.sep
    root_len = len(root_str)

    # Files awaiting MD5 calculation: list of (FileInfo, abs_path, effective_limit)
    files_to_hash: List[Tuple[FileInfo, Path, Optional[int]]] = []
    # 0 oder <0 = "kein Limit" → komplette Textdateien hashen
    limit_bytes: Optional[int] = max_bytes if max_bytes and max_bytes > 0 else None

    # Pre-normalize root for robust containment checks
    root_norm = os.path.normpath(os.path.abspath(root_str))

    for dirpath, dirnames, filenames in os.walk(root_str):
        # Filter directories
        keep_dirs = []
        for d in dirnames:
            if d in SKIP_DIRS:
                continue
            if not include_hidden and d.startswith("."):
                continue
            keep_dirs.append(d)
        dirnames[:] = keep_dirs

        # Security Guardrail (Directory Level)
        # We check the directory once. If dirpath is safely inside root_norm,
        # then all its files (which are simple names) are also safe.
        # This avoids repeating expensive commonpath checks for every file.
        dirpath_norm = os.path.normpath(os.path.abspath(dirpath))
        try:
            is_dir_safe = os.path.commonpath([root_norm, dirpath_norm]) == root_norm
        except ValueError:
            # Can happen on Windows if drives differ
            is_dir_safe = False

        if not is_dir_safe:
            # Skip entire directory if it breaks containment (e.g. symlink traversal out)
            # Note: os.walk descends into dirs, so we should arguably clear dirnames to stop recursion,
            # but here we just skip processing files.
            # If safe recursion is desired, we should also clear dirnames[:] here.
            # But strictly speaking, the check is for the files we are about to add.
            dirnames[:] = []
            continue

        # Calculate relative directory once per folder
        if dirpath == root_str:
            rel_dir = ""
        else:
            rel_dir = dirpath[root_len:].lstrip(os.sep).replace("\\", "/")

        for fn in filenames:
            if fn in SKIP_FILES:
                continue

            # Keep safe .env samples even when include_hidden=False
            if fn.startswith(".env"):
                if fn not in (".env.example", ".env.template", ".env.sample"):
                    continue
            elif not include_hidden and fn.startswith("."):
                continue

            if rel_dir:
                rel_path_str = f"{rel_dir}/{fn}"
            else:
                rel_path_str = fn

            # Optimization: Defer Path object creation until we confirm the file should be processed
            abs_path_str = os.path.join(dirpath, fn)

            # Filter Logic with Force Include
            is_critical = is_critical_file(rel_path_str)
            inclusion_reason = "normal"

            if is_critical:
                _, ext = os.path.splitext(fn)
                ext = ext.lower()
                inclusion_reason = "force_include"
            else:
                # Include Paths Check (Whitelist)
                if include_paths is not None:
                     # If file is explicitly in include_set or under an included directory
                     matched = False
                     if rel_path_str in include_set:
                         matched = True
                     else:
                         for prefix in include_prefixes:
                             if rel_path_str.startswith(prefix):
                                 matched = True
                                 break
                     if not matched:
                         continue

                # Normal filtering
                if path_filter and path_filter not in rel_path_str:
                    continue

                _, ext = os.path.splitext(fn)
                ext = ext.lower()
                if ext_filter is not None and ext not in ext_filter:
                    continue

            # Now create Path objects for further processing
            abs_path = Path(abs_path_str)
            rel_path = Path(rel_path_str)

            try:
                st = abs_path.stat()
            except OSError:
                continue

            size = st.st_size
            total_files += 1
            total_bytes += size
            ext_hist[ext] = ext_hist.get(ext, 0) + 1

            is_text = is_probably_text(abs_path, size)
            category, tags = classify_file_v2(rel_path, ext)

            # MD5 calculation logic (deferred):
            # - Textdateien: immer kompletter MD5 (effective_limit = None)
            # - Binärdateien:
            #   a) wenn kein Limit gesetzt ist (unlimited) -> hashen
            #   b) wenn Limit gesetzt ist -> nur hashen, wenn size <= Limit
            should_hash = False
            effective_limit: Optional[int] = limit_bytes

            if calculate_md5:
                if is_text:
                    should_hash = True
                    effective_limit = None  # Force full hash for text
                else:
                    # Fix v2.4: Allow binary hashing if unlimited (limit_bytes is None)
                    if limit_bytes is None or size <= limit_bytes:
                        should_hash = True
                        # effective_limit remains limit_bytes

            fi = FileInfo(
                root_label=root_label,
                abs_path=abs_path,
                rel_path=rel_path,
                size=size,
                is_text=is_text,
                md5="",  # Placeholder, computed in parallel below
                category=category,
                tags=tags,
                ext=ext,
                inclusion_reason=inclusion_reason
            )
            fi.lens = lenses.infer_lens(rel_path)
            files.append(fi)
            if should_hash:
                files_to_hash.append((fi, abs_path, effective_limit))

    # Parallel MD5 computation
    if files_to_hash:
        # Use a reasonable number of workers (CPU count + 4 usually handles I/O mixed loads well)
        max_workers = min(32, (os.cpu_count() or 1) + 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            paths = [p for _, p, _ in files_to_hash]
            limits = [l for _, _, l in files_to_hash]

            # Note: compute_md5 captures exceptions and returns "ERROR", so this is safe
            results = executor.map(compute_md5, paths, limits)

            for (fi, _, _), result_md5 in zip(files_to_hash, results):
                fi.md5 = result_md5

    # Sort files: first by repo order (if multi-repo context handled outside,
    # but here root_label is constant per scan_repo call unless we merge lists later),
    # then by path.
    files.sort(key=lambda fi: str(fi.rel_path).lower())

    return {
        "root": repo_root,
        "name": root_label,
        "files": files,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "ext_hist": ext_hist,
    }

def parse_human_size(text: str) -> int:
    text = str(text).upper().strip()
    if not text: return 0
    if text.isdigit(): return int(text)

    units = {"K": 1024, "M": 1024**2, "G": 1024**3}
    for u, m in units.items():
        if text.endswith(u) or text.endswith(u+"B"):
            val = text.rstrip(u+"B").rstrip(u)
            try:
                return int(float(val) * m)
            except ValueError:
                return 0
    return 0

def get_repo_snapshot(repo_root: Path) -> Dict[str, Tuple[int, str, str]]:
    """
    Liefert einen Snapshot des Repos für Diff-Zwecke.

    Rückgabe:
      Dict[rel_path] -> (size, md5, category)

    Wichtig:
      - nutzt scan_repo, d. h. dieselben Ignore-Regeln wie der Merger
      - Category stammt direkt aus classify_file_v2 und ist damit
        kompatibel zum Manifest (source/doc/config/test/contract/ci/other)
    """
    snapshot: Dict[str, Tuple[int, str, str]] = {}
    summary = scan_repo(
        repo_root, extensions=None, path_contains=None, max_bytes=100_000_000, calculate_md5=True
    )  # großes Limit, damit wir verlässliche MD5s haben
    for fi in summary["files"]:
        snapshot[fi.rel_path.as_posix()] = (fi.size, fi.md5, fi.category or "other")
    return snapshot


def compute_epistemic_metrics(files: List[FileInfo], processed_files: List[Tuple[FileInfo, str]]) -> Dict[str, Any]:
    """
    Compute epistemic metrics (counts, ratios, risks) in one place.
    Single Source of Truth for JSON and Markdown.
    """
    total_files_count = len(files)

    # Calculate counts from processed status
    full_count = sum(1 for _, s in processed_files if s == "full")
    snippet_count = sum(1 for _, s in processed_files if s == "truncated")
    # Meta is everything else (meta-only, omitted, etc)
    meta_count = sum(1 for _, s in processed_files if s not in ("full", "truncated"))

    # Text-Files specific metrics
    text_files_total = sum(1 for f in files if f.is_text)
    text_files_contact = sum(1 for f, s in processed_files if f.is_text and s in ("full", "truncated"))

    # Ratios
    contact_ratio = round(((full_count + snippet_count) / total_files_count) if total_files_count else 0.0, 2)
    meta_ratio = round((meta_count / total_files_count) if total_files_count else 0.0, 2)
    text_coverage_ratio = round((text_files_contact / text_files_total) if text_files_total else 0.0, 2)

    # Risk Level Logic
    risk_level = "low"
    if text_files_total > 0:
        if text_coverage_ratio < 0.1:
            risk_level = "high"
        elif text_coverage_ratio < 0.5:
            risk_level = "medium"
    else:
        risk_level = "low" # No text files? Low risk of missing text.

    if snippet_count > 0 and risk_level == "low":
        risk_level = "medium"

    risk_rationale = {
        "low_if": "text_coverage_ratio >= 0.5 and snippet_count == 0",
        "medium_if": "text_coverage_ratio < 0.5 or snippet_count > 0",
        "high_if": "text_coverage_ratio < 0.1"
    }

    risk_inputs = {
        "contact_ratio_all_files": contact_ratio,
        "text_coverage_ratio": text_coverage_ratio,
        "snippet_count": snippet_count
    }

    # Uncertainty Score: based on text coverage gap
    # 1.0 - text_coverage_ratio
    uncertainty_score = round(1.0 - text_coverage_ratio, 2)

    return {
        "counts": {
            "total": total_files_count,
            "full": full_count,
            "snippet": snippet_count,
            "meta": meta_count,
            "text_total": text_files_total,
            "text_contact": text_files_contact
        },
        "ratios": {
            "contact_ratio": contact_ratio,
            "meta_ratio": meta_ratio,
            "text_coverage_ratio": text_coverage_ratio
        },
        "risk": {
            "level": risk_level,
            "rationale": risk_rationale,
            "inputs": risk_inputs,
            "uncertainty_score": uncertainty_score
        }
    }


# --- Reporting Logic V2 ---

def _effective_render_mode(plan_only: bool, code_only: bool, meta_none: bool = False) -> str:
    """Return the effective render mode based on flags."""

    if meta_none:
        return "none"

    plan_only = bool(plan_only)
    code_only = bool(code_only)

    # plan_only wins – avoid conflicting content policies.
    if plan_only:
        return "plan-only"
    if code_only:
        return "code-only"
    return "full"


def _normalize_mode_flags(plan_only: bool, code_only: bool, meta_none: bool = False) -> Tuple[bool, bool, bool, Dict[str, bool]]:
    """Normalize plan/code/meta flags and retain the original user request."""

    requested_flags = {
        "plan_only": bool(plan_only),
        "code_only": bool(code_only),
        "meta_none": bool(meta_none),
    }

    meta_none = requested_flags["meta_none"]

    if meta_none:
        # meta: none implies raw content view, so plan_only is strictly False.
        # code_only is allowed as a filter, but we treat it as orthogonal.
        plan_only = False
        code_only = requested_flags["code_only"]
    else:
        plan_only = requested_flags["plan_only"]
        code_only = False if plan_only else requested_flags["code_only"]

    return plan_only, code_only, meta_none, requested_flags


def _resolve_effective_meta_density(
    meta_density: str,
    path_filter: Optional[str] = None,
    ext_filter: Optional[List[str]] = None,
    meta_none: bool = False,
) -> str:
    """
    Resolves the effective meta density based on filters and flags.
    Standardizes logic between Markdown and JSON sidecar.
    """
    if meta_none:
        return "min"  # Interpretation disabled implies minimal metadata overhead

    if meta_density == "auto":
        # Auto-Throttling: resolve to standard if filters are active, otherwise full.
        if path_filter or ext_filter:
            return "standard"
        return "full"

    return meta_density


def _generate_run_id(
    repo_names: List[str],
    detail: str,
    path_filter: Optional[str],
    ext_filter: Optional[str],
    plan_only: bool = False,
    code_only: bool = False,
    timestamp: Optional[str] = None,
    meta_none: bool = False,
) -> str:
    """
    Generate a deterministic run_id for consistent primary artifact naming.

    Args:
        repo_names: List of repository names
        detail: Profile level (dev, max, summary, etc.)
        path_filter: Optional path filter
        ext_filter: Optional extension filter
        timestamp: Optional timestamp string (if None, uses current time)
        meta_none: meta: none mode

    Returns:
        A deterministic run_id string
    """
    if timestamp is None:
        timestamp = clock.now_utc().strftime("%y%m%d-%H%M")

    components: List[str] = []

    plan_only, code_only, meta_none, _ = _normalize_mode_flags(plan_only, code_only, meta_none)

    # Path block first (stable anchor).
    if path_filter:
        path_slug = path_filter.strip().strip("/").replace("/", "-")
        if path_slug:
            components.append(path_slug)

    # Repo block
    if not repo_names:
        components.append("no-repo")
    elif len(repo_names) == 1:
        components.append(repo_names[0].replace("/", "-"))
    else:
        repo_str = "-".join(sorted(repo_names))
        repo_hash = hashlib.md5(repo_str.encode("utf-8")).hexdigest()[:6]
        components.append(f"multi-{repo_hash}")

    # Mode + profile blocks
    components.append(_effective_render_mode(plan_only, code_only, meta_none))
    components.append(detail)

    # Optional filters (makes run_id unique per filter combination)
    if ext_filter:
        ext_clean = ext_filter.replace(".", "").replace(",", "+").replace(" ", "")
        if ext_clean:
            components.append(f"ext-{ext_clean}")

    # Timestamp always last
    components.append(timestamp)

    return "-".join(components)


def build_tree(file_infos: List[FileInfo]) -> str:
    by_root: Dict[str, List[Path]] = {}

    # Sort roots first
    sorted_files = sorted(file_infos, key=lambda fi: (get_repo_sort_index(fi.root_label), fi.root_label.lower()))

    for fi in sorted_files:
        by_root.setdefault(fi.root_label, []).append(fi.rel_path)

    lines = ["```"]
    # Keys are already sorted by insertion order in py3.7+, which matches our sorted_files loop,
    # but let's be safe and sort keys based on REPO_ORDER.
    sorted_roots = sorted(by_root.keys(), key=lambda r: (get_repo_sort_index(r), r.lower()))

    for root in sorted_roots:
        rels = by_root[root]
        lines.append(f"📁 {root}/")

        tree: Dict[str, Any] = {}
        for r in rels:
            parts = list(r.parts)
            node = tree
            for p in parts:
                if p not in node:
                    node[p] = {}
                node = node[p]

        def walk(node, indent, root_lbl):
            dirs = []
            files = []
            for k, v in node.items():
                if v:
                    dirs.append(k)
                else:
                    files.append(k)
            for d in sorted(dirs):
                lines.append(f"{indent}📁 {d}/")
                walk(node[d], indent + "    ", root_lbl)
            for f in sorted(files):
                # Optional: Hyperlinking in Tree
                # Needs rel path reconstruction which is tricky in this recursive walk without passing it down
                # For v2.3 Spec 6.3: 📄 [filename](#file-…)
                # We need to construct the full relative path to generate the anchor.
                # Since we don't pass the path down easily here, let's skip tree linking for this iteration
                # to keep it robust, or do a simple approximation if needed.
                # Actually, we can use a lookup if we want, but "optional" in spec allows skipping.
                # Let's stick to plain text for now to avoid complexity in build_tree.
                lines.append(f"{indent}📄 {f}")

        walk(tree, "    ", root)
    lines.append("```")
    return "\n".join(lines)

def make_output_filename(
    merges_dir: Path,
    repo_names: List[str],
    detail: str,
    part_suffix: str,
    path_filter: Optional[str],
    ext_filter: Optional[str],
    run_id: Optional[str] = None,
    plan_only: bool = False,
    code_only: bool = False,
    timestamp: Optional[str] = None,
    meta_none: bool = False,
    suffix: str = "_merge.md",
) -> Path:
    """
    Erzeugt den endgültigen Dateinamen für den Merge-Report.

    If run_id is provided, uses it as the base stem (deterministic).
    Otherwise, generates filename from components (legacy behavior).

    Neuer Wunsch:
    - Zuerst der Block aus dem Pfad-Filter (ohne 'path-'-Präfix)
    - Danach der bisherige Rest (Repo-Block, Detail, Timestamp, evtl. Filter/Part)
    """

    plan_only, code_only, meta_none, _ = _normalize_mode_flags(plan_only, code_only, meta_none)
    render_mode = _effective_render_mode(plan_only, code_only, meta_none)

    # Normalize "no path filter" sentinels coming from UI/config.
    # If the UI stores "root" (or "/") to mean "no specific subpath selected",
    # we must *not* leak that into the filename.
    if isinstance(path_filter, str):
        pf = path_filter.strip()
        if pf in ("", "root", "/"):
            path_filter = None

    # Phase 1.3: If run_id is provided and mode != single, use simple filename:
    # <run_id>[_partxofy]_merge.md
    #
    # NOTE: We intentionally *disable* the run_id-as-filename shortcut.
    # Reason: it produces opaque stems like "9f75ad" which are bad for humans,
    # and it also hides useful context (mode/detail/timestamp).
    # The run_id can still live in metadata; filenames stay descriptive.

    # Legacy behavior: build filename from components
    # 1. Timestamp (jetzt immer am Ende)
    ts = timestamp if timestamp else clock.now_utc().strftime("%y%m%d-%H%M")

    # 2. Repo-Block
    if not repo_names:
        repo_block = "no-repo"
    elif len(repo_names) == 1:
        repo_block = repo_names[0]
    else:
        repo_block = "multi"
    repo_block = repo_block.replace("/", "-")

    # 3. Detail-Block (overview/summary/dev/max)
    detail_block = detail

    # 4. Pfad-Block: aus path_filter, aber OHNE 'path-' Präfix
    # Wichtig: Wenn KEIN spezifischer Pfad gewählt ist, soll hier gar nichts stehen.
    path_block = None
    if path_filter:
        slug = path_filter.strip().strip("/")
        if slug:
            path_block = slug.replace("/", "-")

    # 5. Mode-Block (Kollisionen vermeiden)
    # Optimization: Omit default 'full' mode to shorten filename
    mode_block = None if render_mode == "full" else render_mode

    # 6. Optional: Extension-Filter-Block (nur, wenn bewusst gesetzt)
    ext_block = None
    if ext_filter:
        cleaned = ext_filter.replace(" ", "").replace(".", "").replace(",", "+")
        if cleaned:
            ext_block = f"ext-{cleaned}"

    # 7. Optional: Part-Suffix (_partXofY o. ä.) – kommt schon fertig rein
    part_block = part_suffix.lstrip("_") if part_suffix else ""

    # 8. Reihenfolge bauen:
    #    1. path_block
    #    2. repo_block
    #    3. mode_block
    #    4. detail_block
    #    5. ext_block (falls vorhanden)
    #    6. part_block (falls vorhanden)
    #    7. ts (am Ende)
    parts: List[str] = []

    if path_block:
        parts.append(path_block)

    parts.append(repo_block)
    if mode_block:
        parts.append(mode_block)
    parts.append(detail_block)

    if ext_block:
        parts.append(ext_block)

    if part_block:
        parts.append(part_block)

    parts.append(ts)

    filename = "-".join(parts) + suffix
    return merges_dir / filename

def read_smart_content(fi: FileInfo, max_bytes: int, encoding="utf-8") -> Tuple[str, bool, str]:
    """
    Reads content.
    Returns (content, truncated, truncation_msg).
    Truncation is disabled in v2.3+ per user request (files are split across parts if needed).
    max_bytes is ignored here, effectively reading the full file.
    """
    try:
        with fi.abs_path.open("r", encoding=encoding, errors="replace") as f:
            return f.read(), False, ""
    except OSError as e:
        return f"_Error reading file: {e}_", False, ""

def is_priority_file(fi: FileInfo) -> bool:
    if "ai-context" in fi.tags: return True
    if "runbook" in fi.tags: return True
    if fi.rel_path.name.lower() == "readme.md": return True
    return False

def _render_delta_block(delta_meta: Dict[str, Any]) -> str:
    """
    Render Delta Report block from delta metadata.
    Shows what changed between base and current import.

    Supports both formats:
    1. Schema-compliant (base_import, current_timestamp, summary.files_*)
    2. Detailed format (base_timestamp, files_added/removed/changed as arrays)
    """
    lines = []
    lines.append("<!-- @delta:start -->")
    lines.append("## ♻ Delta Report")
    lines.append("")

    # Extract timestamps - support both schema (base_import) and legacy (base_timestamp)
    base_ts = delta_meta.get("base_import") or delta_meta.get("base_timestamp", "unknown")
    current_ts = delta_meta.get("current_timestamp", "unknown")

    lines.append(f"- **Base Import:** {base_ts}")
    lines.append(f"- **Current:** {current_ts}")
    lines.append("")

    def _safe_list_len(val):
        """Helper: safely get length of value if it's a list, else 0."""
        return len(val) if isinstance(val, list) else 0

    # Check for schema-compliant summary object
    summary = delta_meta.get("summary", {})
    if summary and isinstance(summary, dict):
        # Schema-compliant format with counts
        added_count = summary.get("files_added", 0)
        removed_count = summary.get("files_removed", 0)
        changed_count = summary.get("files_changed", 0)

        lines.append("**Summary:**")
        lines.append(f"- Files added: {added_count}")
        lines.append(f"- Files removed: {removed_count}")
        lines.append(f"- Files changed: {changed_count}")
        lines.append("")

        # Check for detailed lists (optional extension to schema)
        added = delta_meta.get("files_added", [])
        removed = delta_meta.get("files_removed", [])
        changed = delta_meta.get("files_changed", [])
    else:
        # Legacy detailed format with arrays
        added = delta_meta.get("files_added", [])
        removed = delta_meta.get("files_removed", [])
        changed = delta_meta.get("files_changed", [])

        lines.append("**Summary:**")
        lines.append(f"- Files added: {_safe_list_len(added)}")
        lines.append(f"- Files removed: {_safe_list_len(removed)}")
        lines.append(f"- Files changed: {_safe_list_len(changed)}")
        lines.append("")

    # Detail sections (only if we have lists)
    if isinstance(added, list) and added:
        lines.append("### Added Files")
        for f in added[:MAX_DELTA_FILES]:
            lines.append(f"- `{f}`")
        if len(added) > MAX_DELTA_FILES:
            lines.append(f"- _(and {len(added) - MAX_DELTA_FILES} more)_")
        lines.append("")

    if isinstance(removed, list) and removed:
        lines.append("### Removed Files")
        for f in removed[:MAX_DELTA_FILES]:
            lines.append(f"- `{f}`")
        if len(removed) > MAX_DELTA_FILES:
            lines.append(f"- _(and {len(removed) - MAX_DELTA_FILES} more)_")
        lines.append("")

    if isinstance(changed, list) and changed:
        lines.append("### Changed Files")
        for f in changed[:MAX_DELTA_FILES]:
            if isinstance(f, dict):
                path = f.get("path", "unknown")
                size_delta = f.get("size_delta", 0)
                if size_delta > 0:
                    lines.append(f"- `{path}` (+{size_delta} bytes)")
                elif size_delta < 0:
                    lines.append(f"- `{path}` ({size_delta} bytes)")
                else:
                    lines.append(f"- `{path}`")
            else:
                lines.append(f"- `{f}`")
        if len(changed) > MAX_DELTA_FILES:
            lines.append(f"- _(and {len(changed) - MAX_DELTA_FILES} more)_")
        lines.append("")

    lines.append("<!-- @delta:end -->")
    lines.append("")
    return "\n".join(lines)

def check_fleet_consistency(files: List[FileInfo]) -> List[str]:
    """
    Checks for objective inconsistencies specified in the spec.
    """
    warnings = []

    # Check for hausKI casing
    roots = set(f.root_label for f in files)

    # Check for missing .wgx/profile.yml in repos
    for root in roots:
        has_profile = any(f.root_label == root and "wgx-profile" in f.tags for f in files)
        if not has_profile:
             if root in REPO_ORDER:
                 warnings.append(f"- {root}: missing .wgx/profile.yml")

    return warnings


def _render_reading_lenses(files: List[FileInfo], active_lenses: List[str] = None, meta_density: str = "full") -> List[str]:
    """
    Renders the 'Reading Lenses' block.
    Shows recommended subset (focus overlay) per lens.
    """
    if meta_density == "min":
        return []

    limit = 3 if meta_density == "standard" else 8

    if active_lenses is None:
        active_lenses = lenses.LENS_IDS

    lines = []
    lines.append("## Reading Lenses")
    lines.append("")
    lines.append("Active lenses: " + ", ".join(f"`{l}`" for l in active_lenses))
    lines.append("")
    lines.append("### Recommended subset (focus, not exclusion)")
    lines.append("")

    # Simple heuristic for recommended subset:
    # Take top N files per active lens.
    # Criteria: included (full/truncated), prioritized by shortness of path and specific roles.

    # Sort candidates
    def score_candidate(fi: FileInfo):
        # Shorter paths are usually higher level / more important entry points
        score = -len(fi.rel_path.parts)
        if is_priority_file(fi):
            score += 5
        if fi.inclusion_reason == "force_include":
            score += 3
        return score

    displayed_any = False

    for lens_id in active_lenses:
        candidates = [f for f in files if f.lens == lens_id and f.inclusion_reason != "omitted"] # Include meta-only in recommendation? Maybe.
        # Focus mainly on content available files for reading
        candidates = [f for f in candidates if f.anchor]

        if not candidates:
            continue

        # Sort and take top 5-10
        candidates.sort(key=score_candidate, reverse=True)
        top = candidates[:limit]

        lines.append(f"**({lens_id})**")
        for f in top:
            lines.append(f"- [`{f.rel_path}`](#{f.anchor})")
        lines.append("")
        displayed_any = True

    if not displayed_any:
        lines.append("_No specific recommendations found._")
        lines.append("")

    lines.append("> All files are included below. This subset is a focus suggestion, not a filter.")
    lines.append("")
    return lines

def _render_epistemic_status(
    files: List[FileInfo],
    active_lenses: List[str],
    metrics: Dict[str, Any]
) -> List[str]:
    """
    Renders 'Epistemic Status' block.
    Self-report on text contact and risks.
    """
    lines = []
    lines.append("## Epistemic Status")
    lines.append("")

    counts = metrics["counts"]
    ratios = metrics["ratios"]
    risk = metrics["risk"]

    contact_ratio_pct = int(ratios["contact_ratio"] * 100)
    text_coverage_pct = int(ratios["text_coverage_ratio"] * 100)

    lines.append(f"- **Active Lenses:** {', '.join(active_lenses) if active_lenses else 'none'}")

    lines.append("- **Text Contact Breakdown:**")
    lines.append(f"  - full: {counts['full']}")
    lines.append(f"  - snippet: {counts['snippet']}")
    lines.append(f"  - meta: {counts['meta']}")

    lines.append(f"- **Contact Ratio (all files):** {contact_ratio_pct}%")
    lines.append(f"- **Text Coverage (text files):** {text_coverage_pct}%")
    lines.append(f"- **Truncated Files:** {counts['snippet']}")

    lines.append(f"- **Risk Level:** `{risk['level']}`")

    if risk["level"] == "high":
        lines.append("  - ⚠️ **High Risk:** Low text coverage. Relying heavily on metadata/structure.")
    elif risk["level"] == "medium":
         if counts["snippet"] > 0:
             lines.append("  - ⚠️ **Medium Risk:** Truncation occurred. Some files are incomplete.")
         else:
             lines.append("  - ⚠️ **Medium Risk:** Partial text coverage. Some context might be missing.")

    lines.append("")
    return lines


class ValidationException(Exception):
    pass


class ReportValidator:
    """
    Validates report structure incrementally (Stream Validation).
    Enforces Spec v2.4 Invariant Structure (Section 2).
    """

    # Normalized signatures for required sections in order
    REQUIRED_ORDER = [
        "header",               # # repoLens Report ...
        "source_profile",       # ## Source & Profile
        "profile_desc",         # ## Profile Description
        "reading_plan",         # ## Reading Plan
        "plan",                 # ## Plan
        # Extras come here (Health, Delta, etc) -> no strict check except they are between Plan and Structure
        # Structure is optional (machine-lean)
        # Manifest is required
        # Content is required
    ]

    def __init__(self, plan_only: bool = False, code_only: bool = False, machine_lean: bool = False):
        self.plan_only = plan_only
        self.code_only = code_only
        self.machine_lean = machine_lean
        self.state_idx = 0
        self.seen_sections = set()
        self.buffer = ""
        self.in_code_block = False
        self.fence_len = 0

    def feed(self, chunk: str):
        """
        Feed a chunk of the report (e.g. a block from iter_report_blocks).
        Validates headings found in the chunk.
        """
        # We process line by line to reliably catch headings
        self.buffer += chunk
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._check_line(line)

    def close(self):
        """Finalize validation."""
        # Process remaining buffer
        if self.buffer:
            self._check_line(self.buffer)

        # Check if we missed required sections
        # Note: We can't strictly enforce "Content" presence here because of split-parts (last part might just be content)
        # But for single-file generation it matters.
        # However, since this validator is used in write_reports_v2 which might write partial files,
        # strict "completeness" check at the end is tricky for splits.
        # We assume if the stream finished without order violation, it's OK.
        # Real completeness check is done via internal state logic if needed.
        pass

    def _check_line(self, line: str):
        stripped = line.strip()

        # Track code blocks to avoid false positives in file content
        # Spec v2.4 fix: Support variable fence length (CommonMark)
        if stripped.startswith("```"):
            # Determine length of this fence
            match = re.match(r"^(`+)", stripped)
            current_len = len(match.group(1)) if match else 0

            if not self.in_code_block:
                # Opening a block
                self.in_code_block = True
                self.fence_len = current_len
            else:
                # Closing? Only if length >= opening length
                if current_len >= self.fence_len:
                    self.in_code_block = False
                    self.fence_len = 0
                else:
                    # It's a nested fence (shorter), ignore it (treat as content)
                    pass
            return

        if self.in_code_block:
            return

        if not stripped.startswith("#"):
            return

        # Identify section
        lower = stripped.lower()

        # Map headings to logical steps
        current_step = None

        # Helper: only treat *level-2* headings ("## ") as report sections.
        # NOTE: "### ..." starts with "##" as a prefix, so we must exclude it explicitly.
        is_h2 = stripped.startswith("## ") and not stripped.startswith("###")

        if stripped.startswith("# repoLens Report"):
            current_step = "header"
        elif "source & profile" in lower:
            current_step = "source_profile"
        elif "profile description" in lower:
            current_step = "profile_desc"
        elif "reading plan" in lower:
            current_step = "reading_plan"
        elif stripped == "## Plan":
            current_step = "plan"
        elif "structure" in lower and is_h2:
            current_step = "structure"
        elif "manifest" in lower and is_h2:
            # Could be "## 🧾 Manifest"
            current_step = "manifest"
        elif "content" in lower and (stripped.startswith("## ") or stripped.startswith("# ")):
            # Accept "# Content" (legacy/lean) or "## 📄 Content" (spec strict)
            current_step = "content"
        elif is_h2 and "organism" not in lower:
            # Main Index (Patch B)
            #
            # IMPORTANT:
            # The old check used a substring match ("index" in lower), which
            # false-positives on headings like "Navigation-Indexe", "Indexierung",
            # "Indexe", etc. Those can appear inside repo docs and would break
            # the invariant structure ordering.
            #
            # We only treat it as the report's main Index if it strictly matches
            # "## Index" or "## 🧭 Index".
            #
            # Additionally: never treat "### file-...index..." anchors as the main Index.
            # Those are file section headings and may appear after Content has started,
            # especially in multi-repo merges where many repos contain index.* files.
            if re.search(r"^##\s*(?:🧭\s*)?index\s*$", lower):
                current_step = "index"

        if current_step:
            self._enforce_order(current_step)

    def _enforce_order(self, step: str):
        # Define the strict sequence indices
        # We allow gaps (skipping optional sections), but not backtracking.

        sequence = {
            "header": 0,
            "source_profile": 10,
            "profile_desc": 20,
            "reading_plan": 30,
            "plan": 40,
            # Extras range: 41-49
            "structure": 50,
            "index": 55, # Spec v2.4 Section 8: Index before Manifest
            "manifest": 60,
            "content": 70
        }

        # Plan-only stops after Plan (roughly)
        if self.plan_only and sequence.get(step, 0) > 40:
             # Plan-only might have headers? Usually not Structure/Manifest/Content.
             # But if it does (e.g. meta info formatted as header), we might need to be careful.
             # Standard iter_report_blocks breaks early for plan_only.
             pass

        if step not in sequence:
            return

        new_idx = sequence[step]

        # Special case: Structure is optional.
        # Index is optional.

        if new_idx < self.state_idx:
            # Violation!
            raise ValidationException(
                f"Structure Violation: Found section '{step}' (order {new_idx}) "
                f"after reaching order {self.state_idx}. "
                "Invariant Structure (Spec v2.4) violated."
            )

        self.state_idx = new_idx
        self.seen_sections.add(step)

    def validate_full(self, report_content: str):
        """Validate a full string report."""
        self.feed(report_content)
        self.close()

        # For full validation, we can check required presence
        required = ["header", "source_profile", "profile_desc", "reading_plan", "plan"]
        if not self.plan_only:
            required.append("manifest")
            if not self.machine_lean:
                # Structure optional in machine-lean
                pass
                # Note: Manifest and Content are mandatory for full merge
            required.append("content")

        for req in required:
            if req not in self.seen_sections:
                 # Be lenient if plan_only and we check content
                 if self.plan_only and req in ("manifest", "content"):
                     continue
                 raise ValidationException(f"Missing required section: {req}")


def iter_report_blocks(
    files: List[FileInfo],
    level: str,
    max_file_bytes: int,
    sources: List[Path],
    plan_only: bool,
    code_only: bool = False,
    debug: bool = False,
    path_filter: Optional[str] = None,
    ext_filter: Optional[List[str]] = None,
    extras: Optional[ExtrasConfig] = None,
    delta_meta: Optional[Dict[str, Any]] = None,
    artifact_refs: Optional[Dict[str, str]] = None,
    meta_density: str = "auto",
    meta_none: bool = False,
    redact_secrets: bool = False,
) -> Iterator[str]:
    if extras is None:
        extras = ExtrasConfig.none()

    redactor = Redactor() if redact_secrets else None

    # --- hard safety defaults (prevents UnboundLocalError even under refactors) ---
    content_present = False
    manifest_present = False
    structure_present = False

    if debug:
        print("[lenskit] merge.py loaded from:", __file__)

    # Resolve Effective Meta Density (Consistency Fix)
    requested_meta_density = meta_density
    effective_meta_density = _resolve_effective_meta_density(
        meta_density, path_filter, ext_filter, meta_none
    )

    # Navigation style: default should be quiet.
    # You can later expose this as a UI toggle if desired.
    nav = NavStyle(emit_search_markers=False)

    # UTC Timestamp - ensure strict UTC for Z-suffix validity
    now = clock.now_utc()

    # Strict Path Filtering (Hard Include)
    # Move before sort for performance (minor optimization)
    if path_filter:
        # User explicitly requested a filter path.
        # This acts as a hard filter for manifest and content, overriding force_include logic from scan_repo.
        files = [f for f in files if path_filter in f.rel_path.as_posix()]

    # Sort files according to strict multi-repo order and then path
    files.sort(key=lambda fi: (get_repo_sort_index(fi.root_label), fi.root_label.lower(), str(fi.rel_path).lower()))

    # Optional Code-only-Filter
    if code_only:
        files = [fi for fi in files if fi.category in DEBUG_CONFIG.code_only_categories]

    # Pre-calculate status based on Profile Strict Logic
    processed_files = []

    unknown_categories = set()
    unknown_tags = set()
    roots = set(f.root_label for f in files)

    for fi in files:
        # Generate deterministic anchor based on slugified repo + path, with collision-safe suffix
        rel_id = _slug_token(fi.rel_path.as_posix())
        repo_slug = _slug_token(fi.root_label)
        base_anchor = f"file-{repo_slug}-{rel_id}"
        suffix = (fi.md5 or "")[:6] if getattr(fi, "md5", None) else ""
        fi.anchor_alias = base_anchor
        fi.anchor = f"{base_anchor}-{suffix}" if suffix else base_anchor

        # Compute file roles if not already present
        if fi.roles is None:
            fi.roles = compute_file_roles(fi)

        # Debug checks
        # Kategorien strikt gemäß Spec v2.4 (via DebugConfig).
        # "other" ist gültig, aber signalisiert: nicht eindeutig klassifizierbar.
        if debug and fi.category not in DEBUG_CONFIG.allowed_categories:
            unknown_categories.add(fi.category)
        # If you want "other" as a warning signal, do it explicitly elsewhere (e.g. health metrics).

        # Check tags against the configured allow-list
        if debug:
            for tag in (fi.tags or []):
                if tag not in DEBUG_CONFIG.allowed_tags:
                    unknown_tags.add(tag)

        status = determine_inclusion_status(fi, level, max_file_bytes)

        # Explicitly removed: automatic downgrade from "full" to "truncated"
        # if status == "full" and fi.size > max_file_bytes:
        #    status = "truncated"

        processed_files.append((fi, status))

    if debug:
        print("DEBUG: total files:", len(files))
        print("DEBUG: unknown categories:", unknown_categories)
        print("DEBUG: unknown tags:", unknown_tags)
        print("DEBUG: files without anchors:", [fi.rel_path for fi in files if not hasattr(fi, "anchor")])

    total_size = sum(fi.size for fi in files)
    text_files = [fi for fi in files if fi.is_text]
    included_count = sum(1 for _, s in processed_files if s in ("full", "truncated"))

    # Calculate Epistemic Metrics (SR-Fix-5, 6, 7)
    # Single Source of Truth
    ep_metrics = compute_epistemic_metrics(files, processed_files)

    # pro-Repo-Statistik für "mit Inhalt" (full/truncated),
    # um später im Plan pro Repo eine Coverage-Zeile auszugeben
    included_by_root: Dict[str, int] = {}

    # Declared Purpose (Spec v2.4): based on Profile (level)
    declared_purpose = PROFILE_USECASE.get(level, "(none)")

    # Repository Purpose (extracted from README/docs)
    repo_purpose = ""
    try:
        if sources:
            repo_purpose = extract_purpose(sources[0])
    except Exception as e:
        sys.stderr.write(f"Warning: extract_purpose failed: {e}\n")

    if not repo_purpose:
        repo_purpose = "(none)"

    infra_folders = set()
    code_folders = set()
    doc_folders = set()

    # Organismus-Rollen (ohne neue Tags/Kategorien):
    organism_ai_ctx: List[FileInfo] = []
    organism_contracts: List[FileInfo] = []
    organism_pipelines: List[FileInfo] = []
    organism_wgx_profiles: List[FileInfo] = []

    for fi in files:
        parts = fi.rel_path.parts
        if ".github" in parts or ".wgx" in parts or "contracts" in parts:
            infra_folders.add(parts[0])
        if "src" in parts or "scripts" in parts:
            code_folders.add(parts[0])
        if "docs" in parts:
            doc_folders.add("docs")

        # Organismus-Rollen:
        if fi.category == "contract":
            organism_contracts.append(fi)
        if "ai-context" in (fi.tags or []):
            organism_ai_ctx.append(fi)
        if "ci" in (fi.tags or []):
            organism_pipelines.append(fi)
        if "wgx-profile" in (fi.tags or []):
            organism_wgx_profiles.append(fi)

    # Mini-Summary pro Repo – damit KIs schnell die Lastverteilung sehen
    # Re-calculate or re-use existing categorization?
    # We need files_by_root NOW for Health Check, before Header.
    # It was originally calculated later (at Plan block).
    # So we move the calculation here.
    files_by_root: Dict[str, List[FileInfo]] = {}
    for fi in files:
        files_by_root.setdefault(fi.root_label, []).append(fi)

    # jetzt, nachdem processed_files existiert, die Coverage pro Root berechnen
    for fi, status in processed_files:
        if status in ("full", "truncated"):
            included_by_root[fi.root_label] = included_by_root.get(fi.root_label, 0) + 1

    repo_stats: Dict[str, Dict[str, Any]] = {}
    for root, root_files in files_by_root.items():
        repo_stats[root] = summarize_repo(root_files, included_by_root.get(root, 0))

    # Pre-Calculation for Health (needed for Meta Block)
    health_collector = None
    if extras.health:
        # Pass hub path if available (via sources)
        # sources list typically contains the repo roots.
        # But HealthCollector is initialized once for the merge.
        # If this is a multi-repo merge, sources are diverse.
        # Best effort: try to derive hub from first source.
        derived_hub = None
        if sources:
            derived_hub = sources[0].parent

        health_collector = HealthCollector(hub_path=derived_hub)
        # Analyze each repo
        for root in sorted(files_by_root.keys()):
            root_files = files_by_root[root]
            health_collector.analyze_repo(root, root_files)

    # --- 1. Header ---
    header = []
    # Machine-readable reading policy sentinel
    header.append('<!-- READING_POLICY canonical="merge_md" navigation="dump_index,chunk_index,sidecar_json" -->')
    header.append(READING_POLICY_BANNER)
    header.append(f"# repoLens Report (v{SPEC_VERSION.split('.')[0]}.x)")
    header.append("")

    # --- Canonical Note (Epistemic Protection) ---
    header.append("> **Kanonischer Hinweis**")
    header.append(">")
    header.append("> Dieses Markdown-Dokument ist die vollständige und verbindliche Darstellung des repoLens-Merges.")
    header.append("> Alle Inhalte, Strukturen, Dateien und Kontexte sind hier vollständig enthalten.")
    header.append(">")
    header.append("> Begleitende JSON-Dateien dienen ausschließlich der maschinellen Navigation,")
    header.append("> Filterung und Metainformation.")
    header.append("> **Kein inhaltlich relevanter Aspekt ist ausschließlich im JSON enthalten.**")
    header.append("")

    # --- Contract roles (agent-first clarity) ---
    # Human-readable report contract (this Markdown)
    header.append("**Human Contract:** `repolens-report` (v2.4)")
    # Machine-readable primary contract (the JSON primary artifact)
    header.append(f"**Primary Contract (Agent):** `{AGENT_CONTRACT_NAME}` ({AGENT_CONTRACT_VERSION}) — siehe `artifacts.index_json`")
    header.append("")

    render_mode = _effective_render_mode(plan_only, code_only, meta_none)

    if meta_none:
        header.append("**Meta-Mode:** `none` (Interpretation disabled)")
        header.append("")
    elif effective_meta_density != "full":
        header.append(f"**Meta-Density:** `{effective_meta_density}` (Reduzierter Overhead)")
        if requested_meta_density == "auto" and effective_meta_density == "standard":
            header.append("⚠️ **Auto-Drosselung:** Wegen aktiver Filter wurde der Meta-Overhead reduziert.")
        header.append("")

    if render_mode == "meta-only":
        header.append("**META-ONLY Modus:** Dieser Merge enthält ausschließlich Meta-, Struktur-, Index- und Analyse-Informationen.")
        header.append("**Kein Code, keine Planinhalte. Gedacht als Entscheidungs- und Steuerungsartefakt für Agenten.**")
        header.append("")
    else:
        if code_only:
            header.append("**Profil: CODE-ONLY – dieser Merge enthält bewusst nur Source-Code, Tests, technische Configs und Contracts.**")
            header.append("**Keine Beschreibungs-Dokus; nutze Manifest, Roles und Hotspots als Einstiegspunkte.**")
            header.append("")
        if plan_only:
            header.append("**Profil: PLAN-ONLY – dieser Merge enthält nur Plan-/Doku-/Struktur-Kontext (kein Code, keine Tests).**")
            header.append("**Nutze ihn als Token-sparenden Vorab-Scan; fehlender Code ist Absicht (Modus), nicht „vergessen“.**")
            header.append("")

    # --- 2. Source & Profile ---
    header.append("## Source & Profile")
    source_names = sorted([s.name for s in sources])
    header.append(f"- **Source:** {', '.join(source_names)}")
    header.append(f"- **Profile:** `{level}`")
    header.append(f"- **Generated At:** {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC)")
    if max_file_bytes and max_file_bytes > 0:
        header.append(f"- **Max File Bytes:** {human_size(max_file_bytes)}")
    else:
        # 0 / None = kein per-File-Limit – alles wird vollständig gelesen
        header.append("- **Max File Bytes:** unlimited")
    header.append(f"- **Spec-Version:** {SPEC_VERSION}")
    header.append(f"- **Contract:** {MERGE_CONTRACT_NAME}")
    header.append(f"- **Contract-Version:** {MERGE_CONTRACT_VERSION}")
    header.append(f"- **Plan Only:** {str(bool(plan_only)).lower()}")
    header.append(f"- **Code Only:** {str(bool(code_only)).lower()}")
    header.append(f"- **Render Mode:** `{render_mode}`")

    # Artifacts section (Recommendation 1: Portable Links)
    if artifact_refs:
        header.append("## 📦 Artifacts")
        if artifact_refs.get("index_json_basename"):
            bn = artifact_refs['index_json_basename']
            header.append(f"<!-- artifact:index_json basename=\"{bn}\" -->")
            header.append(f"- Index JSON: [{bn}]({bn})")
        if artifact_refs.get("augment_sidecar_basename"):
            bn = artifact_refs['augment_sidecar_basename']
            header.append(f"<!-- artifact:augment_sidecar basename=\"{bn}\" -->")
            header.append(f"- Augment Sidecar: [{bn}]({bn})")
        header.append("")

    # One-time navigation note (no per-file chatter).
    header.append("### Navigation")
    header.append("- **Index:** [#index](#index) · **Manifest:** [#manifest](#manifest)")
    header.append("- Wenn dein Viewer nicht springt: nutze die Suche nach `manifest`, `index` oder `file-...`.")
    header.append("")

    # Requirement 2: Profile Capability Warning (Epistemic Humility)
    # Profiles other than max/full/dev cannot prove absence.
    # Also if any filters are active.
    # Note: 'full' is not a standard profile key in repoLens (overview, summary, dev, max, machine-lean).
    # 'max' is the full profile.
    allows_negative_claims = (level in ("max",)) and not path_filter and not ext_filter

    if not allows_negative_claims:
        header.append(EPISTEMIC_HUMILITY_WARNING)
        header.append("")

    header.append(f"- **Declared Purpose:** {declared_purpose}")
    if repo_purpose and repo_purpose != "(none)":
        header.append(f"- **Repo Purpose:** {repo_purpose}")

    # Scope-Zeile: welche Roots/Repos sind beteiligt?
    scope_desc = describe_scope(files)
    header.append(f"- **Scope:** {scope_desc}")

    # Neue, explizite Filterangaben
    if path_filter:
        header.append(f"- **Path Filter:** `{path_filter}`")
    else:
        header.append("- **Path Filter:** `none (full tree)`")

    if ext_filter:
        header.append(
            "- **Extension Filter:** "
            + ", ".join(f"`{e}`" for e in sorted(ext_filter))
        )
    else:
        header.append("- **Extension Filter:** `none (all text types)`")

    # Coverage in header (for quick AI assessment)
    if text_files:
        # Spec v2.4: Coverage line
        header.append(f"- **Coverage:** {included_count}/{len(text_files)} Dateien mit vollem Inhalt")

    header.append("")

    # --- 3. Machine-readable Meta Block (für KIs) ---
    # Wir bauen das Meta-Objekt sauber als Dict auf und dumpen es dann als YAML
    # Spec v2.4 requirement: @meta is mandatory in all modes, including plan-only.
    meta_lines: List[str] = []
    # Wrap in zone marker
    meta_lines.append("<!-- zone:begin type=\"meta\" id=\"meta\" -->")
    meta_lines.append("<!-- @meta:start -->")
    meta_lines.append("```yaml")

    # Coverage-Infos für KIs: Wie viel des relevanten Textbestands ist wirklich als Voll-Content drin?
    total_files = len(files)

    # Flags for machine readability of content presence
    # Plan-Only means NO content, NO manifest (usually), NO structure.
    # Check actual logic below: plan_only causes early return before structure/manifest/content.
    content_present = not plan_only
    # Manifest is present unless plan_only (logic: if plan_only: return)
    manifest_present = not plan_only
    # Structure is present unless plan_only OR machine_lean
    structure_present = (not plan_only) and (level != "machine-lean")

    text_files_count = len(text_files)
    if text_files_count:
        coverage_raw = (included_count / text_files_count) * 100.0
        coverage_pct = round(coverage_raw, 1)
    else:
        coverage_pct = 0.0

    if debug:
        print("[lenskit] meta flags:", plan_only, level, content_present, manifest_present, structure_present)

    # Determine if roles are actually present/computed
    # Security fix (PR12): Ensure roles are computed before consulting them for meta
    for fi in files:
        if fi.roles is None:
            fi.roles = compute_file_roles(fi)
    has_roles = any(fi.roles for fi in files)

    meta_dict: Dict[str, Any] = {
        "merge": {
            "spec_version": SPEC_VERSION,
            "profile": level,
            "contract": MERGE_CONTRACT_NAME,
            "contract_version": MERGE_CONTRACT_VERSION,
            # Only declare semantics if roles are present (Empfehlung A)
            **({"role_semantics": "heuristic"} if has_roles else {}),
            # Declare Depends as placeholder (Empfehlung B)
            "depends_semantics": "placeholder",
            "plan_only": plan_only,
            "code_only": code_only,
            "render_mode": render_mode,
            **({"mode": "none", "warning": "interpretation_disabled"} if meta_none else {}),
            "max_file_bytes": max_file_bytes,
            "scope": scope_desc,
            "source_repos": sorted([s.name for s in sources]) if sources else [],
            "path_filter": path_filter,  # Use actual value, not description
            "ext_filter": sorted(ext_filter) if ext_filter else None,  # Use actual value, not description
            "meta_density": effective_meta_density,
            "requested_meta_density": requested_meta_density,
            "generated_at": now.strftime('%Y-%m-%dT%H:%M:%SZ'),  # ISO-8601 timestamp
            "total_files": total_files,        # Total number of files in the merge
            "total_size_bytes": total_size,    # Sum of all file sizes
            "content_present": content_present,
            "manifest_present": manifest_present,
            "structure_present": structure_present,
            "coverage": {
                "included_files": included_count,
                "text_files": text_files_count,
                "coverage_pct": coverage_pct,
            },
        }
    }

    # Extras-Flags
    if extras:
        extras_meta = _build_extras_meta(extras, len(roots))
        if extras_meta:
            meta_dict["merge"]["extras"] = extras_meta

    # Health-Status
    if extras and extras.health and health_collector:
        # Determine overall status from collector results
        all_health = health_collector.get_all_health()
        if any(h.status == "critical" for h in all_health):
            overall = "critical"
        elif any(h.status == "warn" for h in all_health):
            overall = "warning"
        else:
            overall = "ok"

        missing_set = set()
        for h in all_health:
            # Naive mapping logic for 'missing' based on recommendations/warnings
            if not h.has_contracts: missing_set.add("contracts")
            if not h.has_ci_workflows: missing_set.add("ci")
            if not h.has_wgx_profile: missing_set.add("wgx-profile")

        meta_dict["merge"]["health"] = {
            "status": overall,
            "missing": sorted(list(missing_set)),
        }

    # --- Delta Meta (NEW fully correct block) ---
    if extras and extras.delta_reports:
        if delta_meta:
            # Use the real delta metadata if provided
            meta_dict["merge"]["delta"] = delta_meta
        else:
            # Minimal enabling marker
            meta_dict["merge"]["delta"] = {
                "enabled": True
            }

    # Augment-Metadaten
    if extras and extras.augment_sidecar:
        augment_meta = _build_augment_meta(sources)
        if augment_meta:
            meta_dict["merge"]["augment"] = augment_meta

    # Dump to YAML (ohne sort_keys, damit auch ältere PyYAML-Versionen in Pythonista funktionieren)
    if yaml:
        meta_yaml = yaml.safe_dump(meta_dict)
        for line in meta_yaml.rstrip("\n").splitlines():
            meta_lines.append(line)
    else:
        meta_lines.append("# YAML support missing")

    meta_lines.append("```")
    meta_lines.append("<!-- @meta:end -->")
    meta_lines.append("<!-- zone:end type=\"meta\" id=\"meta\" -->")
    meta_lines.append("")
    header.extend(meta_lines)

    # --- 3.1 Epistemic Charter & Declaration (T-Charter-1 + ED-1) ---
    # Moved after Meta block as requested.
    # Spec v2.4 requirement: Charter is mandatory in all modes, including plan-only.
    # User requested condensed version in report header.
    # Full charter is available in assets/epistemic_reading_charter.md

    # META: NONE GUARD
    if not meta_none:
        header.append(_CHARTER_FALLBACK)
        header.append("")

        # Epistemic Declaration
        # Use computed metrics
        _risk_level = ep_metrics["risk"]["level"]
        _contact_ratio_pct = int(ep_metrics["ratios"]["contact_ratio"] * 100)

        decl = []
        decl.append("## Epistemic Declaration")
        decl.append("")
        decl.append("- **Charter:** epistemic_reading_charter v1")
        decl.append("- **Claim Language Guard:** active")
        decl.append(f"- **Risk Level:** {_risk_level}")
        decl.append(f"- **Contact Ratio:** {_contact_ratio_pct}%")
        decl.append("")
        header.extend(decl)

    # --- 3a. Reading Lenses & Epistemic Status (New in v2.4) ---
    if not plan_only and not meta_none:
        active_lenses = lenses.LENS_IDS # Default to all canonical

        # Reading Lenses
        # Pass meta_density for budgeting
        header.extend(_render_reading_lenses(files, active_lenses, meta_density=effective_meta_density))

        # Epistemic Status
        header.extend(_render_epistemic_status(files, active_lenses, ep_metrics))

    # --- 4. Profile Description ---
    header.append("## Profile Description")
    if level == "overview":
        header.append("`overview`")
        header.append("- Nur: README (voll), Runbook (voll), ai-context (voll)")
        header.append("- Andere Dateien: Included = meta-only")
    elif level == "summary":
        header.append("`summary`")
        header.append("- Voll: README, Runbooks, ai-context, docs/, .wgx/, .github/workflows/, zentrale Config, Contracts")
        header.append("- Code & Tests: Manifest + Struktur; nur Prioritätsdateien (README, Runbooks, ai-context) voll")
    elif level == "dev":
        header.append("`dev`")
        header.append("- Code, Tests, Config, CI, Contracts, ai-context, wgx-profile → voll")
        header.append("- Doku nur für Prioritätsdateien voll (README, Runbooks, ai-context), sonst Manifest")
        header.append("- Lockfiles / Artefakte: ab bestimmter Größe meta-only")
    elif level == "machine-lean":
        header.append("`machine-lean`")
        header.append("- Lean Snapshot: volle Inhalte, reduzierter Baum/Decorations")
        header.append("- Manifest + Index + Content für Maschinen-Parsing optimiert")
    elif level == "max":
        header.append("`max`")
        header.append("- alle Textdateien → voll")
        header.append("- keine Kürzung (Dateien werden ggf. gesplittet)")
    else:
        header.append(f"`{level}` (custom)")
    header.append("")

    # --- 4. Reading Plan ---
    header.append("## Reading Plan")
    header.append("")
    if plan_only:
        # Plan-Only: explizit machen, dass nur Plan & Meta im Merge sind.
        header.append("1. Hinweis: Dieser Merge wurde im **PLAN-ONLY** Modus erzeugt.")
        header.append("   - Enthält nur: Profilbeschreibung, Plan und Meta (`@meta`).")
        header.append("   - Enthält **nicht**: `Structure`, `Manifest` oder `Content`-Blöcke.")
        header.append("")
        header.append("2. Nutze diesen Merge, um schnell zu entscheiden, ob sich ein Voll-Merge lohnt,")
        header.append("   ohne Tokens für Dateiinhalte zu verbrauchen.")
    else:
        # Standard-Lesepfad für Voll-Merges
        header.append("1. Lies zuerst: `README.md`, `docs/runbook*.md`, `*.ai-context.yml`")
        if level == "machine-lean":
            header.append("2. Danach: `Manifest` -> `Content`")
        else:
            header.append("2. Danach: `Structure` -> `Manifest` -> `Content`")
        header.append("3. Hinweis: „Multi-Repo-Merges: jeder Repo hat eigenen Block 📦“")
    header.append("")

    yield "\n".join(header) + "\n"

    # --- 5. Plan ---
    plan: List[str] = []
    plan.append("## Plan")
    plan.append("")
    plan.append(f"- **Total Files:** {len(files)} (Text: {len(text_files)})")
    plan.append(f"- **Total Size:** {human_size(total_size)}")
    plan.append(f"- **Included Content:** {included_count} files (full)")
    if text_files:
        plan.append(
            f"- **Coverage:** {included_count}/{len(text_files)} Dateien mit vollem Inhalt"
        )
    plan.append("")

    # Optional Delta Summary (if delta_meta is provided with summary)
    if extras.delta_reports and delta_meta and isinstance(delta_meta, dict):
        summary = delta_meta.get("summary", {})
        if isinstance(summary, dict):
            plan.append("### Delta Summary")
            plan.append("")
            files_added = summary.get("files_added", 0)
            files_removed = summary.get("files_removed", 0)
            files_changed = summary.get("files_changed", 0)
            plan.append(f"- Files added: {files_added}")
            plan.append(f"- Files removed: {files_removed}")
            plan.append(f"- Files changed: {files_changed}")
            plan.append("")

    # Mini-Summary pro Repo – damit KIs schnell die Lastverteilung sehen
    # files_by_root was calculated earlier for Health Check

    if files_by_root:
        plan.append("### Repo Snapshots")
        plan.append("")
        for root in sorted(files_by_root.keys()):
            root_files = files_by_root[root]
            root_total = len(root_files)
            # „relevante Textdateien“: Code, Docs, Config, Tests, CI, Contracts
            root_text = sum(
                1
                for f in root_files
                if f.is_text
                and f.category in {"source", "doc", "config", "test", "contract"}
            )
            root_bytes = sum(f.size for f in root_files)
            root_included = included_by_root.get(root, 0)
            plan.append(
                f"- `{root}` → {root_total} files "
                f"({root_text} relevant text, {human_size(root_bytes)}, {root_included} with content)"
            )
        plan.append("")

    # Meta-Throttling for Hotspots (Spec 3e)
    # hotspots_limit: min/none=0, standard=3, full=8
    hotspots_limit = 0
    if effective_meta_density == "standard":
        hotspots_limit = 3
    elif effective_meta_density == "full":
        hotspots_limit = 8

    if hotspots_limit > 0:
        hotspots = build_hotspots(processed_files, limit=hotspots_limit)
        if hotspots:
            plan.extend(hotspots)
            plan.append("")
    plan.append("**Folder Highlights:**")
    if code_folders: plan.append(f"- Code: `{', '.join(sorted(code_folders))}`")
    if doc_folders: plan.append(f"- Docs: `{', '.join(sorted(doc_folders))}`")
    if infra_folders: plan.append(f"- Infra: `{', '.join(sorted(infra_folders))}`")
    plan.append("")

    # Organismus-Overview (im Plan, ohne Spec-Reihenfolge zu brechen)
    plan.append("### Organism Overview")
    plan.append("")
    plan.append(
        f"- AI-Kontext-Organe: {len(organism_ai_ctx)} Datei(en) (`ai-context`)"
    )
    plan.append(
        f"- Contracts: {len(organism_contracts)} Datei(en) (category = `contract`)"
    )
    plan.append(
        f"- Pipelines (CI/CD): {len(organism_pipelines)} Datei(en) (Tag `ci`)"
    )
    plan.append(
        f"- Fleet-/WGX-Profile: {len(organism_wgx_profiles)} Datei(en) (Tag `wgx-profile`)"
    )
    plan.append("")

    yield "\n".join(plan) + "\n"

    # --- Health Report (Stage 1: Repo Doctor) ---
    # Note: health_collector was already populated before header generation
    if extras.health and health_collector:
        health_report = health_collector.render_markdown()
        if health_report:
            yield health_report

    # --- Delta Report Block (NEW) ---
    if extras.delta_reports and delta_meta:
        try:
            delta_block = _render_delta_block(delta_meta)
            if delta_block:
                yield delta_block
        except Exception as e:
            yield f"\n<!-- delta-error: {e} -->\n"

    # --- Fleet Panorama (Stage 2 Multi-Repo) ---
    if extras.fleet_panorama:
        fleet_block = _render_fleet_panorama(sources, files)
        if fleet_block:
            yield fleet_block

    # --- Organism Index (Stage 2: Single Repo) ---
    if extras.organism_index and len(roots) == 1:
        # Single-Repo-Organismus: Rolle + Organe explizit sichtbar machen
        repo_name = list(roots)[0]
        repo_role = infer_repo_role(repo_name, files)

        organism_index: List[str] = []
        organism_index.append("<!-- @organism-index:start -->")
        organism_index.append("## 🧬 Organism Index")
        organism_index.append("")
        organism_index.append(f"**Repo:** `{repo_name}`")
        organism_index.append(f"**Rolle:** {repo_role}")
        organism_index.append("")
        organism_index.append("**Organ-Status:**")
        organism_index.append(f"- AI-Kontext: {len(organism_ai_ctx)} Datei(en)")
        organism_index.append(f"- Verträge (Contracts): {len(organism_contracts)} Datei(en)")
        organism_index.append(f"- Pipelines (CI/CD): {len(organism_pipelines)} Workflow(s)")
        organism_index.append(f"- WGX / Fleet-Profile: {len(organism_wgx_profiles)} Profil(e)")
        organism_index.append("")

        # Detaillierte Abschnitte mit Fallbacks

        # AI-Kontext
        if organism_ai_ctx:
            organism_index.append("### AI-Kontext")
            for fi in organism_ai_ctx:
                organism_index.append(f"- `{fi.rel_path}`")
            organism_index.append("")
        else:
            organism_index.append("### AI-Kontext")
            organism_index.append("_Keine AI-Kontext-Dateien gefunden._")
            organism_index.append("")

        # Verträge / Contracts
        if organism_contracts:
            organism_index.append("### Verträge (Contracts)")
            for fi in organism_contracts:
                organism_index.append(f"- `{fi.rel_path}`")
            organism_index.append("")
        else:
            organism_index.append("### Verträge (Contracts)")
            organism_index.append("_Keine Contract-Dateien gefunden._")
            organism_index.append("")

        # Pipelines / CI
        if organism_pipelines:
            organism_index.append("### Pipelines (CI/CD)")
            for fi in organism_pipelines:
                organism_index.append(f"- `{fi.rel_path}`")
            organism_index.append("")
        else:
            organism_index.append("### Pipelines (CI/CD)")
            organism_index.append("_Keine CI/CD-Workflows gefunden._")
            organism_index.append("")

        # WGX / Fleet-Profile
        if organism_wgx_profiles:
            organism_index.append("### WGX / Fleet-Profile")
            for fi in organism_wgx_profiles:
                organism_index.append(f"- `{fi.rel_path}`")
            organism_index.append("")
        else:
            organism_index.append("### WGX / Fleet-Profile")
            organism_index.append("_Kein WGX-/Fleet-Profil gefunden._")
            organism_index.append("")

        organism_index.append("<!-- @organism-index:end -->")
        organism_index.append("")
        yield "\n".join(organism_index)

    # --- AI Heatmap (Stage 3: Auto-Discovery) ---
    if extras.heatmap:
        heatmap_collector = HeatmapCollector(files)
        hm_report = heatmap_collector.render_markdown()
        if hm_report:
            yield hm_report

    # --- Augment Intelligence (Stage 4: Sidecar) ---
    if extras.augment_sidecar:
        augment_block = _render_augment_block(sources, meta_density=effective_meta_density)
        if augment_block:
            yield augment_block

    if plan_only:
        return

    # --- 6. Structure --- (skipped for machine-lean)
    if level != "machine-lean":
        structure = []
        structure.append("<!-- zone:begin type=\"structure\" id=\"structure\" -->")
        structure.append("## 📁 Structure")
        structure.append("")
        structure.append(build_tree(files))
        structure.append("")
        structure.append("<!-- zone:end type=\"structure\" id=\"structure\" -->")
        yield "\n".join(structure) + "\n"

    # --- Index (Patch B) ---
    # Generated Categories Index - Only show non-empty categories/tags
    index_blocks = []
    index_blocks.append("<!-- zone:begin type=\"index\" id=\"index\" -->")
    index_blocks.extend(_heading_block(2, "index", "🧭 Index", nav=nav))

    if effective_meta_density == "min":
        index_blocks.append("_Index reduced (meta=min)_")
        index_blocks.append("")
    else:
        # Pre-check which categories/tags have files
        cats_to_idx = ["source", "doc", "config", "contract", "test"]
        non_empty_cats = []
        for c in cats_to_idx:
            cat_files = [f for f in files if f.category == c]
            if cat_files:
                non_empty_cats.append(c)

        # Check tag presence
        ci_files = [f for f in files if "ci" in (f.tags or [])]
        wgx_files = [f for f in files if "wgx-profile" in f.tags]

        # Build TOC - only for non-empty sections
        for c in non_empty_cats:
            index_blocks.append(f"- [{c.capitalize()}](#cat-{_slug_token(c)})")

        # Add tag TOC entries only if they have files
        if ci_files:
            index_blocks.append("- [CI Pipelines](#tag-ci)")
        if wgx_files:
            index_blocks.append("- [WGX Profiles](#tag-wgx-profile)")

        index_blocks.append("")

        # Category Lists - only non-empty
        for c in non_empty_cats:
            cat_files = [f for f in files if f.category == c]
            index_blocks.extend(_heading_block(2, f"cat-{_slug_token(c)}", f"Category: {c}", nav=nav))
            for f in cat_files:
                index_blocks.append(f"- [`{f.rel_path}`](#{f.anchor})")
            index_blocks.append("")

        # Tag Lists – only non-empty
        if ci_files:
            index_blocks.extend(_heading_block(2, "tag-ci", "Tag: ci", nav=nav))
            for f in ci_files:
                index_blocks.append(f"- [`{f.rel_path}`](#{f.anchor})")
            index_blocks.append("")

        if wgx_files:
            index_blocks.extend(_heading_block(2, "tag-wgx-profile", "Tag: wgx-profile", nav=nav))
            for f in wgx_files:
                index_blocks.append(f"- [`{f.rel_path}`](#{f.anchor})")
            index_blocks.append("")

    index_blocks.append("<!-- zone:end type=\"index\" id=\"index\" -->")
    yield "\n".join(index_blocks) + "\n"

    # --- 7. Manifest (Patch A) ---
    manifest: List[str] = []
    manifest.append("<!-- zone:begin type=\"manifest\" id=\"manifest\" -->")
    manifest.extend(_heading_block(2, "manifest", "🧾 Manifest" if not code_only else "🧾 Manifest (Code-Only)", nav=nav))

    roots_sorted = sorted(files_by_root.keys())
    if roots_sorted:
        manifest_nav = " · ".join(
            f"[{r}](#manifest-{_slug_token(r)})" for r in roots_sorted
        )
        manifest.append(f"**Repos im Merge:** {manifest_nav}")
        manifest.append("")

    if code_only:
        manifest.append(
            "_Profil: CODE-ONLY – nur Source/Tests/Config/Contracts. Rollen-Shortcut: "
            "`entrypoint`=CLIs/Starts, `config`=zentral, `ci`=Workflows, `test`=Tests._"
        )
        manifest.append("")

    if not roots_sorted:
        manifest.append("_Keine Dateien im Manifest._")
        manifest.append("")
        yield "\n".join(manifest) + "\n"
    else:
        for root in roots_sorted:
            root_files = files_by_root[root]
            stats = repo_stats.get(root, {})
            repo_role = infer_repo_role(root, root_files)

            manifest.extend(_heading_block(3, f"manifest-{_slug_token(root)}", f"Repo `{root}`", nav=nav))
            manifest.append(
                f"- Rolle: {repo_role}"
            )
            if stats:
                manifest.append(
                    f"- Umfang: {stats.get('total', 0)} Dateien "
                    f"({stats.get('text_files', 0)} Text), {human_size(stats.get('bytes', 0))}; "
                    f"Inhalt: {stats.get('included', 0)} mit Content"
                )
            manifest.append("")
            # Updated to include 'Role' column (Recommendation 5) and 'Depends'
            manifest.append("| Path | Category | Tags | Role? | Depends? | Size | Included | MD5 |")
            manifest.append("| --- | --- | --- | --- | --- | ---: | --- | --- |")

            for fi, status in processed_files:
                if fi.root_label != root:
                    continue

                tags_str = ", ".join(fi.tags) if fi.tags else "-"
                # Use joined roles or '-' for the new column
                roles_str = ", ".join(fi.roles) if fi.roles else "-"
                included_label = status
                if is_noise_file(fi):
                    included_label = f"{status} (noise)"

                # Use stable ID anchor for Manifest links
                stable_anchor = _stable_file_id(fi).replace("FILE:", "file-")
                path_str = f"[`{fi.rel_path}`](#{stable_anchor})"
                manifest.append(
                    f"| {path_str} | `{fi.category}` | {tags_str} | {roles_str} | - | "
                    f"{human_size(fi.size)} | `{included_label}` | `{fi.md5}` |"
                )
            manifest.append("")

        manifest.append("<!-- zone:end type=\"manifest\" id=\"manifest\" -->")
        yield "\n".join(manifest) + "\n"

    # --- Optional: Fleet Consistency ---
    consistency_warnings = check_fleet_consistency(files)
    if consistency_warnings:
        cons = []
        cons.append("## Fleet Consistency")
        cons.append("")
        for w in consistency_warnings:
            cons.append(w)
        cons.append("")
        yield "\n".join(cons) + "\n"

    # --- 8. Content ---
    # Spec v2.4 Section 2: "7. 📄 Content" implies ## level to match invariants.
    # However, legacy "Lean hierarchy" used # Content.
    # We adopt ## 📄 Content for strict compliance and shift sub-levels.

    # Fix: Agent noise reduction (v2.4 Patch D)
    # Insert strict start-of-content marker before the content header.
    # Logic note: This block is reached only if plan_only is False (checked above).
    # Thus, the marker correctly signals the start of the content section when it exists.
    yield "<!-- START_OF_CONTENT -->\n"

    content_header: List[str] = ["## 📄 Content", ""]
    # Only list repos that actually have visible content blocks (full/truncated).
    # meta-only/omitted files don't generate file blocks, so their repo header might be skipped if *all* files are skipped.
    # We check if a repo has at least one file with status "full" or "truncated".

    # Pre-calculate repos with actual content
    visible_roots = set()
    for fi, status in processed_files:
        if status in ("full", "truncated"):
            visible_roots.add(fi.root_label)

    if visible_roots:
        nav_links = " · ".join(
            f"[{root}](#repo-{_slug_token(root)})" for root in sorted(visible_roots)
        )
        content_header.append(f"**Repos im Merge:** {nav_links}")
        content_header.append("")

    yield "\n".join(content_header)

    current_root = None

    for fi, status in processed_files:
        if status in ("omitted", "meta-only"):
            continue

        if fi.root_label != current_root:
            repo_slug = _slug_token(fi.root_label)
            # Level 3 for Repos (was 2)
            yield "\n".join(_heading_block(3, f"repo-{repo_slug}", fi.root_label, nav=nav)) + "\n"
            current_root = fi.root_label

        # Read content early to get byte count for marker
        content, truncated, trunc_msg = read_smart_content(fi, max_file_bytes)
        if redactor:
            content, _ = redactor.redact(content)

        # Calculate SHA256 of content for marker
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        content_bytes = len(content.encode("utf-8"))

        block = ["---"]

        # 1. Stable File Marker (with path) - PR1 + Machine-Readable Extensions
        fid = _stable_file_id(fi) # Now returns FILE:f_...

        # Machine-First: Explicit FILE_START marker
        block.append(f'<!-- FILE_START path="{fi.rel_path}" content_sha256="{content_sha256}" content_bytes="{content_bytes}" file_bytes="{fi.size}" truncated="{str(truncated).lower()}" -->')

        # Fix PR13: Quote attributes to handle paths with spaces
        # Fix PR13-Followup: Quote id as well for consistency
        block.append(f'<!-- file:id="{fid}" path="{fi.rel_path}" -->')

        # 2. Stable Anchors (explicit) - Double Anchoring Strategy
        # Requirement: Every file block MUST have stable anchors in BOTH forms.

        # Form A: Human-stable (FILE_ID based)
        # fid is FILE:f_<hash>, we want file-f_<hash>
        human_stable_id = fid.replace("FILE:", "file-")
        block.append(f'<a id="{human_stable_id}"></a>')

        # Form B: Path-stable (file-<repo>-<path-sanitized>)
        # fi.anchor_alias holds the base anchor (file-{repo_slug}-{rel_id})
        path_stable_id = fi.anchor_alias

        # fi.anchor is the ID used for the heading (may include collision suffix)
        header_id = fi.anchor

        # Avoid duplicate ID if path_stable_id == header_id, as _heading_block will emit header_id
        if path_stable_id != header_id:
            block.append(f'<a id="{path_stable_id}"></a>')

        # Level 4 for Files (was 3)
        # _heading_block emits <a id="{header_id}"></a> which covers the path-stable ID + suffix case
        block.extend(_heading_block(4, header_id, str(fi.rel_path), nav=nav))
        block.append(f"**Path:** `{fi.rel_path}`")

        # Header Drosselung: meta=min versteckt Details
        if effective_meta_density != "min":
            block.append(f"- Category: {fi.category}")
            if fi.tags:
                block.append(f"- Tags: {', '.join(fi.tags)}")
            else:
                block.append("- Tags: -")
            block.append(f"- Size: {human_size(fi.size)}")
            block.append(f"- Included: {status}")

            # MD5 nur bei full oder standard (wenn gewünscht, hier full only)
            if effective_meta_density == "full":
                block.append(f"- MD5: {fi.md5}")

        # File Meta Block (Spec Patch)
        # Gate: min -> aus, standard -> nur wenn partial/truncated, full -> immer
        show_file_meta = False
        if effective_meta_density == "full":
            show_file_meta = True
        elif effective_meta_density == "standard":
            if status != "full":
                show_file_meta = True
        # Sonderregel: bei partial/truncated zwingend minimale Herkunftsspur
        if status != "full":
            show_file_meta = True

        if show_file_meta:
            block.append("<!--")
            block.append("file_meta:")
            block.append(f"  repo: {fi.root_label}")
            block.append(f"  path: {fi.rel_path}")
            block.append(f"  lines: {len(content.splitlines())}")
            block.append(f"  included: {status}")
            if getattr(fi, "inclusion_reason", "normal") != "normal":
                block.append(f"  inclusion_reason: {fi.inclusion_reason}")
            block.append("-->")

        # Dynamic fence length to escape content containing backticks
        max_ticks = 0
        if "```" in content:
            ticks = re.findall(r"`{3,}", content)
            if ticks:
                max_ticks = max(len(t) for t in ticks)

        fence_len = max(3, max_ticks + 1)
        fence = "`" * fence_len

        lang = lang_for(fi.ext)

        # Zone wrapper for code content
        # Fix PR13: Quote attributes
        block.append(f'<!-- zone:begin type="code" lang="{lang}" id="{fid}" -->')
        block.append("")
        block.append(f"{fence}{lang}")
        block.append(content)
        block.append(f"{fence}")
        block.append("")
        # PR-Optimierung: deterministic markers
        block.append(f'<!-- zone:end type="code" id="{fid}" -->')

        # Machine-First: Explicit FILE_END marker
        block.append(f'<!-- FILE_END path="{fi.rel_path}" -->')

        # Backlinks: keep them simple
        block.append("[↑ Manifest](#manifest) · [↑ Index](#index)")
        yield "\n".join(block) + "\n\n"

def generate_report_content(
    files: List[FileInfo],
    level: str,
    max_file_bytes: int,
    sources: List[Path],
    plan_only: bool,
    code_only: bool = False,
    debug: bool = False,
    path_filter: Optional[str] = None,
    ext_filter: Optional[List[str]] = None,
    extras: Optional[ExtrasConfig] = None,
    delta_meta: Optional[Dict[str, Any]] = None,
    artifact_refs: Optional[Dict[str, str]] = None,
    meta_density: str = "auto",
    meta_none: bool = False,
    redact_secrets: bool = False,
) -> str:
    report = "".join(
        iter_report_blocks(
            files,
            level,
            max_file_bytes,
            sources,
            plan_only,
            code_only,
            debug,
            path_filter,
            ext_filter,
            extras,
            delta_meta,
            artifact_refs,
            meta_density=meta_density,
            meta_none=meta_none,
            redact_secrets=redact_secrets,
        )
    )
    if plan_only:
        return "<!-- MODE:PLAN_ONLY -->\n" + report

    # Use new Validator
    validator = ReportValidator(plan_only=plan_only, code_only=code_only, machine_lean=(level=="machine-lean"))
    validator.validate_full(report)

    return report

def extract_retrieval_metadata(content: str, lang: str) -> Dict[str, Any]:
    meta = {}
    # Shebang
    if content.startswith("#!"):
        meta["shebang"] = content.splitlines()[0].strip()

    # Estimated tokens (rough heuristic)
    meta["estimated_tokens"] = len(content) // 4

    # Simple symbol/import extraction (heuristic)
    if lang == "python":
        imports = re.findall(r"^(?:from|import) [\w.]+", content, re.MULTILINE)
        meta["imports"] = list(set(imports))[:20]  # Limit

        # Top level def/class
        defs = re.findall(r"^def (\w+)", content, re.MULTILINE)
        classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
        meta["top_level_symbols"] = sorted(defs + classes)[:50]

    elif lang in ("javascript", "typescript"):
        imports = re.findall(r"import .* from .*", content, re.MULTILINE)
        meta["imports"] = list(set(imports))[:20]

    # Docker
    if lang == "dockerfile":
        from_imgs = re.findall(r"^FROM\s+(\S+)", content, re.MULTILINE | re.IGNORECASE)
        if from_imgs:
            meta["docker_usage"] = {"base_images": from_imgs}

    return meta


# Concepts are heuristic keyword hints; may include false positives.
MAX_CONCEPTS_PER_FILE = 6


def get_semantic_metadata_path_only(file_path: str) -> Dict[str, Any]:
    """
    Derives deterministic semantic metadata from file structure only (no content reading).
    Optimized for architecture summary generation.
    """
    p = Path(file_path)
    parts = p.parts

    # 1. Section (Filename without extension)
    section = p.stem

    # 2. Layer (Path based)
    layer = "unknown"
    # Prioritize specific folders
    if "core" in parts:
        layer = "core"
    elif "tests" in parts or "test" in parts:
        layer = "test"
    elif "cli" in parts:
        layer = "cli"
    elif "docs" in parts:
        layer = "docs"
    elif "scripts" in parts:
        layer = "infra"

    # 3. Artifact Type (Extension based)
    ext = p.suffix.lower()
    artifact_type = "other"
    if ext == ".py":
        artifact_type = "code"
    elif ext == ".json":
        artifact_type = "data"
    elif ext in (".md", ".txt", ".rst"):
        artifact_type = "documentation"
    elif ext in (".sh", ".bash", ".zsh"):
        artifact_type = "script"

    return {
        "section": section,
        "layer": layer,
        "artifact_type": artifact_type,
    }


def get_semantic_metadata(file_path: str, content: str) -> Dict[str, Any]:
    """
    Derives deterministic semantic metadata from file structure and content.
    """
    # Reuse path-only logic
    base_meta = get_semantic_metadata_path_only(file_path)

    # 4. Concepts (Keyword based, lightweight)
    concepts = []
    content_lower = content.lower()

    # Heuristic mapping: simple substring matching (not a tokenizer).
    # This is a lightweight way to tag concepts without full parsing.
    mapping = {
        "sha256": "hashing",
        "error": "error_policy",
        "bundle": "bundling",
        "merge": "merge_logic",
        "extract": "extraction",
        "policy": "policy",
    }

    for keyword, concept in mapping.items():
        if keyword in content_lower:
            concepts.append(concept)
            if len(concepts) >= MAX_CONCEPTS_PER_FILE:
                break

    base_meta["concepts"] = concepts
    return base_meta


def generate_architecture_summary(files: List[FileInfo]) -> str:
    """
    Generates a high-level architecture snapshot based on file metadata.
    """
    layer_counts = {}
    core_modules = set()
    test_files = []

    for fi in files:
        meta = get_semantic_metadata_path_only(fi.rel_path.as_posix())
        layer = meta["layer"]
        section = meta["section"]

        layer_counts[layer] = layer_counts.get(layer, 0) + 1

        if layer == "core":
            core_modules.add(section)
        elif layer == "test":
            test_files.append(fi.rel_path.as_posix())

    lines = []
    # Sentinel Header for Machine Readability
    lines.append("<!-- ARTIFACT:architecture_summary CONTRACT:architecture-summary VERSION:v1 -->")
    lines.append("# Lenskit Architecture Snapshot")
    lines.append("")

    lines.append("## LAYER_DISTRIBUTION")
    for layer, count in sorted(layer_counts.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"{layer}: {count}")
    lines.append("")

    lines.append("## KEY_MODULES")
    if core_modules:
        for mod in sorted(core_modules):
            lines.append(f"- {mod}")
    else:
        lines.append("_No core modules detected._")
    lines.append("")

    lines.append("## TEST_COVERAGE_MAP")
    lines.append(f"total_test_files: {len(test_files)}")
    # Summarize test coverage by parent directory to keep the map compact.
    test_dirs = {}
    for tf in test_files:
        p = Path(tf).parent.as_posix()
        test_dirs[p] = test_dirs.get(p, 0) + 1

    for d, c in sorted(test_dirs.items()):
        unit = "test" if c == 1 else "tests"
        lines.append(f"{d}/: {c} {unit}")

    lines.append("")
    return "\n".join(lines)

def generate_json_sidecar(
    files: List[FileInfo],
    level: str,
    max_file_bytes: int,
    sources: List[Path],
    plan_only: bool,
    code_only: bool = False,
    path_filter: Optional[str] = None,
    ext_filter: Optional[List[str]] = None,
    total_size: int = 0,
    delta_meta: Optional[Dict[str, Any]] = None,
    requested_flags: Optional[Dict[str, bool]] = None,
    requested_meta_density: str = "auto",
    meta_none: bool = False,
    generator_info: Optional[Dict[str, Any]] = None,
    output_mode: str = "dual",
    redact_secrets: bool = False,
    split_size_bytes: int = 0,
    include_hidden: bool = True,
) -> Dict[str, Any]:
    """
    Generate a JSON sidecar structure for machine consumption.
    Contains meta, files array, and minimal verification guards.
    """
    now = clock.now_utc()
    requested_flags = requested_flags or {"plan_only": plan_only, "code_only": code_only, "meta_none": meta_none}
    plan_only, code_only, meta_none, normalized_requested = _normalize_mode_flags(
        requested_flags.get("plan_only", False),
        requested_flags.get("code_only", False),
        requested_flags.get("meta_none", False),
    )
    render_mode = _effective_render_mode(plan_only, code_only, meta_none)

    requested_flags = {
        "plan_only": bool(normalized_requested["plan_only"]),
        "code_only": bool(normalized_requested["code_only"]),
        "meta_none": bool(normalized_requested["meta_none"]),
    }

    if code_only:
        files = [fi for fi in files if fi.category in DEBUG_CONFIG.code_only_categories]

    scope_desc = describe_scope(files)

    total_size = sum(fi.size for fi in files)

    processed = []
    text_files = [f for f in files if f.is_text]
    for fi in files:
        status = determine_inclusion_status(fi, level, max_file_bytes)
        processed.append((fi, status))

    # Calculate metrics early (Single Source of Truth)
    ep_metrics = compute_epistemic_metrics(files, processed)

    # Extract values for legacy/existing fields
    included_count = ep_metrics["counts"]["full"] + ep_metrics["counts"]["snippet"]
    text_files_count = ep_metrics["counts"]["text_total"]

    coverage_pct = 0.0
    if text_files_count > 0:
        coverage_pct = round((ep_metrics["counts"]["text_contact"] / text_files_count) * 100, 1)

    # Resolve Effective Meta Density (Consistency Fix)
    effective_meta_density = _resolve_effective_meta_density(
        requested_meta_density, path_filter, ext_filter, meta_none
    )

    # Determine features based on output mode and enabled logic
    active_features = []
    if output_mode in ("retrieval", "dual"):
        active_features.append("semantic_chunk_fields")
    if output_mode in ("archive", "dual"):
        active_features.append("architecture_summary")

    # Build meta block (agent-first contract)
    meta = {
        "contract": AGENT_CONTRACT_NAME,
        "contract_version": AGENT_CONTRACT_VERSION,
        "dump_index_contract": {
            "name": "dump-index",
            "version": "v1"
        },
        # keep existing useful fields for compatibility/traceability
        "spec_version": SPEC_VERSION,
        "generator": generator_info or {"name": "lenskit", "platform": "unknown"},
        "features": sorted(active_features),
        "profile": level,
        "output_mode": output_mode,
        "include_hidden": include_hidden,
        "redact_secrets": redact_secrets,
        "split_size_bytes": split_size_bytes,
        "max_bytes": max_file_bytes,
        "schema_ids": [AGENT_CONTRACT_NAME, "dump-index"],
        "generated_at": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        **({"mode": "none", "warning": "interpretation_disabled"} if meta_none else {}),
        "plan_only": plan_only,
        "code_only": code_only,
        "requested_flags": {
            "plan_only": bool(requested_flags["plan_only"]),
            "code_only": bool(requested_flags["code_only"]),
            "meta_none": bool(requested_flags.get("meta_none", False)),
        },
        "max_file_bytes": max_file_bytes,
        "meta_density": effective_meta_density,
        "requested_meta_density": requested_meta_density,
        "total_files": len(files),
        "total_size_bytes": total_size,
        "source_repos": sorted([s.name for s in sources]) if sources else [],
        # explicit include/exclude semantics (negation available even if None)
        "filters": {
            "path_filter": (path_filter or "").strip(),
            "ext_filter": ",".join(sorted(ext_filter)) if ext_filter else "",
            # explicit negation sets (agent-safe): empty list means "no restriction" / "none excluded"
            "included_categories": sorted(list(DEBUG_CONFIG.code_only_categories)) if code_only else [],
            "excluded_categories": [],
            "included_globs": [],
            "excluded_globs": [],
            "binary_policy": "ignore",
            "content_policy": render_mode,
        },
    }

    if "semantic_chunk_fields" in active_features:
        meta["chunk_index_contract"] = {
            "name": "chunk-index",
            "version": "v2",
            "legacy_aliases": True
        }
        meta["schema_ids"].append("chunk-index")

    if not meta_none:
        meta["epistemic_charter"] = {
            "applied": True,
            "location": "document_header",
            "version": "1.0",
            "claim_language_guard": "active"
        }
        meta["epistemic_declaration"] = {
            "charter": "epistemic_reading_charter v1",
            "claim_language_guard": "active",
            "risk_level": ep_metrics["risk"]["level"],
            "contact_ratio": ep_metrics["ratios"]["contact_ratio"]
        }

    files_out = []
    contact_list = []
    lens_index = []

    for fi, status in processed:
        fid = _stable_file_id(fi)

        # Populate lens index
        if fi.lens:
            lens_index.append({
                "path": fi.rel_path.as_posix(),
                "lens": fi.lens
            })

        file_obj = {
            "id": fid,
            "path": fi.rel_path.as_posix(),
            "repo": fi.root_label,
            "size_bytes": fi.size,
            "is_text": fi.is_text,
            "category": fi.category,
            "tags": fi.tags or [],
            "included": status in ("full", "truncated"),
            "inclusion_status": status,
            "content_ref": {
                # Markdown marker search is more robust than anchors/links.
                # Patch 1: align JSON marker with quoted MD emitter
                "marker": f'file:id="{fid}"',
                # Patch 2: Structured Selector (robust, future-proof)
                "selector": {
                    "kind": "html_comment_attr",
                    "tag": "file",
                    "attr": "id",
                    "value": fid,
                },
            },
            "md_ref": {
                "anchor": fid.replace("FILE:", "file-"),
                # Patch 3: Full fragment (sanity)
                "fragment": "#" + fid.replace("FILE:", "file-"),
            }
        }
        files_out.append(file_obj)

        # Self Report Contact
        evidence = "meta"
        chars_seen = None

        if status == "full":
            evidence = "full"
        elif status == "truncated":
            evidence = "snippet"

        contact_entry = {
            "path": fi.rel_path.as_posix(),
            "evidence_type": evidence,
        }

        if evidence in ("full", "snippet"):
             # Read content to get truthful char count (Task T-Fix1)
             content, _, _ = read_smart_content(fi, max_file_bytes)
             chars_seen = len(content)
             contact_entry["chars_seen"] = chars_seen

             # Retrieval optimized metadata
             lang = lang_for(fi.ext)
             retrieval_meta = extract_retrieval_metadata(content, lang)
             file_obj.update(retrieval_meta)

             # SHA256 (computed from content)
             file_obj["sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
             file_obj["language"] = lang

        contact_list.append(contact_entry)

    # Metrics construction for self_report
    contact_metrics = {
        "total_files": ep_metrics["counts"]["total"],
        "full": ep_metrics["counts"]["full"],
        "snippet": ep_metrics["counts"]["snippet"],
        "meta": ep_metrics["counts"]["meta"],
        "contact_ratio": ep_metrics["ratios"]["contact_ratio"],
        "meta_ratio": ep_metrics["ratios"]["meta_ratio"],
        "text_files_total": ep_metrics["counts"]["text_total"],
        "text_files_contact": ep_metrics["counts"]["text_contact"],
        "text_coverage_ratio": ep_metrics["ratios"]["text_coverage_ratio"],
    }

    out = {
        "meta": meta,
        "reading_policy": {
            "canonical_content_artifact": "merge_md",
            "navigation_artifacts": ["dump_index", "chunk_index", "sidecar_json"],
            "do_not_assume_json_contains_full_content": True,
            "preferred_retrieval": ["chunk_index(byte_ranges)", "merge_md(byte_ranges)"],
            # Legacy fields for backward compatibility
            "canonical_source": "md",
            "md_required": True,
            "json_role": "index_and_metadata_only",
            "md_contains_full_information": True,
            "lenses_applied": not meta_none,
        },
        "artifacts": {
            # filled by writer (paths)
            "index_json": None,
            "canonical_md": None,
            "md_parts": [],
            # basenames for portable linking (filled by writer)
            "index_json_basename": None,
            "canonical_md_basename": None,
            "md_parts_basenames": [],
        },
        "coverage": {
            "included_text_files": included_count,
            "total_text_files": len(text_files),
            "coverage_pct": coverage_pct,
        },
        "scope": scope_desc,
        "reading_lenses": {
            "active": lenses.LENS_IDS,
            "file_index": lens_index,
            "recommended_files": [], # Populated in MD, optional here
        },
        "self_report": {
             "active_lenses": lenses.LENS_IDS,
             "text_contact": contact_list,
             "contact_metrics": contact_metrics,
             "risk_level": ep_metrics["risk"]["level"],
             "risk_rationale": ep_metrics["risk"]["rationale"],
             "risk_inputs": ep_metrics["risk"]["inputs"],
             "uncertainty_score": ep_metrics["risk"]["uncertainty_score"],
        },
        "files": files_out,
        "delta": delta_meta or None,
    }
    _validate_agent_json_dict(out, allow_empty_primary=True)
    return out

# Helper for derived manifest
def generate_derived_manifest(base_name_func, run_id, dump_sha256, artifacts_map, generator_info, repo_names):
    out_path = base_name_func(part_suffix="").with_suffix(".derived_index.json")
    artifacts_block = {}
    for role, path in artifacts_map.items():
        if path and path.exists():
            name = path.name
            ctype = "application/json" if name.endswith(".json") else "application/octet-stream"
            entry = {
                "path": name,
                "role": role,
                "content_type": ctype,
                "bytes": path.stat().st_size,
                "sha256": _compute_file_sha256(path)
            }
            artifacts_block[role] = entry

    now_str = clock.now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')
    data = {
        "contract": "derived-index",
        "contract_version": "v1",
        "run_id": run_id,
        "created_at": now_str,
        "generated_at": now_str,
        "canonical_dump_index_sha256": dump_sha256,
        "config_sha256": generator_info.get("config_sha256", ""),
        "generator": generator_info,
        "repos": repo_names,
        "artifacts": dict(sorted(artifacts_block.items()))
    }
    out_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return out_path

def build_derived_artifacts(dump_index_path, chunk_path, base_name_func, run_id, hub_path, generator_info, repo_names, debug) -> List[Path]:
    derived_paths = []
    sqlite_index_path = None
    eval_json_path = None

    try:
        from ..retrieval.index_db import build_index
        from ..retrieval.eval_core import do_eval

        sqlite_index_path = chunk_path.with_suffix(".index.sqlite")
        try:
            config_payload = {
                "config_sha256": generator_info.get("config_sha256", ""),
                "lenskit_version": generator_info.get("version", "unknown")
            }
            build_index(dump_path=dump_index_path, chunk_path=chunk_path, db_path=sqlite_index_path, config_payload=config_payload)
            derived_paths.append(sqlite_index_path)

            # Evaluate
            eval_json_path = base_name_func(part_suffix="").with_suffix(".retrieval_eval.json")
            queries_path = hub_path / "docs" / "retrieval" / "queries.md"
            if not queries_path.exists():
                queries_path = Path("docs/retrieval/queries.md")

            if queries_path.exists():
                eval_res = do_eval(sqlite_index_path, queries_path, k=10, is_json_mode=True)
                if eval_res:
                    eval_json_path.write_text(json.dumps(eval_res, indent=2), encoding="utf-8")
                    derived_paths.append(eval_json_path)
        except Exception as e:
            if debug:
                print(f"Error building derived index or evaluating: {e}", file=sys.stderr)
    except ImportError as e:
        if debug:
            print(f"Skipping retrieval artifacts: retrieval modules not available ({e})", file=sys.stderr)

    # Generate Graph Index Artifact
    graph_index_path = None
    try:
        from ..architecture.graph_index import compile_graph_index
        arch_graph_path = base_name_func(part_suffix="").with_suffix(".architecture_graph.json")
        entrypoints_path = base_name_func(part_suffix="").with_suffix(".entrypoints.json")

        if arch_graph_path.exists() and entrypoints_path.exists():
            graph_index_data = compile_graph_index(arch_graph_path, entrypoints_path)
            graph_index_path = base_name_func(part_suffix="").with_suffix(".graph_index.json")
            graph_index_path.write_text(json.dumps(graph_index_data, indent=2, sort_keys=True), encoding="utf-8")
            derived_paths.append(graph_index_path)
    except ImportError as e:
        if debug:
            print(f"Skipping graph index artifact: architecture module not available ({e})", file=sys.stderr)
    except Exception as e:
        if debug:
            print(f"Error compiling graph index artifact: {e}", file=sys.stderr)

    # Write Derived Manifest
    derived_map = {}
    if sqlite_index_path and sqlite_index_path.exists():
        derived_map[ArtifactRole.SQLITE_INDEX.value] = sqlite_index_path
    if eval_json_path and eval_json_path.exists():
        derived_map[ArtifactRole.RETRIEVAL_EVAL_JSON.value] = eval_json_path
    if graph_index_path and graph_index_path.exists():
        derived_map[ArtifactRole.GRAPH_INDEX_JSON.value] = graph_index_path

    if derived_map:
        derived_manifest_path = generate_derived_manifest(
            base_name_func, run_id, _compute_file_sha256(dump_index_path),
            derived_map, generator_info, repo_names
        )
        derived_paths.append(derived_manifest_path)
    return derived_paths


def extract_file_offsets(md_paths: List[Path], debug: bool = False) -> Dict[str, Tuple[str, int]]:
    offsets = {}
    for md_path in md_paths:
        if not md_path or not md_path.exists():
            continue
        try:
            with md_path.open("rb") as f:
                pos = 0
                current_id = None

                while True:
                    line = f.readline()
                    if not line:
                        break

                    line_len = len(line)
                    line_str = line.decode("utf-8", errors="ignore")

                    if "<!-- zone:begin" in line_str and re.search(r'type="?code"?', line_str):
                        # Dual-read: extract id regardless of quotes.
                        # Handles id="FILE:..." or id=FILE:...
                        # Tighter regex ensures we don't grab the trailing -->
                        m = re.search(r'id=(?:"([^"]+)"|([a-zA-Z0-9._:-]+))', line_str)
                        if m:
                            current_id = m.group(1) or m.group(2)
                    elif current_id and line_str.strip().startswith("```"):
                        offsets[current_id] = (md_path.name, pos + line_len)
                        current_id = None
                    elif current_id and "<!-- zone:end" in line_str:
                        if debug:
                            print(f"warning: malformed zone marker in {md_path.name}")
                        current_id = None

                    pos += line_len
        except Exception as e:
            if debug:
                print(f"Error extracting offsets from {md_path}: {e}")
    return offsets

def write_reports_v2(
    merges_dir: Path,
    hub: Path,
    repo_summaries: List[Dict],
    detail: str,
    mode: str,
    max_bytes: int,
    plan_only: bool,
    code_only: bool = False,
    split_size: int = 0,
    debug: bool = False,
    path_filter: Optional[str] = None,
    ext_filter: Optional[List[str]] = None,
    extras: Optional[ExtrasConfig] = None,
    delta_meta: Optional[Dict[str, Any]] = None,
    meta_density: str = "auto",
    meta_none: bool = False,
    output_mode: str = "dual",  # archive, retrieval, dual
    redact_secrets: bool = False,
    include_hidden: bool = True,
    generator_info: Optional[Dict[str, Any]] = None,
) -> MergeArtifacts:
    out_paths = []

    plan_only, code_only, meta_none, requested_flags = _normalize_mode_flags(plan_only, code_only, meta_none)

    ext_filter_str = ",".join(sorted(ext_filter)) if ext_filter else None

    # Global consistent timestamp for this run (all parts/formats must share it)
    global_ts = clock.now_utc().strftime("%y%m%d-%H%M")

    # Phase 1.3: Generate deterministic run_id once for this merge
    repo_names = [s["name"] for s in repo_summaries]
    run_id = _generate_run_id(
        repo_names, detail, path_filter, ext_filter_str,
        plan_only=plan_only, code_only=code_only, timestamp=global_ts, meta_none=meta_none
    )

    # Define consistent limit for both report and chunks
    # max_bytes is a per-file read limit (historical naming).
    max_file_bytes = max_bytes

    # Ensure generator_info is safe
    if generator_info is None:
        generator_info = {
            "name": "lenskit",
            "platform": "unknown",
            "version": os.getenv("RLENS_VERSION", CORE_VERSION)
        }
    elif not isinstance(generator_info, dict):
        try:
            generator_info = dict(generator_info)
        except Exception:
            generator_info = {
                "name": "lenskit",
                "platform": "unknown",
                "version": os.getenv("RLENS_VERSION", CORE_VERSION)
            }

    def _json_safe(obj):
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        if isinstance(obj, (list, tuple)):
            return [_json_safe(x) for x in obj]
        if isinstance(obj, set):
            return sorted([_json_safe(x) for x in obj])
        if isinstance(obj, dict):
            return {str(k): _json_safe(v) for k, v in sorted(obj.items(), key=lambda i: str(i[0]))}
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "name") and hasattr(obj, "value"): # Enum-like
            return obj.name

        # Fallback: Deterministic Type Tagging
        # Avoids unstable repr/str (memory addresses)
        t = type(obj)
        module = getattr(t, "__module__", "__builtin__")
        qualname = getattr(t, "__qualname__", t.__name__)
        return f"__type__:{module}.{qualname}"

    # Calculate config_sha256 for parity checks and bundle manifest provenance
    extras_dict = None
    if extras:
        try:
            extras_dict = asdict(extras)
        except (TypeError, ValueError):
            # Fallback if extras is not a dataclass instance (e.g. mocked object or type)
            extras_dict = getattr(extras, "__dict__", None)
            if extras_dict is None:
                 extras_dict = str(extras)

    # Ensure extras_dict is JSON safe
    extras_dict = _json_safe(extras_dict)

    config_payload = {
        "detail": detail,
        "mode": mode,
        "max_bytes_arg": max_bytes,
        "max_file_bytes_effective": max_file_bytes,
        "plan_only": plan_only,
        "code_only": code_only,
        "split_size": split_size,
        "path_filter": path_filter,
        "ext_filter": sorted(ext_filter) if ext_filter else None,
        "extras": extras_dict,
        "meta_density": meta_density,
        "meta_none": meta_none,
        "output_mode": output_mode,
        "redact_secrets": redact_secrets,
        "include_hidden": include_hidden,
    }
    config_str = json.dumps(config_payload, sort_keys=True, separators=(",", ":"))
    config_sha256 = hashlib.sha256(config_str.encode("utf-8")).hexdigest()

    # Inject the computed config_sha256 into generator_info
    if "config_sha256" not in generator_info:
        generator_info["config_sha256"] = config_sha256

    # Helper for architecture summary writing (DRY)
    def _write_architecture_summary(
        files,
        merges_dir,
        repo_names,
        detail,
        path_filter,
        ext_filter_str,
        run_id,
        plan_only,
        code_only,
        timestamp,
        meta_none,
        out_paths
    ):
        # Helper to generate and write the architecture summary.
        arch_path = make_output_filename(
            merges_dir,
            repo_names,
            detail,
            "",
            path_filter,
            ext_filter_str,
            run_id,
            plan_only=plan_only,
            code_only=code_only,
            timestamp=timestamp,
            meta_none=meta_none,
            suffix="_architecture.md"
        )
        arch_path.write_text(generate_architecture_summary(files), encoding="utf-8")
        out_paths.append(arch_path)
        return arch_path

    # Helper for dump index (Canonical Entrypoint)
    def generate_dump_index(base_name_func, run_id, artifacts_map, generator_info, repo_names):
        out_path = base_name_func(part_suffix="").with_suffix(".dump_index.json")

        artifacts_block = {}
        for role, path in artifacts_map.items():
            if path and path.exists():
                # Infer content_type
                name = path.name
                if name.endswith(".json"):
                    ctype = "application/json"
                elif name.endswith(".jsonl"):
                    ctype = "application/x-ndjson"
                elif name.endswith(".md"):
                    ctype = "text/markdown"
                else:
                    ctype = "application/octet-stream"

                entry = {
                    "path": name,
                    "role": role,
                    "content_type": ctype,
                    "bytes": path.stat().st_size,
                    "sha256": _compute_file_sha256(path)
                }

                # Contract annotations
                if role == ArtifactRole.INDEX_SIDECAR_JSON.value:
                    entry["contract"] = AGENT_CONTRACT_NAME
                    entry["contract_version"] = AGENT_CONTRACT_VERSION
                elif role == ArtifactRole.CANONICAL_MD.value:
                    entry["contract"] = MERGE_CONTRACT_NAME
                    entry["contract_version"] = MERGE_CONTRACT_VERSION
                elif role == ArtifactRole.CHUNK_INDEX_JSONL.value:
                    entry["contract"] = "chunk-index"
                    entry["contract_version"] = "v2"
                elif role == ArtifactRole.ARCHITECTURE_SUMMARY.value:
                    entry["contract"] = "architecture-summary"
                    entry["contract_version"] = "v1"

                artifacts_block[role] = entry

        # Sort artifacts by key for determinism
        artifacts_sorted = dict(sorted(artifacts_block.items()))

        now_str = clock.now_utc().strftime('%Y-%m-%dT%H:%M:%SZ')
        data = {
            "contract": "dump-index",
            "contract_version": "v1",
            "run_id": run_id,
            "created_at": now_str,
            "generated_at": now_str,
            "generator": generator_info,
            "repos": repo_names,
            "artifacts": artifacts_sorted
        }

        out_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return out_path



    # --- Split-Mode Contract ---
    # By architectural mandate (Phase 1, Schwerpunkt D), only the FIRST part of a split
    # bundle is considered fully `bundle-backed` and canonically referenceable.
    # Subsequent parts are transient artifacts and do NOT receive `content_range_ref` provenance.
    # The chunker and the JSON sidecar exclusively refer to `md_parts[0]` as the canonical representation.

    # Helper for chunking (PR-Optimierung)
    def generate_chunk_artifacts(target_files, output_filename_base_func, md_paths: Optional[List[Path]] = None):
        if output_mode not in ("retrieval", "dual"):
            return None

        chunker = Chunker()
        redactor = Redactor() if redact_secrets else None

        # Build offset map from all generated markdown parts
        md_offsets = extract_file_offsets(md_paths, debug) if md_paths else {}
        can_md = resolve_canonical_md(md_paths) if md_paths else None
        canonical_md_name = can_md.name if can_md else None
        canonical_md_bytes = can_md.read_bytes() if (can_md and can_md.exists()) else None

        all_chunks = []

        # Sort files same as report
        target_files.sort(key=lambda fi: (get_repo_sort_index(fi.root_label), fi.root_label.lower(), str(fi.rel_path).lower()))

        for fi in target_files:
            # Only process included text files
            status = determine_inclusion_status(fi, detail, max_file_bytes)
            if not fi.is_text or status not in ("full", "truncated"):
                continue

            # Read content for chunking using the same limit as report to ensure coherence
            content, truncated, trunc_msg = read_smart_content(fi, max_file_bytes)

            was_redacted = False
            if redactor:
                content, _redacted_items = redactor.redact(content)
                was_redacted = bool(_redacted_items)

            # Get Semantic Metadata
            sem_meta = get_semantic_metadata(fi.rel_path.as_posix(), content)

            fid = _stable_file_id(fi)
            # Pass file_path for deterministic chunk ID
            chunks = chunker.chunk_file(fid, content, file_path=fi.rel_path.as_posix())

            lang = lang_for(fi.ext)

            for c in chunks:
                d = asdict(c)
                d["path"] = fi.rel_path.as_posix()
                d["repo"] = fi.root_label
                d["language"] = lang
                d["source_status"] = status
                d["truncated"] = truncated
                # Semantic Extension
                d["section"] = sem_meta["section"]
                d["layer"] = sem_meta["layer"]
                d["artifact_type"] = sem_meta["artifact_type"]
                d["concepts"] = sem_meta["concepts"]

                if trunc_msg:
                    d["truncation_msg"] = trunc_msg

                # Legacy Aliases (Backward Compatibility for v2 transition)
                d["byte_offset_start"] = d["start_byte"]
                d["byte_offset_end"] = d["end_byte"]
                d["line_start"] = d["start_line"]
                d["line_end"] = d["end_line"]
                d["content_sha256"] = d["sha256"]
                d["size_bytes"] = d["size"]

                # Extended machine-readable fields (v2.4)
                d["source_file"] = fi.rel_path.as_posix()
                d["content_artifact"] = "merge_md"
                d["content_range"] = {
                    "start_byte": d["start_byte"],
                    "end_byte": d["end_byte"],
                    "start_line": d["start_line"],
                    "end_line": d["end_line"]
                }

                # V2.4 Range Ref Propagation: Point directly to the canonical_md bytes
                # Contract Fix: The resolver only accepts the primary canonical_md artifact defined in the manifest.
                # We strictly limit full bundle-backed refs to the first part.
                if md_paths and fid in md_offsets:
                    md_file_name, md_start_byte = md_offsets[fid]
                    if md_file_name == canonical_md_name:
                        abs_start = md_start_byte + d["start_byte"]
                        abs_end = md_start_byte + d["end_byte"]

                        if canonical_md_bytes is not None:
                            # Compute canonical-local values once; share across both fields.
                            can_chunk = canonical_md_bytes[abs_start:abs_end]
                            can_sha256 = hashlib.sha256(can_chunk).hexdigest()
                            can_start_line = _line_for_byte(canonical_md_bytes, abs_start)
                            can_end_line = _line_for_byte(canonical_md_bytes, max(abs_start, abs_end - 1))
                        else:
                            # Fall back to source-local values when canonical bytes unavailable.
                            can_sha256 = d["sha256"]
                            can_start_line = d["start_line"]
                            can_end_line = d["end_line"]

                        d["content_range_ref"] = build_explicit_range_ref(
                            artifact_role=ArtifactRole.CANONICAL_MD.value,
                            repo_id=fi.root_label,
                            file_path=md_file_name,
                            start_byte=abs_start,
                            end_byte=abs_end,
                            start_line=can_start_line,
                            end_line=can_end_line,
                            content_sha256=can_sha256,
                        )

                        if canonical_md_bytes is not None:
                            d["canonical_range"] = {
                                "artifact_role": ArtifactRole.CANONICAL_MD.value,
                                "repo_id": fi.root_label,
                                "file_path": md_file_name,
                                "start_byte": abs_start,
                                "end_byte": abs_end,
                                "start_line": can_start_line,
                                "end_line": can_end_line,
                                "content_sha256": can_sha256,
                            }

                # source_range: always present, coordinates in source content space.
                # Status taxonomy: "declared" (source coords claimed, not externally verified) | "unavailable" (redacted or truncated).
                if was_redacted or truncated:
                    d["source_range"] = {
                        "file_path": fi.rel_path.as_posix(),
                        "repo_id": fi.root_label,
                        "status": "unavailable",
                    }
                else:
                    d["source_range"] = {
                        "file_path": fi.rel_path.as_posix(),
                        "repo_id": fi.root_label,
                        "start_byte": d["start_byte"],
                        "end_byte": d["end_byte"],
                        "start_line": d["start_line"],
                        "end_line": d["end_line"],
                        "content_sha256": d["sha256"],
                        "status": "declared",
                    }

                d["search_keys"] = {
                    "repo_id": fi.root_label,
                    "path_norm": fi.rel_path.as_posix().lower(),
                    "ext": fi.ext.lower().lstrip("."),
                    "layer": sem_meta["layer"],
                    "artifact_type": sem_meta["artifact_type"]
                }

                all_chunks.append(d)

        if not all_chunks:
            return None

        out_path = output_filename_base_func(part_suffix="").with_suffix(".chunk_index.jsonl")
        try:
            with out_path.open("w", encoding="utf-8") as f:
                for c in all_chunks:
                    f.write(json.dumps(c) + "\n")
            return out_path
        except Exception as e:
            if debug:
                print(f"Error writing chunk index: {e}")
            return None

    # Helper for writing logic
    def process_and_write(target_files, target_sources, output_filename_base_func):
        generated_paths: List[Path] = []

        # Pre-calculate artifacts basenames for linking in MD (Recommendation 1)
        artifact_refs = {}
        if extras and extras.json_sidecar:
            # We predict the JSON filename
            # Note: We rely on the fact that single-file mode uses part_suffix=""
            # For split mode, JSON usually follows the base name.
            # We use a dummy call to get the base path
            _dummy_path = output_filename_base_func(part_suffix="")
            _json_name = _dummy_path.with_suffix('.json').name
            artifact_refs["index_json_basename"] = _json_name

        if extras and extras.augment_sidecar:
             # Find augment file to get name
             _aug = _find_augment_file_for_sources(target_sources)
             if _aug:
                 artifact_refs["augment_sidecar_basename"] = _aug.name

        # Instantiate stream validator
        validator = ReportValidator(plan_only=plan_only, code_only=code_only, machine_lean=(detail=="machine-lean"))

        if split_size > 0:
            local_out_paths = []
            part_num = 1
            current_size = 0
            current_lines = []

            # --- Metadata tracking for parts (NEW) ---
            parts_meta = []  # List of dicts: {first, last}
            current_part_paths = []  # Paths in current buffer

            # Helper to flush
            def flush_part(is_last=False):
                nonlocal part_num, current_size, current_lines, current_part_paths
                if not current_lines:
                    return

                # Record metadata for this part
                first = current_part_paths[0] if current_part_paths else None
                last = current_part_paths[-1] if current_part_paths else None
                parts_meta.append({"first": first, "last": last})
                current_part_paths = []

                # Temporärer Name während der Generierung
                # Wir nutzen _tmp_partX, um es später sauber umzubenennen
                out_path = output_filename_base_func(part_suffix=f"_tmp_part{part_num}")
                out_path.write_text("".join(current_lines), encoding="utf-8")
                local_out_paths.append(out_path)

                part_num += 1
                current_lines = []
                # Add continuation header for next part
                if not is_last:
                    header = f"# repoLens Report (Part {part_num})\n\n"
                    # Note: we don't feed continuation headers to validator as they are technical split artifacts,
                    # not part of the logical report structure.
                    current_lines.append(header)
                    current_size = len(header.encode('utf-8'))
                else:
                    current_size = 0

            iterator = iter_report_blocks(
                target_files,
                detail,
                max_file_bytes,
                target_sources,
                plan_only,
                code_only,
                debug,
                path_filter,
                ext_filter,
                extras,
                delta_meta,
                artifact_refs=artifact_refs,
                meta_density=meta_density,
                meta_none=meta_none,
                redact_secrets=redact_secrets,
            )

            for block in iterator:
                # Validate the block before writing
                validator.feed(block)

                block_len = len(block.encode('utf-8'))

                # --- Path detection (NEW) ---
                # Detect path in block using regex to track range for signatures
                m = re.search(r"\*\*Path:\*\* `(.+?)`", block)
                block_path = m.group(1) if m else None

                if current_size + block_len > split_size and len(current_lines) > 1:
                    flush_part()
                    # After flush, block belongs to next part.
                    # current_part_paths was cleared in flush_part.

                current_lines.append(block)
                current_size += block_len
                if block_path:
                    current_part_paths.append(block_path)

            flush_part(is_last=True)
            validator.close()

            # Nachlauf: Header normalisieren UND Dateien umbenennen (Part X of Y)
            total_parts = len(local_out_paths)
            final_paths = []

            for idx, path in enumerate(local_out_paths, start=1):
                # 1. Header Rewrite
                try:
                    text = path.read_text(encoding="utf-8")
                    lines = text.splitlines(True)
                    if lines:
                        prefix_part = "# repoLens Report (Part "
                        prefix_main = "# repoLens Report"
                        for i, line in enumerate(lines):
                            stripped = line.lstrip("\ufeff")
                            if stripped.startswith(prefix_part) or stripped.startswith(prefix_main):
                                lines[i] = f"# repoLens Report (Part {idx}/{total_parts})\n"

                                # --- Inject Signature (NEW) ---
                                if total_parts > 1:
                                    meta = parts_meta[idx - 1]
                                    p_start = meta["first"]
                                    p_end = meta["last"]
                                    range_str = f"{p_start} ... {p_end}" if p_start else "Meta/Structure/Index"

                                    prev_name = "none"
                                    if idx > 1:
                                        # calculate name of part idx-1
                                        prev_suffix = f"_part{idx - 1}of{total_parts}"
                                        prev_path_obj = output_filename_base_func(part_suffix=prev_suffix)
                                        prev_name = prev_path_obj.name

                                    sig_block = (
                                        f"<!-- part_signature:\n"
                                        f"  part_index: {idx}\n"
                                        f"  part_total: {total_parts}\n"
                                        f"  continuation_of: \"{prev_name}\"\n"
                                        f"  range: \"{range_str}\"\n"
                                        f"-->\n"
                                        f"**[Part {idx}/{total_parts}]** continuation_of: `{prev_name}` · range: `{range_str}`\n\n"
                                    )
                                    lines.insert(i + 1, sig_block)
                                break
                    text = "".join(lines)
                except Exception:
                    text = None  # Skip rewrite if read fails, but still rename

                # 2. Rename File
                # If total_parts == 1, no part suffix.
                # If total_parts > 1, _partXofY.
                if total_parts == 1:
                    new_suffix = ""
                else:
                    new_suffix = f"_part{idx}of{total_parts}"

                new_path = output_filename_base_func(part_suffix=new_suffix)

                if text is not None:
                    new_path.write_text(text, encoding="utf-8")
                    # Delete old tmp file
                    try:
                        path.unlink()
                    except OSError:
                        pass
                else:
                    # Just replace/move if we couldn't read/edit content
                    try:
                        path.replace(new_path)
                    except OSError as e:
                        raise OSError(f"Failed to replace '{path}' with '{new_path}'") from e

                final_paths.append(new_path)

            generated_paths.extend(final_paths)
            out_paths.extend(final_paths)

        else:
            # Standard single file (Streamed Write)
            out_path = output_filename_base_func(part_suffix="")

            with out_path.open("w", encoding="utf-8") as f:
                if plan_only:
                    f.write("<!-- MODE:PLAN_ONLY -->\n")

                iterator = iter_report_blocks(
                    target_files,
                    detail,
                    max_file_bytes,
                    target_sources,
                    plan_only,
                    code_only,
                    debug,
                    path_filter,
                    ext_filter,
                    extras,
                    delta_meta,
                    artifact_refs=artifact_refs,
                    meta_density=meta_density,
                    meta_none=meta_none,
                    redact_secrets=redact_secrets,
                )

                for i, block in enumerate(iterator):
                    # Enforce Part 1/1 header strictly on the first yielded block (Header contract)
                    if i == 0:
                        lines = block.splitlines(True)
                        for line_idx, line in enumerate(lines):
                            stripped = line.lstrip("\ufeff")
                            if stripped.startswith("# repoLens Report"):
                                lines[line_idx] = "# repoLens Report (Part 1/1)\n"
                                break
                        block = "".join(lines)

                    validator.feed(block)
                    f.write(block)

            validator.close()
            generated_paths.append(out_path)
            out_paths.append(out_path)

        return generated_paths

    last_chunk_index_path = None
    last_dump_index_path = None

    if mode == "gesamt":
        all_files = []
        repo_names = []
        sources = []
        for s in repo_summaries:
            all_files.extend(s["files"])
            repo_names.append(s["name"])
            sources.append(s["root"])

        # Create base filename lambda
        base_name_func = lambda part_suffix="": make_output_filename(
            merges_dir,
            repo_names,
            detail,
            part_suffix,
            path_filter,
            ext_filter_str,
            run_id,
            plan_only=plan_only,
            code_only=code_only,
            timestamp=global_ts,
            meta_none=meta_none,
        )

        generated_paths = []
        arch_path = None
        if output_mode in ("archive", "dual"):
            generated_paths = process_and_write(all_files, sources, base_name_func)

            arch_path = _write_architecture_summary(
                all_files,
                merges_dir,
                repo_names,
                detail,
                path_filter,
                ext_filter_str,
                run_id,
                plan_only,
                code_only,
                global_ts,
                meta_none,
                out_paths
            )

        chunk_path = None
        if output_mode in ("retrieval", "dual"):
            # Pass all generated MD parts to support split_size > 0
            md_parts = [p for p in generated_paths if p.suffix.lower() == ".md"]
            chunk_path = generate_chunk_artifacts(all_files, base_name_func, md_paths=md_parts)
            if chunk_path:
                out_paths.append(chunk_path)
                last_chunk_index_path = chunk_path

        # Write JSON sidecar if enabled (agent-first: also for plan_only)
        # JSON must be written when json_sidecar is active - no conditions like "and not plan_only"
        json_path = None
        if extras and extras.json_sidecar:
            total_size = sum(
                f.size for f in all_files if (not code_only or f.category in DEBUG_CONFIG.code_only_categories)
            )
            json_data = generate_json_sidecar(
                all_files,
                detail,
                max_bytes,
                sources,
                plan_only,
                code_only,
                path_filter,
                ext_filter,
                total_size,
                delta_meta,
                requested_flags=requested_flags,
                requested_meta_density=meta_density,
                meta_none=meta_none,
                generator_info=generator_info,
                output_mode=output_mode,
                    redact_secrets=redact_secrets,
                    split_size_bytes=split_size,
                    include_hidden=include_hidden,
                )
            # Generate JSON filename using deterministic base name (via base_name_func)
            md_parts = [p for p in generated_paths if p.suffix.lower() == ".md"]

            json_path = base_name_func(part_suffix="").with_suffix('.json')

            json_data["artifacts"]["index_json"] = str(json_path)
            json_data["artifacts"]["index_json_basename"] = json_path.name

            json_data["artifacts"]["md_parts"] = [str(p) for p in md_parts]
            json_data["artifacts"]["md_parts_basenames"] = [p.name for p in md_parts]

            can_md = resolve_canonical_md(md_parts)
            json_data["artifacts"]["canonical_md"] = str(can_md) if can_md else None
            json_data["artifacts"]["canonical_md_basename"] = can_md.name if can_md else None

            if chunk_path:
                json_data["artifacts"]["chunk_index"] = str(chunk_path)
                json_data["artifacts"]["chunk_index_basename"] = chunk_path.name

            _validate_agent_json_dict(json_data)
            json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
            out_paths.append(json_path)

        # Generate Dump Index
        md_parts = [p for p in generated_paths if p.suffix.lower() == ".md"]
        artifacts_map = {
            ArtifactRole.CANONICAL_MD.value: resolve_canonical_md(md_parts),
            ArtifactRole.INDEX_SIDECAR_JSON.value: json_path,
            ArtifactRole.CHUNK_INDEX_JSONL.value: chunk_path,
            ArtifactRole.ARCHITECTURE_SUMMARY.value: arch_path
        }
        dump_index_path = generate_dump_index(base_name_func, run_id, artifacts_map, generator_info, repo_names)
        out_paths.append(dump_index_path)
        last_dump_index_path = dump_index_path

        if output_mode in ("retrieval", "dual") and chunk_path:
            # Build derived/transient retrieval artifacts AFTER dump_index is finalized
            derived_paths = build_derived_artifacts(
                dump_index_path, chunk_path, base_name_func, run_id, hub, generator_info, repo_names, debug
            )
            out_paths.extend(derived_paths)

    else:
        for s in repo_summaries:
            s_name = s["name"]
            s_files = s["files"]
            s_root = s["root"]

            # Generate per-repo run_id for deterministic naming
            repo_run_id = _generate_run_id(
                [s_name], detail, path_filter, ext_filter_str,
                plan_only=plan_only, code_only=code_only, timestamp=global_ts
            )

            # Fix: Explicitly capture loop variables (s_name, repo_run_id) as default args
            # to avoid lazy binding issues in the lambda.
            base_name_func = lambda part_suffix="", _name=s_name, _rid=repo_run_id: make_output_filename(
                merges_dir,
                [_name],
                detail,
                part_suffix,
                path_filter,
                ext_filter_str,
                _rid,
                plan_only=plan_only,
                code_only=code_only,
                timestamp=global_ts,
                meta_none=meta_none,
            )

            generated_paths = []
            arch_path = None
            if output_mode in ("archive", "dual"):
                generated_paths = process_and_write(s_files, [s_root], base_name_func)

                arch_path = _write_architecture_summary(
                    s_files,
                    merges_dir,
                    [s_name],
                    detail,
                    path_filter,
                    ext_filter_str,
                    repo_run_id,
                    plan_only,
                    code_only,
                    global_ts,
                    meta_none,
                    out_paths
                )

            chunk_path = None
            if output_mode in ("retrieval", "dual"):
                md_parts = [p for p in generated_paths if p.suffix.lower() == ".md"]
                chunk_path = generate_chunk_artifacts(s_files, base_name_func, md_paths=md_parts)
                if chunk_path:
                    out_paths.append(chunk_path)
                    last_chunk_index_path = chunk_path

            # Write JSON sidecar if enabled (agent-first: also for plan_only)
            # JSON must be written when json_sidecar is active - no conditions like "and not plan_only"
            json_path = None
            if extras and extras.json_sidecar:
                total_size = sum(
                    f.size for f in s_files if (not code_only or f.category in DEBUG_CONFIG.code_only_categories)
                )
                json_data = generate_json_sidecar(
                    s_files,
                    detail,
                    max_bytes,
                    [s_root],
                    plan_only,
                    code_only,
                    path_filter,
                    ext_filter,
                    total_size,
                    delta_meta,
                    requested_flags=requested_flags,
                    requested_meta_density=meta_density,
                    meta_none=meta_none,
                    generator_info=generator_info,
                    output_mode=output_mode,
                    redact_secrets=redact_secrets,
                    split_size_bytes=split_size,
                    include_hidden=include_hidden,
                )
                # Generate JSON filename using deterministic base name (via base_name_func)
                md_parts = [p for p in generated_paths if p.suffix.lower() == ".md"]

                json_path = base_name_func(part_suffix="").with_suffix('.json')

                json_data["artifacts"]["index_json"] = str(json_path)
                json_data["artifacts"]["index_json_basename"] = json_path.name

                json_data["artifacts"]["md_parts"] = [str(p) for p in md_parts]
                json_data["artifacts"]["md_parts_basenames"] = [p.name for p in md_parts]

                can_md = resolve_canonical_md(md_parts)
                if can_md:
                    json_data["artifacts"]["canonical_md"] = str(can_md)
                    json_data["artifacts"]["canonical_md_basename"] = can_md.name
                else:
                    json_data["artifacts"]["canonical_md"] = None
                    json_data["artifacts"]["canonical_md_basename"] = None

                if chunk_path:
                    json_data["artifacts"]["chunk_index"] = str(chunk_path)
                    json_data["artifacts"]["chunk_index_basename"] = chunk_path.name

                _validate_agent_json_dict(json_data)
                json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
                out_paths.append(json_path)

            # Generate Dump Index
            md_parts = [p for p in generated_paths if p.suffix.lower() == ".md"]
            artifacts_map = {
                ArtifactRole.CANONICAL_MD.value: resolve_canonical_md(md_parts),
                ArtifactRole.INDEX_SIDECAR_JSON.value: json_path,
                ArtifactRole.CHUNK_INDEX_JSONL.value: chunk_path,
                ArtifactRole.ARCHITECTURE_SUMMARY.value: arch_path
            }
            dump_index_path = generate_dump_index(base_name_func, repo_run_id, artifacts_map, generator_info, [s_name])
            out_paths.append(dump_index_path)
            last_dump_index_path = dump_index_path

            if output_mode in ("retrieval", "dual") and chunk_path:
                # Build derived/transient retrieval artifacts AFTER dump_index is finalized
                derived_paths = build_derived_artifacts(
                    dump_index_path, chunk_path, base_name_func, repo_run_id, hub, generator_info, [s_name], debug
                )
                out_paths.extend(derived_paths)

    # --- Post-check & deterministic ordering (primary artifact first) ---
    md_paths = [p for p in out_paths if p.suffix.lower() == ".md"]

    # Sidecar json / Canonical JSONs (exclude derived manifests and evals)
    json_paths = [
        p for p in out_paths
        if p.suffix.lower() == ".json"
        and not p.name.endswith(".dump_index.json")
        and not p.name.endswith(".derived_index.json")
        and not p.name.endswith(".retrieval_eval.json")
    ]

    dump_indices = [p for p in out_paths if p.name.endswith(".dump_index.json")]

    # Extract specific derived artifacts
    sqlite_indices = sorted([p for p in out_paths if p.name.endswith(".index.sqlite")], key=lambda p: p.name)
    retrieval_evals = sorted([p for p in out_paths if p.name.endswith(".retrieval_eval.json")], key=lambda p: p.name)
    graph_indices = sorted([p for p in out_paths if p.name.endswith(".graph_index.json")], key=lambda p: p.name)
    derived_manifests = sorted([p for p in out_paths if p.name.endswith(".derived_index.json")], key=lambda p: p.name)

    # Everything else goes to other_paths (but exclude the ones explicitly extracted)
    other_paths = [
        p for p in out_paths
        if p not in md_paths
        and p not in json_paths
        and p not in dump_indices
        and p not in sqlite_indices
        and p not in retrieval_evals
        and p not in graph_indices
        and p not in derived_manifests
    ]

    # Verify that reported .md outputs really exist and are non-empty.
    # This prevents "generated" messages when the file did not land where expected.
    verified_md: List[Path] = []
    for p in md_paths:
        try:
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                verified_md.append(p)
        except Exception:
            # treat as missing
            pass

    if md_paths and not verified_md:
        # We *expected* at least one markdown output, but none is actually usable.
        # Make this a hard error so callers don't display a success message.
        raise RuntimeError(
            "repoLens: Report was announced as written, but no non-empty .md output exists on disk. "
            "Check merges_dir / permissions / rename logic."
        )

    # If json_sidecar is enabled, JSON is the primary artifact: verify it exists & is non-empty.
    verified_json: List[Path] = []
    if extras and extras.json_sidecar:
        for p in json_paths:
            try:
                if p.exists() and p.is_file() and p.stat().st_size > 0:
                    # sanity: load + minimal validate
                    d = json.loads(p.read_text(encoding="utf-8"))
                    _validate_agent_json_dict(d)
                    verified_json.append(p)
            except Exception:
                pass
        if json_paths and not verified_json:
            raise RuntimeError(
                "repoLens: JSON primary artifact was announced as written, but no valid non-empty .json exists on disk."
            )

    # Primary ordering: JSON (if enabled) first, then Markdown, then other artifacts.
    # Return structured MergeArtifacts object instead of flat list

    # Fix: In pro-repo mode, we generate multiple sidecars and indices.
    # Avoid returning an arbitrary last index in the global summary object.
    # The authoritative references are in the per-repo JSON sidecars.
    is_gesamt = (mode == "gesamt")
    # However, for single-repo usage (common in tests), we populate fields to allow assertions.
    final_chunk_index = last_chunk_index_path
    final_index_json = (verified_json[0] if verified_json else None)
    final_canonical_md = (verified_md[0] if verified_md else None)
    final_dump_index = last_dump_index_path

    # Determine the dump index sha for links
    canonical_dump_index_sha256 = None
    if final_dump_index and final_dump_index.exists():
        canonical_dump_index_sha256 = _compute_file_sha256(final_dump_index)

    # Build the bundle manifest
    bundle_manifest_path = None
    # We generate the manifest regardless of is_gesamt, to ensure it exists
    # as the deterministic root of navigation for every merge job.
    bundle_manifest_path = make_output_filename(
        merges_dir,
        repo_names,
        detail,
        "",
        path_filter,
        ext_filter_str,
        run_id,
        plan_only=plan_only,
        code_only=code_only,
        timestamp=global_ts,
        meta_none=meta_none,
        ).with_suffix(".bundle.manifest.json")

    # Aliases into module-level registries (ARTIFACT_CONTRACT_REGISTRY / ARTIFACT_AUTHORITY_REGISTRY).
    CONTRACT_REGISTRY = ARTIFACT_CONTRACT_REGISTRY
    AUTHORITY_REGISTRY = ARTIFACT_AUTHORITY_REGISTRY

    artifacts_list = []
    def _add_artifact(p: Optional[Path], role: ArtifactRole, content_type: str):
        if p and p.exists():
            sha = _compute_file_sha256(p)
            if sha:
                try:
                    rel_path = p.relative_to(merges_dir).as_posix()
                except ValueError:
                    rel_path = p.name

                entry = {
                    "role": role.value,
                    "path": rel_path,
                    "content_type": content_type,
                    "bytes": p.stat().st_size,
                    "sha256": sha
                }

                if role in CONTRACT_REGISTRY:
                    entry["contract"] = CONTRACT_REGISTRY[role]
                    entry["interpretation"] = {"mode": "contract"}
                else:
                    entry["interpretation"] = {"mode": "role_only"}

                if role in AUTHORITY_REGISTRY:
                    entry.update(AUTHORITY_REGISTRY[role])

                artifacts_list.append(entry)

    _add_artifact(final_canonical_md, ArtifactRole.CANONICAL_MD, "text/markdown")
    if extras and extras.json_sidecar:
        _add_artifact(final_index_json, ArtifactRole.INDEX_SIDECAR_JSON, "application/json")
    _add_artifact(final_chunk_index, ArtifactRole.CHUNK_INDEX_JSONL, "application/x-ndjson")
    _add_artifact(final_dump_index, ArtifactRole.DUMP_INDEX_JSON, "application/json")
    if sqlite_indices:
        _add_artifact(sqlite_indices[-1], ArtifactRole.SQLITE_INDEX, "application/octet-stream")
    if retrieval_evals:
        _add_artifact(retrieval_evals[-1], ArtifactRole.RETRIEVAL_EVAL_JSON, "application/json")
    if graph_indices:
        _add_artifact(graph_indices[-1], ArtifactRole.GRAPH_INDEX_JSON, "application/json")
    if derived_manifests:
        _add_artifact(derived_manifests[-1], ArtifactRole.DERIVED_MANIFEST_JSON, "application/json")

    # Write output health report BEFORE the bundle manifest is finalized.
    # In this implementation, health checks are anchored to already-materialized primary artifacts
    # (especially dump_index), not to the final bundle manifest entry itself.
    output_health_path = bundle_manifest_path.with_name(
        bundle_manifest_path.name.replace(".bundle.manifest.json", ".output_health.json")
    )
    _output_health_stem = bundle_manifest_path.name.replace(".bundle.manifest.json", "")
    from .output_health import write_output_health
    # Collect expected SHAs from already-computed artifacts_list entries
    _exp_md_sha = next(
        (e["sha256"] for e in artifacts_list if e["role"] == ArtifactRole.CANONICAL_MD.value), None
    )
    _exp_chunk_sha = next(
        (e["sha256"] for e in artifacts_list if e["role"] == ArtifactRole.CHUNK_INDEX_JSONL.value), None
    )
    _exp_eval_sha = next(
        (e["sha256"] for e in artifacts_list if e["role"] == ArtifactRole.RETRIEVAL_EVAL_JSON.value), None
    )
    expected_sqlite_index_path = sqlite_indices[-1] if sqlite_indices else (
        final_chunk_index.with_suffix(".index.sqlite")
        if output_mode in ("retrieval", "dual") and final_chunk_index
        else None
    )
    write_output_health(
        output_health_path,
        run_id=run_id,
        stem=_output_health_stem,
        primary_manifest_path=final_dump_index,
        canonical_md_path=final_canonical_md,
        chunk_index_path=final_chunk_index,
        dump_index_path=final_dump_index,
        sqlite_index_path=expected_sqlite_index_path,
        redact_secrets=redact_secrets,
        canonical_md_required=(output_mode in ("archive", "dual") or _exp_md_sha is not None),
        chunk_index_required=(output_mode in ("retrieval", "dual") or _exp_chunk_sha is not None),
        sqlite_index_required=bool(output_mode in ("retrieval", "dual") and final_chunk_index),
        expected_canonical_md_sha256=_exp_md_sha,
        expected_chunk_index_sha256=_exp_chunk_sha,
        retrieval_eval_path=retrieval_evals[-1] if retrieval_evals else None,
        retrieval_eval_sha256=_exp_eval_sha,
    )
    out_paths.append(output_health_path)
    _add_artifact(output_health_path, ArtifactRole.OUTPUT_HEALTH, "application/json")

    links = {}
    if canonical_dump_index_sha256:
        links["canonical_dump_index_sha256"] = canonical_dump_index_sha256

    config_sha256 = generator_info.get("config_sha256")
    if not config_sha256 or not re.fullmatch(r"[a-f0-9]{64}", config_sha256):
        raise ValueError("generator_info.config_sha256 (64 hex lowercase) is required for bundle manifest provenance")

    # Ensure deterministic artifact ordering for stable machine diffs
    artifacts_list.sort(key=lambda a: (a["role"], a["path"]))

    bundle_manifest = {
        "kind": "repolens.bundle.manifest",
        "version": "1.0",
        "run_id": run_id,
        "created_at": clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {
            "name": generator_info.get("name", "lenskit"),
            "version": generator_info.get("version", "unknown"),
            "config_sha256": config_sha256
        },
        "artifacts": artifacts_list,
        "links": links,
        "capabilities": {
            "fts5_bm25": bool(sqlite_indices),
            "redaction": redact_secrets
        }
    }
    bundle_manifest_path.write_text(json.dumps(bundle_manifest, indent=2), encoding="utf-8")
    out_paths.append(bundle_manifest_path)

    if extras and extras.json_sidecar:
        # JSON is primary when json_sidecar is enabled
        return MergeArtifacts(
            index_json=final_index_json,
            canonical_md=final_canonical_md,
            chunk_index=final_chunk_index,
            md_parts=verified_md,
            dump_index=final_dump_index,
            sqlite_index=sqlite_indices[-1] if sqlite_indices else None,
            retrieval_eval=retrieval_evals[-1] if retrieval_evals else None,
            derived_manifest=derived_manifests[-1] if derived_manifests else None,
            bundle_manifest=bundle_manifest_path,
            output_health=output_health_path,
            other=other_paths
        )
    else:
        # Markdown is primary when json_sidecar is disabled
        return MergeArtifacts(
            index_json=None,
            canonical_md=final_canonical_md,
            chunk_index=final_chunk_index,
            md_parts=verified_md,
            dump_index=final_dump_index,
            sqlite_index=sqlite_indices[-1] if sqlite_indices else None,
            retrieval_eval=retrieval_evals[-1] if retrieval_evals else None,
            derived_manifest=derived_manifests[-1] if derived_manifests else None,
            bundle_manifest=bundle_manifest_path,
            output_health=output_health_path,
            other=other_paths
        )
