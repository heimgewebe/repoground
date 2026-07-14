from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
INPUT_REL = "requirements/repobrief-semantic-linux-x86_64-py312.in"
CONSTRAINTS_REL = "requirements/repobrief-semantic-linux-x86_64-py312.constraints.txt"
LOCK_REL = "requirements/repobrief-semantic-linux-x86_64-py312.lock.txt"
TORCH_URL = (
    "https://download-r2.pytorch.org/whl/cpu/"
    "torch-2.13.0%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl"
)
TORCH_SHA256 = "4ca4a9394b0c771238a4f73590fdbbc4debad85ed0fa63d026ae1b085da7d6e2"
SUPPORTED_TARGET_ID = "cpython-312-linux-x86_64"
ROOT_PINS = {
    "sentence-transformers": "5.6.0",
    "torch": "2.13.0+cpu",
}


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_observation() -> dict[str, str]:
    return {
        "implementation": platform.python_implementation(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "os": sys.platform,
        "architecture": platform.machine().lower(),
    }


def is_supported_target(observed: dict[str, str]) -> bool:
    return (
        observed.get("implementation") == "CPython"
        and observed.get("python_minor") == "3.12"
        and observed.get("os") == "linux"
        and observed.get("architecture") in {"x86_64", "amd64"}
    )


def require_supported_target() -> dict[str, str]:
    observed = target_observation()
    supported = is_supported_target(observed)
    if not supported:
        raise RuntimeError(
            "semantic lock generation/install is supported only for "
            f"{SUPPORTED_TARGET_ID}; observed={json.dumps(observed, sort_keys=True)}"
        )
    return observed


def _pip_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": env.get("HOME", "/tmp/repobrief-semantic-home"),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONHASHSEED": "0",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HOME": "/tmp/repobrief-semantic-hf-home",
        }
    )
    return env


def _archive_hash(item: dict[str, object]) -> str:
    download = item.get("download_info")
    if not isinstance(download, dict):
        raise RuntimeError("pip report entry has no download_info object")
    archive = download.get("archive_info")
    if not isinstance(archive, dict):
        raise RuntimeError("pip report entry has no archive_info object")
    hashes = archive.get("hashes")
    if isinstance(hashes, dict):
        value = hashes.get("sha256")
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    legacy = archive.get("hash")
    if isinstance(legacy, str) and legacy.startswith("sha256="):
        value = legacy.removeprefix("sha256=")
        if re.fullmatch(r"[0-9a-f]{64}", value):
            return value
    raise RuntimeError("pip report entry has no valid SHA-256 archive hash")



def _report_package_record(item: object) -> dict[str, str]:
    if not isinstance(item, dict):
        raise RuntimeError("pip report install entry is not an object")
    metadata = item.get("metadata")
    download = item.get("download_info")
    if not isinstance(metadata, dict) or not isinstance(download, dict):
        raise RuntimeError("pip report entry is missing metadata/download_info")
    raw_name = metadata.get("name")
    version = metadata.get("version")
    url = download.get("url")
    if not all(isinstance(value, str) and value for value in (raw_name, version, url)):
        raise RuntimeError("pip report entry has incomplete name/version/url")
    assert isinstance(raw_name, str)
    assert isinstance(version, str)
    assert isinstance(url, str)
    filename = Path(unquote(urlparse(url).path)).name
    if not filename.endswith(".whl"):
        raise RuntimeError(f"non-wheel artifact rejected for {raw_name}: {filename}")
    return {
        "name": _canonical_name(raw_name),
        "version": version,
        "sha256": _archive_hash(item),
        "filename": filename,
        "url": url,
    }


def _validate_semantic_root_records(packages: dict[str, dict[str, str]]) -> None:
    for name, expected_version in ROOT_PINS.items():
        record = packages.get(name)
        if record is None:
            raise RuntimeError(f"required semantic root missing from closure: {name}")
        if record["version"] != expected_version:
            raise RuntimeError(
                f"semantic root version mismatch for {name}: "
                f"expected={expected_version} observed={record['version']}"
            )
    torch = packages["torch"]
    if torch["url"] != TORCH_URL or torch["sha256"] != TORCH_SHA256:
        raise RuntimeError(
            "Torch CPU wheel identity/hash does not match the pinned target artifact"
        )


