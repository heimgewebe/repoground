from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import jsonschema

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.build_release_candidate import (
    LICENSE_EXPRESSION,
    LOCK_PATHS,
    SEMANTIC_CONSTRAINTS_PATH,
    SEMANTIC_INPUT_PATH,
    SEMANTIC_LOCK_PATH,
    SEMANTIC_PLATFORM_CONTRACT_PATH,
    VERSION_RE,
)

INPUT_PATHS = (
    "requirements/repobrief-runtime.in",
    "requirements/repobrief-dev.in",
    "requirements/repobrief-browser.in",
    "requirements/repobrief-lock-tools.in",
)

REQUIRED_FILES = (
    "RELEASE_VERSION",
    "LICENSE",
    "CHANGELOG.md",
    "docs/release/licensing.md",
    "docs/release/release-policy.md",
    "docs/release/upgrade-rollback.md",
    "scripts/release/build_release_candidate.py",
    "scripts/release/verify_release_candidate.py",
    "scripts/release/compile_dependency_locks.sh",
    *INPUT_PATHS,
    *LOCK_PATHS,
    SEMANTIC_PLATFORM_CONTRACT_PATH,
    "merger/lenskit/contracts/repobrief-semantic-platforms.v1.schema.json",
    "merger/lenskit/requirements-semantic.txt",
    SEMANTIC_INPUT_PATH,
    SEMANTIC_CONSTRAINTS_PATH,
    SEMANTIC_LOCK_PATH,
    "scripts/release/compile_semantic_lock.py",
    "scripts/release/compile_semantic_lock.sh",
)


def _finding(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _check_lock(path: Path, relative: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    text = path.read_text(encoding="utf-8")
    if "Python 3.12" not in text:
        findings.append(
            _finding(
                "LOCK_PYTHON_VERSION",
                relative,
                "lock must be compiled with Python 3.12",
            )
        )

    lines = text.splitlines()
    package_starts: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, 1):
        if not line or line[0].isspace() or line.startswith(("#", "--")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s\\]+)\s+\\", line)
        if match is None:
            findings.append(
                _finding(
                    "LOCK_REQUIREMENT_UNSUPPORTED",
                    relative,
                    f"line {lineno}: {line}",
                )
            )
            continue
        package_starts.append((lineno - 1, match.group(1)))

    if not package_starts:
        findings.append(
            _finding("LOCK_EMPTY", relative, "no exact package pins found")
        )
        return findings

    for index, (start, package) in enumerate(package_starts):
        end = package_starts[index + 1][0] if index + 1 < len(package_starts) else len(lines)
        block = "\n".join(lines[start:end])
        if "--hash=sha256:" not in block:
            findings.append(
                _finding(
                    "LOCK_HASH_MISSING",
                    relative,
                    f"{package} has no SHA-256 hash",
                )
            )
    return findings



def _load_semantic_contract(
    repo: Path,
) -> tuple[dict[str, object] | None, dict[str, str] | None]:
    contract_path = repo / SEMANTIC_PLATFORM_CONTRACT_PATH
    schema_path = (
        repo / "merger/lenskit/contracts/repobrief-semantic-platforms.v1.schema.json"
    )
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft7Validator(schema).validate(contract)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        return None, _finding(
            "SEMANTIC_PLATFORM_CONTRACT_INVALID",
            SEMANTIC_PLATFORM_CONTRACT_PATH,
            str(exc),
        )
    if not isinstance(contract, dict):
        return None, _finding(
            "SEMANTIC_PLATFORM_CONTRACT_INVALID",
            SEMANTIC_PLATFORM_CONTRACT_PATH,
            "contract root is not an object",
        )
    return contract, None


def _semantic_target(
    contract: dict[str, object],
) -> tuple[dict[str, object] | None, dict[str, str] | None]:
    try:
        target = contract["supported_targets"][0]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as exc:
        return None, _finding(
            "SEMANTIC_PLATFORM_CONTRACT_INVALID",
            SEMANTIC_PLATFORM_CONTRACT_PATH,
            str(exc),
        )
    if not isinstance(target, dict):
        return None, _finding(
            "SEMANTIC_PLATFORM_CONTRACT_INVALID",
            SEMANTIC_PLATFORM_CONTRACT_PATH,
            "semantic target is not an object",
        )
    return target, None


