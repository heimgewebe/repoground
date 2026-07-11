from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PUBLISH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main"
WATCH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main-if-changed"
INSTALLER = ROOT / "scripts/ops/install_systemkatalog_publish_runtime.sh"
UNIT_DIR = ROOT / "ops/systemd/systemkatalog-publish"
OLD_BASE = "repobrief-publish-heimgewebe-katalog-main"
NEW_BASE = "repobrief-publish-systemkatalog-main"


def test_publish_uses_canonical_systemkatalog_identity() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert "SYSTEMKATALOG_REPO=/home/alex/repos/systemkatalog" in text
    assert "SOURCE_WT=/home/alex/repos/.repobrief-sources/heimgewebe__systemkatalog__main" in text
    assert 'OUT_BASE="$PUB_ROOT/repobrief-auto/systemkatalog-main"' in text
    assert "--repository systemkatalog" in text
    assert "heimgewebe-katalog" not in text


def test_watcher_uses_canonical_systemkatalog_identity() -> None:
    text = WATCH.read_text(encoding="utf-8")
    assert "SYSTEMKATALOG_REPO=/home/alex/repos/systemkatalog" in text
    assert "PUBLISH=/home/alex/.local/bin/repobrief-publish-systemkatalog-main" in text
    assert 'LAST_SHA_FILE="$STATE_DIR/systemkatalog-main.last-sha"' in text
    assert "heimgewebe-katalog" not in text


def test_active_runtime_files_use_only_new_names() -> None:
    paths = [PUBLISH, WATCH, *UNIT_DIR.iterdir()]
    assert all(OLD_BASE not in path.name for path in paths)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert OLD_BASE not in text
        assert "/home/alex/repos/heimgewebe-katalog" not in text
        assert "cabinet" not in path.name.lower()


def test_installer_cuts_over_old_units_and_enables_new_timers() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert f"NEW_BASE={NEW_BASE}" in text
    assert f"OLD_BASE={OLD_BASE}" in text
    assert 'rm -f -- "$BIN_DIR/$OLD_BASE" "$BIN_DIR/$OLD_BASE-if-changed"' in text
    assert 'systemctl --user disable "$unit"' in text
    assert 'systemctl --user enable --now "$unit"' in text
    assert "INSTALL-SYSTEMKATALOG-PUBLISH-RUNTIME: PASS" in text
