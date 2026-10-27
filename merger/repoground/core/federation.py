import datetime
import json
from pathlib import Path
from typing import Any, Optional
import hashlib as _hashlib
import re as _re
import yaml as _yaml
from .history_lens import _git_read, _git_tree, _repo_id, _repo_root, _revision

try:
    import jsonschema
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
except ImportError:
    jsonschema = None
    JsonSchemaValidationError = None


def _require_jsonschema() -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema is required for federation schema validation but is not installed.")


FEDERATION_KIND = "repolens.federation.index"
FEDERATION_VERSION = "1.0"


def _resolve_new_federation_index(index_path: Path) -> Path:
    raw = str(index_path)
    if not raw.strip() or "\x00" in raw:
        raise ValueError("Invalid federation index path")
    if index_path.suffix.lower() != ".json":
        raise ValueError("Federation index must be a JSON file")
    try:
        parent = index_path.parent.resolve(strict=True)  # lgtm[py/path-injection] codeql-boundary:federation-index-file
    except (OSError, RuntimeError) as exc:
        raise FileNotFoundError("Federation index parent directory not found") from exc
    if not parent.is_dir():
        raise ValueError("Federation index parent must be a directory")
    return parent / index_path.name


def _resolve_existing_federation_index(index_path: Path) -> Path:
    raw = str(index_path)
    if not raw.strip() or "\x00" in raw:
        raise ValueError("Invalid federation index path")
    if index_path.suffix.lower() != ".json":
        raise ValueError("Federation index must be a JSON file")
    try:
        resolved = index_path.resolve(strict=True)  # lgtm[py/path-injection] codeql-boundary:federation-index-file
    except (OSError, RuntimeError) as exc:
        raise FileNotFoundError(f"Federation index not found at: {index_path}") from exc
    if not resolved.is_file():  # lgtm[py/path-injection] codeql-boundary:federation-index-file
        raise ValueError("Federation index path is not a regular file")
    return resolved

def load_federation_schema() -> Optional[dict]:
    """Loads the federation schema."""
    # Attempt to resolve from module path
    module_dir = Path(__file__).parent
    schema_path = module_dir.parent / "contracts" / "federation-index.v1.schema.json"
    if schema_path.exists():
        with schema_path.open() as f:
            return json.load(f)
    return None

def init_federation(federation_id: str, out_path: Path) -> dict:
    """
    Initializes a new empty federation index adhering to the federation-index.v1.schema.json contract.
    If the file already exists, it raises an exception to prevent accidental overwrites.
    """
    out_path = _resolve_new_federation_index(out_path)

    # We do a quick check to see if the schema exists
    # If not, we fail fast.
    schema = load_federation_schema()
    if not schema:
        raise RuntimeError("Federation schema missing at expected path (contracts/federation-index.v1.schema.json)")

    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    fed_data = {
        "kind": FEDERATION_KIND,
        "version": FEDERATION_VERSION,
        "federation_id": federation_id,
        "created_at": now,
        "updated_at": now,
        "bundles": []
    }

    # Validate against our own schema before writing (fail safe)
    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Failed to generate valid federation index schema: {e}")

    try:
        # Exclusive creation prevents overwrite and rejects existing symlinks,
        # including dangling links, at the filesystem operation itself.
        with out_path.open("x", encoding="utf-8") as handle:  # lgtm[py/path-injection] codeql-boundary:federation-index-file
            json.dump(fed_data, handle, indent=2, sort_keys=True)
    except FileExistsError as exc:
        raise FileExistsError(
            f"Federation index already exists at: {out_path.as_posix()}"
        ) from exc

    return fed_data

def validate_federation_data(fed_data: dict[str, Any]) -> bool:
    """
    Validates a federation index object against its schema and logical constraints.

    This is shared by persisted federation_index.json files and transient, read-only
    bundle lists built by callers such as the CLI. It validates only structure and
    identifiers; it does not inspect bundle contents, run refreshes, touch Git or
    establish runtime correctness.
    """
    schema = load_federation_schema()
    if not schema:
        raise RuntimeError("Federation schema missing at expected path (contracts/federation-index.v1.schema.json)")

    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Schema validation failed: {e.message} at path {list(e.path)}")

    bundles = fed_data.get("bundles", [])
    repo_ids = set()
    for b in bundles:
        repo_id = b.get("repo_id")
        bundle_path = b.get("bundle_path")

        if not repo_id:
            raise ValueError("Invalid bundle: missing 'repo_id'.")
        if not bundle_path:
            raise ValueError("Invalid bundle: missing 'bundle_path'.")

        if repo_id in repo_ids:
            raise ValueError(f"Duplicate 'repo_id' found: {repo_id}")
        repo_ids.add(repo_id)

    return True


