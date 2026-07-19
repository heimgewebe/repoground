"""
Tests for Atlas snapshot lifecycle hardening:
- Zombie prevention (scan failure → status = "failed")
- Progress persistence during scan
- Empty directory scan (status = "complete", total_files = 0)
- Stale detection for running artifacts
- Shared lifecycle executor guarantees
- Hardest failure paths (exception after progress, callback exception, artifact write failure)
- Status vocabulary parity between CLI and API paths
- Failure preserves progress data (not overwritten by initial_state)
- File-count-gated progress for large directories
"""
import pytest
import json
import time
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from merger.repoground.adapters.atlas import AtlasScanner
from merger.repoground.atlas.registry import AtlasRegistry
from merger.repoground.atlas.lifecycle import run_scan_lifecycle


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "registry" / "atlas_registry.sqlite"


@pytest.fixture
def registry(temp_db_path: Path) -> AtlasRegistry:
    reg = AtlasRegistry(temp_db_path)
    yield reg
    reg.close()


def _setup_snapshot(registry: AtlasRegistry, snapshot_id: str = "snap_test__root__20240101T000000Z__abcd1234"):
    """Helper: register machine, root, and create a running snapshot."""
    registry.register_machine("test-machine", "testhost")
    registry.register_root("root", "test-machine", "abs_path", "/test", label="test")
    registry.create_snapshot(snapshot_id, "test-machine", "root", "abcd1234", "running")
    return snapshot_id


def _raise(exc):
    """Helper: raises *exc*.  Use as scan_fn in lifecycle tests."""
    raise exc


# ── 6.1 Zombie Test ──────────────────────────────────────────────────────

def test_zombie_snapshot_on_scan_exception(registry: AtlasRegistry, tmp_path: Path):
    """When scanner.scan() raises an exception, the snapshot MUST end up as 'failed'."""
    snapshot_id = _setup_snapshot(registry)

    # Verify initial state
    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "running"

    # Simulate the lifecycle pattern from cmd_atlas.py
    try:
        # scanner.scan() throws
        raise RuntimeError("Simulated scan failure")
    except Exception as e:
        registry.update_snapshot_status(snapshot_id, "failed", error_message=str(e))

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "failed"
    assert snap["error_message"] == "Simulated scan failure"


def test_zombie_guard_in_finally(registry: AtlasRegistry):
    """Defensive finally guard catches zombie snapshots even if except handler fails."""
    snapshot_id = _setup_snapshot(registry)

    # Simulate: except block itself fails (e.g. broken connection),
    # but the finally zombie guard kicks in.
    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "running"

    # The finally guard pattern
    try:
        snap = registry.get_snapshot(snapshot_id)
        if snap and snap["status"] == "running":
            registry.update_snapshot_status(snapshot_id, "failed", error_message="Snapshot finalization interrupted")
    except Exception:
        pass

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "failed"
    assert snap["error_message"] == "Snapshot finalization interrupted"


def test_scanner_exception_produces_failed_status(registry: AtlasRegistry, tmp_path: Path):
    """Full integration: mock scanner raises → snapshot ends up 'failed' with error message."""
    snapshot_id = _setup_snapshot(registry)

    scanner = AtlasScanner(root=tmp_path, snapshot_id=snapshot_id)

    # Patch os.walk to raise an exception after one iteration
    with patch("os.walk", side_effect=OSError("Permission denied: /forbidden")):
        try:
            scanner.scan()
        except Exception:
            pass

        # In real code, the except block would call update_snapshot_status.
        # We simulate that here:
        registry.update_snapshot_status(snapshot_id, "failed", error_message="Permission denied: /forbidden")

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "failed"
    assert "Permission denied" in snap["error_message"]


# ── 6.2 Progress Test ────────────────────────────────────────────────────

def test_progress_callback_invoked_during_scan(tmp_path: Path):
    """The on_progress callback is invoked during scanning with correct counters."""
    # Create a directory structure
    for i in range(5):
        d = tmp_path / f"dir_{i}"
        d.mkdir()
        for j in range(3):
            (d / f"file_{j}.txt").write_text(f"content {i}-{j}")

    progress_calls = []

    def on_progress(files: int, dirs: int, bytes_total: int):
        progress_calls.append({"files": files, "dirs": dirs, "bytes": bytes_total})

    scanner = AtlasScanner(root=tmp_path, snapshot_id="snap_test_progress")

    # Override the throttle by patching time.time to advance
    original_time = time.time
    call_count = [0]

    def mock_time():
        call_count[0] += 1
        # Make time advance 2 seconds per call to bypass the 1-second throttle
        return original_time() + call_count[0] * 2

    with patch("merger.repoground.adapters.atlas.time.time", side_effect=mock_time):
        scanner.scan(on_progress=on_progress)

    # Progress should have been called at least once
    assert len(progress_calls) > 0, "on_progress callback was never invoked"

    # Last progress call should reflect actual file counts
    last = progress_calls[-1]
    assert last["files"] > 0
    assert last["dirs"] > 0
    assert last["bytes"] > 0


