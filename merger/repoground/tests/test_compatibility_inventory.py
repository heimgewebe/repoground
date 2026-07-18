from __future__ import annotations

import json
from pathlib import Path

from merger.repoground.core.compatibility_inventory import (
    build_inventory,
    dumps_inventory,
    scan_configs,
    scan_processes,
)


def test_process_inventory_reports_categories_without_raw_argv(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    process = proc / "123"
    process.mkdir(parents=True)
    raw = (
        b"python3\0/home/alex/repos/lenskit/scripts/repobrief-mcp-stdio.py\0"
        b"--bundle-root\0/home/alex/.local/share/repobrief/lenskit-briefs\0"
    )
    (process / "cmdline").write_bytes(raw)

    findings = scan_processes(proc)

    assert findings == [
        {
            "pid": 123,
            "executable": "python3",
            "matched_surfaces": [
                "legacy-bundle-storage-root",
                "legacy-cli-entrypoints",
                "legacy-repository-path",
            ],
            "argv_sha256": findings[0]["argv_sha256"],
        }
    ]
    serialized = json.dumps(findings)
    assert "--bundle-root" not in serialized
    assert "lenskit-briefs" not in serialized


def test_config_inventory_is_hash_only_and_bounded(tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(
        '{"command":"repobrief-mcp-stdio.py","uri":"repobrief://snapshot/demo/manifest"}',
        encoding="utf-8",
    )

    findings = scan_configs([config])

    assert findings[0]["status"] == "scanned"
    assert findings[0]["matched_surfaces"] == [
        "legacy-cli-entrypoints",
        "legacy-mcp-resource-scheme",
    ]
    assert "sha256" in findings[0]
    assert "command" not in findings[0]


def test_inventory_can_skip_live_service_probe(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    proc.mkdir()

    inventory = build_inventory(proc_root=proc, include_services=False)

    assert inventory["schema"] == "repoground.compatibility_inventory.v1"
    assert inventory["read_only"] is True
    assert inventory["raw_command_lines_included"] is False
    assert inventory["raw_config_contents_included"] is False
    assert inventory["matched_surfaces"] == []
    assert inventory["service_states"] == []
    assert json.loads(dumps_inventory(inventory))["schema"] == inventory["schema"]


def test_process_inventory_excludes_observer_pid(tmp_path: Path, monkeypatch) -> None:
    proc = tmp_path / "proc"
    process = proc / "123"
    process.mkdir(parents=True)
    (process / "cmdline").write_bytes(b"python3\0repobrief-mcp-stdio.py\0")
    monkeypatch.setattr("merger.repoground.core.compatibility_inventory.os.getpid", lambda: 123)

    assert scan_processes(proc) == []
