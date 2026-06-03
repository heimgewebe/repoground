import json
import re
import subprocess
from pathlib import Path

from merger.lenskit.core.merge import ExtrasConfig, scan_repo, write_reports_v2
from merger.lenskit.tests._test_constants import make_generator_info

SCRATCH_PATH = ".tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json"
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "rlens-post-merge-surface-smoke.sh"


def _write_bundle(tmp_path: Path):
    hub = tmp_path / "hub"
    repo = hub / "repo"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(
        "# Demo\n"
        f"This proof text mentions {SCRATCH_PATH} as a prevented leak, "
        "but it is documentation, not an emitted source path.\n",
        encoding="utf-8",
    )
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "guard.yml").write_text("name: guard\n", encoding="utf-8")
    (repo / ".wgx").mkdir()
    (repo / ".wgx" / "profile.yml").write_text("profile: demo\n", encoding="utf-8")
    scratch = repo / SCRATCH_PATH
    scratch.parent.mkdir(parents=True)
    scratch.write_text('{"status":"fixture-noise"}\n', encoding="utf-8")

    summary = scan_repo(repo, calculate_md5=True, include_hidden=True)
    merges = tmp_path / "merges"
    merges.mkdir()
    artifacts = write_reports_v2(
        merges_dir=merges,
        hub=hub,
        repo_summaries=[summary],
        detail="test",
        mode="gesamt",
        max_bytes=1000,
        plan_only=False,
        code_only=False,
        extras=ExtrasConfig(json_sidecar=True),
        output_mode="dual",
        generator_info=make_generator_info(),
    )
    return merges, artifacts


def _run_smoke(merges: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(merges)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_rlens_surface_smoke_allows_documented_scratch_path_mentions(tmp_path):
    merges, artifacts = _write_bundle(tmp_path)

    # The canonical artifact legitimately contains the scratch path as prose in
    # README content. The smoke must not treat arbitrary text as a leaked file.
    assert SCRATCH_PATH in artifacts.canonical_md.read_text(encoding="utf-8")

    result = _run_smoke(merges)

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"noise_surface_check": "pass"' in result.stdout
    assert '"structured_path_absent": ".tmp/forensic-preflight-ci-canary"' in result.stdout
    count_match = re.search(r'"excluded_noise_count": (\d+)', result.stdout)
    assert count_match is not None, result.stdout
    assert int(count_match.group(1)) > 0


def test_rlens_surface_smoke_fails_structured_chunk_path_leak(tmp_path):
    merges, artifacts = _write_bundle(tmp_path)

    lines = artifacts.chunk_index.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["path"] = SCRATCH_PATH
    lines[0] = json.dumps(first)
    artifacts.chunk_index.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _run_smoke(merges)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "scratch noise leaked as structured path" in combined
    assert "chunk_index_jsonl" in combined


def test_rlens_surface_smoke_fails_structured_sidecar_file_index_leak(tmp_path):
    merges, artifacts = _write_bundle(tmp_path)

    sidecar = json.loads(artifacts.index_json.read_text(encoding="utf-8"))
    sidecar["reading_lenses"]["file_index"][0]["path"] = SCRATCH_PATH
    artifacts.index_json.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    result = _run_smoke(merges)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "scratch noise leaked as structured path" in combined
    assert "index_sidecar_json" in combined
