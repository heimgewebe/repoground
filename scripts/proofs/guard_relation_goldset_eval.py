#!/usr/bin/env python3
"""Evaluate the diagnostic Guard Relation Goldset.

This evaluator measures a fixed goldset candidate surface. It does not produce
persistent relation cards and does not prove test sufficiency, runtime behavior,
or schema runtime equivalence.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


VALID_EXPECTED = {"accepted", "rejected", "unresolved"}
VALID_CANDIDATE = {"accepted", "rejected", "unresolved"}


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return round(num / den, 6)


def _validate_goldset(payload: dict[str, Any]) -> None:
    if payload.get("kind") != "lenskit.guard_relation_goldset":
        raise ValueError("invalid goldset kind")
    if payload.get("version") != "1.0":
        raise ValueError("invalid goldset version")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("goldset cases must be a non-empty list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("goldset case must be an object")
        cid = case.get("id")
        if not isinstance(cid, str) or not cid:
            raise ValueError("goldset case id must be a non-empty string")
        if cid in seen:
            raise ValueError(f"duplicate case id: {cid}")
        seen.add(cid)
        if case.get("candidate_status") not in VALID_CANDIDATE:
            raise ValueError(f"invalid candidate_status for {cid}")
        if case.get("expected_status") not in VALID_EXPECTED:
            raise ValueError(f"invalid expected_status for {cid}")
        if not isinstance(case.get("relation_type"), str) or not case.get("relation_type"):
            raise ValueError(f"invalid relation_type for {cid}")
        if not isinstance(case.get("subject"), str) or not case.get("subject"):
            raise ValueError(f"invalid subject for {cid}")
        if case.get("expected_status") != "unresolved" and case.get("object") is None:
            raise ValueError(f"resolved/rejected case requires object: {cid}")


def evaluate_goldset(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _validate_goldset(payload)

    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_case = []
    for case in payload["cases"]:
        relation_type = case["relation_type"]
        candidate = case["candidate_status"]
        expected = case["expected_status"]
        bucket = counts[relation_type]
        bucket["total"] += 1

        if candidate == "unresolved" or expected == "unresolved":
            outcome = "unresolved"
            bucket["unresolved"] += 1
        elif candidate == "accepted" and expected == "accepted":
            outcome = "true_positive"
            bucket["true_positive"] += 1
        elif candidate == "accepted" and expected == "rejected":
            outcome = "false_positive"
            bucket["false_positive"] += 1
        elif candidate != "accepted" and expected == "accepted":
            outcome = "false_negative"
            bucket["false_negative"] += 1
        else:
            outcome = "true_negative"
            bucket["true_negative"] += 1

        per_case.append({
            "id": case["id"],
            "relation_type": relation_type,
            "candidate_status": candidate,
            "expected_status": expected,
            "outcome": outcome,
        })

    by_relation: dict[str, Any] = {}
    for relation_type, raw_counts in sorted(counts.items()):
        tp = raw_counts.get("true_positive", 0)
        fp = raw_counts.get("false_positive", 0)
        fn = raw_counts.get("false_negative", 0)
        tn = raw_counts.get("true_negative", 0)
        unresolved = raw_counts.get("unresolved", 0)
        by_relation[relation_type] = {
            "total": raw_counts.get("total", 0),
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "unresolved": unresolved,
            "precision": _ratio(tp, tp + fp),
            "recall_on_resolved_positive_cases": _ratio(tp, tp + fn),
            "false_positive_rate_on_resolved_negative_cases": _ratio(fp, fp + tn),
        }

    policy = payload.get("decision_policy", {})
    needs_consumer = bool(policy.get("persist_contract_requires_consumer", True))
    persist_requested = bool(payload.get("persistence_decision", {}).get("persist_guard_relation_cards"))
    report = {
        "kind": "lenskit.guard_relation_goldset_eval",
        "version": "1.0",
        "source_goldset": str(path),
        "relation_types": sorted(by_relation),
        "by_relation": by_relation,
        "per_case": per_case,
        "decision": {
            "persist_guard_relation_cards": False,
            "input_requested_persistence": persist_requested,
            "reason": "diagnostic goldset only; no established consumer need; unresolved/negative-control cases remain explicit",
            "requires_consumer_before_persistence": needs_consumer,
        },
        "does_not_establish": payload.get("does_not_establish", []),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate diagnostic Guard Relation Goldset")
    parser.add_argument("goldset", nargs="?", default="docs/retrieval/guard_relation_goldset.v1.json")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = evaluate_goldset(Path(args.goldset))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
