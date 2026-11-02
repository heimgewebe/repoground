"""Source-bound, paired Git-only vs precomputed Flake evidence read benchmark."""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from merger.repoground.cli.cmd_federation import _parse_pinned_targets
from merger.repoground.core.flake_evidence_pack import (
    prepare_flake_evidence_pack, read_flake_evidence_pack, write_flake_evidence_pack,
)

KIND = "repoground.flake_evidence_latency_study"
VERSION = "1.0"


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)], 3),
        "maximum_ms": round(ordered[-1], 3),
        "minimum_ms": round(ordered[0], 3),
    }


def measure_flake_evidence(
    source_root: str | Path, source_commit: str, *, source_repo: str,
    targets: dict[str, tuple[Path, str]], samples: int = 30, warmups: int = 3,
) -> dict:
    """Same exact edge set with warm cache; alternate request order to limit bias."""
    if not 5 <= samples <= 200 or not 0 <= warmups <= 20:
        raise ValueError("samples must be 5..200; warmups must be 0..20")
    with tempfile.TemporaryDirectory(prefix="repoground-flake-study-") as temp:
        pack_path = Path(temp) / "flake_evidence.json"
        original = prepare_flake_evidence_pack(
            source_root, source_commit, source_repo=source_repo, targets=targets,
        )
        write_flake_evidence_pack(pack_path, original)

        def git_query():
            return prepare_flake_evidence_pack(
                source_root, source_commit,
                source_repo=source_repo, targets=targets,
            )

        def offline_query():
            return read_flake_evidence_pack(
                pack_path, expected_repo=source_repo,
                expected_commit=source_commit,
            )

        for _ in range(warmups):
            if git_query()["pack_sha256"] != original["pack_sha256"]:
                raise AssertionError("Git producer changed during warmup")
            if offline_query()["pack_sha256"] != original["pack_sha256"]:
                raise AssertionError("precomputed artifact changed during warmup")
        timings = {"git_only": [], "precomputed_offline": []}
        queries = {"git_only": git_query, "precomputed_offline": offline_query}
        for iteration in range(samples):
            order = (
                ("git_only", "precomputed_offline")
                if iteration % 2 == 0
                else ("precomputed_offline", "git_only")
            )
            for name in order:
                start = time.perf_counter_ns()
                observed = queries[name]()
                elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
                if observed["pack_sha256"] != original["pack_sha256"]:
                    raise AssertionError(name + " produced a different evidence payload")
                timings[name].append(elapsed_ms)
    measurement = {
        "kind": KIND, "version": VERSION,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "source_repo": source_repo, "source_commit": source_commit,
        "target_pins": original["target_pins"],
        "pack_sha256": original["pack_sha256"],
        "relations": len(original["evidence"]["relations"]),
        "gaps": original["evidence"]["gaps"],
        "status": original["evidence"]["status"],
        "method": {
            "samples_per_path": samples,
            "warmups_per_path": warmups,
            "order": "alternating paired, same process and pinned Git objects",
            "git_only": "compute full producer from requested Git objects each query",
            "precomputed_offline": "hash-check content-addressed JSON, no Git or network",
            "excludes": [
                "one-time artifact production", "fleet publishing",
                "MCP transport", "network access", "live runtime checks",
            ],
        },
        "results": {name: _summary(values) for name, values in timings.items()},
        "does_not_establish": [
            "agent_answer_quality", "runtime_dependency",
            "complete_impact", "cross-machine performance",
        ],
    }
    measurement["speedup_p95"] = round(
        measurement["results"]["git_only"]["p95_ms"]
        / max(measurement["results"]["precomputed_offline"]["p95_ms"], 0.001),
        3,
    )
    return measurement


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--target", action="append", required=True)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = measure_flake_evidence(
        args.repo_root, args.commit, source_repo=args.repo_id,
        targets=_parse_pinned_targets(args.target),
        samples=args.samples, warmups=args.warmups,
    )
    text = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        if out.exists() or out.is_symlink() or not out.parent.is_dir():
            raise ValueError("measurement output must be an absent file in an existing directory")
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
