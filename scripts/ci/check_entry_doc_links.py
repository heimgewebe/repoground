#!/usr/bin/env python3
"""Fail-closed entry-document link check for RepoGround.

Scans a fixed set of entry documents for relative Markdown links that point
to missing paths. Historical proof/diagnostic surfaces are not scanned here;
this gate only protects the operator entry surface named by T005 freshness.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

DEFAULT_ENTRY_DOCS = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "docs/GETTING_STARTED.md",
    "docs/FAQ.md",
    "docs/glossary.md",
    "docs/roadmap.md",
    "docs/architecture/system-map.repoground.md",
    "docs/architecture/product-boundaries.md",
    "docs/roadmap/repoground-master-roadmap.md",
)


def _iter_broken(root: Path, docs: tuple[str, ...]) -> list[dict[str, str]]:
    broken: list[dict[str, str]] = []
    for rel in docs:
        doc = root / rel
        if not doc.is_file():
            broken.append(
                {
                    "doc": rel,
                    "href": "",
                    "label": "",
                    "reason": "entry_doc_missing",
                }
            )
            continue
        text = doc.read_text(encoding="utf-8")
        for label, href in LINK_RE.findall(text):
            if href.startswith(("http://", "https://", "mailto:", "#")):
                continue
            href_path = href.split("#", 1)[0].strip()
            if not href_path:
                continue
            target = (doc.parent / href_path).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                broken.append(
                    {
                        "doc": rel,
                        "href": href,
                        "label": label,
                        "reason": "outside_repo",
                    }
                )
                continue
            if not target.exists():
                broken.append(
                    {
                        "doc": rel,
                        "href": href,
                        "label": label,
                        "reason": "missing_target",
                    }
                )
    return broken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    findings = _iter_broken(root, DEFAULT_ENTRY_DOCS)
    report = {
        "ok": not findings,
        "entry_doc_count": len(DEFAULT_ENTRY_DOCS),
        "broken_count": len(findings),
        "broken": findings,
    }
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        if findings:
            print("entry doc link check: FAIL")
            for item in findings:
                print(
                    f"  - {item['doc']}: {item['href'] or '(missing doc)'} "
                    f"({item['reason']})"
                )
        else:
            print(
                "entry doc link check: PASS "
                f"({report['entry_doc_count']} entry docs, 0 broken links)"
            )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
