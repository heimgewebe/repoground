import json
import hashlib
from merger.repoground.core import extractor
from merger.repoground.core.extractor import _compute_sha256_with_size, generate_review_bundle

def test_compute_sha256_with_size_happy_path(tmp_path):
    f = tmp_path / "test.txt"
    content = "hello world ü" # Unicode to test byte length
    f.write_text(content, encoding="utf-8")

    content_bytes = content.encode("utf-8")
    expected_sha = hashlib.sha256(content_bytes).hexdigest()
    sha, size, status = _compute_sha256_with_size(f)

    assert sha == expected_sha
    assert size == len(content_bytes)
    assert status is None

def test_compute_sha256_with_size_missing(tmp_path):
    path = tmp_path / "does_not_exist_repolens"
    sha, size, status = _compute_sha256_with_size(path)

    assert sha is None
    assert size == 0
    assert status == "missing"

def test_compute_sha256_with_size_open_permission_error(tmp_path, monkeypatch):
    f = tmp_path / "open_perm.txt"
    content = "can stat but not open due to permission"
    f.write_text(content, encoding="utf-8")

    # Targeted patch for open
    cls = type(f)
    original_open = cls.open

    def mock_open(self, *args, **kwargs):
        if self.name == "open_perm.txt":
            raise PermissionError("Access denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(cls, "open", mock_open)

    sha, size, status = _compute_sha256_with_size(f)

    assert sha is None
    assert size == 0 # no pre-stat anymore, so size is 0 on open failure
    assert status == "permission"

def test_make_entry_logic_with_errors(tmp_path, monkeypatch):
    """
    Verifies that make_entry sets sha256_status based on err_code
    when sha256 is missing.
    """
    hub_dir = tmp_path / "hub"
    hub_dir.mkdir()

    old_repo = tmp_path / "old"
    old_repo.mkdir()

    new_repo = tmp_path / "new"
    new_repo.mkdir()

    # Create a file that will fail
    (new_repo / "secret.txt").write_text("secret")

    # Mock _compute_sha256_with_size to return error for secret.txt
    original_compute = extractor._compute_sha256_with_size

    def mock_compute(path, *args, **kwargs):
        if path.name == "secret.txt":
            # Simulate a permission error
            return None, 999, "permission"
        # For other files (e.g. parts of the bundle), behave normally
        return original_compute(path, *args, **kwargs)

    monkeypatch.setattr(extractor, "_compute_sha256_with_size", mock_compute)

    generate_review_bundle(old_repo, new_repo, "test-repo", hub_dir)

    # Check delta.json
    pr_schau_dir = hub_dir / ".repoground" / "pr-schau" / "test-repo"
    assert pr_schau_dir.exists()

    # Find the timestamp folder robustly (latest by mtime)
    ts_folders = [p for p in pr_schau_dir.iterdir() if p.is_dir()]
    assert ts_folders, "No timestamp folder found"
    bundle_dir = max(ts_folders, key=lambda p: p.stat().st_mtime)

    delta_json_path = bundle_dir / "delta.json"

    with open(delta_json_path, encoding="utf-8") as f:
        delta = json.load(f)

    # Find the entry for secret.txt
    entry = next(e for e in delta["files"] if e["path"] == "secret.txt")

    assert entry["sha256_status"] == "permission"
    assert entry.get("sha256") is None
    # ensure no sha256_error_class (deprecated/removed in favor of status)
    assert "sha256_error_class" not in entry


def _prepare_extractor_main(monkeypatch, tmp_path, outcomes):
    hub = tmp_path / "hub"
    hub.mkdir()
    merges_dir = tmp_path / "merges"
    calls = []

    for name in outcomes:
        (hub / name).write_bytes(b"zip")

    def fake_import_zip_wrapper(zip_path, observed_hub, observed_merges_dir):
        calls.append((zip_path.name, observed_hub, observed_merges_dir))
        return outcomes[zip_path.name]

    monkeypatch.setattr(extractor.sys, "argv", ["extractor", "--hub", str(hub)])
    monkeypatch.setattr(extractor, "detect_hub_dir", lambda *_: hub)
    monkeypatch.setattr(extractor, "get_merges_dir", lambda _: merges_dir)
    monkeypatch.setattr(extractor, "import_zip_wrapper", fake_import_zip_wrapper)
    monkeypatch.setattr(extractor, "console", None)
    return hub, merges_dir, calls


def test_main_reports_diff_paths_in_sorted_zip_order(tmp_path, monkeypatch, capsys):
    outcomes = {
        "b.zip": tmp_path / "b-diff.md",
        "a.zip": tmp_path / "a-diff.md",
    }
    hub, merges_dir, calls = _prepare_extractor_main(monkeypatch, tmp_path, outcomes)

    result = extractor.main()
    captured = capsys.readouterr()

    assert result == 0
    assert calls == [
        ("a.zip", hub, merges_dir),
        ("b.zip", hub, merges_dir),
    ]
    assert captured.err == ""
    assert captured.out == (
        f"RepoGround extractor – Hub: {hub}\n"
        "Import fertig.\n"
        f"Hub: {hub}\n"
        "Diff-Berichte (2):\n"
        f"  - {outcomes['a.zip']}\n"
        f"  - {outcomes['b.zip']}\n"
    )


def test_main_reports_when_processed_zips_create_no_diffs(tmp_path, monkeypatch, capsys):
    outcomes = {"b.zip": None, "a.zip": None}
    hub, merges_dir, calls = _prepare_extractor_main(monkeypatch, tmp_path, outcomes)

    result = extractor.main()
    captured = capsys.readouterr()

    assert result == 0
    assert calls == [
        ("a.zip", hub, merges_dir),
        ("b.zip", hub, merges_dir),
    ]
    assert captured.err == ""
    assert captured.out == (
        f"RepoGround extractor – Hub: {hub}\n"
        "Import fertig.\n"
        f"Hub: {hub}\n"
        "Keine Diff-Berichte erzeugt.\n"
    )
