from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PUBLISH = ROOT / "scripts/ops/repobrief-publish-heimgewebe-katalog-main"
WATCH = ROOT / "scripts/ops/repobrief-publish-heimgewebe-katalog-main-if-changed"
INSTALLER = ROOT / "scripts/ops/install_systemkatalog_publish_runtime.sh"
UNIT_DIR = ROOT / "ops/systemd/systemkatalog-publish"


def test_publish_output_is_inside_publication_root() -> None:
    text = PUBLISH.read_text(encoding="utf-8")
    assert "PUB_ROOT=/home/alex/repos/manifest-publications" in text
    assert 'OUT_BASE="$PUB_ROOT/repobrief-auto/heimgewebe-katalog-main"' in text
    assert "/repos/merges/repobrief-auto/heimgewebe-katalog-main" not in text


def test_runtime_uses_only_systemkatalog_names() -> None:
    paths = [PUBLISH, WATCH, INSTALLER, *UNIT_DIR.iterdir()]
    for path in paths:
        assert "cabinet" not in path.name.lower()
        assert "/home/alex/repos/cabinet" not in path.read_text(encoding="utf-8")


def test_installer_enables_watcher_and_fallback() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "repobrief-publish-heimgewebe-katalog-main-watch.timer" in text
    assert "repobrief-publish-heimgewebe-katalog-main.timer" in text
    assert text.count("enable --now") == 2
