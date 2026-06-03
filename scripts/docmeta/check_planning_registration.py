import json
import os
import re
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_PATH_REF_RE = re.compile(r"(?:docs|scripts)/[A-Za-z0-9_./-]+")

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
    errors = []

    # 1. docs/tasks/index.json
    index_text, err = _read_text("docs/tasks/index.json")
    if err:
        errors.append(("CONTROL_FILE_MISSING", "docs/tasks/index.json", err))
    else:
        try:
            data = json.loads(index_text)
            for task in data.get("tasks", []):
                for path in task.get("evidence", []) or []:
                    ref = _normalize_ref(path)
                    if ref:
                        registered.add(ref)
                for item in task.get("missing_evidence", []) or []:
                    # Transitional report-only behavior: missing_evidence may
                    # contain free text with path references. Normalize them so
                    # punctuation/backticks do not create false drift.
                    registered.update(_extract_path_refs(str(item)))
        except json.JSONDecodeError as e:
            errors.append(("CONTROL_FILE_PARSE_ERROR", "docs/tasks/index.json", f"Invalid JSON: {e}"))

    # 2. docs/tasks/board.md
    board_text, err = _read_text("docs/tasks/board.md")
    if err:
        errors.append(("CONTROL_FILE_MISSING", "docs/tasks/board.md", err))
    else:
        registered.update(_extract_path_refs(board_text))

    # 3. docs/roadmap.md
    roadmap_text, err = _read_text("docs/roadmap.md")
    if err:
        errors.append(("CONTROL_FILE_MISSING", "docs/roadmap.md", err))
    else:
        matches = re.findall(r'\]\(([^)]+)\)', roadmap_text)
        for match in matches:
            match = _normalize_ref(match)
            if match.endswith('.md'):
                if not match.startswith('docs/'):
                    # Relative links from roadmap.md need to be resolved to docs/
                    registered.add(os.path.normpath(os.path.join('docs', match)))
                else:
                    registered.add(match)
        # Also plain docs/ and scripts/ paths, normalized from free text.
        registered.update(_extract_path_refs(roadmap_text))

    # Self-register control files
    registered.add("docs/tasks/index.json")
    registered.add("docs/tasks/board.md")
    registered.add("docs/roadmap.md")

    return registered, errors

def is_registered(rel_path, registered_paths, meta):
    # 1. Exact match
    if rel_path in registered_paths:
        return True

    # 2. Inside a registered directory (simple prefix)
    for rp in registered_paths:
        if rp.endswith("/") and rel_path.startswith(rp):
            return True

    # 3. Check alias or redirects in meta (if supported later)

    # 4. Check relations (e.g. if the document itself claims to be related to a planning artifact)
    if meta and "relations" in meta:
        for relation in meta["relations"]:
            if relation.startswith("docs/tasks/") or relation == "docs/roadmap.md":
                # Report-only transitional escape hatch; not sufficient for a
                # future strict/ratchet exception contract.
                return True

    # 5. Marked as deprecated, superseded, archived, or deferred
    if meta and meta.get("status") in ("deprecated", "superseded", "archived", "deferred"):
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
                     if ":" in lines[i]:
                         parts = lines[i].split(":", 1)
                         key = parts[0].strip()
                         val = parts[1].strip()
                         # very basic array parsing
                         if val.startswith("[") and val.endswith("]"):
                              meta[key] = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                         else:
                              meta[key] = val.strip("'\"")
    except OSError as exc:
         print(f"Warning: failed to read {filepath}: {exc}", file=sys.stderr)
    except UnicodeDecodeError as exc:
         print(f"Warning: failed to decode {filepath}: {exc}", file=sys.stderr)
    except Exception as exc:
         print(f"Warning: unexpected error parsing {filepath}: {exc}", file=sys.stderr)
    return meta

def run_checks():
    registered_paths, errors = get_registered_paths()
    findings = [{"code": code, "file": f, "message": msg} for code, f, msg in errors]

    # Walk docs/ and check blueprints, ADRs, etc.
    docs_dir = os.path.join(REPO_ROOT, "docs")
    for root, dirs, files in os.walk(docs_dir):
        # Ignore _generated, etc
        if "_generated" in root or ".git" in root:
             continue
        for file in files:
            if not file.endswith(".md"):
                continue
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, REPO_ROOT)

            # Skip templates or non-normative
            if "templates/" in rel_path or file.startswith("_"):
                continue

            meta = parse_markdown_meta(full_path)

            # For now, we only enforce on blueprints and adrs, not general docs
            if "blueprints/" in rel_path or "adrs/" in rel_path:
                if not is_registered(rel_path, registered_paths, meta):
                     findings.append({
                         "code": "UNREGISTERED_PLANNING_ARTIFACT",
                         "file": rel_path,
                         "message": f"Artifact {rel_path} is active but not registered in tasks/board.md, tasks/index.json or roadmap.md"
                     })

    return findings

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Check registration of planning artifacts.")
    parser.add_argument("--strict", action="store_true", help="Fail if unregistered artifacts are found.")
    args = parser.parse_args(argv)

    findings = run_checks()
    if not findings:
        print("All planning artifacts are registered.")
        return 0

    print("Findings:")
    for f in findings:
        print(f"  {f['code']} in {f['file']}: {f['message']}")

    if args.strict:
        return 1
    print("Report-only mode: findings do not fail CI. Use --strict to fail.", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
