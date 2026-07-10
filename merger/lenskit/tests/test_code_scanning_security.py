import json
from pathlib import Path

import pytest
import yaml

from merger.lenskit.core.federation import add_bundle, init_federation
from merger.lenskit.core.path_security import resolve_secure_path
from merger.lenskit.retrieval.federation_query import execute_federated_query


def test_resolve_secure_path_accepts_normalized_descendant(tmp_path):
    root = tmp_path / "root"
    nested = root / "docs" / "index.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")

    assert resolve_secure_path(root, "docs/index.json") == nested.resolve()


@pytest.mark.parametrize(
    "raw",
    ["", " docs/index.json", "docs/index.json ", ".", "..", "../escape", "a/../b", "/etc/passwd", "a\\b", "a:b", "C:/escape", "a//b", "a/./b", "nul\x00byte"],
)
def test_resolve_secure_path_rejects_untrusted_syntax(tmp_path, raw):
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ValueError):
        resolve_secure_path(root, raw)


def test_resolve_secure_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="Path resolution failed"):
        resolve_secure_path(root, "escape/secret.json")


def test_prescan_api_rejects_repo_symlink_escape(service_client, tmp_path):
    outside = tmp_path / "outside-repo"
    outside.mkdir()
    (outside / "secret.txt").write_text("not for prescan", encoding="utf-8")
    (service_client.hub_path / "escape").symlink_to(outside, target_is_directory=True)

    response = service_client.client.post(
        "/api/prescan",
        json={"repo": "escape", "max_depth": 2},
        headers=service_client.headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid repository path"}
    assert "secret.txt" not in response.text


def test_federation_api_rejects_index_symlink_escape(service_client, tmp_path):
    outside_index = tmp_path / "outside-federation.json"
    outside_index.write_text(
        json.dumps(
            {
                "kind": "repolens.federation.index",
                "version": "1.0",
                "federation_id": "outside",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "bundles": [],
            }
        ),
        encoding="utf-8",
    )
    (service_client.merges_dir / "outside.json").symlink_to(outside_index)

    response = service_client.client.post(
        "/api/federation/query",
        json={"federation_index": "outside.json", "q": "test", "k": 1},
        headers=service_client.headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid federation index path"}
    assert str(outside_index) not in response.text


def test_federation_api_mode_rejects_external_bundle_path(tmp_path):
    federation_dir = tmp_path / "merges"
    external_bundle = tmp_path / "external-bundle"
    federation_dir.mkdir()
    external_bundle.mkdir()
    federation_index = federation_dir / "federation.json"
    init_federation("secure-api", federation_index)
    add_bundle(federation_index, "external", str(external_bundle))

    result = execute_federated_query(
        federation_index,
        query_text="test",
        trace=True,
        allow_external_bundle_paths=False,
    )

    trace = result["federation_trace"]
    assert trace["bundle_status"] == {"external": "bundle_path_rejected"}
    assert trace["queried_bundles_effective"] == 0
    assert str(external_bundle) not in json.dumps(result)


def test_ai_context_workflow_has_read_only_permissions():
    workflow_path = Path(".github/workflows/ai-context-guard.yml")
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"repo-root", "templates"}


def test_init_federation_rejects_non_json_output(tmp_path):
    with pytest.raises(ValueError, match="must be a JSON file"):
        init_federation("invalid-output", tmp_path / "federation.txt")


def test_init_federation_rejects_missing_parent(tmp_path):
    output = tmp_path / "missing" / "federation.json"

    with pytest.raises(FileNotFoundError, match="parent directory not found"):
        init_federation("missing-parent", output)

    assert not output.exists()


def test_init_federation_rejects_dangling_symlink_output(tmp_path):
    output = tmp_path / "federation.json"
    output.symlink_to(tmp_path / "outside-target.json")

    with pytest.raises(FileExistsError, match="already exists"):
        init_federation("symlink-output", output)

    assert output.is_symlink()
    assert not (tmp_path / "outside-target.json").exists()
