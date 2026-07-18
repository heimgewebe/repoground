import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

from merger.repoground.core.merge import ExtrasConfig, scan_repo, write_reports_v2
from merger.repoground.tests._test_constants import make_generator_info


REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "scripts" / "repoground-launcher.sh"


def _build_fixture(tmp_path: Path, *, output_mode: str):
    hub = tmp_path / "hub"
    repo_root = hub / "fixture"
    repo_root.mkdir(parents=True)
    source = repo_root / "src" / "pathonlymarker.py"
    source.parent.mkdir()
    source.write_text(
        "def searchable_symbol():\n"
        "    return 'contentonlytokenq7x9'\n",
        encoding="utf-8",
    )
    merges_dir = tmp_path / "merges"
    merges_dir.mkdir()
    summary = scan_repo(repo_root, calculate_md5=True)
    return write_reports_v2(
        merges_dir=merges_dir,
        hub=hub,
        repo_summaries=[summary],
        detail="max",
        mode="gesamt",
        max_bytes=0,
        plan_only=False,
        output_mode=output_mode,
        extras=ExtrasConfig(json_sidecar=False),
        redact_secrets=False,
        generator_info=make_generator_info(),
        publish_generation=False,
    )


def test_retrieval_only_build_populates_searchable_content(tmp_path):
    artifacts = _build_fixture(tmp_path, output_mode="retrieval")
    assert artifacts.chunk_index is not None
    chunks = [
        json.loads(line)
        for line in artifacts.chunk_index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert chunks
    assert all("canonical_range" not in chunk for chunk in chunks)
    assert all(chunk.get("content") for chunk in chunks)
    assert all(
        hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest()
        == chunk["sha256"]
        for chunk in chunks
    )

    db_path = artifacts.chunk_index.with_suffix(".index.sqlite")
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        rows, nonempty = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE length(content) > 0) "
            "FROM chunks_fts"
        ).fetchone()
        assert rows == nonempty == len(chunks)
        assert conn.execute(
            "SELECT count(*) FROM chunks_fts "
            "WHERE chunks_fts MATCH 'contentonlytokenq7x9'"
        ).fetchone()[0] >= 1
        assert conn.execute(
            "SELECT count(*) FROM chunks_fts "
            "WHERE chunks_fts MATCH 'pathonlymarker'"
        ).fetchone()[0] >= 1
        assert conn.execute(
            "SELECT count(*) FROM chunks_fts "
            "WHERE chunks_fts MATCH 'definitelymissingt006token'"
        ).fetchone()[0] == 0


def test_dual_build_keeps_canonical_chunks_range_backed(tmp_path):
    artifacts = _build_fixture(tmp_path, output_mode="dual")
    assert artifacts.chunk_index is not None
    chunks = [
        json.loads(line)
        for line in artifacts.chunk_index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ranged = [chunk for chunk in chunks if "canonical_range" in chunk]
    assert ranged
    assert all("content" not in chunk for chunk in ranged)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _launcher_env(
    tmp_path: Path,
    *,
    payload: dict[str, object],
    expected_version: str = "expected-version",
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "systemctl",
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *'--property=MainPID --value'*) echo 0 ;;\n"
        "  *'--property=WorkingDirectory --value'*) echo '' ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    encoded = json.dumps(payload)
    _write_executable(
        bin_dir / "curl",
        "#!/bin/sh\n"
        "out=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = '-o' ]; then shift; out=$1; fi\n"
        "  shift\n"
        "done\n"
        f"printf '%s' {json.dumps(encoded)} >\"$out\"\n",
    )
    _write_executable(bin_dir / "journalctl", "#!/bin/sh\nexit 0\n")
    _write_executable(bin_dir / "xdg-open", "#!/bin/sh\nexit 0\n")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "REPOGROUND_EXPECTED_VERSION": expected_version,
            "REPOGROUND_HEALTH_RETRIES": "1",
            "REPOGROUND_HEALTH_INTERVAL": "0",
        }
    )
    return env


def _run_launcher(
    tmp_path: Path,
    *,
    payload: dict[str, object],
    expected_version: str = "expected-version",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(LAUNCHER)],
        env=_launcher_env(
            tmp_path,
            payload=payload,
            expected_version=expected_version,
        ),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _healthy_payload(
    *, server_version: str, auth_enabled: bool = True
) -> dict[str, object]:
    return {
        "status": "ok",
        "version": "2.4",
        "server_version": server_version,
        "hub": "/srv/repoground",
        "auth_enabled": auth_enabled,
    }


def test_launcher_uses_canonical_health_endpoint_and_accepts_exact_version(tmp_path):
    text = LAUNCHER.read_text(encoding="utf-8")
    assert 'HEALTH_URL="${URL}/api/health"' in text
    assert '"${URL}/health"' not in text

    result = _run_launcher(
        tmp_path,
        payload=_healthy_payload(server_version="expected-version"),
    )
    assert result.returncode == 0, result.stderr


def test_launcher_accepts_safe_git_sha_prefix(tmp_path):
    expected = "0123456789abcdef0123456789abcdef01234567"
    result = _run_launcher(
        tmp_path,
        payload=_healthy_payload(server_version=expected[:12]),
        expected_version=expected,
    )
    assert result.returncode == 0, result.stderr


def test_launcher_rejects_unsafe_short_git_sha_prefix(tmp_path):
    expected = "0123456789abcdef0123456789abcdef01234567"
    result = _run_launcher(
        tmp_path,
        payload=_healthy_payload(server_version=expected[:6]),
        expected_version=expected,
    )
    assert result.returncode == 1


def test_launcher_rejects_wrong_version(tmp_path):
    result = _run_launcher(
        tmp_path,
        payload=_healthy_payload(server_version="wrong-version"),
    )
    assert result.returncode == 1


def test_launcher_rejects_disabled_authentication(tmp_path):
    result = _run_launcher(
        tmp_path,
        payload=_healthy_payload(
            server_version="expected-version",
            auth_enabled=False,
        ),
    )
    assert result.returncode == 1
