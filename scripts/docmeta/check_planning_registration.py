import argparse
import datetime
import glob
import hashlib
import json
import os
import posixpath
import re
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

GENERATOR = "scripts/docmeta/check_planning_registration.py"
REPORT_SCHEMA = "lenskit.planning_registration_report.v1"
BASELINE_SCHEMA = "lenskit.planning_registration_baseline.v1"

_PATH_REF_RE = re.compile(r"(?:docs|scripts)/[A-Za-z0-9_./-]+")

# doc_type values that make a spec a planning artifact
_PLANNING_DOC_TYPES = {"roadmap", "plan", "status", "status-matrix"}

# Terminal status values that are excluded from checks
_TERMINAL_STATUSES = {"deprecated", "superseded", "archived", "deferred"}

# Finding codes
CODE_UNREGISTERED = "UNREGISTERED_PLANNING_ARTIFACT"
CODE_INVALID_EXCEPTION = "INVALID_PLANNING_EXCEPTION"
CODE_CONTROL_FILE_MISSING = "CONTROL_FILE_MISSING"
CODE_CONTROL_FILE_PARSE_ERROR = "CONTROL_FILE_PARSE_ERROR"

# Codes that count as "invalid exceptions" (always blocking in ratchet mode,
# never tolerated via baseline).
_INVALID_EXCEPTION_CODES = {CODE_INVALID_EXCEPTION}

# Control-file errors: the tool cannot read/parse its own control structure.
# These always block hard (exit 2) and are never baseline-eligible.
_CONTROL_FILE_CODES = {CODE_CONTROL_FILE_MISSING, CODE_CONTROL_FILE_PARSE_ERROR}

# Codes excluded from the ratchet partition (new/known): each is handled by its
# own dedicated blocking class, never mixed into ordinary drift.
_NON_RATCHETABLE_CODES = _INVALID_EXCEPTION_CODES | _CONTROL_FILE_CODES

# Only UNREGISTERED_PLANNING_ARTIFACT findings may be written to or loaded from
# a baseline. Control-file errors signal a broken governance structure and must
# never be grandfathered; invalid exceptions are handled separately above.
_BASELINE_ELIGIBLE_CODES = {CODE_UNREGISTERED}

# Allowed top-level / per-entry fields, mirroring the baseline contract's
# additionalProperties:false. Enforced at runtime because the CI runner does not
# install jsonschema; the contract schema is validated in tests instead.
_BASELINE_TOP_FIELDS = {"schema", "generated_at", "generator", "entries"}
_BASELINE_ENTRY_FIELDS = {"id", "code", "path", "kind", "reason"}

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_BASELINE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

# YAML block-scalar fold/literal indicators.  A planning_registration field
# whose value reduces to one of these after inline-comment stripping is a
# multiline/block scalar that the parser cannot interpret; it must be rejected
# rather than silently treated as a one-character value.
_BLOCK_SCALAR_INDICATORS = frozenset({">", "|", ">-", ">+", "|-", "|+"})

# Explicit scan patterns: (glob_pattern, extra_filter_fn_or_None)
# extra_filter_fn receives (rel_path, meta) and returns True if the file should be checked
_SCAN_PATTERNS = [
    ("docs/blueprints/*.md", None),
    ("docs/roadmap/*.md", None),
    ("docs/roadmap.md", None),
    ("docs/reports/*status*.md", None),
    ("docs/reports/*roadmap*.md", None),
    ("docs/reports/*next-step*.md", None),
    ("docs/specs/*.md", "_is_planning_spec"),
]

# Directories to exclude from scanning (relative to REPO_ROOT)
_EXCLUDED_PREFIXES = (
    "docs/_generated/",
    "docs/proofs/",
    "docs/runbooks/",
    "docs/reference/",
    "docs/adr/",
    "docs/policies/",
    "docs/process/",
    "docs/claims/",
)


def _today():
    """Return today's date in UTC. Indirected for testability."""
    return datetime.datetime.now(datetime.timezone.utc).date()


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_ref(raw):
    """Normalize a path-like reference extracted from markdown/free text."""
    ref = str(raw).strip().strip("`'\"")
    ref = ref.rstrip(".,);:]")
    ref = ref.strip().strip("`'\"")
    return ref


def _extract_path_refs(text):
    """Extract normalized docs/ and scripts/ references from free text."""
    refs = set()
    if not text:
        return refs
    for match in _PATH_REF_RE.findall(text):
        ref = _normalize_ref(match)
        if ref:
            refs.add(ref)
    return refs


def _read_text(rel_path):
    full_path = os.path.join(REPO_ROOT, rel_path)
    if not os.path.exists(full_path):
        return "", f"File not found: {rel_path}"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read(), None


