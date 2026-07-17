#!/usr/bin/env python3
"""Build a diagnostic Retrieval Promotion Gate report from existing measurements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from merger.repoground.retrieval.retrieval_promotion_gate import (  # noqa: E402
    build_promotion_gate_report,
    load_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="diagnostic retrieval promotion gate")
    parser.add_argument("--legacy", required=True, help="Legacy FTS baseline JSON")
    parser.add_argument("--review", required=True, help="Review-intent baseline JSON")
    parser.add_argument("--graph", help="Optional graph freshness/status JSON")
    parser.add_argument("--range", dest="range_report", help="Optional range/citation health JSON")
    parser.add_argument("--recall-key", default="recall@10")
    parser.add_argument("--out")
    args = parser.parse_args()

    report = build_promotion_gate_report(
        load_json(Path(args.legacy)),
        load_json(Path(args.review)),
        graph_report=load_json(Path(args.graph)) if args.graph else None,
        range_report=load_json(Path(args.range_report)) if args.range_report else None,
        recall_key=args.recall_key,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