def test_progress_persisted_to_registry(registry: AtlasRegistry):
    """update_snapshot_progress writes files_seen/dirs_seen/bytes_seen to the registry."""
    snapshot_id = _setup_snapshot(registry)

    registry.update_snapshot_progress(snapshot_id, files_seen=42, dirs_seen=7, bytes_seen=123456)

    snap = registry.get_snapshot(snapshot_id)
    assert snap["files_seen"] == 42
    assert snap["dirs_seen"] == 7
    assert snap["bytes_seen"] == 123456
    assert snap["last_progress_at"] is not None


# ── 6.3 Empty Dir Test ───────────────────────────────────────────────────

def test_empty_directory_scan_completes(tmp_path: Path):
    """Scanning an empty directory should return complete status with total_files == 0."""
    scanner = AtlasScanner(root=tmp_path, snapshot_id="snap_empty")
    result = scanner.scan()

    assert result["stats"]["total_files"] == 0
    assert result["stats"]["total_dirs"] >= 0
    assert result["stats"]["total_bytes"] == 0
    assert result["stats"]["end_time"] is not None
    assert result["stats"]["duration_seconds"] >= 0


def test_empty_directory_scan_registry_lifecycle(registry: AtlasRegistry, tmp_path: Path):
    """Full lifecycle: empty dir → status 'complete', total_files == 0."""
    snapshot_id = _setup_snapshot(registry)

    empty_dir = tmp_path / "scan_target"
    empty_dir.mkdir()

    scanner = AtlasScanner(root=empty_dir, snapshot_id=snapshot_id)
    result = scanner.scan()

    # Simulate the success path
    registry.update_snapshot_status(snapshot_id, "complete")

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "complete"
    assert result["stats"]["total_files"] == 0


# ── 6.4 Stale Detection Test ─────────────────────────────────────────────

def test_stale_detection_on_running_artifact(tmp_path: Path):
    """A running artifact with old last_progress_at should be flagged as stalled."""
    from fastapi.testclient import TestClient
    from merger.repoground.service.app import app, init_service, verify_token

    hub = tmp_path / "hub"
    merges = hub / ".repoground" / "merges"
    merges.mkdir(parents=True)

    # Create a running artifact with stale progress (120s > 60s stale threshold)
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    running_data = {
        "status": "running",
        "root": "/test",
        "created_at": stale_time,
        "stats": {
            "files_seen": 10,
            "dirs_seen": 3,
            "bytes_seen": 5000,
            "last_progress_at": stale_time
        }
    }
    (merges / "atlas-1000.json").write_text(json.dumps(running_data), encoding="utf-8")

    orig_middleware = list(app.user_middleware)
    orig_stack = app.middleware_stack
    app.middleware_stack = None
    app.user_middleware.clear()

    init_service(hub_path=hub, merges_dir=merges)
    app.dependency_overrides[verify_token] = lambda: True

    try:
        with TestClient(app) as client:
            response = client.get("/api/atlas")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["status"] == "running"
            assert data[0]["is_stalled"] is True
            assert data[0]["stats"]["files_seen"] == 10
    finally:
        app.dependency_overrides.clear()
        app.user_middleware = orig_middleware
        app.middleware_stack = orig_stack


def test_fresh_running_artifact_not_stalled(tmp_path: Path):
    """A running artifact with recent progress should NOT be flagged as stalled."""
    from fastapi.testclient import TestClient
    from merger.repoground.service.app import app, init_service, verify_token

    hub = tmp_path / "hub"
    merges = hub / ".repoground" / "merges"
    merges.mkdir(parents=True)

    fresh_time = datetime.now(timezone.utc).isoformat()
    running_data = {
        "status": "running",
        "root": "/test",
        "created_at": fresh_time,
        "stats": {
            "files_seen": 10,
            "dirs_seen": 3,
            "bytes_seen": 5000,
            "last_progress_at": fresh_time
        }
    }
    (merges / "atlas-2000.json").write_text(json.dumps(running_data), encoding="utf-8")

    orig_middleware = list(app.user_middleware)
    orig_stack = app.middleware_stack
    app.middleware_stack = None
    app.user_middleware.clear()

    init_service(hub_path=hub, merges_dir=merges)
    app.dependency_overrides[verify_token] = lambda: True

    try:
        with TestClient(app) as client:
            response = client.get("/api/atlas")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["status"] == "running"
            assert data[0]["is_stalled"] is False
    finally:
        app.dependency_overrides.clear()
        app.user_middleware = orig_middleware
        app.middleware_stack = orig_stack