def _check_semantic_artifacts(
    repo: Path,
    target: dict[str, object],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for key, expected_path in (
        ("input", SEMANTIC_INPUT_PATH),
        ("constraints", SEMANTIC_CONSTRAINTS_PATH),
        ("lock", SEMANTIC_LOCK_PATH),
    ):
        record = target.get(key)
        if not isinstance(record, dict):
            findings.append(
                _finding(
                    "SEMANTIC_PLATFORM_CONTRACT_INVALID",
                    SEMANTIC_PLATFORM_CONTRACT_PATH,
                    f"{key} record is not an object",
                )
            )
            continue
        observed_path = record.get("path")
        if observed_path != expected_path:
            findings.append(
                _finding(
                    "SEMANTIC_PATH_MISMATCH",
                    SEMANTIC_PLATFORM_CONTRACT_PATH,
                    f"{key}: expected={expected_path} observed={observed_path}",
                )
            )
            continue
        data = (repo / expected_path).read_bytes()
        observed_hash = hashlib.sha256(data).hexdigest()
        if record.get("sha256") != observed_hash:
            findings.append(
                _finding(
                    "SEMANTIC_HASH_MISMATCH",
                    expected_path,
                    f"contract={record.get('sha256')} observed={observed_hash}",
                )
            )
    return findings


def _semantic_package_starts(lock_text: str) -> list[str]:
    return [
        line
        for line in lock_text.splitlines()
        if line and not line[0].isspace() and not line.startswith(("#", "--"))
    ]


def _check_semantic_lock_boundary(
    repo: Path,
    target: dict[str, object],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    lock_text = (repo / SEMANTIC_LOCK_PATH).read_text(encoding="utf-8")
    starts = _semantic_package_starts(lock_text)
    if len(starts) != target.get("package_count"):
        findings.append(
            _finding(
                "SEMANTIC_PACKAGE_COUNT_MISMATCH",
                SEMANTIC_LOCK_PATH,
                f"contract={target.get('package_count')} observed={len(starts)}",
            )
        )
    required_fragments = (
        (
            "sentence-transformers==5.6.0 \\",
            "SEMANTIC_ROOT_PIN_MISSING",
            "sentence-transformers==5.6.0",
        ),
        (
            "torch @ https://download-r2.pytorch.org/whl/cpu/torch-2.13.0%2Bcpu",
            "SEMANTIC_TORCH_TARGET_MISSING",
            "target-specific CPU Torch wheel is absent",
        ),
    )
    for fragment, code, detail in required_fragments:
        if fragment not in lock_text:
            findings.append(_finding(code, SEMANTIC_LOCK_PATH, detail))
    if lock_text.count("--hash=sha256:") != len(starts):
        findings.append(
            _finding(
                "SEMANTIC_HASH_COUNT_MISMATCH",
                SEMANTIC_LOCK_PATH,
                "every selected wheel must have exactly one SHA-256",
            )
        )
    return findings


def _check_semantic_core_isolation(repo: Path) -> list[dict[str, str]]:
    core_lock = (repo / "requirements/repobrief-runtime.lock.txt").read_text(
        encoding="utf-8"
    ).lower()
    leaked = "sentence-transformers" in core_lock or re.search(
        r"(?m)^torch(?:==|\s@)", core_lock
    )
    if not leaked:
        return []
    return [
        _finding(
            "SEMANTIC_DEPENDENCY_LEAKED_TO_CORE",
            "requirements/repobrief-runtime.lock.txt",
            "semantic roots must remain outside the core runtime lock",
        )
    ]


def _check_semantic_extension(repo: Path) -> list[dict[str, str]]:
    contract, contract_error = _load_semantic_contract(repo)
    if contract_error is not None or contract is None:
        return [contract_error] if contract_error is not None else []
    target, target_error = _semantic_target(contract)
    if target_error is not None or target is None:
        return [target_error] if target_error is not None else []
    return [
        *_check_semantic_artifacts(repo, target),
        *_check_semantic_lock_boundary(repo, target),
        *_check_semantic_core_isolation(repo),
    ]

def _path_filter_blocks(header: str) -> list[set[str]]:
    lines = header.splitlines()
    blocks: list[set[str]] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s+)paths:\s*$", lines[index])
        if match is None:
            index += 1
            continue
        base_indent = len(match.group(1))
        values: set[str] = set()
        index += 1
        while index < len(lines):
            line = lines[index]
            indent = len(line) - len(line.lstrip())
            if line.strip() and indent <= base_indent:
                break
            item = re.match(r'^\s+-\s+["\']?([^"\']+?)["\']?\s*$', line)
            if item is not None:
                values.add(item.group(1))
            index += 1
        blocks.append(values)
    return blocks


def _check_workflows(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    workflow_dir = root / ".github/workflows"
    paths = sorted(
        {*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")}
    )
    lock_pattern = r"requirements/repobrief-[A-Za-z-]+\.lock\.txt"
    for path in paths:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if re.search(r"\bpip(?:3)?\s+install\b", stripped):
                if "--upgrade pip" in stripped:
                    findings.append(
                        _finding(
                            "WORKFLOW_PIP_UPGRADE",
                            relative,
                            f"line {lineno}: mutable pip upgrade",
                        )
                    )
                    continue
                if (
                    "--require-hashes" not in stripped
                    or "repobrief-" not in stripped
                    or ".lock.txt" not in stripped
                ):
                    findings.append(
                        _finding(
                            "WORKFLOW_UNLOCKED_INSTALL",
                            relative,
                            f"line {lineno}: {stripped}",
                        )
                    )

        jobs_match = re.search(r"(?m)^jobs:\s*$", text)
        if jobs_match is None:
            continue
        header = text[: jobs_match.start()]
        jobs = text[jobs_match.end() :]
        used_locks = set(re.findall(lock_pattern, jobs))
        if used_locks:
            python_versions = set(
                re.findall(
                    r"python-version:\s*[\"']?([^\"'\s]+)", jobs
                )
            )
            if python_versions != {"3.12"}:
                findings.append(
                    _finding(
                        "WORKFLOW_LOCK_PYTHON_MISMATCH",
                        relative,
                        "RepoBrief locks require exactly Python 3.12; "
                        f"observed={sorted(python_versions)!r}",
                    )
                )
        blocks = _path_filter_blocks(header)
        for block_number, block in enumerate(blocks, 1):
            for lock in sorted(used_locks - block):
                findings.append(
                    _finding(
                        "WORKFLOW_LOCK_TRIGGER_MISSING",
                        relative,
                        f"paths block {block_number} does not include {lock}",
                    )
                )
    return findings


def scan(root: str | Path) -> dict[str, object]:
    repo = Path(root).resolve()
    findings: list[dict[str, str]] = []
    for relative in REQUIRED_FILES:
        if not (repo / relative).is_file():
            findings.append(_finding("RELEASE_FILE_MISSING", relative, "required release file is missing"))
    if findings:
        return {"status": "fail", "findings": findings}

    release_version = (repo / "RELEASE_VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(release_version):
        findings.append(_finding("RELEASE_VERSION_INVALID", "RELEASE_VERSION", release_version))
    license_text = (repo / "LICENSE").read_text(encoding="utf-8")
    if LICENSE_EXPRESSION not in license_text:
        findings.append(_finding("LICENSE_REF_MISSING", "LICENSE", LICENSE_EXPRESSION))
    if "No permission is granted" not in license_text:
        findings.append(_finding("LICENSE_BOUNDARY_MISSING", "LICENSE", "restrictive boundary is absent"))
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{release_version}]" not in changelog:
        findings.append(_finding("CHANGELOG_VERSION_MISSING", "CHANGELOG.md", release_version))

    for relative in LOCK_PATHS:
        findings.extend(_check_lock(repo / relative, relative))
    findings.extend(_check_semantic_extension(repo))
    findings.extend(_check_workflows(repo))

    task_index = json.loads((repo / "docs/tasks/index.json").read_text(encoding="utf-8"))
    task_ids = {
        item.get("id")
        for item in task_index.get("tasks", [])
        if isinstance(item, dict)
    }
    for task_id in (
        "TASK-LENSKIT-SEMANTIC-LOCK-001",
        "TASK-REPOBRIEF-PUBLIC-LICENSE-DECISION-001",
    ):
        if task_id not in task_ids:
            findings.append(_finding("FOLLOWUP_TASK_MISSING", "docs/tasks/index.json", task_id))

    return {
        "status": "pass" if not findings else "fail",
        "release_version": release_version,
        "lock_count": len(LOCK_PATHS),
        "findings": findings,
        "does_not_establish": [
            "public_distribution_permission",
            "product_readiness",
            "semantic_quality",
            "cross_platform_semantic_support",
            "semantic_default_promotion",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check RepoBrief release packaging contracts")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    report = scan(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
