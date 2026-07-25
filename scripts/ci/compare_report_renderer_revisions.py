from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


class DifferentialError(RuntimeError):
    pass


SCENARIOS: dict[str, dict[str, Any]] = {
    "profile_max": {},
    "profile_summary": {"level": "summary"},
    "profile_machine_lean": {"level": "machine-lean"},
    "plan_only": {"plan_only": True},
    "code_only": {"code_only": True},
    "redaction": {"redact_secrets": True},
    "meta_min": {"meta_density": "min"},
    "meta_standard": {"meta_density": "standard"},
    "meta_full": {"meta_density": "full"},
    "meta_none": {"meta_none": True},
    "organism": {"extras": {"organism_index": True}},
    "heatmap": {"extras": {"heatmap": True}},
    "augment_delta": {
        "extras": {"augment_sidecar": True, "delta_reports": True},
        "delta_meta": {"summary": {"files_added": 1}},
    },
    "artifact_refs": {"artifact_refs": {"index_json_basename": "index.json"}},
    "extension_filter": {"ext_filter": [".py"]},
    "path_filter": {"path_filter": "src/"},
    "truncation": {"max_file_bytes": 24},
    "multi_repo": {"multi_repo": True},
}

ALLOWED_DIFFERENCES: dict[str, set[str]] = {
    "plan_only": {
        "contact_ratio", "coverage",
        "risk_level", "snapshots", "yaml_content",
    },
    "extension_filter": {
        "content_paths", "coverage", "end_count", "file_id_count",
        "snapshots", "start_count", "yaml_content",
    },
}

_RUNNER = r'''
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import yaml
from merger.repoground.core import clock, merge

fixture = Path(sys.argv[1])
scenarios = json.loads(sys.argv[2])
frozen = datetime.datetime(2026, 7, 24, 12, 0, tzinfo=datetime.timezone.utc)
specs = (
    ("README.md", "doc", ["ai-context"]),
    ("src/main.py", "source", ["entrypoint"]),
    ("docs/guide.md", "doc", ["runbook"]),
    (".github/workflows/ci.yml", "config", ["ci"]),
)

def file_info(path, rel_path, root_label="report-fixture", category="source", tags=None):
    payload = path.read_bytes()
    return merge.FileInfo(
        root_label=root_label, abs_path=path, rel_path=Path(rel_path),
        size=len(payload), is_text=True,
        md5=hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        category=category, tags=[] if tags is None else tags, ext=path.suffix, content=None,
        inclusion_reason="normal",
    )

def files():
    return [
        file_info(fixture / rel, rel, category=category, tags=list(tags))
        for rel, category, tags in specs
    ]

def yaml_meta(report):
    payload = report.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    loaded = yaml.safe_load(payload)
    return loaded if isinstance(loaded, dict) else {}

def project(report):
    meta = yaml_meta(report)
    content = meta.get("content", {}) if isinstance(meta.get("content", {}), dict) else {}
    coverage_meta = meta.get("coverage", {}) if isinstance(meta.get("coverage", {}), dict) else {}
    ids = re.findall(r'file:id="([^"]+)"', report)
    return {
        "contact_ratio": re.findall(r"\*\*Contact Ratio:\*\*\s*([^\n]+)", report),
        "content_paths": re.findall(r"\*\*Path:\*\* `([^`]*)`", report),
        "coverage": re.findall(r"\*\*Coverage:\*\*\s*([^\n]+)", report),
        "end_count": report.count("<!-- FILE_END "),
        "file_id_count": [len(ids), len(set(ids))],
        "risk_level": re.findall(r"\*\*Risk Level:\*\*\s*([^\n]+)", report),
        "snapshots": sorted(line.strip() for line in report.splitlines() if "with content)" in line),
        "start_count": report.count("<!-- FILE_START "),
        "yaml_content": {
            "coverage_included_files": coverage_meta.get("included_files"),
            "coverage_pct": coverage_meta.get("coverage_pct"),
            "emitted_files": content.get("emitted_files"),
            "present": content.get("present"),
            "selected_text_files": content.get("selected_text_files"),
        },
    }

out = {}
for name, raw_options in scenarios.items():
    options = dict(raw_options)
    multi_repo = options.pop("multi_repo", False)
    extras = options.pop("extras", None)
    if extras is not None:
        options["extras"] = merge.ExtrasConfig(**extras)
    selected = files()
    if multi_repo:
        selected.append(file_info(fixture / "src/main.py", "extra.py", root_label="second-repo"))
    kwargs = {
        "files": selected, "max_file_bytes": 0, "sources": [fixture],
        "debug": False, "level": "max", "plan_only": False,
    }
    kwargs.update(options)
    with clock.frozen(frozen):
        report = "".join(merge.iter_report_blocks(**kwargs))
    out[name] = project(report)
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
'''