def _report_packages(report_path: Path) -> list[dict[str, str]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    items = report.get("install")
    if not isinstance(items, list) or not items:
        raise RuntimeError("pip report contains no install closure")

    packages: dict[str, dict[str, str]] = {}
    for item in items:
        record = _report_package_record(item)
        name = record["name"]
        previous = packages.get(name)
        if previous is not None and previous != record:
            raise RuntimeError(f"duplicate conflicting package record: {name}")
        packages[name] = record

    _validate_semantic_root_records(packages)
    return [packages[name] for name in sorted(packages)]

def _constraints_bytes(packages: list[dict[str, str]]) -> bytes:
    lines = [
        "# Exact target closure for RepoBrief's optional semantic extension.",
        f"# Target: {SUPPORTED_TARGET_ID}",
        "# Generated from the reviewed lock compiler; do not install this file directly.",
        "",
    ]
    lines.extend(f"{item['name']}=={item['version']}" for item in packages)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _lock_bytes(packages: list[dict[str, str]]) -> bytes:
    lines = [
        "#",
        "# Target-specific SHA-256 lock for RepoBrief's optional semantic extension.",
        f"# Target: {SUPPORTED_TARGET_ID}",
        "# Compiler environment: scripts/release/compile_semantic_lock.sh",
        "# One selected wheel hash per package intentionally fails closed on other targets.",
        "#",
        "",
    ]
    for item in packages:
        if item["name"] == "torch":
            lines.append(f"torch @ {item['url']} \\")
        else:
            lines.append(f"{item['name']}=={item['version']} \\")
        lines.append(f"    --hash=sha256:{item['sha256']}")
        lines.append(f"    # wheel: {item['filename']}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _resolve_report(constraints: Path | None, report_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--ignore-installed",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--report",
        str(report_path),
        "-r",
        str(ROOT / INPUT_REL),
    ]
    if constraints is not None:
        command.extend(["-c", str(constraints)])
    subprocess.run(command, cwd=ROOT, env=_pip_environment(), check=True)


def compile_lock(*, check: bool) -> dict[str, object]:
    observed = require_supported_target()
    constraints_path = ROOT / CONSTRAINTS_REL
    lock_path = ROOT / LOCK_REL
    if check and (not constraints_path.is_file() or not lock_path.is_file()):
        raise RuntimeError("committed semantic constraints/lock are required for --check")

    with tempfile.TemporaryDirectory(prefix="repobrief-semantic-lock-") as tmp:
        report_path = Path(tmp) / "pip-report.json"
        _resolve_report(constraints_path if check else None, report_path)
        packages = _report_packages(report_path)
        constraints_bytes = _constraints_bytes(packages)
        lock_bytes = _lock_bytes(packages)

    if check:
        actual_constraints = constraints_path.read_bytes()
        actual_lock = lock_path.read_bytes()
        if actual_constraints != constraints_bytes:
            raise RuntimeError("semantic constraints do not reproduce byte-for-byte")
        if actual_lock != lock_bytes:
            raise RuntimeError("semantic lock does not reproduce byte-for-byte")
        operation = "checked"
    else:
        constraints_path.write_bytes(constraints_bytes)
        lock_path.write_bytes(lock_bytes)
        operation = "written"

    return {
        "status": "pass",
        "operation": operation,
        "target_id": SUPPORTED_TARGET_ID,
        "observed": observed,
        "package_count": len(packages),
        "root_pins": ROOT_PINS,
        "constraints": {
            "path": CONSTRAINTS_REL,
            "sha256": hashlib.sha256(constraints_bytes).hexdigest(),
        },
        "lock": {
            "path": LOCK_REL,
            "sha256": hashlib.sha256(lock_bytes).hexdigest(),
        },
        "does_not_establish": [
            "semantic_quality",
            "cross_platform_completeness",
            "vulnerability_absence",
            "default_promotion_readiness",
        ],
    }


def verify_install(target: Path) -> dict[str, object]:
    observed = require_supported_target()
    lock_path = ROOT / LOCK_REL
    if not lock_path.is_file():
        raise RuntimeError(f"semantic lock missing: {LOCK_REL}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--only-binary=:all:",
        "--require-hashes",
        "--target",
        str(target),
        "-r",
        str(lock_path),
    ]
    subprocess.run(command, cwd=ROOT, env=_pip_environment(), check=True)
    probe_code = (
        "import sys;sys.path.insert(0,sys.argv[1]);"
        "import importlib.metadata as m, json, sentence_transformers, torch;"
        "print(json.dumps({'sentence-transformers':"
        "m.version('sentence-transformers'),'torch':m.version('torch'),"
        "'torch_cuda_available':torch.cuda.is_available()},sort_keys=True))"
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            probe_code,
            str(target),
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        env=_pip_environment(),
    )
    versions = json.loads(probe.stdout)
    if versions["sentence-transformers"] != ROOT_PINS["sentence-transformers"]:
        raise RuntimeError("installed sentence-transformers version mismatch")
    if versions["torch"] != ROOT_PINS["torch"]:
        raise RuntimeError("installed torch version mismatch")
    return {
        "status": "pass",
        "target_id": SUPPORTED_TARGET_ID,
        "observed": observed,
        "lock_path": LOCK_REL,
        "lock_sha256": _sha256(lock_path),
        "installed": versions,
        "model_downloaded": False,
        "does_not_establish": [
            "model_quality",
            "semantic_ranking_quality",
            "gpu_support",
            "cross_platform_installability",
            "vulnerability_absence",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile or verify the target-specific RepoBrief semantic lock"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-install", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_install is not None:
            result = verify_install(args.verify_install)
        else:
            result = compile_lock(check=args.check)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
