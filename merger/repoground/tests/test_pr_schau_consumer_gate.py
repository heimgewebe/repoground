"""
PR-Schau Consumer Gate (CI Guard)

Purpose:
  Prevent "best effort" consumers from bypassing the canonical loader/verifier.
  Direct parsing of bundle.json in random places is a drift factory.

Rule:
  Within merger/repoground/, references to 'bundle.json' are allowed ONLY in:
    - core/pr_schau_bundle.py   (canonical loader)
    - cli/pr_schau_verify.py    (official verifier)
    - tests/*                   (tests may craft bundles)
  Everywhere else: FAIL.

Etymology:
  "gate" = a controllable boundary. Contracts without boundaries are vibes.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple


# ROOT is merger/repoground
ROOT = Path(__file__).resolve().parents[1]

# Allowed occurrences (relative to ROOT)
ALLOW_CONTAINS: Tuple[str, ...] = (
    "core/pr_schau_bundle.py",
    "cli/pr_schau_verify.py",
    "tests/",
    "core/extractor.py",  # Allowed because it generates the bundle
)

# Extra allow: if you later add a dedicated migrator, whitelist it explicitly here, e.g.:
# "cli/pr_schau_migrate.py",


def _is_allowed(rel_posix: str) -> bool:
    for a in ALLOW_CONTAINS:
        if a.endswith("/") and rel_posix.startswith(a):
            return True
        if rel_posix == a:
            return True
    return False


def _read_text_safely(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def test_no_direct_bundle_json_consumers_outside_loader():
    """
    CI Guard:
      No direct consumer should read or reference bundle.json outside the canonical layer.
    """
    offenders: List[Tuple[str, int, str]] = []

    # Scan only python sources inside merger/repoground
    for py in ROOT.rglob("*.py"):
        try:
            rel = py.relative_to(ROOT).as_posix()
        except ValueError:
             # Should not happen given glob
             continue

        text = _read_text_safely(py)
        if not text:
            continue

        if "bundle.json" in text and not _is_allowed(rel):
            # collect line hits to make it actionable
            for i, line in enumerate(text.splitlines(), start=1):
                if "bundle.json" in line:
                    offenders.append((rel, i, line.strip()))

    if offenders:
        msg_lines = []
        msg_lines.append("Direct 'bundle.json' usage detected outside canonical loader/verifier.")
        msg_lines.append("Fix: use merger.repoground.core.pr_schau_bundle.load_pr_schau_bundle(...) instead.")
        msg_lines.append("")
        msg_lines.append("Offenders:")
        for rel, ln, line in offenders[:50]:
            msg_lines.append(f"  - {rel}:{ln}: {line}")
        if len(offenders) > 50:
            msg_lines.append(f"  ... and {len(offenders) - 50} more")
        raise AssertionError("\n".join(msg_lines))