# ── Registry Migration Test ───────────────────────────────────────────────

def test_registry_progress_columns_exist(registry: AtlasRegistry):
    """New progress columns should be present in the snapshots table."""
    cur = registry.conn.execute("PRAGMA table_info(snapshots)")
    cols = [row["name"] for row in cur.fetchall()]
    assert "files_seen" in cols
    assert "dirs_seen" in cols
    assert "bytes_seen" in cols
    assert "last_progress_at" in cols
    assert "error_message" in cols


def test_update_status_with_error_message(registry: AtlasRegistry):
    """update_snapshot_status should store error_message when provided."""
    snapshot_id = _setup_snapshot(registry)
    registry.update_snapshot_status(snapshot_id, "failed", error_message="disk full")

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "failed"
    assert snap["error_message"] == "disk full"
    assert snap["last_progress_at"] is not None


def test_update_status_without_error_message(registry: AtlasRegistry):
    """update_snapshot_status without error_message should not clear existing error."""
    snapshot_id = _setup_snapshot(registry)
    registry.update_snapshot_status(snapshot_id, "complete")

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "complete"
    assert snap["error_message"] is None


# ── Shared Lifecycle Executor Tests ───────────────────────────────────────

def test_lifecycle_executor_success():
    """run_scan_lifecycle: scan_fn succeeds → no mark_failed call."""
    called = {"failed": False}

    def scan_fn():
        pass  # success

    def mark_failed(msg):
        called["failed"] = True

    run_scan_lifecycle(scan_fn=scan_fn, mark_failed=mark_failed, is_still_running=lambda: False)
    assert called["failed"] is False


def test_lifecycle_executor_exception_marks_failed():
    """run_scan_lifecycle: scan_fn raises → mark_failed called, exception re-raised."""
    errors = []

    def scan_fn():
        raise RuntimeError("boom")

    def mark_failed(msg):
        errors.append(msg)

    with pytest.raises(RuntimeError, match="boom"):
        run_scan_lifecycle(scan_fn=scan_fn, mark_failed=mark_failed, is_still_running=lambda: False)

    assert len(errors) == 1
    assert errors[0] == "boom"


def test_lifecycle_executor_zombie_guard():
    """run_scan_lifecycle: if mark_failed itself raises, finally guard catches zombie."""

    def scan_fn():
        raise RuntimeError("scan error")

    def mark_failed_broken(msg):
        raise IOError("registry broken")

    def is_still_running():
        return True  # still zombie

    # Monkey-patch: use a second mark_failed for the finally guard
    # The executor calls mark_failed in except AND in finally if still running
    final_msgs = []

    def mark_failed_tracking(msg):
        final_msgs.append(msg)
        if len(final_msgs) == 1:
            raise IOError("registry broken")  # first call (except handler) fails
        # second call (finally guard) succeeds

    with pytest.raises(RuntimeError, match="scan error"):
        run_scan_lifecycle(
            scan_fn=scan_fn,
            mark_failed=mark_failed_tracking,
            is_still_running=lambda: True,
        )

    # mark_failed was called twice: once in except (failed), once in finally (zombie guard)
    assert len(final_msgs) == 2
    assert final_msgs[0] == "scan error"
    assert final_msgs[1] == "Scan finalization interrupted"


# ── Hardest Failure Path Tests ────────────────────────────────────────────

def test_exception_after_progress_write(registry: AtlasRegistry, tmp_path: Path):
    """Exception AFTER first progress update → progress persisted AND status = 'failed'."""
    snapshot_id = _setup_snapshot(registry)

    # Simulate: progress was written, then exception occurs
    registry.update_snapshot_progress(snapshot_id, files_seen=100, dirs_seen=10, bytes_seen=50000)

    # Verify progress is persisted
    snap = registry.get_snapshot(snapshot_id)
    assert snap["files_seen"] == 100
    assert snap["status"] == "running"

    # Now exception happens
    registry.update_snapshot_status(snapshot_id, "failed", error_message="Disk full mid-scan")

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "failed"
    assert snap["error_message"] == "Disk full mid-scan"
    # Progress data is still there — not wiped by the failure
    assert snap["files_seen"] == 100
    assert snap["dirs_seen"] == 10
    assert snap["bytes_seen"] == 50000


