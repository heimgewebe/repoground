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
        pattern = _re.compile(r"^\s{2,}[\'\"]?" + _re.escape(key) + r"[\'\"]?:\s*(?:#.*)?$")
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


def _add_related_fleet_members(fleet: dict[str, Any], kinds: dict[str, str]) -> None:
    """Check the static 'related' declarations without upgrading them to Core."""
    static = fleet.get("static") or {}
    if not isinstance(static, dict):
        raise ValueError("invalid related fleet list")
    related = static.get("include", [])
    if not isinstance(related, list):
        raise ValueError("invalid related fleet list")
    for item in related:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("invalid related entry")
        name = _repo_id(item["name"])
        if name in kinds:
            raise ValueError("ambiguous fleet member/related overlap")
        if item.get("status") != "related":
            raise ValueError("non-related static include is not a Fleet declaration")
        kinds[name] = "fleet_related"


def _fleet_member_kinds(fleet: dict[str, Any]) -> dict[str, str]:
    """Only fleet/repos.yml grants Core/Related membership, not metadata."""
    core = fleet.get("repos")
    if not isinstance(core, list):
        raise ValueError("invalid authoritative fleet schema")
    kinds: dict[str, str] = {}
    for item in core:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("invalid fleet member entry")
        name = _repo_id(item["name"])
        if name in kinds:
            raise ValueError("ambiguous duplicate fleet member")
        kinds[name] = "fleet_core"
    _add_related_fleet_members(fleet, kinds)
    return kinds


def _commit_only_target(repo_id: str, sha: str) -> dict[str, Any]:
    """A checked target commit without a proven target-side file."""
    return {"repo_id": repo_id, "commit": sha, "path": None,
            "blob_oid": None, "sha256": None, "source_type": "commit_identity_only",
            "status": "commit_verified"}