def load_federation_index_data(index_path: Path) -> dict[str, Any]:
    """Load and validate a persisted federation index JSON file."""
    resolved_index = _resolve_existing_federation_index(index_path)
    with resolved_index.open("r", encoding="utf-8") as handle:  # lgtm[py/path-injection] codeql-boundary:federation-index-file
        fed_data = json.load(handle)

    validate_federation_data(fed_data)
    return fed_data


def validate_federation(index_path: Path) -> bool:
    """
    Validates a federation index against its schema and additional logical constraints.
    Returns True if valid, raises an exception otherwise.
    """
    load_federation_index_data(index_path)
    return True

def inspect_federation(index_path: Path) -> dict:
    """
    Returns a brief, readable summary of a federation index.
    """
    fed_data = load_federation_index_data(index_path)

    federation_id = fed_data.get("federation_id", "<unknown>")
    bundles = fed_data.get("bundles", [])
    updated_at = fed_data.get("updated_at", "<unknown>")

    repo_ids = [b.get("repo_id") for b in bundles if "repo_id" in b]

    return {
        "federation_id": federation_id,
        "bundle_count": len(bundles),
        "repo_ids": repo_ids,
        "updated_at": updated_at
    }

def add_bundle(index_path: Path, repo_id: str, bundle_path: str) -> dict:
    """
    Adds a bundle to an existing federation index.
    Ensures that repo_id is unique and valid before writing.
    """
    index_path = _resolve_existing_federation_index(index_path)

    schema = load_federation_schema()
    if not schema:
        raise RuntimeError("Federation schema missing at expected path (contracts/federation-index.v1.schema.json)")

    with index_path.open("r", encoding="utf-8") as handle:  # lgtm[py/path-injection] codeql-boundary:federation-index-file
        fed_data = json.load(handle)

    # Pre-validate existing data to prevent poor failure modes (e.g. KeyError on missing repo_id)
    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Existing federation index is corrupt: schema validation failed: {e.message} at path {list(e.path)}")

    # Check for uniqueness of repo_id
    for bundle in fed_data.get("bundles", []):
        if bundle.get("repo_id") == repo_id:
            raise ValueError(f"repo_id '{repo_id}' already exists in federation index.")

    # Update state
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    new_bundle = {
        "repo_id": repo_id,
        "bundle_path": bundle_path # preserve exactly as passed (opaque string/URI)
    }

    if "bundles" not in fed_data:
        fed_data["bundles"] = []

    fed_data["bundles"].append(new_bundle)

    # Canonicalize bundle order for deterministic federation index output.
    fed_data["bundles"].sort(key=lambda x: x["repo_id"])

    fed_data["updated_at"] = now

    # Validate against our own schema before writing (fail safe)
    _require_jsonschema()

    try:
        jsonschema.validate(instance=fed_data, schema=schema)
    except JsonSchemaValidationError as e:
        raise ValueError(f"Failed to generate valid federation index schema after modification: {e}")

    with index_path.open("w", encoding="utf-8") as handle:  # lgtm[py/path-injection] codeql-boundary:federation-index-file
        json.dump(fed_data, handle, indent=2, sort_keys=True)

    return fed_data

# Thread 2: explicit, revision-pinned Fleet federation. Persisted federation-index.v1
# remains untouched. All facts below are a read-only projection of Git objects.

_FEDERATION_EVIDENCE_KIND = "repoground.federation-evidence"
_MAX_FLEET_TARGETS = 64
_MAX_SYNC_ENTRIES = 128
_MAX_RELATIONS = 256


def _git_object_bytes(root: Path, tree: dict[str, str], path: str) -> bytes | None:
    if not isinstance(path, str) or path.startswith("/") or "\x00" in path or "\\" in path:
        return None
    if any(part in ("", ".", "..") for part in path.split("/")):
        return None
    oid = tree.get(path)
    if not oid:
        return None
    try:
        return _git_read(root, "cat-file", "blob", oid, max_bytes=250_000)
    except ValueError:
        return None


def _artifact_evidence(repo_id: str, commit: str, path: str,
                       tree: dict[str, str], data: bytes | None,
                       line: int | None = None) -> dict[str, Any]:
    return {
        "repo_id": repo_id, "commit": commit, "path": path,
        "blob_oid": tree.get(path), "sha256": _hashlib.sha256(data).hexdigest() if data is not None else None,
        "line_start": line, "line_end": line, "source_type": "git_blob",
        "status": "observed" if data is not None else "unavailable",
    }