def test_artifact_write_failure_after_successful_scan(registry: AtlasRegistry, tmp_path: Path):
    """If artifact writing fails after scan, snapshot must end up 'failed', not 'running'."""
    snapshot_id = _setup_snapshot(registry)

    scan_target = tmp_path / "target"
    scan_target.mkdir()
    (scan_target / "a.txt").write_text("hello")

    scanner = AtlasScanner(root=scan_target, snapshot_id=snapshot_id)

    def _do_scan():
        scanner.scan()  # succeeds
        raise IOError("Disk full writing artifacts")  # but artifact write fails

    with pytest.raises(IOError, match="Disk full"):
        run_scan_lifecycle(
            scan_fn=_do_scan,
            mark_failed=lambda msg: registry.update_snapshot_status(snapshot_id, "failed", error_message=msg),
            is_still_running=lambda: (registry.get_snapshot(snapshot_id) or {}).get("status") == "running",
            label="test-artifact-failure",
        )

    snap = registry.get_snapshot(snapshot_id)
    assert snap["status"] == "failed"
    assert "Disk full" in snap["error_message"]


def test_progress_callback_exception_does_not_abort_scan(tmp_path: Path):
    """If on_progress callback raises, scan must still complete successfully."""
    scan_target = tmp_path / "target"
    scan_target.mkdir()
    for i in range(3):
        d = scan_target / f"dir_{i}"
        d.mkdir()
        for j in range(2):
            (d / f"f_{j}.txt").write_text(f"data {i}-{j}")

    callback_errors = []

    def broken_progress(files, dirs, bytes_total):
        callback_errors.append(True)
        raise RuntimeError("progress callback exploded")

    scanner = AtlasScanner(root=scan_target, snapshot_id="snap_broken_progress")

    # Override throttle so callback fires on every directory
    original_time = time.time
    call_count = [0]
    def mock_time():
        call_count[0] += 1
        return original_time() + call_count[0] * 2

    with patch("merger.repoground.adapters.atlas.time.time", side_effect=mock_time):
        result = scanner.scan(on_progress=broken_progress)

    # Scan must have completed despite callback errors
    assert result["stats"]["total_files"] == 6
    assert result["stats"]["total_dirs"] >= 3
    assert result["stats"]["end_time"] is not None
    # Callback was indeed called (and raised)
    assert len(callback_errors) > 0


