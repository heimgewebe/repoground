#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
repoground_extractor – ZIPs im repolens-hub entpacken und Repos aktualisieren.
Verwendet merge_core.

Funktion:
- Suche alle *.zip im Hub (repolens-hub).
- Für jede ZIP:
  - Entpacke in temporären Ordner.
  - Wenn es bereits einen Zielordner mit gleichem Namen gibt:
    - Erzeuge einfachen Diff-Bericht (Markdown) alt vs. neu.
    - Lösche den alten Ordner.
  - Benenne Temp-Ordner in Zielordner um.
  - Lösche die ZIP-Datei.

Diff-Berichte:
- Liegen direkt im merges-Verzeichnis des Hubs.
"""

import sys
import shutil
import zipfile
import datetime
import json
import hashlib
import fnmatch
import os
from pathlib import Path
from typing import Dict, Tuple, Optional, List, Any

try:
    import console  # type: ignore
except ImportError:
    console = None  # type: ignore


def safe_script_path() -> Path:
    """
    Versucht, den Pfad dieses Skripts robust zu bestimmen.

    Reihenfolge:
    1. __file__ (Standard-Python)
    2. sys.argv[0] (z. B. in Shortcuts / eingebetteten Umgebungen)
    3. aktuelle Arbeitsdirectory (Last Resort)
    """
    try:
        return Path(__file__).resolve()
    except NameError:
        # Pythonista / Shortcuts oder exotischer Kontext
        argv0 = None
        try:
            if getattr(sys, "argv", None):
                argv0 = sys.argv[0] or None
        except Exception:
            argv0 = None

        if argv0:
            try:
                return Path(argv0).resolve()
            except Exception:
                pass

        # Fallback: aktuelle Arbeitsdirectory
        return Path.cwd().resolve()


# Cache script path at module level for consistent behavior
SCRIPT_PATH = safe_script_path()
SCRIPT_DIR = SCRIPT_PATH.parent

# Import from core
try:
    from merger.repoground.core.merge import (
        detect_hub_dir,
        get_merges_dir,
        get_repo_snapshot,
        PR_SCHAU_DIR,
    )
except ImportError:
    # SCRIPT_DIR is lenskit/core. Parent is lenskit. Parent is merger.
    sys.path.append(str(SCRIPT_DIR.parent.parent))
    from merger.repoground.core.merge import (
        detect_hub_dir,
        get_merges_dir,
        get_repo_snapshot,
        PR_SCHAU_DIR,
    )


def detect_hub(explicit_hub: Optional[str] = None) -> Path:
    return detect_hub_dir(SCRIPT_PATH, explicit_hub)


def build_delta_meta_from_diff(
    only_old: List[str],
    only_new: List[str],
    changed: List[Tuple[str, int, int, str, str, str, str]],
    base_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Builds a delta metadata dict conforming to repolens-delta.schema.json.

    Args:
        only_old: List of files removed
        only_new: List of files added
        changed: List of changed file tuples (path, size_old, size_new, ...)
        base_timestamp: Optional timestamp of base import

    Returns:
        Delta metadata dict conforming to schema
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    delta_meta = {
        "type": "repolens-delta",
        "base_import": base_timestamp or now.isoformat(),
        "current_timestamp": now.isoformat(),
        "summary": {
            "files_added": len(only_new),
            "files_removed": len(only_old),
            "files_changed": len(changed),
        },
        # Optional: detailed lists (extension to schema)
        "files_added": list(only_new),
        "files_removed": list(only_old),
        "files_changed": [
            {
                "path": item[0],
                "size_delta": item[2] - item[1],  # size_new - size_old
            }
            for item in changed
        ],
    }

    return delta_meta


def extract_delta_meta_from_diff_file(diff_path: Path) -> Optional[Dict[str, Any]]:
    """
    Extract delta metadata from an import-diff file.

    Args:
        diff_path: Path to the import-diff markdown file

    Returns:
        Delta metadata dict conforming to repolens-delta.schema.json,
        or None if extraction fails
    """
    try:
        text = diff_path.read_text(encoding="utf-8")

        # Extract base timestamp from diff file if available
        base_timestamp = None
        lines = text.splitlines()
        for line in lines:
            if line.strip().startswith("- Zeitpunkt:"):
                # Try to extract timestamp, but don't fail if it's malformed
                try:
                    ts_part = line.split("`")[1]
                    # Expected format: "YYYY-MM-DD HH:MM:SS"
                    # Timestamp from diff_trees() is always in this format
                    # We assume UTC timezone as diff_trees uses datetime.now() without timezone
                    dt = datetime.datetime.strptime(ts_part, "%Y-%m-%d %H:%M:%S")
                    base_timestamp = dt.replace(tzinfo=datetime.timezone.utc).isoformat()
                except (IndexError, ValueError):
                    pass
                break

        rows = parse_import_diff_table(text)

        # Auch bei fehlender Tabelle ein „leeres“ Delta zurückgeben, um Stale-Fallbacks zu vermeiden
        if not rows:
            return build_delta_meta_from_diff([], [], [], base_timestamp)

        # Categorize rows
        only_old = [r["path"] for r in rows if r["status"] == "removed"]
        only_new = [r["path"] for r in rows if r["status"] == "added"]
        # Format: (path, size_old, size_new, md5_old, md5_new, cat_old, cat_new)
        # MD5 and category fields aren't used by build_delta_meta_from_diff, so we pass empty strings
        changed = [
            (r["path"], r["size_old"] or 0, r["size_new"] or 0, "", "", "", "")
            for r in rows if r["status"] == "changed"
        ]

        return build_delta_meta_from_diff(only_old, only_new, changed, base_timestamp)

    except Exception as e:
        sys.stderr.write(f"Warning: Failed to extract delta meta from {diff_path}: {e}\n")
        return None


def diff_trees(
    old: Path,
    new: Path,
    repo_name: str,
    merges_dir: Path,
) -> Path:
    """
    Vergleicht zwei Repo-Verzeichnisse und schreibt einen Markdown-Diff-Bericht.

    Neu: „Manifest-Anklang“
      - kleine Tabelle mit Pfad, Status, Kategorie, Größen und MD5-Änderung
      - Kategorien stammen aus merge_core.classify_file_v2 via get_repo_snapshot

    Rückgabe:
      Pfad zur Diff-Datei.
    """
    # Snapshot-Maps:
    #   rel_path -> (size, md5, category)
    old_map = get_repo_snapshot(old)
    new_map = get_repo_snapshot(new)

    old_keys = set(old_map.keys())
    new_keys = set(new_map.keys())

    only_old = sorted(old_keys - new_keys)
    only_new = sorted(new_keys - old_keys)
    common = sorted(old_keys & new_keys)

    # Für gemeinsame Dateien merken wir uns auch MD5 und Kategorien
    changed = []
    for rel in common:
        size_old, md5_old, cat_old = old_map[rel]
        size_new, md5_new, cat_new = new_map[rel]
        if size_old != size_new or md5_old != md5_new:
            changed.append((rel, size_old, size_new, md5_old, md5_new, cat_old, cat_new))

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts = datetime.datetime.now().strftime("%y%m%d-%H%M%S")
    fname = "{}-import-diff-{}.md".format(repo_name, ts)
    out_path = merges_dir / fname

    lines: List[str] = []
    lines.append("# Import-Diff `{}`".format(repo_name))
    lines.append("")
    lines.append("- Zeitpunkt: `{}`".format(now))
    lines.append("- Alter Pfad: `{}`".format(old))
    lines.append("- Neuer Pfad (Temp): `{}`".format(new))
    lines.append("")
    lines.append("- Dateien nur im alten Repo: **{}**".format(len(only_old)))
    lines.append("- Dateien nur im neuen Repo: **{}**".format(len(only_new)))
    lines.append("- Dateien mit geändertem Inhalt: **{}**".format(len(changed)))
    lines.append("")

    # Manifest-artige Tabelle: ein Eintrag pro betroffener Datei
    any_rows = bool(only_old or only_new or changed)

    # Immer Delta-Metadaten neben das Diff schreiben – auch wenn keine Änderungen vorliegen
    try:
        delta_meta = build_delta_meta_from_diff(only_old, only_new, changed)
        delta_json_path = out_path.with_suffix(".delta.json")
        delta_json_path.write_text(
            json.dumps(delta_meta, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to save delta metadata: {e}\n")

    if any_rows:
        lines.append("## Dateiliste (Manifest-Stil)")
        lines.append("")
        lines.append(
            "| Pfad | Status | Kategorie | Größe alt | Größe neu | Δ Größe | MD5 geändert |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: | --- |")

        # Entfernte Dateien
        for rel in only_old:
            size_old, md5_old, cat_old = old_map[rel]
            lines.append(
                "| `{path}` | removed | `{cat}` | {s_old} | - | -{delta} | n/a |".format(
                    path=rel,
                    cat=cat_old,
                    s_old=size_old,
                    delta=size_old,
                )
            )

        # Neue Dateien
        for rel in only_new:
            size_new, md5_new, cat_new = new_map[rel]
            lines.append(
                "| `{path}` | added | `{cat}` | - | {s_new} | +{delta} | n/a |".format(
                    path=rel,
                    cat=cat_new,
                    s_new=size_new,
                    delta=size_new,
                )
            )

        # Geänderte Dateien
        for (
            rel,
            s_old,
            s_new,
            md5_old,
            md5_new,
            cat_old,
            cat_new,
        ) in changed:
            delta = s_new - s_old
            md5_changed = "ja" if md5_old != md5_new else "nein"
            # Falls sich die Kategorie ändert (selten), neue Kategorie anzeigen
            cat_display = cat_new or cat_old
            lines.append(
                "| `{path}` | changed | `{cat}` | {s_old} | {s_new} | {delta:+d} | {md5_flag} |".format(
                    path=rel,
                    cat=cat_display,
                    s_old=s_old,
                    s_new=s_new,
                    delta=delta,
                    md5_flag=md5_changed,
                )
            )

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _construct_logical_payload(header_lines: List[str], content_chunks: List[str]) -> str:
    """
    Constructs the logical payload text from header and content chunks.

    This function serves as the Single Source of Truth for:
    1. Calculating expected_bytes
    2. (Conceptually) Generating single-file content (though parts are flushed directly)

    Logic: "\n".join(header_lines + content_chunks)
    """
    return "\n".join(header_lines + content_chunks)


def _compute_sha256_with_size(path: Path) -> Tuple[Optional[str], int, Optional[str]]:
    """
    Computes SHA256 and size for a file.
    Returns (sha, size, error_code).
    error_code is None on success, or one of "missing", "permission", "io_error", "error".
    """
    try:
        with path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            h = hashlib.sha256()
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest(), size, None
    except FileNotFoundError:
        return None, 0, "missing"
    except PermissionError:
        return None, 0, "permission"
    except OSError:
        return None, 0, "io_error"
    except Exception:
        return None, 0, "error"


def _compute_sha256(path: Path) -> Optional[str]:
    """Computes SHA256 for a file. Returns None on failure."""
    sha, _, _ = _compute_sha256_with_size(path)
    return sha


def _is_secret_file(path_str: str) -> bool:
    """Checks for sensitive files based on naming patterns."""
    name = Path(path_str).name
    patterns = [
        ".env*",
        "*.pem",
        "*.key",
        "id_rsa*",
        "*token*",
        "secrets*",
        "*.p12",
        "*.pfx",
        "*.kdbx",
    ]
    for pat in patterns:
        if fnmatch.fnmatch(name, pat):
            return True
    return False


def _heuristic_category(rel_path: str) -> str:
    """
    Determine heuristic category for review bundles.
    """
    p = Path(rel_path)
    name = p.name.lower()
    ext = p.suffix.lower()
    parts = p.parts

    # Schema/Contracts
    if name.endswith(".schema.json") or "contracts" in parts:
        return "schema"

    # CI
    if ".github" in parts and "workflows" in parts:
        return "ci"
    if "ci" in parts:
        return "ci"

    # Config (explicit heuristic)
    if "config" in parts or ext in (".yml", ".yaml", ".toml", ".ini"):
        return "config"
    if name in ("package.json", "dockerfile", "makefile", "justfile"):
        return "config"

    # Docs
    if ext in (".md", ".txt", ".rst") or "docs" in parts:
        return "docs"

    # Code
    if ext in (".py", ".js", ".ts", ".rs", ".go", ".c", ".cpp", ".h", ".java", ".rb", ".sh"):
        return "code"

    return "other"


def _content_looks_like_secret(text: str) -> bool:
    # Heuristik: wenige, harte Patterns. Keine False-Positive-Panik, lieber einmal zu viel redacted.
    # Convert to lower case for insensitive check
    text_lower = text.lower()
    patterns = [
        "ghp_", "github_pat_",                    # GitHub tokens
        "akia",                                   # AWS access key prefix
        "-----begin private key-----",
        "-----begin rsa private key-----",
        "-----begin openssh private key-----",
        "bearer ",                                # OAuth bearer
        "xoxb-", "xoxp-",                         # Slack tokens
        "aiza",                                   # Google API key prefix
    ]
    # Simple check, no regex for performance and simplicity
    for p in patterns:
        if p in text_lower:
            return True
    return False


def generate_review_bundle(
    old_repo: Path, new_repo: Path, repo_name: str, hub: Path
) -> None:
    """
    Erzeugt ein persistentes 'PR-Schau'-Bundle aus dem Vergleich zweier Repo-Stände.
    Das Bundle wird unter wc-hub/.repoground/pr-schau/<repo>/<timestamp>/ abgelegt.

    Enthält:
    - delta.json (Format 1)
    - review.md (Content)
    - bundle.json (Meta)
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    ts_folder = now_utc.strftime("%Y-%m-%dT%H%M%SZ")

    # Bundle Output Directory (using centralized constant)
    bundle_dir = hub / PR_SCHAU_DIR / repo_name / ts_folder
    bundle_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Erzeuge PR-Review-Bundle in: {bundle_dir}")

    # Snapshots holen (basierend auf lenskit.core.merge Logik)
    # get_repo_snapshot liefert: Dict[rel_path] -> (size, md5, category)
    # Wir brauchen aber SHA256 und echten Content, also scannen wir die Keys
    # und lesen dann gezielt.

    old_snap = get_repo_snapshot(old_repo)
    new_snap = get_repo_snapshot(new_repo)

    old_files = set(old_snap.keys())
    new_files = set(new_snap.keys())

    added = sorted(list(new_files - old_files))
    removed = sorted(list(old_files - new_files))
    common = old_files & new_files

    changed = []
    for f in common:
        # Robust snapshot unpacking
        tup_old = old_snap.get(f, ())
        tup_new = new_snap.get(f, ())

        s_old = tup_old[0] if len(tup_old) > 0 else 0
        m_old = tup_old[1] if len(tup_old) > 1 else ""

        s_new = tup_new[0] if len(tup_new) > 0 else 0
        m_new = tup_new[1] if len(tup_new) > 1 else ""

        if s_old != s_new or m_old != m_new:
            changed.append(f)
    changed.sort()

    # --- 1. delta.json ---
    delta_files = []

    # Helper to build file entry
    def make_entry(rel_path, status, root_path):
        fpath = root_path / rel_path

        # Simple heuristic for suspicious patterns
        lower_path = rel_path.lower()
        suspicious = []
        if "secret" in lower_path or "password" in lower_path:
            suspicious.append("secret")
        if "auth" in lower_path:
            suspicious.append("auth")
        if "migration" in lower_path:
            suspicious.append("migration")

        if status == "removed":
            size = old_snap[rel_path][0] if rel_path in old_snap else 0
            return {
                "path": rel_path,
                "status": status,
                "category": _heuristic_category(rel_path),
                "size_bytes": size,
                "sha256": None,
                "sha256_status": "skipped",
                "affected_chunk_ids": [],
                "suspicious_patterns": suspicious
            }

        # For added/changed: use robust computation
        sha, size, error_code = _compute_sha256_with_size(fpath)

        sha_status = "ok" if sha else (error_code or "error")

        return {
            "path": rel_path,
            "status": status,
            "category": _heuristic_category(rel_path),
            "size_bytes": size,
            "sha256": sha,
            "sha256_status": sha_status,
            "affected_chunk_ids": [],
            "suspicious_patterns": suspicious
        }

    # Populate delta_files with prioritization for review order
    # Priority: schema > ci > config > docs > code > other
    # Sort order mapping
    cat_prio = {"schema": 0, "ci": 1, "config": 2, "docs": 3, "code": 4, "other": 5}

    # We collect all entries first
    all_entries = []
    for f in added:
        all_entries.append(make_entry(f, "added", new_repo))
    for f in changed:
        all_entries.append(make_entry(f, "changed", new_repo))
    for f in removed:
        all_entries.append(make_entry(f, "removed", old_repo))

    # Sort for delta.json (optional, but good for consistency)
    # Primary sort: Status (added/changed/removed) - actually standard is usually by path or status.
    # Let's keep delta.json strictly sorted by path to be canonical.
    delta_files = sorted(all_entries, key=lambda x: x["path"])

    delta_json = {
        "kind": "repolens.pr_schau.delta",
        "version": 1,
        "repo": repo_name,
        "generated_at": now_utc.isoformat(),
        "summary": {
            "added": len(added),
            "changed": len(changed),
            "removed": len(removed)
        },
        "files": delta_files
    }

    (bundle_dir / "delta.json").write_text(
        json.dumps(delta_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # --- 2. review.md (Content Splitting & Zones) ---
    MAX_PART_SIZE = 200 * 1024 # 200 KB per part threshold
    MAX_INLINE_SIZE = 200 * 1024 # 200 KB max file content size

    # Sort files for review order
    def review_sort_key(item):
        cat = item.get("category", "other")
        prio = cat_prio.get(cat, 99)
        return (prio, item["path"])

    review_files = sorted(all_entries, key=review_sort_key)

    # -- Part 1 Header --
    header_lines = []
    header_lines.append(f"# PR-Review: {repo_name}")

    header_lines.append("<!-- zone:begin type=\"summary\" -->")
    header_lines.append(f"- **Date:** {now_utc.isoformat()}")
    header_lines.append(f"- **Summary:** +{len(added)} / ~{len(changed)} / -{len(removed)}")
    header_lines.append("<!-- zone:end -->")
    header_lines.append("")

    # Hotspots check (extended heuristic)
    hotspots = []
    for f in (added + changed):
        # Original
        if f.startswith(".github/") or f.startswith("contracts/") or f.endswith(".schema.json"):
            hotspots.append(f)
            continue
        # Extended
        if f.startswith("ci/") or f.startswith("scripts/") or f.startswith("config/"):
            hotspots.append(f)
            continue

    if hotspots:
        header_lines.append("<!-- zone:begin type=\"hotspots\" -->")
        header_lines.append("## 🔥 Hotspots")
        for h in sorted(hotspots)[:10]: # Limit list
            header_lines.append(f"- `{h}`")
        if len(hotspots) > 10:
            header_lines.append(f"- ... ({len(hotspots)-10} more)")
        header_lines.append("<!-- zone:end -->")
        header_lines.append("")

    # Files Manifest
    header_lines.append("<!-- zone:begin type=\"files_manifest\" -->")
    header_lines.append("## Details")
    header_lines.append("")
    for item in review_files:
        path = item["path"]
        status = item["status"]
        icon = "❌" if status == "removed" else ("🆕" if status == "added" else "📝")
        header_lines.append(f"- {icon} `{path}` ({item['size_bytes']} bytes)")
    header_lines.append("<!-- zone:end -->")
    header_lines.append("")

    # Calculate content for diffs
    content_chunks = [] # List of strings (blocks)

    # Pre-calculate content to enable splitting (logical, un-splitted payload)
    content_chunks.append("<!-- zone:begin type=\"diff\" -->")

    def _normalize_list(lst: List[str]) -> List[str]:
        """Ensure all strings use strictly \n, removing potential \r."""
        return [s.replace("\r\n", "\n").replace("\r", "\n") for s in lst]

    for item in review_files:
        path = item["path"]
        status = item["status"]

        block = []
        if status == "removed":
            block.append(f"### ❌ `{path}` (Removed)")
            block.append(f"- Size: {item['size_bytes']} bytes")
            block.append("")
        else:
            # Added or Changed
            block.append(f"### {'🆕' if status == 'added' else '📝'} `{path}`")
            block.append(f"- Status: {status}")
            block.append(f"- Size: {item['size_bytes']} bytes")
            if item.get("sha256"):
                block.append(f"- SHA256: `{item['sha256']}`")
            else:
                block.append("- SHA256: (n/a)")

            # Security / Binary / Size checks
            skip_content = False
            if _is_secret_file(path):
                block.append("\n> 🔒 **REDACTED (filename rule)**\n")
                skip_content = True
            elif item["size_bytes"] > MAX_INLINE_SIZE:
                 block.append(f"\n> ⚠️ **Omitted (Size > {MAX_INLINE_SIZE/1024:.0f}KB)**\n")
                 skip_content = True

            if not skip_content:
                # Read Content
                fpath = new_repo / path
                try:
                    # Check for binary content
                    with fpath.open("rb") as bf:
                        chunk = bf.read(4096)
                        if b"\x00" in chunk:
                            block.append("\n> 💾 **Binary File**\n")
                            skip_content = True

                    if not skip_content:
                        # Read text
                        text_content = fpath.read_text(encoding="utf-8", errors="replace")

                        # Check for secret content
                        if _content_looks_like_secret(text_content):
                            block.append("\n> 🔒 **REDACTED (content rule)**\n")
                        else:
                            # Extension for code block
                            p_obj = Path(path)
                            ext = p_obj.suffix.lstrip(".") or "txt"
                            if p_obj.name.endswith(".schema.json") or ext == "json":
                                ext = "json"
                            elif ext in ("yml", "yaml"):
                                ext = "yaml"

                            block.append("")
                            block.append(f"```{ext}")
                            block.append(text_content)
                            block.append("```")
                except Exception as e:
                    block.append(f"\n> ⚠️ Error reading content: {e}\n")

            block.append("")

        content_chunks.append("\n".join(block))

    content_chunks.append("<!-- zone:end -->")

    # Harden: Normalize inputs to ensure byte-exactness holds across all potential input anomalies
    header_lines = _normalize_list(header_lines)
    content_chunks = _normalize_list(content_chunks)

    # Splitting Logic
    parts_created = []
    current_part_lines = list(header_lines)
    current_part_size = sum(len(l.encode('utf-8')) + 1 for l in current_part_lines) # +1 for newline
    part_idx = 1

    # Helper to flush current part
    def flush_part(idx, lines):
        fname = "review.md" if idx == 1 else f"review_part{idx}.md"
        out_path = bundle_dir / fname
        text = "\n".join(lines)
        # Enforce LF for exact byte accounting across platforms
        with out_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return fname

    for chunk in content_chunks:
        # chunk is a multi-line block; we add it as one entry (with newline via join)
        chunk_size = len(chunk.encode('utf-8')) + 1

        # If adding this chunk exceeds limit and we have content (header excluded if part > 1), flush
        # Note: header is always in part 1. Part 2+ start empty or with continuation header.
        if current_part_size + chunk_size > MAX_PART_SIZE and len(current_part_lines) > 0:
             # Flush current
             pname = flush_part(part_idx, current_part_lines)
             parts_created.append(pname)

             # Start next part
             part_idx += 1
             # continuation header (counts as overhead by design)
             current_part_lines = [f"# PR-Review (Part {part_idx})"]
             current_part_size = len(current_part_lines[0].encode('utf-8')) + 1

        current_part_lines.append(chunk)
        current_part_size += chunk_size

    # Flush last part
    if current_part_lines:
        pname = flush_part(part_idx, current_part_lines)
        parts_created.append(pname)

    # --- 3. bundle.json ---
    # Construct artifacts list for v1 schema
    artifacts_list = []

    # Bundle itself (index)
    artifacts_list.append({
        "role": "index_json",
        "basename": "bundle.json",
        "content_type": "application/json",
        "bytes": 0, # Placeholder, updated via Fixpoint 2-pass write below
        "mime": "application/json" # Legacy alias
    })

    # Delta JSON
    delta_json_path = bundle_dir / "delta.json"
    if delta_json_path.exists():
        sha_delta, size_delta, _ = _compute_sha256_with_size(delta_json_path)
        artifacts_list.append({
            "role": "delta_json",
            "basename": "delta.json",
            "content_type": "application/json",
            "bytes": size_delta,
            "sha256": sha_delta,
            "mime": "application/json"
        })

    # Collect parts artifacts
    emitted_bytes = 0
    # expected_bytes must be exact: byte-size of the logical, un-splitted payload
    logical_text = _construct_logical_payload(header_lines, content_chunks)
    expected_bytes = len(logical_text.encode("utf-8"))

    for pname in parts_created:
        ppath = bundle_dir / pname
        sha, psize, error = _compute_sha256_with_size(ppath)
        if error or not sha or len(sha) != 64:
            raise RuntimeError(f"Bundle part missing or computation failed: {ppath} (error={error})")

        emitted_bytes += psize

        role = "canonical_md" if pname == "review.md" else "part_md"
        artifacts_list.append({
            "role": role,
            "basename": pname,
            "content_type": "text/markdown",
            "bytes": psize,
            "sha256": sha,
            "mime": "text/markdown"
        })

    # Sort artifacts by role/basename for determinism
    artifacts_list.sort(key=lambda x: (x["role"], x["basename"]))

    bundle_meta = {
        "kind": "repolens.pr_schau.bundle",
        "version": "1.0",
        "meta": {
            "repo": repo_name,
            "generated_at": now_utc.isoformat(),
            "generator": {
                "name": "repolens-extractor",
                "component": "core",
                "version": "2.4.0"
            }
        },
        "view_mode": "full",
        "content_scope": "mixed",
        "completeness": {
            "is_complete": True,
            "policy": "split",
            "parts": parts_created,
            "primary_part": "review.md",
            "expected_bytes": expected_bytes,
            "emitted_bytes": emitted_bytes
        },
        "artifacts": artifacts_list,
        "verification": {
            "checked_at": now_utc.isoformat(),
            "checker": {
                "name": "repolens-extractor",
                "version": "2.4.0"
            },
            "level": "basic"
        }
    }

    bundle_json_path = bundle_dir / "bundle.json"

    # Fixpoint 2-pass (size depends on embedded size value)
    # Loop max 3 times to stabilize bytes (usually stabilizes in 2)
    current_size = 0

    # Initial write (bytes=0 placeholder)
    bundle_json_path.write_text(
        json.dumps(bundle_meta, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    for i in range(3):
        try:
            current_size = bundle_json_path.stat().st_size

            # Load, update, write
            data = json.loads(bundle_json_path.read_text(encoding="utf-8"))
            found_self = False
            changed = False

            # Update self-reference
            if "artifacts" in data:
                for art in data["artifacts"]:
                    if art.get("role") == "index_json" and art.get("basename") == "bundle.json":
                        found_self = True
                        if art.get("bytes") != current_size:
                            art["bytes"] = current_size
                            changed = True
                        break

            if not found_self:
                sys.stderr.write("Warning: bundle.json self-artifact entry not found during stabilization.\n")
                break

            if not changed:
                # Stable state reached
                break

            bundle_json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
            )

            # Check convergence immediately
            new_size = bundle_json_path.stat().st_size
            if new_size == current_size:
                break

        except Exception as e:
            sys.stderr.write(f"Warning: Failed to stabilize bundle.json size: {e}\n")
            break

    # Post-stabilization check
    try:
        data = json.loads(bundle_json_path.read_text(encoding="utf-8"))
        found_self = False
        for art in data.get("artifacts", []):
             if art.get("role") == "index_json" and art.get("basename") == "bundle.json":
                 found_self = True
                 if art.get("bytes", 0) == 0:
                     sys.stderr.write("Warning: bundle.json bytes is still 0 after stabilization.\n")
                 break
        if not found_self:
            sys.stderr.write("Warning: bundle.json self-artifact entry missing after stabilization.\n")
    except Exception:
        pass

    # Note on SHA256: We intentionally skip adding a self-referential SHA256 to the bundle.json entry
    # to avoid the logical impossibility of a file containing its own hash.


def import_zip(zip_path: Path, hub: Path, merges_dir: Path) -> Optional[Path]:
    """
    Entpackt eine einzelne ZIP-Datei in den Hub, behandelt Konflikte,
    schreibt ggf. Diff und ersetzt das alte Repo.

    Rückgabe:
      Pfad zum Diff-Bericht oder None.
    """
    repo_name = zip_path.stem
    target_dir = hub / repo_name
    tmp_dir = hub / ("__extract_tmp_" + repo_name)

    print("Verarbeite ZIP:", zip_path.name, "-> Repo", repo_name)

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    tmp_dir.mkdir(parents=True, exist_ok=True)

    # ZIP entpacken
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(tmp_dir)

    diff_path = None  # type: Optional[Path]

    # Wenn es schon ein Repo mit diesem Namen gibt -> Diff + Bundle + löschen
    if target_dir.exists():
        print("  Zielordner existiert bereits:", target_dir)

        # 1. PR-Review-Bundle erzeugen (Kritisch: muss VOR Löschung passieren)
        try:
            generate_review_bundle(target_dir, tmp_dir, repo_name, hub)
            print("  PR-Review-Bundle erfolgreich erstellt.")
        except Exception as e:
            print(f"  ❌ FEHLER bei PR-Bundle-Erstellung: {e}")
            print("  ⚠️ ABBRUCH: Alter Ordner wird NICHT gelöscht, um Datenverlust zu vermeiden.")
            # Aufräumen des Temp-Ordners
            shutil.rmtree(tmp_dir)
            raise e  # Hard stop

        # 2. Legacy Diff (Optional, but kept for compatibility as 'diff work state')
        try:
            diff_path = diff_trees(target_dir, tmp_dir, repo_name, merges_dir)
            print("  Diff-Bericht:", diff_path)
        except Exception as e:
            print(f"  Warnung: Fehler beim Diff-Erstellen ({e}). Fahre fort.")

        # 3. Löschen
        shutil.rmtree(target_dir)
        print("  Alter Ordner gelöscht:", target_dir)
    else:
        print("  Kein vorhandenes Repo – frischer Import.")

    # Temp-Ordner ins Ziel verschieben
    tmp_dir.rename(target_dir)
    print("  Neuer Repo-Ordner:", target_dir)

    # ZIP nach erfolgreichem Import löschen
    try:
        zip_path.unlink()
        print("  ZIP gelöscht:", zip_path.name)
    except OSError as e:
        print(f"  Warnung: Konnte ZIP nicht löschen ({e})")
    print("")

    return diff_path


def import_zip_wrapper(zip_path: Path, hub: Path, merges_dir: Path) -> Optional[Path]:
    """Wraps import_zip, erzeugt optional Delta-Merge und sorgt für Cleanup."""
    diff_path: Optional[Path] = None
    try:
        # Normalen Import + Diff laufen lassen
        diff_path = import_zip(zip_path, hub, merges_dir)

        # Automatisch Delta-Merge erzeugen, wenn ein Diff existiert
        if diff_path is not None:
            repo_name = zip_path.stem
            repo_root = hub / repo_name
            if repo_root.exists():
                try:
                    delta_path = create_delta_merge_from_diff(
                        diff_path, repo_root, merges_dir, profile="delta-full"
                    )
                    print(f"  Delta-Merge: {delta_path}")
                except Exception as e:
                    print(f"  Warnung: Konnte Delta-Merge nicht erzeugen ({e}).")

        return diff_path
    except Exception:
        raise
    finally:
        if zip_path.exists():
            try:
                zip_path.unlink()
                print(f"  Cleanup: ZIP gelöscht ({zip_path.name})")
            except OSError:
                pass


def _console_alert(title: str, msg: str) -> None:
    if console:
        try:
            console.alert(title, msg, "OK", hide_cancel_button=True)
        except Exception:
            pass
    else:
        sys.stderr.write(f"[{title}] {msg}\n")


def _state_path(merges_dir: Path) -> Path:
    return merges_dir / ".extractor_state.json"


def _zip_fingerprint(zip_path: Path) -> Dict[str, Any]:
    st = zip_path.stat()
    return {
        "name": zip_path.name,
        "mtime": int(st.st_mtime),
        "size": int(st.st_size),
    }


def _read_state(merges_dir: Path) -> Dict[str, Any]:
    p = _state_path(merges_dir)
    try:
        if not p.exists():
            return {}
        return json.loads(p.read_text("utf-8"))
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to read extractor state: {e}\n")
        return {}


def _write_state(merges_dir: Path, state: Dict[str, Any]) -> None:
    p = _state_path(merges_dir)
    try:
        p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to write extractor state: {e}\n")


def run_extractor(
    hub_override: Optional[Path] = None,
    show_alert: bool = False,
    incremental: bool = True,
) -> Tuple[int, str]:
    """Programmatic entry point for callers like RepoGround build.

    By default: quiet (no alerts), best-effort, returns a status+message.
    """
    if hub_override is not None:
        hub = hub_override
    else:
        try:
            hub = detect_hub_dir(SCRIPT_PATH)
        except FileNotFoundError as e:
            msg = f"Working Copy Hub not found. {e}"
            if show_alert:
                _console_alert(msg, "Please open Working Copy at least once.")
            return 1, msg

    merges_dir = get_merges_dir(hub)
    zips = sorted(hub.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        msg = "No .zip imports found in hub"
        if show_alert:
            _console_alert("No imports found", msg)
        return 0, msg

    newest = zips[0]
    newest_fp = _zip_fingerprint(newest)
    prev_state = _read_state(merges_dir)

    if incremental:
        prev_fp = prev_state.get("newest_zip", {})
        if (
            isinstance(prev_fp, dict)
            and prev_fp.get("name") == newest_fp.get("name")
            and int(prev_fp.get("mtime", -1)) == int(newest_fp.get("mtime"))
            and int(prev_fp.get("size", -1)) == int(newest_fp.get("size"))
        ):
            msg = "No new hub zip detected; extractor skipped (incremental)."
            if show_alert:
                _console_alert("Extractor skipped", msg)
            return 0, msg

    processed = 0
    failures = 0
    for zp in zips:
        try:
            diff_path = import_zip_wrapper(zp, hub, merges_dir)
            if diff_path is not None:
                processed += 1
        except Exception as e:
            sys.stderr.write(f"Error processing {zp.name}: {e}\n")
            failures += 1

    # Update state after a run (even if some failures happened)
    _write_state(merges_dir, {"newest_zip": newest_fp})

    msg = f"imports processed: {processed}, failures: {failures}, hub zips: {len(zips)}, incremental: {incremental}"
    if show_alert:
        _console_alert("Extractor finished", msg)
    return (0 if failures == 0 else 2), msg


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="repolens-extractor-v2: Import ZIPs to hub.")
    parser.add_argument("--hub", help="Hub directory override.")
    args = parser.parse_args()

    try:
        hub = detect_hub_dir(SCRIPT_PATH, args.hub)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not hub.exists():
         print(f"Hub directory not found: {hub}")
         return 1

    merges_dir = get_merges_dir(hub)

    print("RepoGround extractor – Hub:", hub)
    zips = sorted(hub.glob("*.zip"))

    if not zips:
        msg = "Keine ZIP-Dateien im Hub gefunden."
        print(msg)
        if console:
            console.alert("RepoGround extractor", msg, "OK", hide_cancel_button=True)
        return 0

    diff_paths = []

    for zp in zips:
        try:
            diff = import_zip_wrapper(zp, hub, merges_dir)
            if diff is not None:
                diff_paths.append(diff)
        except Exception as e:
            print("Fehler bei {}: {}".format(zp, e), file=sys.stderr)

    summary_lines = []
    summary_lines.append("Import fertig.")
    summary_lines.append("Hub: {}".format(hub))
    if diff_paths:
        summary_lines.append(
            "Diff-Berichte ({}):".format(len(diff_paths))
        )
        for p in diff_paths:
            summary_lines.append("  - {}".format(p))
    else:
        summary_lines.append("Keine Diff-Berichte erzeugt.")

    summary = "\n".join(summary_lines)
    print(summary)

    if console:
        console.alert("RepoGround extractor", summary, "OK", hide_cancel_button=True)

    return 0



# ---------------------------------------------------------------------------
# Diff-Parser (Prototyp)
# ---------------------------------------------------------------------------

def parse_import_diff_table(text: str) -> List[Dict[str, Any]]:
    """
    Parst die „Dateiliste (Manifest-Stil)“-Tabelle aus einem Import-Diff.

    Rückgabe:
      Liste von Dicts mit Schlüsseln:
        - path: str
        - status: "added" | "removed" | "changed"
        - category: str
        - size_old: Optional[int]
        - size_new: Optional[int]
        - delta: Optional[int]
        - md5_changed: Optional[bool]  # True/False/nicht verfügbar

    Wenn die Tabelle nicht gefunden wird, wird eine leere Liste zurückgegeben.
    """
    lines = text.splitlines()

    # Header-Zeile der Tabelle finden
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("| Pfad | Status | Kategorie |"):
            header_idx = i
            break

    if header_idx is None or header_idx + 2 >= len(lines):
        return []

    # Nach der Headerzeile kommt die Separatorzeile, danach die Datenzeilen
    rows = []
    i = header_idx + 2
    while i < len(lines):
        line = lines[i]
        if not line.strip().startswith("|"):
            break
        # Spalten extrahieren: | col1 | col2 | ... |
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 7:
            i += 1
            continue

        path_raw, status, category_raw, s_old_raw, s_new_raw, delta_raw, md5_flag_raw = parts[:7]

        def _strip_ticks(s):
            s = s.strip()
            if s.startswith("`") and s.endswith("`") and len(s) >= 2:
                return s[1:-1]
            return s

        path = _strip_ticks(path_raw)
        category = _strip_ticks(category_raw)

        def _parse_int_or_none(s):
            s = s.strip()
            if s == "-" or not s:
                return None
            try:
                return int(s.replace("+", ""))
            except ValueError:
                return None

        size_old = _parse_int_or_none(s_old_raw)
        size_new = _parse_int_or_none(s_new_raw)
        delta = _parse_int_or_none(delta_raw)

        md5_flag = md5_flag_raw.strip().lower()
        if md5_flag in ("ja", "yes", "true"):
            md5_changed = True
        elif md5_flag in ("nein", "no", "false"):
            md5_changed = False
        else:
            md5_changed = None

        rows.append(
            {
                "path": path,
                "status": status.strip(),
                "category": category,
                "size_old": size_old,
                "size_new": size_new,
                "delta": delta,
                "md5_changed": md5_changed,
            }
        )
        i += 1

    return rows


# ---------------------------------------------------------------------------
# Delta-Merge auf Basis des Import-Diffs
# ---------------------------------------------------------------------------

def build_delta_merge_report(
    repo_root: Path,
    repo_name: str,
    diff_rows: List[Dict[str, Any]],
    merges_dir: Path,
    profile: str = "delta-full",
) -> Path:
    """
    Erzeugt einen WC-Merger-kompatiblen Delta-Report auf Basis eines
    Import-Diffs (parse_import_diff_table).

    Standardverhalten:
      - Status "changed" und "added" → mit Inhalt
      - Status "removed"             → nur im Manifest / Summary
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%y%m%d-%H%M")
    fname = f"{repo_name}_{profile}_delta_{ts}_merge.md"
    out_path = merges_dir / fname

    rows = list(diff_rows or [])
    changed = [r for r in rows if r.get("status") == "changed"]
    added = [r for r in rows if r.get("status") == "added"]
    removed = [r for r in rows if r.get("status") == "removed"]

    lines = []
    lines.append("# WC-Merger Delta Report (v2.x)")
    lines.append("")
    lines.append("## Source & Profile")
    lines.append(f"- **Source:** {repo_name}")
    lines.append(f"- **Profile:** `{profile}`")
    lines.append(f"- **Generated At:** {now.isoformat()} (UTC)")
    lines.append("- **Spec-Version:** 2.3")
    lines.append(
        f"- **Declared Purpose:** Delta-Merge – changed+added files for `{repo_name}`"
    )
    lines.append(f"- **Scope:** single repo `{repo_name}`")
    lines.append("")

    lines.append("## Change Summary")
    lines.append("")
    lines.append(f"- Changed files: **{len(changed)}**")
    lines.append(f"- Added files: **{len(added)}**")
    lines.append(f"- Removed files: **{len(removed)}**")
    lines.append("")

    if rows:
        lines.append("## File Manifest (Delta)")
        lines.append("")
        lines.append(
            "| Pfad | Status | Kategorie | Größe alt | Größe neu | Δ Größe | MD5 geändert |"
        )
        lines.append("| --- | --- | --- | ---: | ---: | ---: | --- |")

        def _fmt_int(v):
            if v is None:
                return "-"
            return str(v)

        for row in rows:
            path = row.get("path", "")
            status = row.get("status", "")
            category = row.get("category") or "-"
            size_old = row.get("size_old")
            size_new = row.get("size_new")
            delta = row.get("delta")
            md5_flag = row.get("md5_changed")
            if md5_flag is True:
                md5_text = "ja"
            elif md5_flag is False:
                md5_text = "nein"
            else:
                md5_text = "n/a"

            lines.append(
                f"| `{path}` | {status} | `{category}` | "
                f"{_fmt_int(size_old)} | {_fmt_int(size_new)} | {_fmt_int(delta)} | {md5_text} |"
            )

        lines.append("")

    def _anchor_for(rel_path: str) -> str:
        return "delta-" + rel_path.replace("/", "-").replace(".", "-")

    lines.append("## Content – changed & added")
    lines.append("")

    if not (changed or added):
        lines.append("_Keine geänderten oder neuen Dateien im Snapshot._")
    else:
        interesting = sorted(changed + added, key=lambda r: r.get("path", ""))
        for row in interesting:
            rel = row.get("path", "")
            status = row.get("status", "")
            category = row.get("category") or "-"
            size_old = row.get("size_old")
            size_new = row.get("size_new")
            delta = row.get("delta")
            md5_flag = row.get("md5_changed")
            if md5_flag is True:
                md5_text = "ja"
            elif md5_flag is False:
                md5_text = "nein"
            else:
                md5_text = "n/a"

            lines.append(f"<a id=\"file-{_anchor_for(rel)}\"></a>")
            lines.append(f"### `{rel}`")
            lines.append(f"- Status: `{status}`")
            lines.append(f"- Kategorie: `{category}`")
            if size_old is not None:
                lines.append(f"- Größe alt: {size_old}")
            if size_new is not None:
                lines.append(f"- Größe neu: {size_new}")
            if delta is not None:
                try:
                    lines.append(f"- Δ Größe: {int(delta):+d}")
                except Exception:
                    lines.append(f"- Δ Größe: {delta}")
            lines.append(f"- MD5 geändert: {md5_text}")
            lines.append("")

            target = (repo_root / rel)
            if status in ("changed", "added") and target.is_file():
                ext = target.suffix.lower()
                lang_map = {
                    ".py": "python",
                    ".rs": "rust",
                    ".ts": "ts",
                    ".tsx": "tsx",
                    ".js": "js",
                    ".json": "json",
                    ".toml": "toml",
                    ".yml": "yaml",
                    ".yaml": "yaml",
                }
                lang = lang_map.get(ext, "")
                fence = f"```{lang}".rstrip()
                lines.append(fence)
                try:
                    content = target.read_text(encoding="utf-8")
                except Exception:
                    try:
                        content = target.read_text(errors="replace")
                    except Exception:
                        content = "[Fehler beim Lesen der Datei]"
                lines.append(content)
                lines.append("```")
            else:
                lines.append("_Inhalt nicht verfügbar (Datei fehlt im Repo)._")

            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def find_latest_diff_for_repo(merges_dir: Path, repo_name: str) -> Optional[Path]:
    """
    Find the most recent import-diff file for a given repo.

    Args:
        merges_dir: Directory containing merge files
        repo_name: Name of the repository

    Returns:
        Path to the most recent diff file, or None if not found
    """
    try:
        pattern = f"{repo_name}-import-diff-*.md"
        candidates = list(merges_dir.glob(pattern))
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except Exception:
        return None


def create_delta_merge_from_diff(
    diff_path: Path,
    repo_root: Path,
    merges_dir: Path,
    profile: str = "delta-full",
) -> Path:
    """
    Komfort-Helfer:
      - liest einen vorhandenen Import-Diff
      - parst die Manifest-Tabelle
      - erzeugt einen Delta-Merge-Report

    Rückgabe:
      Pfad zur erzeugten Delta-Merge-Datei.
    """
    text = diff_path.read_text(encoding="utf-8")
    rows = parse_import_diff_table(text)
    return build_delta_merge_report(repo_root, repo_root.name, rows, merges_dir, profile=profile)


if __name__ == "__main__":
    sys.exit(main())
