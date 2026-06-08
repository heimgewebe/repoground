import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys

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

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
    """Return today's date. Indirected for testability."""
    return datetime.date.today()


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
            for task in data.get("tasks", []):
                for path in task.get("evidence", []) or []:
                    ref = _normalize_ref(path)
                    if ref:
                        registered.add(ref)
        except json.JSONDecodeError as e:
            findings.append({
                "code": CODE_CONTROL_FILE_PARSE_ERROR,
                "path": "docs/tasks/index.json",
                "kind": "control_file_parse_error",
                "reason": f"Invalid JSON: {e}",
                "suggestion": "Fix the JSON syntax in docs/tasks/index.json.",
                "source": "planning-registration",
            })

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
                        val = parts[1].strip().strip('"\'')
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


def parse_planning_registration_block(filepath):
    """Extract the nested `planning_registration:` frontmatter mapping.

    Returns a dict of scalar key->value if the block is present, otherwise None.
    Only single-level nesting is supported (status/reason/owner/expires).
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
            if indent == 0 and stripped.rstrip() == "planning_registration:":
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
            block[k.strip()] = v.strip().strip('"\'')
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
                        "reason, owner and an unexpired ISO expires (YYYY-MM-DD)."
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

    Invalid exceptions are intentionally NOT baselined: a broken/expired
    exemption must always be fixed, never grandfathered.
    """
    entries = [
        _baseline_entry(f)
        for f in findings
        if f["code"] not in _INVALID_EXCEPTION_CODES
    ]
    entries.sort(key=lambda e: (e["path"], e["code"], e["id"]))
    return {
        "schema": BASELINE_SCHEMA,
        "generated_at": _now_iso(),
        "generator": GENERATOR,
        "entries": entries,
    }


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
    if data.get("schema") != BASELINE_SCHEMA:
        raise BaselineError(
            f"Baseline schema mismatch: expected {BASELINE_SCHEMA!r}, got {data.get('schema')!r}."
        )
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise BaselineError("Baseline 'entries' must be a list.")
    for e in entries:
        if not isinstance(e, dict) or "id" not in e:
            raise BaselineError("Each baseline entry must be an object with an 'id'.")
    return data


def partition_ratchet(current_findings, baseline_entries):
    """Split current findings into known/new and compute resolved baseline entries."""
    baseline_ids = {e["id"] for e in baseline_entries}
    current_ids = {f["id"] for f in current_findings}

    new_findings = [f for f in current_findings if f["id"] not in baseline_ids]
    known_findings = [f for f in current_findings if f["id"] in baseline_ids]
    resolved_findings = [
        dict(e) for e in baseline_entries if e["id"] not in current_ids
    ]
    resolved_findings.sort(key=lambda e: (e["path"], e["code"], e["id"]))
    return new_findings, known_findings, resolved_findings


def _invalid_exceptions(findings):
    return [f for f in findings if f["code"] in _INVALID_EXCEPTION_CODES]


def build_report(mode, findings, baseline_path, baseline_loaded,
                 new_findings, known_findings, resolved_findings):
    invalid = _invalid_exceptions(findings)
    baseline_count = len(known_findings) + len(resolved_findings)
    return {
        "schema": REPORT_SCHEMA,
        "created_at": _now_iso(),
        "mode": mode,
        "summary": {
            "current_findings": len(findings),
            "baseline_findings": baseline_count,
            "new_findings": len(new_findings),
            "known_findings": len(known_findings),
            "resolved_findings": len(resolved_findings),
            "invalid_exceptions": len(invalid),
        },
        "findings": findings,
        "baseline": {
            "path": baseline_path,
            "loaded": baseline_loaded,
        },
        "new_findings": new_findings,
        "known_findings": known_findings,
        "resolved_findings": resolved_findings,
        "invalid_exceptions": invalid,
    }


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render_human(report, stream):
    s = report["summary"]
    print("Planning Registration Report", file=stream)
    print(f"  mode:                {report['mode']}", file=stream)
    print(f"  current findings:    {s['current_findings']}", file=stream)
    print(f"  baseline findings:   {s['baseline_findings']}", file=stream)
    print(f"  known findings:      {s['known_findings']}", file=stream)
    print(f"  new findings:        {s['new_findings']}", file=stream)
    print(f"  resolved findings:   {s['resolved_findings']}", file=stream)
    print(f"  invalid exceptions:  {s['invalid_exceptions']}", file=stream)
    if report["new_findings"]:
        print("New findings (blocking):", file=stream)
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
    args = parser.parse_args(argv)

    # Usage validation.
    if args.ratchet and args.update_baseline:
        print("Usage error: --ratchet and --update-baseline are mutually exclusive.",
              file=sys.stderr)
        return 2
    if args.update_baseline and not args.baseline:
        print("Usage error: --update-baseline requires --baseline <path>.", file=sys.stderr)
        return 2
    if args.ratchet and not args.baseline:
        print("Usage error: --ratchet requires --baseline <path>.", file=sys.stderr)
        return 2

    findings = run_checks()

    # --- update-baseline mode ---
    if args.update_baseline:
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
                              new_findings=[], known_findings=[], resolved_findings=[])
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
        if args.format == "json":
            print(json.dumps(report, indent=2, ensure_ascii=False))
            _render_human(report, sys.stderr)
        else:
            _render_human(report, sys.stdout)

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
                              args.baseline is not None,
                              new_findings=[], known_findings=[], resolved_findings=[])
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if findings and args.strict:
            return 1
        return 0

    return _legacy_scan(findings, args)


if __name__ == "__main__":
    sys.exit(main())
