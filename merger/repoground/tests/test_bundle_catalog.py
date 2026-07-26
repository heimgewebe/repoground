import hashlib
import json
from pathlib import Path

from merger.repoground.core.bundle_catalog import (
    discover_bundle_catalog,
    manifest_repo_aliases,
    normalize_repo_remote,
    select_bundle_manifest,
)


def _write_json(path: Path, value: dict) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _write_bundle(
    root: Path,
    *,
    directory: str,
    stem: str,
    created_at: str,
    run_id: str,
    output_status: str = "pass",
    remote: str = "git@github.com:heimgewebe/repoground.git",
) -> Path:
    bundle_dir = root / directory
    output_path = bundle_dir / f"{stem}.output_health.json"
    output_bytes, output_sha = _write_json(
        output_path,
        {"verdict": output_status},
    )
    post_path = bundle_dir / f"{stem}.bundle_health.post.json"
    _write_json(post_path, {"status": "pass"})
    manifest = bundle_dir / f"{stem}.bundle.manifest.json"
    _write_json(
        manifest,
        {
            "kind": "repoground.bundle.manifest",
            "version": "2.0",
            "run_id": run_id,
            "created_at": created_at,
            "snapshot_provenance": {
                "repositories": [
                    {
                        "name": "heimgewebe__repoground__main",
                        "repo_remote": remote,
                        "git_commit": "a" * 40,
                        "git_dirty": False,
                        "provenance_status": "present",
                    }
                ]
            },
            "artifacts": [
                {
                    "role": "output_health",
                    "path": output_path.name,
                    "bytes": output_bytes,
                    "sha256": output_sha,
                }
            ],
            "links": {
                "post_emit_health_path": post_path.name,
                "bundle_surface_validation_status": "pass",
                "agent_export_gate_status": "pass",
                "export_safety_report_status": "pass",
            },
        },
    )
    return manifest


def test_normalize_repo_remote_accepts_common_github_forms():
    assert normalize_repo_remote("git@github.com:heimgewebe/repoground.git") == (
        "heimgewebe/repoground"
    )
    assert normalize_repo_remote("https://github.com/heimgewebe/repoground.git") == (
        "heimgewebe/repoground"
    )


def test_manifest_repo_aliases_include_canonical_and_short_identity():
    aliases = manifest_repo_aliases(
        {
            "snapshot_provenance": {
                "repositories": [
                    {
                        "name": "heimgewebe__repoground__main",
                        "repo_remote": "git@github.com:heimgewebe/repoground.git",
                    }
                ]
            }
        }
    )

    assert aliases == [
        "heimgewebe/repoground",
        "heimgewebe__repoground",
        "heimgewebe__repoground__main",
        "repoground",
    ]


def test_catalog_ignores_hidden_generation_copy_and_selects_publication(tmp_path):
    public = _write_bundle(
        tmp_path,
        directory="heimgewebe__repoground/main/run-1",
        stem="repoground-main",
        created_at="2026-07-25T21:09:13Z",
        run_id="run-1",
    )
    _write_bundle(
        tmp_path,
        directory=(
            "heimgewebe__repoground/main/run-1/.repoground-generations/repoground-main/hash"
        ),
        stem="repoground-main",
        created_at="2026-07-25T21:09:13Z",
        run_id="run-1",
    )

    catalog = discover_bundle_catalog(tmp_path)
    selection = select_bundle_manifest(tmp_path, repo="heimgewebe/repoground")

    assert catalog["candidate_count"] == 1
    assert selection["status"] == "available"
    assert selection["selected"]["manifest_path"] == str(public.resolve())


def test_selector_skips_newer_unhealthy_bundle(tmp_path):
    healthy = _write_bundle(
        tmp_path,
        directory="repo/main/healthy",
        stem="healthy",
        created_at="2026-07-25T20:00:00Z",
        run_id="healthy-run",
    )
    _write_bundle(
        tmp_path,
        directory="repo/main/unhealthy",
        stem="unhealthy",
        created_at="2026-07-25T21:00:00Z",
        run_id="unhealthy-run",
        output_status="fail",
    )

    selection = select_bundle_manifest(tmp_path, repo="repoground")

    assert selection["status"] == "available"
    assert selection["selected"]["manifest_path"] == str(healthy.resolve())
    assert selection["match_count"] == 1


def test_selector_fails_closed_for_equal_newest_identity(tmp_path):
    for directory in ("repo/main/a", "repo/main/b"):
        _write_bundle(
            tmp_path,
            directory=directory,
            stem=Path(directory).name,
            created_at="2026-07-25T21:00:00Z",
            run_id="same-run",
        )

    selection = select_bundle_manifest(tmp_path, repo="heimgewebe/repoground")

    assert selection["status"] == "ambiguous"
    assert selection["reason"] == "newest_bundle_identity_ambiguous"
    assert selection["selected"] is None
