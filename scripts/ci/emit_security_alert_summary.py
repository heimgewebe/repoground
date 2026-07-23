#!/usr/bin/env python3
"""Emit a fail-closed, machine-readable GitHub security-alert readback summary.

Primary evidence is the raw CodeQL SARIF this repository's own `codeql.yml`
job already produces (no extra permission, no network call). Optional
secondary evidence is a captured GitHub code-scanning alerts API response,
supplied as a small JSON file so this script never makes network calls or
handles credentials itself.

Exit code is 0 only for the "clean" state. Every other state --
alerts_present, unavailable, unauthorized, unknown -- exits non-zero, so a
missing or unreachable readback can never be silently treated as "zero
alerts".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.assert_codeql_sarif_clean import collect_results  # noqa: E402

from merger.repoground.retrieval.security_alert_summary import (  # noqa: E402
    SecurityAlertSummaryError,
    classify_security_alert_state,
)


def _load_sarif_evidence(sarif_dir: Path | None) -> dict[str, Any] | None:
    if sarif_dir is None:
        return None
    try:
        _files, findings = collect_results(sarif_dir)
    except ValueError as exc:
        print(f"security-alert readback: raw SARIF unavailable ({exc})")
        return {"available": False, "alert_count": None}
    return {"available": True, "alert_count": len(findings)}


def _load_api_evidence(api_response_path: Path | None) -> dict[str, Any] | None:
    if api_response_path is None:
        return None
    try:
        payload = json.loads(api_response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"security-alert readback: cannot read API evidence file {api_response_path}: {exc}"
        ) from exc

    if isinstance(payload, list):
        # Raw GitHub REST API GET /repos/{owner}/{repo}/code-scanning/alerts response array
        return {
            "status_code": 200,
            "open_alert_count": len(payload),
            "paginated": None,
            "page_count": 1,
        }

    if not isinstance(payload, dict):
        raise SystemExit(
            "security-alert readback: API evidence file must contain a JSON object or list"
        )

    if "alerts" in payload and "open_alert_count" not in payload:
        status_code = payload.get("status_code", 200)
        alerts = payload["alerts"]
        if not isinstance(alerts, list):
            raise SystemExit("security-alert readback: 'alerts' in API evidence must be a list")
        return {
            "status_code": status_code,
            "open_alert_count": len(alerts) if status_code == 200 else None,
            "repository": payload.get("repository"),
            "commit_sha": payload.get("commit_sha"),
            "paginated": payload.get("paginated"),
            "page_count": payload.get("page_count"),
            "stale": payload.get("stale"),
        }

    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sarif-dir",
        type=Path,
        default=None,
        help="Directory containing raw CodeQL SARIF output from this job's analyze step.",
    )
    parser.add_argument(
        "--api-response",
        type=Path,
        default=None,
        help=(
            "Optional JSON file with captured code-scanning alert evidence. "
            "A raw GitHub API array is treated as one non-exhaustive page; zero items "
            "therefore cannot prove clean. To prove exhaustive zero, pass a structured "
            "object with status_code=200, open_alert_count=0, and paginated=true. "
            "Never fetched by this script; the caller owns any token."
        ),
    )
    parser.add_argument(
        "--repository",
        type=str,
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="Target repository (owner/repo). Defaults to GITHUB_REPOSITORY if set.",
    )
    parser.add_argument(
        "--commit-sha",
        type=str,
        default=os.environ.get("GITHUB_SHA"),
        help="Target commit SHA. Defaults to GITHUB_SHA if set.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write the summary JSON. Always printed to stdout as well.",
    )
    args = parser.parse_args()

    sarif_evidence = _load_sarif_evidence(args.sarif_dir)
    api_evidence = _load_api_evidence(args.api_response)

    try:
        summary = classify_security_alert_state(
            sarif_evidence=sarif_evidence,
            api_evidence=api_evidence,
            repository=args.repository,
            commit_sha=args.commit_sha,
        )
    except SecurityAlertSummaryError as exc:
        print(f"security-alert readback error: {exc}")
        return 2

    rendered = json.dumps(summary, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    state = summary["state"]
    if state == "clean":
        print("security-alert readback: state=clean (0 alerts, evidence confirmed)")
        return 0

    print(
        f"security-alert readback: state={state} ({summary['state_reason']}); "
        "failing closed -- missing or non-clean evidence is never treated as clean"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