def _run_git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=text
    )
    return completed.stdout


def _materialize(repo: Path, revision: str, destination: Path) -> None:
    process = subprocess.Popen(
        ["git", "archive", "--format=tar", revision],
        cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        archive.extractall(destination, filter="data")
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    if process.wait() != 0:
        raise DifferentialError(f"git archive failed for {revision}: {stderr}")


def _module_sha(root: Path) -> str:
    path = root / "merger" / "repoground" / "core" / "merge.py"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _worktree_digest(repo: Path) -> str:
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=repo, check=True, capture_output=True,
    ).stdout
    untracked = str(_run_git(repo, "ls-files", "--others", "--exclude-standard")).splitlines()
    digest = hashlib.sha256(diff)
    for rel in sorted(untracked):
        path = repo / rel
        digest.update(rel.encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _identity(repo: Path, root: Path, revision: str | None) -> dict[str, Any]:
    commit = str(_run_git(repo, "rev-parse", revision or "HEAD")).strip()
    tree = str(_run_git(repo, "rev-parse", f"{commit}^{{tree}}")).strip()
    dirty = False if revision else bool(str(_run_git(repo, "status", "--porcelain")).strip())
    return {
        "commit": commit,
        "dirty": dirty,
        "module_sha256": _module_sha(root),
        "tree": tree,
        "worktree_diff_sha256": None if revision else _worktree_digest(repo),
    }


def _render(root: Path, fixture_root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        [sys.executable, "-c", _RUNNER, str(fixture_root), json.dumps(SCENARIOS)],
        cwd=root, env=env, check=False, capture_output=True,
        text=True, timeout=180,
    )
    if completed.returncode != 0:
        raise DifferentialError(
            f"renderer failed for {root}: {completed.stderr.strip()}"
        )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise DifferentialError("renderer runner returned a non-object payload")
    return payload


def compare_revisions(
    repo: Path,
    base_revision: str,
    target_root: Path,
    *,
    target_revision: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    target_root = target_root.resolve()
    fixture_root = target_root / "merger/repoground/tests/fixtures/report_renderer/repo"
    with tempfile.TemporaryDirectory(prefix="repoground-differential-") as temp_dir:
        base_root = Path(temp_dir) / "base"
        base_root.mkdir()
        _materialize(repo, base_revision, base_root)
        actual_target_root = target_root
        if target_revision is not None:
            actual_target_root = Path(temp_dir) / "target"
            actual_target_root.mkdir()
            _materialize(repo, target_revision, actual_target_root)
        base_identity = _identity(repo, base_root, base_revision)
        target_identity = _identity(repo, actual_target_root, target_revision)
        if base_identity["commit"] == target_identity["commit"] and not target_identity["dirty"]:
            raise DifferentialError("differential comparison requires distinct revisions")
        base_output = _render(base_root, fixture_root)
        target_output = _render(actual_target_root, fixture_root)

    comparisons: dict[str, dict[str, Any]] = {}
    unapproved: dict[str, list[str]] = {}
    for scenario in SCENARIOS:
        base_projection = base_output[scenario]
        target_projection = target_output[scenario]
        differing = sorted(
            key for key in set(base_projection) | set(target_projection)
            if base_projection.get(key) != target_projection.get(key)
        )
        allowed = ALLOWED_DIFFERENCES.get(scenario, set())
        rejected = sorted(set(differing) - allowed)
        comparisons[scenario] = {
            "allowed_differences": sorted(allowed),
            "base_projection": base_projection,
            "differing_fields": differing,
            "target_projection": target_projection,
            "unapproved_differences": rejected,
        }
        if rejected:
            unapproved[scenario] = rejected

    return {
        "base": base_identity,
        "comparisons": comparisons,
        "intentional_corrections": {
            key: sorted(value) for key, value in ALLOWED_DIFFERENCES.items()
        },
        "scenarios": sorted(SCENARIOS),
        "schema_version": 1,
        "target": target_identity,
        "unapproved_differences": unapproved,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--target-root", type=Path, default=Path.cwd())
    parser.add_argument("--target-revision")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare_revisions(
        args.repo, args.base_revision, args.target_root,
        target_revision=args.target_revision,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 1 if result["unapproved_differences"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
