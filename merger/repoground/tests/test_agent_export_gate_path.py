from pathlib import Path

from merger.repoground.core.agent_export_gate import derive_agent_export_gate_path


def test_derive_agent_export_gate_path_strips_bundle_manifest_suffix(tmp_path: Path) -> None:
    manifest = tmp_path / "demo.bundle.manifest.json"

    result = derive_agent_export_gate_path(manifest)

    assert result == tmp_path / "demo.agent_export_gate.json"


def test_derive_agent_export_gate_path_uses_generic_stem(tmp_path: Path) -> None:
    manifest = tmp_path / "generic-manifest.json"

    result = derive_agent_export_gate_path(manifest)

    assert result == tmp_path / "generic-manifest.agent_export_gate.json"


def test_derive_agent_export_gate_path_preserves_manifest_parent(tmp_path: Path) -> None:
    manifest = tmp_path / "nested" / "demo.bundle.manifest.json"

    result = derive_agent_export_gate_path(manifest)

    assert result.parent == manifest.parent
