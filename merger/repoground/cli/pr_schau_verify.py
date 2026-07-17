#!/usr/bin/env python3
"""
pr-schau-verify: Official Verifier for PR-Schau Bundles (Contract v1.0).

Usage:
    python -m merger.repoground.cli.pr_schau_verify <bundle_dir_or_json> [--level {basic,full}]

Checks:
    [BASIC]
    - Schema validation (pr-schau.v1.schema.json)
    - Physical existence of 'parts'

    [FULL]
    - Integrity: primary_part in parts
    - Integrity: parts <-> artifacts mapping
    - SHA256 verification of content artifacts
    - Guard: No-Truncate check in Markdown content
    - Semantics: Byte overhead check (<= 64KB or 5%)
"""

import sys
import json
import hashlib
import argparse
import re
from pathlib import Path
from typing import Dict, Any

try:
    import jsonschema
except ImportError:
    jsonschema = None

# Constants from Contract
# Locate schema relative to this script
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "pr-schau.v1.schema.json"
MAX_OVERHEAD_BYTES = 64 * 1024
MAX_OVERHEAD_RATIO = 0.05

def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def _fail(msg: str):
    print(f"❌ FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

def _pass(msg: str):
    print(f"✅ PASS: {msg}")

def load_schema() -> Dict[str, Any]:
    # Candidates for schema location: relative to script or standard location
    candidates = [SCHEMA_PATH]

    schema_file = None
    for c in candidates:
        if c.exists():
            schema_file = c
            break

    if not schema_file:
        _fail(f"Schema not found. Checked: {[str(c) for c in candidates]}")

    try:
        return json.loads(schema_file.read_text("utf-8"))
    except Exception as e:
        _fail(f"Failed to load schema: {e}")
        return {}

def verify_basic(bundle_path: Path, data: Dict[str, Any], schema: Dict[str, Any]) -> None:
    # 1. Schema Validation
    if jsonschema:
        try:
            jsonschema.validate(instance=data, schema=schema)
            _pass("Schema validation")
        except jsonschema.ValidationError as e:
            _fail(f"Schema violation: {e.message}")
    else:
        print("⚠️  WARNING: jsonschema not installed, skipping strict schema check.")

    # 2. File Existence
    bundle_dir = bundle_path.parent
    completeness = data.get("completeness", {})
    parts = completeness.get("parts", [])

    # Check if parts is None or empty list
    if not parts:
        _fail("No parts listed (completeness.parts is empty or missing).")

    for part in parts:
        part_path = bundle_dir / part
        if not part_path.exists():
            _fail(f"Missing part file: {part}")

    _pass(f"All {len(parts)} parts exist on disk")

def verify_full(bundle_path: Path, data: Dict[str, Any]) -> None:
    bundle_dir = bundle_path.parent
    comp = data.get("completeness", {})
    arts = data.get("artifacts", [])

    parts = comp.get("parts", [])
    primary = comp.get("primary_part")
    is_complete = comp.get("is_complete", False)
    policy = comp.get("policy", "unknown")

    # 1. Integrity: primary_part in parts
    if primary and primary not in parts:
        _fail(f"primary_part '{primary}' is not listed in parts {parts}")
    _pass("primary_part is valid")

    # 2. Integrity: parts <-> artifacts
    # Every part must have an artifact entry with matching basename
    art_map = {a.get("basename"): a for a in arts}
    for p in parts:
        if p not in art_map:
            _fail(f"Part '{p}' has no corresponding artifact entry")
    _pass("All parts map to artifacts")

    # 3. SHA256 Verification
    # Check all artifacts that have a sha256 field, especially canonical_md/part_md
    for art in arts:
        basename = art.get("basename")
        declared_sha = art.get("sha256")
        role = art.get("role")

        if not basename:
            continue

        target = bundle_dir / basename

        # If schema mandates SHA (canonical_md/part_md), it must be there.
        # Schema check covers existence, here we check correctness if present or required by logic.
        if role in ("canonical_md", "part_md") and not declared_sha:
             _fail(f"Artifact '{basename}' (role={role}) missing required sha256")

        if target.exists() and declared_sha:
            computed = _compute_sha256(target)
            if computed != declared_sha:
                _fail(f"SHA256 mismatch for {basename}. Declared: {declared_sha}, Computed: {computed}")
            print(f"   - Verified hash for {basename}")
    _pass("Artifact hashes verified")

    # 4. Guard: No-Truncate
    # Scan all parts for forbidden text
    if not (policy == "truncate" and not is_complete):
        # The contract says "No silent truncation". Binary omission is explicit.
        # However, "content truncated at" usually implies the file reader gave up.
        # For now, we strictly guard against 'truncated at' which implies partial read.
        strict_forbidden = ["Content truncated at", "content truncated at", "truncated at"]

        for p in parts:
            p_path = bundle_dir / p
            if p_path.exists():
                try:
                    text = p_path.read_text(encoding="utf-8", errors="ignore")
                    for sub in strict_forbidden:
                        if sub in text:
                            _fail(f"Found truncation marker '{sub}' in {p}, but policy is not 'truncate'")
                except Exception as e:
                    print(f"⚠️  Could not read {p} for text scan: {e}")
        _pass("No silent truncation detected")

    # 5. Zone Verification (MUST)
    # Primary part must contain summary and files_manifest zones
    if primary:
        p_path = bundle_dir / primary
        if p_path.exists():
            try:
                text = p_path.read_text(encoding="utf-8", errors="ignore")
                # Dual-read: accept both quoted and unquoted type for migration compatibility.
                # Robust regex handles varied whitespace and optional attributes within the marker.
                # Matches: type=summary, type="summary", type="summary" id="..."
                if not re.search(r'<!--\s+zone:begin\s+[^>]*?\btype=(?:"summary"|summary)(?:\s+|-->)', text):
                    _fail(f"Primary part {primary} missing mandatory 'summary' zone")
                if not re.search(r'<!--\s+zone:begin\s+[^>]*?\btype=(?:"files_manifest"|files_manifest)(?:\s+|-->)', text):
                    _fail(f"Primary part {primary} missing mandatory 'files_manifest' zone")
                _pass("Mandatory zones (summary, files_manifest) present")
            except Exception:
                pass

    # 6. Semantics: Byte Overhead & Consistency
    if is_complete:
        expected = comp.get("expected_bytes", 0)
        declared_emitted = comp.get("emitted_bytes", 0)

        actual_emitted = 0
        for p in parts:
            p_path = bundle_dir / p
            if p_path.exists():
                actual_emitted += p_path.stat().st_size

        # expected must be meaningful for complete bundles
        if expected <= 0 and len(parts) > 0:
            # Note: expected_bytes might be 0 if the content is empty.
            # We allow 0, but negative values are invalid.
            if expected < 0:
                 _fail(f"Invalid expected_bytes for complete bundle: expected_bytes={expected}")

        # Check declared vs actual
        if actual_emitted != declared_emitted:
             _fail(f"Emitted bytes mismatch! Declared: {declared_emitted}, Actual on disk: {actual_emitted}")

        # For complete bundles, emitted should never be smaller than expected (split overhead should increase emitted)
        if actual_emitted < expected:
            _fail(f"Emitted bytes smaller than expected_bytes! Expected: {expected}, Emitted: {actual_emitted}")

        # Contract: emitted_bytes must be roughly expected_bytes
        # Calculate overhead (can be negative if logic differs, but logically should be >= 0)
        # Overhead is metadata/headers/etc added during splitting.
        overhead = actual_emitted - expected

        # Calculate allowed overhead relative to expected bytes
        allowed_overhead = max(MAX_OVERHEAD_BYTES, int(expected * MAX_OVERHEAD_RATIO))

        if overhead > allowed_overhead:
            _fail(f"Byte overhead excessive! Expected: {expected}, Emitted: {actual_emitted}, Overhead: {overhead} (Allowed: {allowed_overhead})")

        _pass(f"Byte consistency check passed (Overhead: {overhead} bytes)")

def run_verify(bundle: str, level: str = "full") -> int:
    """Library entry point: verify a PR-Schau bundle and return an exit code.

    Mirrors ``main()`` but returns an int exit code instead of calling
    ``sys.exit`` so the unified ``lenskit`` CLI can dispatch to it. Returns
    0 on success, 1 on verification failure, and 2 for invalid parameters.
    The internal checks still use ``_fail`` (which raises ``SystemExit``);
    that is caught here and converted to a return code, keeping the standalone
    behaviour identical.
    """
    # Validate level parameter
    allowed_levels = {"basic", "full"}
    if level not in allowed_levels:
        allowed = ", ".join(sorted(allowed_levels))
        print(
            f"❌ Invalid verification level: {level!r}. Expected one of: {allowed}",
            file=sys.stderr,
        )
        return 2

    try:
        target = Path(bundle)
        if target.is_dir():
            target = target / "bundle.json"

        if not target.exists():
            _fail(f"Bundle file not found: {target}")

        print(f"🔍 Verifying {target} [Level: {level}]...")

        try:
            with target.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            _fail(f"Invalid JSON: {e}")

        schema = load_schema()

        # Always run basic
        verify_basic(target, data, schema)

        if level == "full":
            verify_full(target, data)
    except SystemExit as e:
        code = e.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1

    print("\n✨ Verification Successful.")
    return 0

def main():
    parser = argparse.ArgumentParser(description="PR-Schau Verify")
    parser.add_argument("bundle", help="Path to bundle.json or bundle directory")
    parser.add_argument("--level", choices=["basic", "full"], default="full", help="Verification level")
    args = parser.parse_args()

    sys.exit(run_verify(args.bundle, args.level))

if __name__ == "__main__":
    main()
