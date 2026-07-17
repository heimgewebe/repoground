from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PUBLISH = ROOT / "scripts/ops/repoground-publish-systemkatalog-main"
WATCH = ROOT / "scripts/ops/repoground-publish-systemkatalog-main-if-changed"
LEGACY_PUBLISH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main"
LEGACY_WATCH = ROOT / "scripts/ops/repobrief-publish-systemkatalog-main-if-changed"
INSTALLER = ROOT / "scripts/ops/install_systemkatalog_publish_runtime.sh"
FLEET_INSTALLER = ROOT / "scripts/ops/install_repoground_publish_fleet_runtime.sh"
OLD_BASE = "repobrief-publish-heimgewebe-katalog-main"


def test_publish_uses_canonical_systemkatalog_identity_through_fleet_runtime() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert "/home/alex/.local/bin/repoground-publish-fleet" in text
    assert "--repo heimgewebe/systemkatalog" in text
    assert "--if-changed" in text
    assert "--retention 3" in text
    assert "heimgewebe-katalog" not in text


def test_watcher_is_only_a_compatibility_entrypoint() -> None:
    text = WATCH.read_text(encoding="utf-8")
    assert "is a compatibility alias" in text
    assert "repoground-publish-systemkatalog-main" in text
    assert "repoground-publish-fleet" not in text
    assert "--repo" not in text


def test_legacy_systemkatalog_entrypoints_are_thin_delegates() -> None:
    for path in (LEGACY_PUBLISH, LEGACY_WATCH):
        text = path.read_text(encoding="utf-8")
        assert "is deprecated; use repoground-" in text
        assert "systemctl" not in text


def test_compatibility_installer_delegates_to_single_fleet_installer() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "install_repoground_publish_fleet_runtime.sh" in text
    assert "${BASH_SOURCE[0]}" in text
    assert 'dirname ""' not in text
    assert "systemctl" not in text
    assert "INSTALL-SYSTEMKATALOG-PUBLISH-RUNTIME" not in text


def test_fleet_installer_removes_old_and_duplicate_units() -> None:
    text = FLEET_INSTALLER.read_text(encoding="utf-8")
    assert OLD_BASE not in text
    assert "rb-publish-fleet-daily.timer" in text
    assert "repobrief-publish-systemkatalog-main-watch.timer" in text
    assert "systemkatalog-repobrief-localize.path" in text
    assert 'systemctl --user disable --now "$unit"' in text
    assert 'rm -f -- "$UNIT_DIR/$unit"' in text