def _declared_target_relations(name: str, target_sha: str, ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Differentiate authoritative Fleet declaration from optional metadata."""
    kind = ctx["member_kinds"].get(name)
    if not kind:
        return [], ["target_not_listed_in_authoritative_fleet:" + name]
    line = _declaration_line(ctx["fleet_text"], name)
    if line is None:
        return [], ["fleet_declaration_ambiguous:" + name]
    annotation = ctx["annotations"].get(name, {})
    gaps: list[str] = []
    if annotation and not isinstance(annotation, dict):
        gaps.append("invalid_metadata:" + name)
        annotation = {}
    conflict = annotation.get("fleet") is False
    if conflict:
        gaps.append("metadata_fleet_false:" + name)
    source_tree, source_sha = ctx["source_tree"], ctx["source_commit"]
    relations = [{
        "relation_type": kind, "direction": "metarepo_to_target",
        "confidence": "declared", "asserts_runtime_dependency": False,
        "source": _artifact_evidence("metarepo", source_sha, ctx["fleet_path"],
                                     source_tree, ctx["fleet_blob"], line),
        "target": _commit_only_target(name, target_sha),
        "status": "conflicting_declarations" if conflict else "observed_declaration",
    }]
    metadata_blob = ctx["metadata_blob"]
    if annotation and metadata_blob is not None:
        metadata_line = _declaration_line(metadata_blob.decode("utf-8"), name, mapping=True)
        if metadata_line is None:
            gaps.append("fleet_metadata_declaration_unresolved:" + name)
        else:
            relations.append({
                "relation_type": "fleet_metadata", "direction": "metarepo_to_target",
                "confidence": "declared", "asserts_runtime_dependency": False,
                "source": _artifact_evidence("metarepo", source_sha, ctx["metadata_path"],
                                             source_tree, metadata_blob, metadata_line),
                "target": _commit_only_target(name, target_sha),
                "status": "observed_declaration",
                "metadata": {key: annotation[key] for key in ("domain", "scope", "default_branch")
                             if isinstance(annotation.get(key), str)},
            })
    return relations, gaps


def _copy_target_evidence(name: str, sha: str, target_tree: dict[str, str],
                          path: str, source_path: str, source_bytes: bytes,
                          entry_id: str, ctx: dict[str, Any],
                          target_root: Path) -> dict[str, Any] | None:
    if not isinstance(path, str):
        return None
    target_bytes = _git_object_bytes(target_root, target_tree, path)
    if target_bytes is None:
        return None
    same = _hashlib.sha256(source_bytes).digest() == _hashlib.sha256(target_bytes).digest()
    return {
        "relation_type": "declared_copy_target", "direction": "metarepo_to_target",
        "confidence": "observed_content" if same else "declaration_only",
        "asserts_runtime_dependency": False,
        "source": _artifact_evidence("metarepo", ctx["source_commit"], source_path,
                                     ctx["source_tree"], source_bytes),
        "target": _artifact_evidence(name, sha, path, target_tree, target_bytes),
        "declaration": _artifact_evidence("metarepo", ctx["source_commit"], ctx["sync_path"],
                                           ctx["source_tree"], ctx["sync_blob"]),
        "status": "identical_content" if same else "diverged_at_revisions",
        "sync_entry_id": entry_id[:128],
    }


def _sync_entry_relations(entry: Any, name: str, sha: str, target_root: Path,
                          target_tree: dict[str, str], ctx: dict[str, Any]
                          ) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(entry, dict):
        return [], ["invalid_sync_entry"]
    source_path, paths = entry.get("source"), entry.get("targets")
    if not isinstance(source_path, str) or not isinstance(paths, list):
        return [], ["invalid_sync_entry"]
    entry_id = str(entry.get("id", ""))[:128]
    source_bytes = _git_object_bytes(ctx["source_root"], ctx["source_tree"], source_path)
    if source_bytes is None:
        return [], ["sync_source_unavailable:" + entry_id]
    gaps = ["sync_targets_capped:" + entry_id] if len(paths) > 8 else []
    links: list[dict[str, Any]] = []
    for path in paths[:8]:
        link = _copy_target_evidence(
            name, sha, target_tree, path, source_path, source_bytes,
            entry_id, ctx, target_root,
        )
        if link is not None:
            links.append(link)
        elif isinstance(path, str) and path in target_tree:
            # Its OID was observed in Git, but the blob could not be read
            # within limits (or is missing in a partial clone). This is not
            # proof of removal; relation-delta must withhold that verdict.
            gaps.append("sync_target_unavailable:" + entry_id + ":" + path)
    return links, gaps


def _sync_target_relations(name: str, sha: str, target_root: Path, target_tree: dict[str, str],
                           ctx: dict[str, Any], limit: int
                           ) -> tuple[list[dict[str, Any]], list[str]]:
    if ctx["sync_blob"] is None:
        return [], ["sync_manifest_unavailable"]
    if limit <= 0:
        return [], ["relation_limit"]
    links: list[dict[str, Any]] = []
    gaps: list[str] = []
    for entry in ctx["sync_entries"]:
        found, errors = _sync_entry_relations(entry, name, sha, target_root, target_tree, ctx)
        gaps.extend(errors)
        links.extend(found[:max(0, limit - len(links))])
        if len(links) >= limit:
            gaps.append("relation_limit")
            break
    return links, gaps


def _one_fleet_target(name: str, target_spec: tuple[Path, str],
                      ctx: dict[str, Any], remaining: int
                      ) -> tuple[list[dict[str, Any]], list[str]]:
    _repo_id(name)
    if not isinstance(target_spec, (tuple, list)) or len(target_spec) != 2:
        raise ValueError("target must contain repo directory and Git SHA")
    target_root = _repo_root(Path(target_spec[0]))
    target_sha = _revision(target_root, target_spec[1])
    target_tree, limited = _git_tree(target_root, target_sha)
    gaps = ["target_git_tree_capped:" + name] if limited else []
    declared, declaration_gaps = _declared_target_relations(name, target_sha, ctx)
    gaps.extend(declaration_gaps)
    if not declared:
        return [], gaps
    copies, copy_gaps = _sync_target_relations(
        name, target_sha, target_root, target_tree, ctx, max(0, remaining - len(declared))
    )
    gaps.extend(copy_gaps)
    return declared + copies, gaps


def fleet_revision_relations(metarepo: Path, metarepo_commit: str,
                             targets: dict[str, tuple[Path, str]]) -> dict[str, Any]:
    """Bounded Git-object projection of normative Fleet and declared copy contracts.

    All target roots/revisions are explicit; never fetch Git or infer deployment.
    """
    if not isinstance(targets, dict) or len(targets) > _MAX_FLEET_TARGETS:
        raise ValueError("targets must be a bounded mapping")
    root = _repo_root(metarepo)
    commit = _revision(root, metarepo_commit)
    tree, limited = _git_tree(root, commit)
    fleet_path = "fleet/repos.yml"
    metadata_path = "fleet/repo-metadata.yml"
    sync_path = "sync/metarepo-sync.yml"
    fleet_blob = _git_object_bytes(root, tree, fleet_path)
    if fleet_blob is None:
        return {
            "kind": _FEDERATION_EVIDENCE_KIND, "version": "1",
            "status": "unavailable", "source_repo": "metarepo",
            "source_commit": commit, "relations": [],
            "observation_time": None, "publication_time": None,
            "gaps": ["authoritative_fleet_repos_yml_unavailable"],
            "does_not_establish": ["runtime_dependency", "successful_sync", "deployed_version", "causal_relation"],
            "authoritative_membership_source": fleet_path,
            "supplementary_sources": [metadata_path, sync_path],
        }
    if len(fleet_blob) > 250_000:
        raise ValueError("fleet source exceeds parsing limit")
    fleet = _validated_yaml_mapping(fleet_blob, fleet_path)
    metadata_blob = _git_object_bytes(root, tree, metadata_path)
    sync_blob = _git_object_bytes(root, tree, sync_path)
    metadata = _validated_yaml_mapping(metadata_blob, metadata_path)
    sync_data = _validated_yaml_mapping(sync_blob, sync_path)
    annotations = metadata.get("repositories", {})
    if not isinstance(annotations, dict):
        raise ValueError("invalid metadata repositories mapping")
    entries = sync_data.get("entries", [])
    if not isinstance(entries, list) or len(entries) > _MAX_SYNC_ENTRIES:
        raise ValueError("sync entries unavailable or over limit")
    ctx = {
        "source_root": root, "source_commit": commit, "source_tree": tree,
        "fleet_path": fleet_path, "fleet_blob": fleet_blob, "fleet_text": fleet_blob.decode("utf-8"),
        "metadata_path": metadata_path, "metadata_blob": metadata_blob,
        "sync_path": sync_path, "sync_blob": sync_blob,
        "member_kinds": _fleet_member_kinds(fleet),
        "annotations": annotations, "sync_entries": entries,
    }
    relations: list[dict[str, Any]] = []
    gaps = ["git_tree_capped"] if limited else []
    if metadata_blob is None and metadata_path in tree:
        gaps.append("fleet_metadata_unavailable")
    for name in sorted(targets):
        found, problems = _one_fleet_target(name, targets[name], ctx, _MAX_RELATIONS - len(relations))
        relations.extend(found[:max(0, _MAX_RELATIONS - len(relations))])
        gaps.extend(problems)
        if len(relations) >= _MAX_RELATIONS:
            gaps.append("relation_limit")
            break
    relations.sort(key=lambda row: (
        row["target"]["repo_id"], row["relation_type"],
        row["source"]["path"] or "", row["target"]["path"] or "",
    ))
    return {
        "kind": _FEDERATION_EVIDENCE_KIND, "version": "1",
        "status": "partial" if gaps else "ok",
        "source_repo": "metarepo", "source_commit": commit,
        "observation_time": None, "publication_time": None,
        "relations": relations[:_MAX_RELATIONS], "gaps": sorted(set(gaps)),
        "does_not_establish": [
            "runtime_dependency", "successful_sync", "deployed_version",
            "pr_approval", "ci_success", "causal_relation"
        ],
        "authoritative_membership_source": fleet_path,
        "supplementary_sources": [metadata_path, sync_path],
    }


def _complete_membership_observation(view: dict[str, Any]) -> bool:
    """Only a read-complete normative Fleet manifest can establish removal."""
    return (
        view["status"] == "ok"
        or (
            view["status"] == "partial"
            and bool(view["gaps"])
            and all(gap.startswith("target_not_listed_in_authoritative_fleet:")
                    for gap in view["gaps"])
        )
    )


def _stable_relation_key(relation: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        relation["relation_type"], relation["target"]["repo_id"],
        relation["source"].get("path") or "", relation["target"].get("path") or "",
    )


def _same_material_relation(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Commit SHA changes alone do not prove the relationship has changed."""
    if before == after:
        return True
    if before["status"] != after["status"]:
        return False
    relation_type = before["relation_type"]
    if relation_type in {"fleet_core", "fleet_related"}:
        return True
    if relation_type == "fleet_metadata":
        return before.get("metadata") == after.get("metadata")
    return (
        before["source"].get("sha256") == after["source"].get("sha256")
        and before["target"].get("sha256") == after["target"].get("sha256")
        and before.get("metadata") == after.get("metadata")
    )


def _material_relation_deltas(
    before_relations: list[dict[str, Any]],
    after_relations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    previous = {_stable_relation_key(row): row for row in before_relations}
    current = {_stable_relation_key(row): row for row in after_relations}
    deltas: list[dict[str, Any]] = []
    unchanged = 0
    for key in sorted(set(previous) | set(current)):
        a, b = previous.get(key), current.get(key)
        if a is not None and b is not None and _same_material_relation(a, b):
            unchanged += 1
            continue
        transition = "introduced" if a is None else "removed" if b is None else "modified"
        deltas.append({
            "relation_type": key[0], "target_repo": key[1],
            "source_path": key[2] or None, "target_path": key[3] or None,
            "transition": transition, "before": a, "after": b,
            "comparison": "git_blob_evidence_only", "causality": "unknown",
        })
    return deltas, unchanged


def fleet_relation_delta(
    metarepo: Path,
    base_metarepo_commit: str,
    head_metarepo_commit: str,
    base_targets: dict[str, tuple[Path, str]],
    head_targets: dict[str, tuple[Path, str]],
) -> dict[str, Any]:
    """Compare two independently pinned Fleet observations, not a causal chain."""
    if not isinstance(base_targets, dict) or not isinstance(head_targets, dict):
        raise ValueError("both target sets must be mappings")
    if set(base_targets) != set(head_targets):
        raise ValueError("comparison requires identical named target repository sets")
    before = fleet_revision_relations(metarepo, base_metarepo_commit, base_targets)
    after = fleet_revision_relations(metarepo, head_metarepo_commit, head_targets)
    shared = {
        "kind": _FEDERATION_EVIDENCE_KIND, "version": "1", "operation": "delta",
        "source_repo": "metarepo", "source_commit": after["source_commit"],
        "base_commit": before["source_commit"], "head_commit": after["source_commit"],
        "relations": after["relations"], "relation_deltas": [],
        "unchanged_relations_count": 0,
        "authoritative_membership_source": "fleet/repos.yml",
        "supplementary_sources": ["fleet/repo-metadata.yml", "sync/metarepo-sync.yml"],
        "observation_time": None, "publication_time": None,
        "does_not_establish": [
            "runtime_dependency", "successful_sync", "deployed_version",
            "real_time_ci", "causal_relation", "absence_from_incomplete_sources",
        ],
    }
    if not (_complete_membership_observation(before)
            and _complete_membership_observation(after)):
        return {
            **shared, "status": "partial",
            "gaps": sorted(set(
                ["relation_delta_requires_two_complete_source_views"]
                + ["before:" + x for x in before["gaps"]]
                + ["after:" + x for x in after["gaps"]]
            )),
        }
    deltas, unchanged = _material_relation_deltas(before["relations"], after["relations"])
    return {**shared, "status": "ok", "gaps": [],
            "relation_deltas": deltas, "unchanged_relations_count": unchanged}