def _validate_index_json_structure(data):
    """Return an error string if docs/tasks/index.json has unexpected structure, else None."""
    if not isinstance(data, dict):
        return f"Root must be an object, got {type(data).__name__}."
    if "tasks" not in data:
        return "Missing required 'tasks' field."
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return f"'tasks' must be a list, got {type(tasks).__name__}."
    for i, task in enumerate(tasks or []):
        if not isinstance(task, dict):
            return f"tasks[{i}] must be an object, got {type(task).__name__}."
        evidence = task.get("evidence")
        if evidence is not None and not isinstance(evidence, list):
            return f"tasks[{i}].evidence must be a list, got {type(evidence).__name__}."
        for j, ev in enumerate(evidence or []):
            if not isinstance(ev, str):
                return f"tasks[{i}].evidence[{j}] must be a string, got {type(ev).__name__}."
    return None


def get_registered_paths():
    registered = set()
    findings = []

    # 1. docs/tasks/index.json
    index_text, err = _read_text("docs/tasks/index.json")
    if err:
        findings.append({
            "code": CODE_CONTROL_FILE_MISSING,
            "path": "docs/tasks/index.json",
            "kind": "control_file_missing",
            "reason": err,
            "suggestion": "Create docs/tasks/index.json with a tasks array.",
            "source": "planning-registration",
        })
    else:
        try:
            data = json.loads(index_text)
        except json.JSONDecodeError as e:
            findings.append({
                "code": CODE_CONTROL_FILE_PARSE_ERROR,
                "path": "docs/tasks/index.json",
                "kind": "control_file_parse_error",
                "reason": f"Invalid JSON: {e}",
                "suggestion": "Fix the JSON syntax in docs/tasks/index.json.",
                "source": "planning-registration",
            })
            data = None
        if data is not None:
            struct_err = _validate_index_json_structure(data)
            if struct_err:
                findings.append({
                    "code": CODE_CONTROL_FILE_PARSE_ERROR,
                    "path": "docs/tasks/index.json",
                    "kind": "control_file_parse_error",
                    "reason": f"Structural error: {struct_err}",
                    "suggestion": "Fix the structure of docs/tasks/index.json.",
                    "source": "planning-registration",
                })
            else:
                for task in (data.get("tasks") or []):
                    for path in (task.get("evidence") or []):
                        ref = _normalize_ref(path)
                        if ref:
                            registered.add(ref)

    # 2. docs/tasks/board.md
    board_text, err = _read_text("docs/tasks/board.md")
    if err:
        findings.append({
            "code": CODE_CONTROL_FILE_MISSING,
            "path": "docs/tasks/board.md",
            "kind": "control_file_missing",
            "reason": err,
            "suggestion": "Create docs/tasks/board.md as the task board.",
            "source": "planning-registration",
        })
    else:
        registered.update(_extract_path_refs(board_text))

    # 3. docs/roadmap.md
    roadmap_text, err = _read_text("docs/roadmap.md")
    if err:
        findings.append({
            "code": CODE_CONTROL_FILE_MISSING,
            "path": "docs/roadmap.md",
            "kind": "control_file_missing",
            "reason": err,
            "suggestion": "Create docs/roadmap.md as the project roadmap.",
            "source": "planning-registration",
        })
    else:
        for match in re.findall(r'\]\(([^)]+)\)', roadmap_text):
            match = _normalize_ref(match)
            if match.endswith('.md'):
                if not match.startswith('docs/'):
                    registered.add(os.path.normpath(os.path.join('docs', match)))
                else:
                    registered.add(match)
        registered.update(_extract_path_refs(roadmap_text))

    # Self-register control files
    registered.add("docs/tasks/index.json")
    registered.add("docs/tasks/board.md")
    registered.add("docs/roadmap.md")

    return registered, findings


def _is_excluded(rel_path):
    for prefix in _EXCLUDED_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    return False


def _is_planning_spec(rel_path, meta):
    """Return True if a docs/specs file counts as a planning artifact."""
    doc_type = meta.get("doc_type", "").strip().strip('"\'')
    return doc_type in _PLANNING_DOC_TYPES


def is_registered(rel_path, registered_paths):
    if rel_path in registered_paths:
        return True
    for rp in registered_paths:
        if rp.endswith("/") and rel_path.startswith(rp):
            return True
    return False


def parse_markdown_meta(filepath):
    meta = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines and lines[0].strip() == "---":
                for i in range(1, len(lines)):
                    if lines[i].strip() == "---":
                        break
                    # Only consider top-level keys (no leading whitespace) so
                    # nested blocks like planning_registration do not pollute the
                    # flat meta map.
                    if lines[i] != lines[i].lstrip():
                        continue
                    if ":" in lines[i]:
                        parts = lines[i].split(":", 1)
                        key = parts[0].strip()
                        val = _strip_inline_comment(parts[1])
                        if val.startswith("[") and val.endswith("]"):
                            meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                        else:
                            meta[key] = val
    except OSError as exc:
        print(f"Warning: failed to read {filepath}: {exc}", file=sys.stderr)
    except UnicodeDecodeError as exc:
        print(f"Warning: failed to decode {filepath}: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: unexpected error parsing {filepath}: {exc}", file=sys.stderr)
    return meta


