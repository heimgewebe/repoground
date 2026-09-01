from pathlib import Path

import pytest

from merger.repoground.core.merge import MERGES_DIR_NAME
from merger.repoground.service.jobstore import JobStore


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("jobs.json", b"[{broken-json"),
        ("jobs.json", b"[{}]"),
        ("artifacts.json", b"[{broken-json"),
        ("artifacts.json", b"[{}]"),
    ],
    ids=[
        "jobs-invalid-json",
        "jobs-invalid-record",
        "artifacts-invalid-json",
        "artifacts-invalid-record",
    ],
)
def test_existing_invalid_state_fails_closed_and_preserves_bytes(
    tmp_path: Path,
    filename: str,
    payload: bytes,
) -> None:
    state_dir = tmp_path / MERGES_DIR_NAME / ".repoground-service"
    state_dir.mkdir(parents=True)
    state_path = state_dir / filename
    state_path.write_bytes(payload)

    with pytest.raises(RuntimeError, match="refusing to start"):
        JobStore(tmp_path)

    assert state_path.read_bytes() == payload
    assert not state_path.with_suffix(".tmp").exists()


def test_valid_empty_state_still_loads(tmp_path: Path) -> None:
    state_dir = tmp_path / MERGES_DIR_NAME / ".repoground-service"
    state_dir.mkdir(parents=True)
    (state_dir / "jobs.json").write_text("[]", encoding="utf-8")
    (state_dir / "artifacts.json").write_text("[]", encoding="utf-8")

    store = JobStore(tmp_path)

    assert store.get_all_jobs() == []
    assert store.get_all_artifacts() == []