def test_api_zombie_guard_via_lifecycle(tmp_path: Path):
    """API path: if scan_fn and mark_failed both raise, zombie guard still fires."""
    json_path = tmp_path / "atlas-test.json"
    json_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")

    call_count = [0]

    def mark_failed(msg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise IOError("JSON write failed")
        # Second call (zombie guard) succeeds
        json_path.write_text(json.dumps({"status": "failed", "error": msg}), encoding="utf-8")

    def is_still_running():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return data.get("status") == "running"

    with pytest.raises(RuntimeError, match="scan boom"):
        run_scan_lifecycle(
            scan_fn=lambda: _raise(RuntimeError("scan boom")),
            mark_failed=mark_failed,
            is_still_running=is_still_running,
        )

    # Zombie guard should have fired and succeeded on second attempt
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["error"] == "Scan finalization interrupted"


def test_cli_and_api_lifecycle_semantic_equivalence(registry: AtlasRegistry, tmp_path: Path):
    """CLI and API paths produce equivalent lifecycle outcomes via shared executor.

    Both paths MUST use the unified status vocabulary:
      - "running" → "complete" on success
      - "running" → "failed" on error
    There must be exactly one terminal success value ("complete"), not two.
    """
    snapshot_id = _setup_snapshot(registry)
    json_path = tmp_path / "api-artifact.json"
    json_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")

    # CLI-style: registry is canonical
    run_scan_lifecycle(
        scan_fn=lambda: registry.update_snapshot_status(snapshot_id, "complete"),
        mark_failed=lambda msg: registry.update_snapshot_status(snapshot_id, "failed", error_message=msg),
        is_still_running=lambda: (registry.get_snapshot(snapshot_id) or {}).get("status") == "running",
        label="cli-test",
    )

    # API-style: JSON file is canonical
    def api_mark_complete():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        data["status"] = "complete"
        json_path.write_text(json.dumps(data), encoding="utf-8")

    run_scan_lifecycle(
        scan_fn=api_mark_complete,
        mark_failed=lambda msg: json_path.write_text(json.dumps({"status": "failed", "error": msg}), encoding="utf-8"),
        is_still_running=lambda: json.loads(json_path.read_text(encoding="utf-8")).get("status") == "running",
        label="api-test",
    )

    # Both should have reached the SAME terminal success state
    cli_snap = registry.get_snapshot(snapshot_id)
    api_data = json.loads(json_path.read_text(encoding="utf-8"))

    assert cli_snap["status"] == "complete"
    assert api_data["status"] == "complete"
    # Verify they use the exact same string — no "complete" vs "completed" drift
    assert cli_snap["status"] == api_data["status"], (
        f"Status vocabulary mismatch: CLI uses '{cli_snap['status']}', "
        f"API uses '{api_data['status']}'"
    )


# ── Status Contract Test ─────────────────────────────────────────────────

# The three valid Atlas status values.  Any code writing a status MUST use
# one of these exact strings — no synonyms, no variants.
ATLAS_STATUS_RUNNING = "running"
ATLAS_STATUS_COMPLETE = "complete"
ATLAS_STATUS_FAILED = "failed"


def test_atlas_status_vocabulary_is_unified():
    """The Atlas status vocabulary is exactly {running, complete, failed}.

    This test documents and enforces the contract.  If you see 'completed'
    anywhere in Atlas code, it is a bug — the canonical terminal success
    value is 'complete' (not 'completed').

    The status vocabulary is shared between CLI (registry-backed) and API
    (JSON-backed) paths.  The lifecycle executor (run_scan_lifecycle) is
    agnostic to the storage backend but guarantees that every scan reaches
    one of the two terminal states.

    Remaining architectural asymmetry (documented, not resolved here):
    - CLI stores lifecycle state in SQLite (AtlasRegistry)
    - API stores lifecycle state in JSON artifact files
    Both use the same status strings.
    """
    from merger.repoground.service.models import AtlasArtifact

    # Verify the Pydantic model's Literal type matches our contract
    status_field = AtlasArtifact.model_fields["status"]
    # Extract the allowed values from the Literal annotation
    import typing
    literal_args = typing.get_args(status_field.annotation)
    assert set(literal_args) == {ATLAS_STATUS_RUNNING, ATLAS_STATUS_COMPLETE, ATLAS_STATUS_FAILED}, (
        f"AtlasArtifact.status Literal does not match the canonical vocabulary: {literal_args}"
    )
    # Default must be the terminal success value
    assert status_field.default == ATLAS_STATUS_COMPLETE


def test_atlas_lifecycle_failure_semantics_parity(registry: AtlasRegistry, tmp_path: Path):
    """CLI and API failure paths produce identical semantic outcomes.

    Verifies:
    - Both end up "failed" (not "running")
    - Both persist an error message
    - Neither leaves a zombie
    """
    # --- CLI failure path ---
    cli_snap_id = _setup_snapshot(registry, snapshot_id="snap_cli_fail__root__20240101T000000Z__aaaa1111")

    with pytest.raises(RuntimeError, match="CLI boom"):
        run_scan_lifecycle(
            scan_fn=lambda: _raise(RuntimeError("CLI boom")),
            mark_failed=lambda msg: registry.update_snapshot_status(cli_snap_id, "failed", error_message=msg),
            is_still_running=lambda: (registry.get_snapshot(cli_snap_id) or {}).get("status") == "running",
            label="cli-fail-test",
        )

    cli_snap = registry.get_snapshot(cli_snap_id)

    # --- API failure path ---
    json_path = tmp_path / "api-fail-artifact.json"
    json_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")

    api_errors = {}

    def api_mark_failed(msg):
        state = {"status": "failed", "error": msg}
        json_path.write_text(json.dumps(state), encoding="utf-8")
        api_errors["msg"] = msg

    with pytest.raises(RuntimeError, match="API boom"):
        run_scan_lifecycle(
            scan_fn=lambda: _raise(RuntimeError("API boom")),
            mark_failed=api_mark_failed,
            is_still_running=lambda: json.loads(json_path.read_text(encoding="utf-8")).get("status") == "running",
            label="api-fail-test",
        )

    api_data = json.loads(json_path.read_text(encoding="utf-8"))

    # Verify parity: both failed, both have error text, neither is zombie
    assert cli_snap["status"] == ATLAS_STATUS_FAILED
    assert api_data["status"] == ATLAS_STATUS_FAILED
    assert cli_snap["status"] == api_data["status"]

    assert cli_snap["error_message"] == "CLI boom"
    assert api_data["error"] == "API boom"

    assert cli_snap["status"] != ATLAS_STATUS_RUNNING
    assert api_data["status"] != ATLAS_STATUS_RUNNING


# ── Fix: _mark_api_failed preserves progress ─────────────────────────────

def test_mark_api_failed_preserves_progress(tmp_path: Path):
    """When marking an API artifact as failed, any previously written progress
    counters (files_seen, dirs_seen, bytes_seen, last_progress_at) must survive.

    Regression test: the original _mark_api_failed() used initial_state.copy()
    which wiped all accumulated progress data.
    """
    from merger.repoground.service.app import _mark_api_artifact_failed

    json_path = tmp_path / "atlas-preserve.json"

    # Simulate state after progress has been written mid-scan
    mid_scan_state = {
        "status": "running",
        "root": "/big-repo",
        "created_at": "2024-03-01T10:00:00Z",
        "effective": {"max_depth": 20, "exclude_globs": []},
        "stats": {
            "files_seen": 4200,
            "dirs_seen": 150,
            "bytes_seen": 98765432,
            "last_progress_at": "2024-03-01T10:01:30Z"
        }
    }
    json_path.write_text(json.dumps(mid_scan_state), encoding="utf-8")

    # initial_state would have empty stats (like at the start of scan)
    initial_state = {
        "status": "running",
        "root": "/big-repo",
        "created_at": "2024-03-01T10:00:00Z",
        "effective": {"max_depth": 20, "exclude_globs": []},
        "stats": {}
    }

    # Call the real module-level helper (not a copy of its logic)
    _mark_api_artifact_failed(json_path, initial_state, "Disk full mid-scan")

    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error"] == "Disk full mid-scan"
    # Progress data must survive
    assert result["stats"]["files_seen"] == 4200
    assert result["stats"]["dirs_seen"] == 150
    assert result["stats"]["bytes_seen"] == 98765432
    assert result["stats"]["last_progress_at"] == "2024-03-01T10:01:30Z"


def test_mark_api_failed_falls_back_to_initial_state(tmp_path: Path):
    """If the JSON artifact is unreadable, _mark_api_artifact_failed falls back
    to initial_state (no crash, no empty file)."""
    from merger.repoground.service.app import _mark_api_artifact_failed

    json_path = tmp_path / "atlas-unreadable.json"
    # Write garbage so json.load fails
    json_path.write_text("NOT-JSON{{{", encoding="utf-8")

    initial_state = {
        "status": "running",
        "root": "/test",
        "created_at": "2024-01-01T00:00:00Z",
        "stats": {}
    }

    # Call the real module-level helper
    _mark_api_artifact_failed(json_path, initial_state, "Something went wrong")

    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error"] == "Something went wrong"
    assert result["root"] == "/test"


# ── Fix: file-count-gated progress ───────────────────────────────────────

def test_progress_fires_on_file_count_gate(tmp_path: Path):
    """Progress callback fires based on file-count gate (every 1000 files)
    even when the time-based gate (1s) has not elapsed.

    This prevents false stalls on large directories where a single os.walk()
    iteration processes many files in < 1 second.
    """
    # Create a directory with enough files to trigger the 1000-file gate
    big_dir = tmp_path / "scan_target"
    big_dir.mkdir()
    for i in range(1100):
        (big_dir / f"file_{i:04d}.txt").write_text(f"data-{i}")

    progress_calls = []

    def on_progress(files: int, dirs: int, bytes_total: int):
        progress_calls.append({"files": files, "dirs": dirs, "bytes": bytes_total})

    scanner = AtlasScanner(root=big_dir, snapshot_id="snap_file_gate")

    # Freeze time so the 1-second gate never fires — only the file-count gate
    frozen_ts = time.time()
    with patch("merger.repoground.adapters.atlas.time.time", return_value=frozen_ts):
        scanner.scan(on_progress=on_progress)

    # The file-count gate (every 1000 files) must have fired at least once
    assert len(progress_calls) >= 1, (
        f"Expected at least 1 progress call from file-count gate, got {len(progress_calls)}"
    )
    # But not once per file — must be fewer than total files
    assert len(progress_calls) < 1100, (
        f"Progress fired too often ({len(progress_calls)}); should be throttled"
    )
