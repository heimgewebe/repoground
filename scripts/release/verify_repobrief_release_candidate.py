from __future__ import annotations

import argparse
import json
import sys
import tarfile
import warnings
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.verify_release_candidate import verify_legacy_release_candidate

verify_release_candidate = verify_legacy_release_candidate


def main() -> int:
    warnings.warn(
        "verify_repobrief_release_candidate.py is deprecated; use verify_release_candidate.py",
        DeprecationWarning,
        stacklevel=2,
    )
    parser = argparse.ArgumentParser(
        description="Verify a legacy RepoBrief v1 release candidate"
    )
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--repo")
    args = parser.parse_args()
    try:
        report = verify_legacy_release_candidate(args.candidate_dir, repo=args.repo)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