def _strip_inline_comment(value: str) -> str:
    """Remove a trailing inline comment and outer quotes from a YAML scalar string.

    '#' is treated as a comment start only when it appears outside of single or
    double quoted strings.  '#' inside quotes is part of the value.  Outer
    matching single/double quotes are stripped from the returned value.

    Examples::

        'abc # comment'          -> 'abc'
        '"abc" # comment'        -> 'abc'
        '"abc # not comment"'    -> 'abc # not comment'
        'ops#team'               -> 'ops#team'
    """
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            # In YAML, an inline comment requires whitespace before '#'.
            if i == 0 or value[i - 1] in (" ", "\t"):
                value = value[:i].rstrip()
                break
    result = value.strip()
    if (
        len(result) >= 2
        and result[0] == result[-1]
        and result[0] in ('"', "'")
    ):
        result = result[1:-1]
    return result


def parse_planning_registration_block(filepath):
    """Extract the nested `planning_registration:` frontmatter mapping.

    Returns a dict of scalar key->value if the block is present, otherwise None.
    Only single-level nesting is supported (status/reason/owner/expires).
    Multiline/block scalar values (YAML '>' and '|' indicators) are not
    supported; validate_exemption() will reject them as exempt_unsupported_scalar.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Warning: failed to read {filepath}: {exc}", file=sys.stderr)
        return None

    if not lines or lines[0].strip() != "---":
        return None

    # Locate frontmatter bounds.
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None

    block = None
    base_indent = None
    for i in range(1, end):
        raw = lines[i].rstrip("\n")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if block is None:
            # Check for planning_registration: block header, allowing inline comments.
            # Strip comments first, then check if it's the header.
            stripped_without_comment = _strip_inline_comment(stripped)
            if indent == 0 and stripped_without_comment == "planning_registration:":
                block = {}
            continue
        # Inside the block: collect more-indented key: value lines.
        if indent == 0:
            # A new top-level key ends the block.
            break
        if base_indent is None:
            base_indent = indent
        if indent < base_indent:
            break
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            block[k.strip()] = _strip_inline_comment(v)
    return block


def validate_exemption(block, today=None):
    """Validate a planning_registration exemption block.

    Returns (is_valid_exempt, invalid_kind):
      - (True, None): a complete, unexpired exemption.
      - (False, "<kind>"): the block declares an exemption that is invalid;
        <kind> describes why (stable, used in finding id).
      - (False, None): the block does not assert an exemption at all.
    """
    if today is None:
        today = _today()
    status = (block.get("status") or "").strip().strip('"\'')
    if status != "exempt":
        # Any declared planning_registration block that is not a clean exempt
        # assertion is treated as an invalid exception, except a fully empty one.
        if not block:
            return (False, None)
        return (False, "exempt_unknown_status")

    missing = [k for k in ("reason", "owner", "expires") if not (block.get(k) or "").strip()]
    if missing:
        return (False, "exempt_missing_fields")

    # Block-scalar fold/literal indicators are not supported as field values.
    # Detect them here so they produce a stable, distinct kind rather than
    # falling through to a misleading exempt_bad_date or exempt_missing_fields.
    if any(
        (block.get(f) or "").strip() in _BLOCK_SCALAR_INDICATORS
        for f in ("reason", "owner", "expires")
    ):
        return (False, "exempt_unsupported_scalar")

    expires = block["expires"].strip().strip('"\'')
    if not _ISO_DATE_RE.match(expires):
        return (False, "exempt_bad_date")
    try:
        exp_date = datetime.date.fromisoformat(expires)
    except ValueError:
        return (False, "exempt_bad_date")

    if exp_date < today:
        return (False, "exempt_expired")

    return (True, None)


def compute_finding_id(code, path, kind):
    """Deterministic, line-number-independent finding id."""
    norm_path = str(path).replace("\\", "/")
    payload = f"{code}\0{norm_path}\0{kind}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _finalize_findings(findings):
    """Assign stable ids and sort deterministically by (path, code, id)."""
    for f in findings:
        f.setdefault("kind", f["code"].lower())
        f["id"] = compute_finding_id(f["code"], f["path"], f["kind"])
    findings.sort(key=lambda f: (f["path"], f["code"], f["id"]))
    return findings


def run_checks(today=None):
    registered_paths, findings = get_registered_paths()

    for rel_path, extra_filter_name in _collect_scan_targets():
        full_path = os.path.join(REPO_ROOT, rel_path)
        if not os.path.isfile(full_path):
            continue

        meta = parse_markdown_meta(full_path)

        # Skip terminal-status artifacts
        status = meta.get("status", "").strip().strip('"\'')
        if status in _TERMINAL_STATUSES:
            continue

        # Apply extra filter for specs
        if extra_filter_name == "_is_planning_spec":
            if not _is_planning_spec(rel_path, meta):
                continue

        # Explicit frontmatter exemption flow.
        block = parse_planning_registration_block(full_path)
        if block is not None:
            is_valid_exempt, invalid_kind = validate_exemption(block, today=today)
            if is_valid_exempt:
                continue
            if invalid_kind is not None:
                findings.append({
                    "code": CODE_INVALID_EXCEPTION,
                    "path": rel_path,
                    "kind": invalid_kind,
                    "reason": f"Invalid planning_registration exemption ({invalid_kind}).",
                    "suggestion": (
                        "An exempt block requires status: exempt with non-empty "
                        "reason, owner and an unexpired ISO expires (YYYY-MM-DD). "
                        "planning_registration supports simple single-line scalar "
                        "values only; multiline/block scalar values are not supported."
                    ),
                    "source": "planning-registration",
                })
                continue
            # block present but asserts nothing meaningful -> fall through

        if not is_registered(rel_path, registered_paths):
            findings.append({
                "code": CODE_UNREGISTERED,
                "path": rel_path,
                "kind": "unregistered",
                "reason": "Planning artifact is active but not registered in task-control or roadmap.",
                "suggestion": "Add the path to docs/tasks/index.json evidence, docs/tasks/board.md, or docs/roadmap.md.",
                "source": "planning-registration",
            })

    return _finalize_findings(findings)


def _collect_scan_targets():
    """Collect (rel_path, extra_filter_name) tuples to scan."""
    targets = []
    for pattern, extra_filter in _SCAN_PATTERNS:
        full_pattern = os.path.join(REPO_ROOT, pattern)
        for full_path in glob.glob(full_pattern):
            rel_path = os.path.relpath(full_path, REPO_ROOT)
            if not _is_excluded(rel_path):
                targets.append((rel_path, extra_filter))
    return targets


# --------------------------------------------------------------------------- #
# Baseline / ratchet
# --------------------------------------------------------------------------- #


class BaselineError(Exception):
    """Raised for malformed/unreadable baseline files."""


def _baseline_entry(finding):
    return {
        "id": finding["id"],
        "code": finding["code"],
        "path": finding["path"],
        "kind": finding["kind"],
        "reason": finding.get("reason", ""),
    }


def build_baseline(findings):
    """Build a deterministic baseline document from current findings.

    Only UNREGISTERED_PLANNING_ARTIFACT findings are eligible. Control-file
    errors (CONTROL_FILE_MISSING, CONTROL_FILE_PARSE_ERROR) mean the governance
    structure itself is broken and must be fixed, not tolerated. Invalid
    exceptions (INVALID_PLANNING_EXCEPTION) must always be fixed, never
    grandfathered.
    """
    entries = [
        _baseline_entry(f)
        for f in findings
        if f["code"] in _BASELINE_ELIGIBLE_CODES
    ]
    entries.sort(key=lambda e: (e["path"], e["code"], e["id"]))
    return {
        "schema": BASELINE_SCHEMA,
        "generated_at": _now_iso(),
        "generator": GENERATOR,
        "entries": entries,
    }


def _validate_baseline_path(path_str, index):
    """Reject unsafe, non-canonical, or absolute baseline entry paths."""
    if not path_str or path_str == ".":
        raise BaselineError(
            f"Baseline entry [{index}] path must be a non-empty, non-dot string."
        )
    if posixpath.isabs(path_str):
        raise BaselineError(
            f"Baseline entry [{index}] path must be repo-relative (not absolute): {path_str!r}."
        )
    if "\\" in path_str:
        raise BaselineError(
            f"Baseline entry [{index}] path contains a backslash: {path_str!r}."
        )
    normalized = posixpath.normpath(path_str)
    if normalized != path_str:
        raise BaselineError(
            f"Baseline entry [{index}] path is not canonical: "
            f"{path_str!r} normalizes to {normalized!r}."
        )
    if normalized.startswith(".."):
        raise BaselineError(
            f"Baseline entry [{index}] path escapes repo root via traversal: {path_str!r}."
        )


def _validate_baseline_entry(entry, index):
    """Validate a single baseline entry dict. Raises BaselineError on violation."""
    if not isinstance(entry, dict):
        raise BaselineError(f"Baseline entry [{index}] must be an object.")

    for field in ("id", "code", "path", "kind", "reason"):
        if field not in entry:
            raise BaselineError(
                f"Baseline entry [{index}] missing required field '{field}'."
            )

    extra = set(entry) - _BASELINE_ENTRY_FIELDS
    if extra:
        raise BaselineError(
            f"Baseline entry [{index}] has unexpected field(s): {sorted(extra)}."
        )

    eid = entry["id"]
    if not isinstance(eid, str) or not _BASELINE_ID_RE.match(eid):
        raise BaselineError(
            f"Baseline entry [{index}] has invalid id {eid!r}; "
            "expected 16 lowercase hex chars."
        )

    for field in ("code", "path", "kind"):
        val = entry[field]
        if not isinstance(val, str) or not val.strip():
            raise BaselineError(
                f"Baseline entry [{index}] field '{field}' must be a non-empty string."
            )

    _validate_baseline_path(entry["path"], index)

    if not isinstance(entry["reason"], str):
        raise BaselineError(
            f"Baseline entry [{index}] field 'reason' must be a string."
        )

    if entry["code"] not in _BASELINE_ELIGIBLE_CODES:
        raise BaselineError(
            f"Baseline entry [{index}] has code {entry['code']!r}; "
            "only UNREGISTERED_PLANNING_ARTIFACT is permitted in a baseline."
        )

    # ID integrity: the id must be reconstructible from code/path/kind. A formally
    # well-formed but computationally wrong id would let a finding be tolerated
    # under a foreign identity — a hand-edited or forged baseline must be rejected.
    expected = compute_finding_id(entry["code"], entry["path"], entry["kind"])
    if eid != expected:
        raise BaselineError(
            f"Baseline entry [{index}] id {eid!r} does not match the id computed "
            f"from its code/path/kind ({expected!r}); baseline is hand-edited or corrupt."
        )


def load_baseline(path):
    """Load and validate a baseline file. Raises BaselineError on problems."""
    full = path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
    if not os.path.exists(full):
        raise BaselineError(f"Baseline file not found: {path}")
    try:
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"Invalid baseline JSON: {exc}") from exc
    except OSError as exc:
        raise BaselineError(f"Cannot read baseline: {exc}") from exc

    if not isinstance(data, dict):
        raise BaselineError("Baseline root must be an object.")

    extra = set(data) - _BASELINE_TOP_FIELDS
    if extra:
        raise BaselineError(
            f"Baseline has unexpected top-level field(s): {sorted(extra)}."
        )

    if data.get("schema") != BASELINE_SCHEMA:
        raise BaselineError(
            f"Baseline schema mismatch: expected {BASELINE_SCHEMA!r}, got {data.get('schema')!r}."
        )
    if data.get("generator") != GENERATOR:
        raise BaselineError(
            f"Baseline generator mismatch: expected {GENERATOR!r}, got {data.get('generator')!r}."
        )
    gen_at = data.get("generated_at")
    if not isinstance(gen_at, str) or not _ISO_DATETIME_RE.match(gen_at):
        raise BaselineError(
            "Baseline 'generated_at' must be an ISO-8601 UTC timestamp "
            f"(YYYY-MM-DDThh:mm:ssZ); got {gen_at!r}."
        )
    try:
        datetime.datetime.strptime(gen_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise BaselineError(
            f"Baseline 'generated_at' has an invalid calendar date/time: {gen_at!r}."
        )

    entries = data.get("entries")
    if not isinstance(entries, list):
        raise BaselineError("Baseline 'entries' must be a list.")
    for i, e in enumerate(entries):
        _validate_baseline_entry(e, i)

    ids = [e["id"] for e in entries]
    seen = set()
    dupes = sorted({i for i in ids if i in seen or seen.add(i)})
    if dupes:
        raise BaselineError(f"Baseline contains duplicate entry id(s): {dupes}.")

    keys = [(e["path"], e["code"], e["id"]) for e in entries]
    if keys != sorted(keys):
        raise BaselineError(
            "Baseline entries are not in canonical order (path, code, id); "
            "regenerate with --update-baseline."
        )
    return data


def partition_ratchet(current_findings, baseline_entries):
    """Split current findings into known/new and compute resolved baseline entries.

    INVALID_PLANNING_EXCEPTION and CONTROL_FILE_* findings are excluded from
    new/known: each is a separate blocking class (handled via _invalid_exceptions()
    / _control_errors()), never baselined and never counted as ordinary drift.
    """
    ratchetable = [
        f for f in current_findings
        if f.get("code") not in _NON_RATCHETABLE_CODES
    ]
    baseline_ids = {e["id"] for e in baseline_entries}
    current_ids = {f["id"] for f in ratchetable}

    new_findings = [f for f in ratchetable if f["id"] not in baseline_ids]
    known_findings = [f for f in ratchetable if f["id"] in baseline_ids]
    resolved_findings = [
        dict(e) for e in baseline_entries if e["id"] not in current_ids
    ]
    resolved_findings.sort(key=lambda e: (e["path"], e["code"], e["id"]))
    return new_findings, known_findings, resolved_findings


def _invalid_exceptions(findings):
    return [f for f in findings if f["code"] in _INVALID_EXCEPTION_CODES]


def _control_errors(findings):
    return [f for f in findings if f["code"] in _CONTROL_FILE_CODES]


def build_report(mode, findings, baseline_path, baseline_loaded,
                 new_findings, known_findings, resolved_findings,
                 written_baseline_entries=None, prune=None):
    invalid = _invalid_exceptions(findings)
    control = _control_errors(findings)
    baseline_count = len(known_findings) + len(resolved_findings)
    summary = {
        "current_findings": len(findings),
        "baseline_findings": baseline_count,
        "new_findings": len(new_findings),
        "known_findings": len(known_findings),
        "resolved_findings": len(resolved_findings),
        "invalid_exceptions": len(invalid),
        "control_errors": len(control),
    }
    if written_baseline_entries is not None:
        summary["written_baseline_entries"] = written_baseline_entries
    return {
        "schema": REPORT_SCHEMA,
        "created_at": _now_iso(),
        "mode": mode,
        "summary": summary,
        "findings": findings,
        "baseline": {
            "path": baseline_path,
            "loaded": baseline_loaded,
        },
        "new_findings": new_findings,
        "known_findings": known_findings,
        "resolved_findings": resolved_findings,
        "invalid_exceptions": invalid,
        "control_errors": control,
        "prune": prune or {
            "enabled": False,
            "dry_run": False,
            "write": False,
            "removed_count": 0,
            "removed": [],
            "blocked": False,
            "block_reasons": [],
            "write_would_block": False,
            "write_block_reasons": [],
        },
    }


def _prune_report(write, resolved_findings, block_reasons=None, write_would_block=False, write_block_reasons=None):
    """Describe a prune attempt without mutating the baseline."""
    removed = [entry["id"] for entry in resolved_findings]
    return {
        "enabled": True,
        "dry_run": not write,
        "write": bool(write),
        "removed_count": len(removed),
        "removed": removed,
        "blocked": bool(block_reasons),
        "block_reasons": list(block_reasons or []),
        "write_would_block": bool(write_would_block),
        "write_block_reasons": list(write_block_reasons or []),
    }


def _write_pruned_baseline(path, baseline, resolved_findings):
    """Remove exactly resolved entries, returning whether the baseline changed.

    An empty removal set is always a no-op, including for an already-empty
    baseline. Any mutating write that would remove every loaded entry fails
    closed, even if a caller omitted its own preflight check.
    """
    resolved_ids = [entry["id"] for entry in resolved_findings]
    if not resolved_ids:
        return False
    if len(resolved_ids) != len(set(resolved_ids)):
        raise BaselineError("Resolved baseline entries do not map uniquely by id.")

    existing_ids = {entry["id"] for entry in baseline["entries"]}
    missing = sorted(set(resolved_ids) - existing_ids)
    if missing:
        raise BaselineError(
            f"Resolved baseline entries are not present in the loaded baseline: {missing}."
        )

    resolved_id_set = set(resolved_ids)
    retained = [
        dict(entry) for entry in baseline["entries"]
        if entry["id"] not in resolved_id_set
    ]
    if not retained:
        raise BaselineError(
            "Prune write would remove the last remaining baseline entry; "
            "refusing to write."
        )

    retained.sort(key=lambda e: (e["path"], e["code"], e["id"]))

    pruned = dict(baseline)
    pruned["generated_at"] = _now_iso()
    pruned["entries"] = retained

    full = path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
    fd = None
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{os.path.basename(full)}.",
            suffix=".tmp",
            dir=os.path.dirname(full) or ".",
            text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None  # os.fdopen() owns and closes the descriptor.
            json.dump(pruned, f, indent=2, ensure_ascii=False)
            f.write("\n")
        # Validate the exact serialized document before replacing the baseline.
        load_baseline(temp_path)
        os.replace(temp_path, full)
    except OSError as exc:
        raise BaselineError(f"Cannot write pruned baseline: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
    return True


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render_human(report, stream):
    s = report["summary"]
    print("Planning Registration Report", file=stream)
    print(f"  mode:                {report['mode']}", file=stream)
    if report["mode"] == "prune_baseline" and not report["baseline"]["loaded"]:
        print(
            "Baseline partition unavailable because baseline failed to load.",
            file=stream,
        )
    print(f"  current findings:    {s['current_findings']}", file=stream)
    print(f"  baseline findings:   {s['baseline_findings']}", file=stream)
    print(f"  known findings:      {s['known_findings']}", file=stream)
    print(f"  new findings:        {s['new_findings']}", file=stream)
    print(f"  resolved findings:   {s['resolved_findings']}", file=stream)
    print(f"  invalid exceptions:  {s['invalid_exceptions']}", file=stream)
    print(f"  control errors:      {s.get('control_errors', 0)}", file=stream)
    if report.get("control_errors"):
        print("Control-file errors (blocking, exit 2):", file=stream)
        for f in report["control_errors"]:
            print(f"  x {f['code']} {f['path']} [{f['id']}]: {f['reason']}", file=stream)
    if report["new_findings"]:
        new_label = (
            "New findings (visible; not accepted by prune):"
            if report["mode"] == "prune_baseline"
            else "New findings (blocking):"
        )
        print(new_label, file=stream)
        for f in report["new_findings"]:
            print(f"  + {f['code']} {f['path']} [{f['id']}]: {f['reason']}", file=stream)
    if report["invalid_exceptions"]:
        print("Invalid exceptions (blocking):", file=stream)
        for f in report["invalid_exceptions"]:
            print(f"  ! {f['code']} {f['path']} [{f['id']}]: {f['reason']}", file=stream)
    if report["resolved_findings"]:
        print("Resolved/stale baseline entries (non-blocking):", file=stream)
        for f in report["resolved_findings"]:
            print(f"  - {f['code']} {f['path']} [{f['id']}]", file=stream)
    prune = report.get("prune", {})
    if prune.get("enabled"):
        action = "dry-run" if prune.get("dry_run") else "write"
        print(f"Baseline prune: {action}", file=stream)
        print(f"  removable entries:  {prune.get('removed_count', 0)}", file=stream)
        for entry_id in prune.get("removed", []):
            print(f"  - {entry_id}", file=stream)
        if prune.get("blocked"):
            print("  blocked:", file=stream)
            for reason in prune.get("block_reasons", []):
                print(f"    x {reason}", file=stream)
        if prune.get("write_would_block"):
            print("  Write would block:", file=stream)
            for reason in prune.get("write_block_reasons", []):
                print(f"    x {reason}", file=stream)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _legacy_scan(findings, args):
    """Preserve the original report-only / --strict scan behavior."""
    if not findings:
        print("All planning artifacts are registered.")
        return 0

    print("Findings:")
    for f in findings:
        print(f"  {f['code']} in {f['path']}: {f['reason']}")
        print(f"    Suggestion: {f['suggestion']}")

    if args.strict:
        return 1
    print("Report-only mode: findings do not fail CI. Use --strict to fail.", file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check registration of planning artifacts.")
    parser.add_argument("--strict", action="store_true",
                        help="Scan mode: fail if unregistered artifacts are found.")
    parser.add_argument("--format", choices=["human", "json"], default="human",
                        help="Output format. JSON is emitted on stdout only.")
    parser.add_argument("--baseline", metavar="PATH",
                        help="Path to the planning-registration baseline file.")
    parser.add_argument("--ratchet", action="store_true",
                        help="Compare current findings against the baseline.")
    parser.add_argument("--update-baseline", action="store_true",
                        help="Write a fresh baseline from current findings and exit 0.")
    parser.add_argument("--prune-baseline", action="store_true",
                        help="Report resolved baseline entries eligible for safe pruning.")
    parser.add_argument("--write", action="store_true",
                        help="With --prune-baseline, write the pruned baseline (default: dry-run).")
    args = parser.parse_args(argv)

    # Usage validation.
    selected_modes = sum(bool(mode) for mode in (
        args.ratchet, args.update_baseline, args.prune_baseline
    ))
    if selected_modes > 1:
        print("Usage error: --ratchet, --update-baseline, and --prune-baseline "
              "are mutually exclusive.", file=sys.stderr)
        return 2
    if args.write and not args.prune_baseline:
        print("Usage error: --write requires --prune-baseline.", file=sys.stderr)
        return 2
    if args.update_baseline and not args.baseline:
        print("Usage error: --update-baseline requires --baseline <path>.", file=sys.stderr)
        return 2
    if args.ratchet and not args.baseline:
        print("Usage error: --ratchet requires --baseline <path>.", file=sys.stderr)
        return 2
    if args.prune_baseline and not args.baseline:
        print("Usage error: --prune-baseline requires --baseline <path>.", file=sys.stderr)
        return 2

    findings = run_checks()

    # --- prune-baseline mode ---
    if args.prune_baseline:
        try:
            baseline = load_baseline(args.baseline)
        except BaselineError as exc:
            prune = _prune_report(args.write, [], [f"baseline_error: {exc}"])
            report = build_report(
                "prune_baseline", findings, args.baseline, False, [], [], [], prune=prune
            )
            if args.format == "json":
                print(json.dumps(report, indent=2, ensure_ascii=False))
                _render_human(report, sys.stderr)
            else:
                _render_human(report, sys.stdout)
            return 2

        new_findings, known_findings, resolved_findings = partition_ratchet(
            findings, baseline.get("entries", [])
        )
        block_reasons = []
        if _control_errors(findings):
            block_reasons.append("control_errors")
        if _invalid_exceptions(findings):
            block_reasons.append("invalid_exceptions")

        write_would_block = False
        write_block_reasons = []

        resolved_ids = {f["id"] for f in resolved_findings}
        baseline_ids = {e["id"] for e in baseline.get("entries", [])}
        would_remove_all_loaded_entries = bool(baseline_ids) and resolved_ids == baseline_ids

        if would_remove_all_loaded_entries:
            write_would_block = True
            write_block_reasons.append("empty_baseline_write")
            if args.write:
                block_reasons.append("empty_baseline_write")

        prune = _prune_report(args.write, resolved_findings, block_reasons, write_would_block, write_block_reasons)
        report = build_report(
            "prune_baseline", findings, args.baseline, True,
            new_findings, known_findings, resolved_findings, prune=prune
        )
        if block_reasons:
            if args.format == "json":
                print(json.dumps(report, indent=2, ensure_ascii=False))
                _render_human(report, sys.stderr)
            else:
                _render_human(report, sys.stdout)
            print("prune-baseline: blocked; baseline not written.", file=sys.stderr)
            return 2

        if args.write:
            try:
                _write_pruned_baseline(args.baseline, baseline, resolved_findings)
            except BaselineError as exc:
                prune["blocked"] = True
                prune["block_reasons"].append(f"write_error: {exc}")
                if args.format == "json":
                    print(json.dumps(report, indent=2, ensure_ascii=False))
                    _render_human(report, sys.stderr)
                else:
                    _render_human(report, sys.stdout)
                return 2

        if args.format == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _render_human(report, sys.stdout)
        return 0

    # --- update-baseline mode ---
    if args.update_baseline:
        # Refuse to write a baseline over a broken governance structure. A control
        # error (exit 2) means findings are unreliable; an invalid exception (exit 1)
        # must be fixed, never grandfathered. In both cases NO baseline is written,
        # so a defective state can never be silently stamped "resolved".
        control = _control_errors(findings)
        invalid = _invalid_exceptions(findings)
        if control or invalid:
            report = build_report("update_baseline", findings, args.baseline, False,
                                  new_findings=[], known_findings=[], resolved_findings=[])
            if args.format == "json":
                print(json.dumps(report, indent=2, ensure_ascii=False))
                _render_human(report, sys.stderr)
            else:
                _render_human(report, sys.stdout)
            if control:
                print("update-baseline: control-file error(s) present; baseline not written.",
                      file=sys.stderr)
                return 2
            print("update-baseline: invalid exception(s) present; baseline not written.",
                  file=sys.stderr)
            return 1

        baseline = build_baseline(findings)
        full = (args.baseline if os.path.isabs(args.baseline)
                else os.path.join(REPO_ROOT, args.baseline))
        try:
            os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                json.dump(baseline, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except OSError as exc:
            print(f"Error: cannot write baseline: {exc}", file=sys.stderr)
            return 2
        report = build_report("update_baseline", findings, args.baseline, True,
                              new_findings=[], known_findings=[], resolved_findings=[],
                              written_baseline_entries=len(baseline["entries"]))
        if args.format == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            _render_human(report, sys.stdout)
            print(f"Baseline written: {args.baseline} ({len(baseline['entries'])} entries)",
                  file=sys.stderr)
        return 0

    # --- ratchet mode ---
    if args.ratchet:
        try:
            baseline = load_baseline(args.baseline)
        except BaselineError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        new_findings, known_findings, resolved_findings = partition_ratchet(
            findings, baseline.get("entries", []))
        report = build_report("ratchet", findings, args.baseline, True,
                              new_findings, known_findings, resolved_findings)
        invalid = report["invalid_exceptions"]
        control = report["control_errors"]
        if args.format == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
            _render_human(report, sys.stderr)
        else:
            _render_human(report, sys.stdout)

        # Control-file errors mean the tool cannot trust its own control structure,
        # so the ratchet comparison is unreliable: fail config-style (exit 2).
        if control:
            print("Ratchet: control-file error(s) — cannot read control structure; "
                  "treating as config error.", file=sys.stderr)
            return 2
        should_block = bool(new_findings) or bool(invalid)
        if should_block:
            print("Ratchet: blocking — new findings or invalid exceptions present.",
                  file=sys.stderr)
            return 1
        print("Ratchet: no new drift. Known findings tolerated via baseline.",
              file=sys.stderr)
        return 0

    # --- scan mode ---
    if args.format == "json":
        report = build_report("scan", findings, args.baseline,
                              False,
                              new_findings=[], known_findings=[], resolved_findings=[])
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if findings and args.strict:
            return 1
        return 0

    return _legacy_scan(findings, args)


if __name__ == "__main__":
    sys.exit(main())