def _declaration_line(contents: str, key: str, *, mapping: bool = False) -> int | None:
    """Return a unique exact source line; ambiguous declarations remain unresolved."""
    if mapping:
        pattern = _re.compile(r"^\s{2}" + _re.escape(key) + r":\s*(?:#.*)?$")
    else:
        pattern = _re.compile(r"^\s*-\s*name:\s*['\"]?" + _re.escape(key) + r"['\"]?\s*(?:#.*)?$")
    found = [n for n, line in enumerate(contents.splitlines(), 1) if pattern.fullmatch(line)]
    return found[0] if len(found) == 1 else None


def _validated_yaml_mapping(data: bytes | None, label: str) -> dict[str, Any]:
    if data is None:
        return {}
    try:
        obj = _yaml.safe_load(data.decode("utf-8"))
    except (_yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid YAML at {label}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"expected YAML mapping at {label}")
    return obj


def fleet_revision_relations(metarepo: Path, metarepo_commit: str,
                             targets: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    """Compute directional declarations, never assume fleet=runtime dependency.

    targets is an explicitly authorized set of local repos with full Git SHAs.
    No clone/fetch/publish occurs; missing target commits and paths stay visible.
    """
    if not isinstance(targets, dict) or len(targets) > _MAX_FLEET_TARGETS:
        raise ValueError("targets must be a bounded mapping")
    source_root = _repo_root(metarepo)
    source_commit = _revision(source_root, metarepo_commit)
    source_tree, tree_limited = _git_tree(source_root, source_commit)
    fleet_path = "fleet/repos.yml"
    metadata_path = "fleet/repo-metadata.yml"
    sync_path = "sync/metarepo-sync.yml"
    fleet_blob = _git_object_bytes(source_root, source_tree, fleet_path)
    if fleet_blob is None:
        return {
            "kind": _FEDERATION_EVIDENCE_KIND, "version": "1",
            "status": "unavailable", "source_repo": "metarepo",
            "source_commit": source_commit, "relations": [],
            "observation_time": None, "publication_time": None,
            "gaps": ["authoritative_fleet_repos_yml_unavailable"],
            "does_not_establish": ["runtime_dependency", "successful_sync", "deployed_version", "causal_relation"],
            "authoritative_membership_source": fleet_path,
            "supplementary_sources": [metadata_path, sync_path],
        }
    if len(fleet_blob) > 250_000:
        raise ValueError("fleet source exceeds parsing limit")
    fleet_text = fleet_blob.decode("utf-8")
    fleet = _validated_yaml_mapping(fleet_blob, fleet_path)
    if not isinstance(fleet.get("repos"), list):
        raise ValueError("invalid authoritative fleet schema")

    member_kind = {}
    for item in fleet["repos"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("invalid fleet member entry")
        name = _repo_id(item["name"])
        if name in member_kind:
            raise ValueError("ambiguous duplicate fleet member")
        member_kind[name] = "fleet_core"
    related = (fleet.get("static") or {}).get("include", [])
    if not isinstance(related, list):
        raise ValueError("invalid related fleet list")
    for item in related:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("invalid related entry")
        name = _repo_id(item["name"])
        if name in member_kind:
            raise ValueError("ambiguous fleet member/related overlap")
        if item.get("status") != "related":
            raise ValueError("non-related static include is not a Fleet declaration")
        member_kind[name] = "fleet_related"

    metadata_blob = _git_object_bytes(source_root, source_tree, metadata_path)
    sync_blob = _git_object_bytes(source_root, source_tree, sync_path)
    metadata = _validated_yaml_mapping(metadata_blob, metadata_path)
    sync_data = _validated_yaml_mapping(sync_blob, sync_path)
    annotations = metadata.get("repositories", {})
    if not isinstance(annotations, dict):
        raise ValueError("invalid metadata repositories mapping")
    sync_entries = sync_data.get("entries", [])
    if not isinstance(sync_entries, list) or len(sync_entries) > _MAX_SYNC_ENTRIES:
        raise ValueError("sync entries unavailable or over limit")

    relations = []
    gaps = ["git_tree_capped"] if tree_limited else []
    for name in sorted(targets):
        _repo_id(name)
        target_spec = targets[name]
        if not isinstance(target_spec, (tuple, list)) or len(target_spec) != 2:
            raise ValueError("target must contain repo directory and Git SHA")
        target_root = _repo_root(Path(target_spec[0]))
        target_sha = _revision(target_root, target_spec[1])
        target_tree, limited = _git_tree(target_root, target_sha)
        if limited:
            gaps.append("target_git_tree_capped:" + name)

        kind = member_kind.get(name)
        if not kind:
            gaps.append("target_not_listed_in_authoritative_fleet:" + name)
            continue
        line = _declaration_line(fleet_text, name)
        if line is None:
            gaps.append("fleet_declaration_ambiguous:" + name)
            continue
        annotation = annotations.get(name, {})
        if annotation and not isinstance(annotation, dict):
            gaps.append("invalid_metadata:" + name)
            annotation = {}
        if annotation.get("fleet") is False:
            gaps.append("metadata_fleet_false:" + name)
            # Membership is sourced from fleet/repos.yml; report the conflict.
            # Never silently promote this target to a runtime dependency.
        relations.append({
            "relation_type": kind, "direction": "metarepo_to_target",
            "confidence": "declared", "asserts_runtime_dependency": False,
            "source": _artifact_evidence("metarepo", source_commit, fleet_path, source_tree, fleet_blob, line),
            "target": {"repo_id": name, "commit": target_sha, "path": None,
                       "blob_oid": None, "sha256": None, "source_type": "commit_identity_only",
                       "status": "commit_verified"},
            "status": "conflicting_declarations" if annotation.get("fleet") is False else "observed_declaration",
        })
        if annotation and metadata_blob is not None:
            metadata_line = _declaration_line(metadata_blob.decode("utf-8"), name, mapping=True)
            if metadata_line is not None:
                relations.append({
                    "relation_type": "fleet_metadata", "direction": "metarepo_to_target",
                    "confidence": "declared", "asserts_runtime_dependency": False,
                    "source": _artifact_evidence("metarepo", source_commit, metadata_path,
                                                 source_tree, metadata_blob, metadata_line),
                    "target": {"repo_id": name, "commit": target_sha, "path": None,
                               "blob_oid": None, "sha256": None, "source_type": "commit_identity_only",
                               "status": "commit_verified"},
                    "status": "observed_declaration",
                    "metadata": {key: annotation[key] for key in ("domain", "scope", "default_branch")
                                 if isinstance(annotation.get(key), str)},
                })

        # Existing metarepo-sync.yml declares a copy *target path*, not a
        # validated runtime dependency or successful rollout to every fleet repo.
        if sync_blob is None:
            gaps.append("sync_manifest_unavailable")
            continue
        for entry in sync_entries:
            if not isinstance(entry, dict):
                gaps.append("invalid_sync_entry")
                continue
            source_path = entry.get("source")
            paths = entry.get("targets")
            if not isinstance(source_path, str) or not isinstance(paths, list):
                gaps.append("invalid_sync_entry")
                continue
            source_bytes = _git_object_bytes(source_root, source_tree, source_path)
            if source_bytes is None:
                gaps.append("sync_source_unavailable:" + str(entry.get("id", "")))
                continue
            for target_path in paths[:8]:
                if not isinstance(target_path, str):
                    continue
                target_bytes = _git_object_bytes(target_root, target_tree, target_path)
                if target_bytes is None:
                    # A copy declaration without a target is not a proven link.
                    continue
                same = _hashlib.sha256(source_bytes).digest() == _hashlib.sha256(target_bytes).digest()
                relations.append({
                    "relation_type": "declared_copy_target",
                    "direction": "metarepo_to_target",
                    "confidence": "observed_content" if same else "declaration_only",
                    "asserts_runtime_dependency": False,
                    "source": _artifact_evidence("metarepo", source_commit, source_path,
                                                 source_tree, source_bytes),
                    "target": _artifact_evidence(name, target_sha, target_path,
                                                 target_tree, target_bytes),
                    "declaration": _artifact_evidence("metarepo", source_commit, sync_path,
                                                       source_tree, sync_blob),
                    "status": "identical_content" if same else "diverged_at_revisions",
                    "sync_entry_id": str(entry.get("id", ""))[:128],
                })
                if len(relations) >= _MAX_RELATIONS:
                    gaps.append("relation_limit")
                    break
            if len(relations) >= _MAX_RELATIONS:
                break
        if len(relations) >= _MAX_RELATIONS:
            break
    relations.sort(key=lambda row: (
        row["target"]["repo_id"], row["relation_type"],
        row["source"]["path"] or "", row["target"]["path"] or "",
    ))
    return {
        "kind": _FEDERATION_EVIDENCE_KIND, "version": "1",
        "status": "partial" if gaps else "ok",
        "source_repo": "metarepo", "source_commit": source_commit,
        "observation_time": None, "publication_time": None,
        "relations": relations[:_MAX_RELATIONS], "gaps": sorted(set(gaps)),
        "does_not_establish": [
            "runtime_dependency", "successful_sync", "deployed_version",
            "pr_approval", "ci_success", "causal_relation"
        ],
        "authoritative_membership_source": fleet_path,
        "supplementary_sources": [metadata_path, sync_path],
    }