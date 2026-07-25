from __future__ import annotations

import ast
import datetime
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from merger.repoground.core import clock, merge


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "report_renderer"
REPO_ROOT = FIXTURE_ROOT / "repo"
GOLDEN_ROOT = FIXTURE_ROOT / "golden"
LOCK_FILE = Path(__file__).parents[3] / "requirements" / "repoground-runtime.lock.txt"
FROZEN_TIME = datetime.datetime(2026, 7, 24, 12, 0, tzinfo=datetime.timezone.utc)


_FILE_SPECS = (
    ("README.md", "doc", ["ai-context"]),
    ("src/main.py", "source", ["entrypoint"]),
    ("docs/guide.md", "doc", ["runbook"]),
    (".github/workflows/ci.yml", "config", ["ci"]),
)


def _file_info(
    path: Path,
    *,
    rel_path: str,
    root_label: str = "report-fixture",
    category: str = "source",
    tags: list[str] | None = None,
) -> merge.FileInfo:
    payload = path.read_bytes()
    return merge.FileInfo(
        root_label=root_label,
        abs_path=path,
        rel_path=Path(rel_path),
        size=len(payload),
        is_text=True,
        md5=hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        category=category,
        tags=tags,
        ext=path.suffix,
        content=None,
        inclusion_reason="normal",
    )


def _files() -> list[merge.FileInfo]:
    return [
        _file_info(
            REPO_ROOT / rel_path,
            rel_path=rel_path,
            category=category,
            tags=list(tags),
        )
        for rel_path, category, tags in _FILE_SPECS
    ]


def _common_kwargs(files: list[merge.FileInfo] | None = None) -> dict[str, object]:
    return {
        "files": _files() if files is None else files,
        "max_file_bytes": 0,
        "sources": [REPO_ROOT],
        "debug": False,
    }


def _scenario_kwargs(name: str) -> dict[str, object]:
    common = _common_kwargs()
    if name == "full_extras":
        return common | {
            "level": "max",
            "plan_only": False,
            "extras": merge.ExtrasConfig(
                organism_index=True,
                delta_reports=True,
                heatmap=True,
            ),
            "delta_meta": {
                "base_import": "2026-07-23T12:00:00Z",
                "current_timestamp": "2026-07-24T12:00:00Z",
                "summary": {"files_added": 1, "files_removed": 0, "files_changed": 2},
            },
            "artifact_refs": {
                "index_json_basename": "fixture.index.json",
                "augment_sidecar_basename": "fixture.augment.json",
            },
            "meta_density": "full",
        }
    if name == "plan_filtered":
        return common | {
            "level": "summary",
            "plan_only": True,
            "path_filter": "docs/",
            "meta_density": "auto",
        }
    if name == "machine_redacted":
        return common | {
            "level": "machine-lean",
            "plan_only": False,
            "code_only": True,
            "meta_density": "min",
            "redact_secrets": True,
        }
    raise AssertionError(f"unknown scenario: {name}")


def _render(name: str) -> list[str]:
    with clock.frozen(FROZEN_TIME):
        return list(merge.iter_report_blocks(**_scenario_kwargs(name)))


def _render_kwargs(kwargs: dict[str, object]) -> list[str]:
    with clock.frozen(FROZEN_TIME):
        return list(merge.iter_report_blocks(**kwargs))


def _block_manifest(blocks: list[str]) -> dict[str, object]:
    return {
        "block_count": len(blocks),
        "joined_sha256": hashlib.sha256("".join(blocks).encode()).hexdigest(),
        "blocks": [
            {
                "index": index,
                "bytes": len(block.encode()),
                "sha256": hashlib.sha256(block.encode()).hexdigest(),
            }
            for index, block in enumerate(blocks)
        ],
    }


def _yaml_meta(report: str) -> dict[str, object]:
    payload = report.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    loaded = yaml.safe_load(payload)
    assert isinstance(loaded, dict)
    return loaded


def _python_source(report: str, rel_path: str) -> str:
    segment = report.split(f'<!-- FILE_START path="{rel_path}"', 1)[1]
    fenced = segment.split("```python\n", 1)[1]
    return fenced.split("\n```", 1)[0]


@pytest.mark.parametrize("name", ["full_extras", "plan_filtered", "machine_redacted"])
def test_report_renderer_matches_byte_and_block_goldens(name: str) -> None:
    blocks = _render(name)
    assert "".join(blocks) == (GOLDEN_ROOT / f"{name}.txt").read_text(encoding="utf-8")
    assert _block_manifest(blocks) == json.loads(
        (GOLDEN_ROOT / f"{name}.blocks.json").read_text(encoding="utf-8")
    )


def test_pyyaml_byte_golden_dependency_is_exactly_bound() -> None:
    assert yaml.__version__ == "6.0.3"
    assert "pyyaml==6.0.3" in LOCK_FILE.read_text(encoding="utf-8").lower()


def test_report_renderer_stays_lazy_until_actual_content_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def read(file_info: merge.FileInfo, _max_bytes: int):
        calls.append(file_info.rel_path.as_posix())
        return file_info.abs_path.read_text(encoding="utf-8"), False, ""

    monkeypatch.setattr(merge, "read_smart_content", read)
    with clock.frozen(FROZEN_TIME):
        iterator = merge.iter_report_blocks(**_scenario_kwargs("full_extras"))
        while True:
            block = next(iterator)
            assert calls == []
            if block == "<!-- START_OF_CONTENT -->\n":
                break
        next(iterator)  # content heading
        assert calls == []
        next(iterator)  # first repository heading
        assert calls == []
        first_file_block = next(iterator)

    assert calls == [".github/workflows/ci.yml"]
    assert 'FILE_START path=".github/workflows/ci.yml"' in first_file_block


def test_tags_none_is_safe_in_full_index(tmp_path: Path) -> None:
    path = tmp_path / "untagged.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    files = [_file_info(path, rel_path="untagged.py", tags=None)]
    report = "".join(
        _render_kwargs(
            _common_kwargs(files) | {"level": "max", "plan_only": False}
        )
    )
    assert "untagged.py" in report
    assert "Tag: wgx-profile" not in report


def test_empty_manifest_zone_is_balanced_and_has_no_content_file() -> None:
    report = "".join(
        _render_kwargs(_common_kwargs([]) | {"level": "max", "plan_only": False})
    )
    start = '<!-- zone:begin type="manifest" id="manifest" -->'
    end = '<!-- zone:end type="manifest" id="manifest" -->'
    assert report.count(start) == 1
    assert report.count(end) == 1
    assert report.index(start) < report.index(end)
    assert "<!-- FILE_START" not in report


def test_renderer_does_not_reorder_caller_list_but_documents_object_enrichment() -> None:
    files = list(reversed(_files()))
    original_ids = [id(file_info) for file_info in files]
    original_paths = [file_info.rel_path for file_info in files]
    _render_kwargs(_common_kwargs(files) | {"level": "max", "plan_only": False})
    assert [id(file_info) for file_info in files] == original_ids
    assert [file_info.rel_path for file_info in files] == original_paths
    assert all(file_info.anchor for file_info in files)
    assert all(file_info.anchor_alias for file_info in files)
    assert all(file_info.roles is not None for file_info in files)


def test_redacted_python_preserves_assignment_and_syntax() -> None:
    report = "".join(_render("machine_redacted"))
    source = _python_source(report, "src/main.py")
    assert "fixture-secret-value-1234567890" not in report
    assert 'API_KEY = "[REDACTED]"' in source
    assert 'API_KEY"[REDACTED]"' not in source
    ast.parse(source)


def test_plan_only_separates_selection_from_emitted_content() -> None:
    report = "".join(_render("plan_filtered"))
    merge_meta = _yaml_meta(report)["merge"]
    assert merge_meta["content_present"] is False
    assert merge_meta["selection"] == {"selected_files": 1, "text_files": 1}
    assert merge_meta["content"] == {"present": False, "emitted_files": 0}
    assert merge_meta["coverage"] == {
        "included_files": 0,
        "text_files": 1,
        "coverage_pct": 0.0,
    }
    assert "**Included Content:** 0 files" in report
    assert "**Coverage:** 0/1 Dateien mit vollem Inhalt" in report


@pytest.mark.parametrize(
    ("kwargs", "present"),
    [
        ({"level": "max", "plan_only": False}, True),
        ({"level": "max", "plan_only": False, "code_only": True}, True),
        ({"level": "machine-lean", "plan_only": False}, True),
        ({"level": "summary", "plan_only": True}, False),
        ({"level": "max", "plan_only": False, "meta_none": True}, True),
    ],
)
def test_content_coverage_semantics_across_modes(
    kwargs: dict[str, object], present: bool
) -> None:
    report = "".join(_render_kwargs(_common_kwargs() | kwargs))
    merge_meta = _yaml_meta(report)["merge"]
    assert merge_meta["content_present"] is present
    assert merge_meta["content"]["present"] is present
    expected = merge_meta["coverage"]["included_files"]
    assert merge_meta["content"]["emitted_files"] == expected
    if present:
        assert expected > 0
    else:
        assert expected == 0
        assert merge_meta["coverage"]["coverage_pct"] == 0.0


def test_long_backtick_fence_is_escaped(tmp_path: Path) -> None:
    path = tmp_path / "fence.py"
    path.write_text('VALUE = "``````"\n', encoding="utf-8")
    report = "".join(
        _render_kwargs(
            _common_kwargs([_file_info(path, rel_path="fence.py")])
            | {"level": "max", "plan_only": False}
        )
    )
    source_segment = report.split('FILE_START path="fence.py"', 1)[1]
    assert "```````python" in source_segment


def test_slug_collisions_remain_distinct(tmp_path: Path) -> None:
    first = tmp_path / "a_b.py"
    second = tmp_path / "a-b.py"
    first.write_text("FIRST = 1\n", encoding="utf-8")
    second.write_text("SECOND = 2\n", encoding="utf-8")
    files = [
        _file_info(first, rel_path="a_b.py"),
        _file_info(second, rel_path="a-b.py"),
    ]
    _render_kwargs(_common_kwargs(files) | {"level": "max", "plan_only": False})
    assert files[0].anchor_alias == files[1].anchor_alias
    assert files[0].anchor != files[1].anchor


def test_empty_sources_and_extract_purpose_failure_are_nonfatal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(merge, "extract_purpose", lambda _path: (_ for _ in ()).throw(RuntimeError("boom")))
    _render_kwargs(
        _common_kwargs() | {"level": "max", "plan_only": False, "sources": []}
    )
    _render_kwargs(_common_kwargs() | {"level": "max", "plan_only": False})
    assert "extract_purpose failed: boom" in capsys.readouterr().err


def test_multi_repo_health_fleet_augment_and_truncation(tmp_path: Path) -> None:
    alpha_source = tmp_path / "alpha"
    beta_source = tmp_path / "beta"
    alpha_source.mkdir()
    beta_source.mkdir()
    first = alpha_source / "one.py"
    second = beta_source / "two.py"
    first.write_text("A = 1\n", encoding="utf-8")
    second.write_text("B = " + "x" * 200 + "\n", encoding="utf-8")
    (alpha_source / "alpha_augment.yml").write_text(
        "augment:\n  suggestions:\n    - keep fixture deterministic\n",
        encoding="utf-8",
    )
    files = [
        _file_info(first, rel_path="one.py", root_label="alpha", tags=["ci"]),
        _file_info(second, rel_path="two.py", root_label="beta", tags=["wgx-profile"]),
    ]
    blocks = _render_kwargs(
        _common_kwargs(files)
        | {
            "level": "max",
            "plan_only": False,
            "max_file_bytes": 32,
            "sources": [alpha_source, beta_source],
            "extras": merge.ExtrasConfig(
                health=True,
                fleet_panorama=True,
                augment_sidecar=True,
            ),
        }
    )
    report = "".join(blocks)
    merge_meta = _yaml_meta(report)["merge"]
    assert "Repo `alpha`" in report
    assert "Repo `beta`" in report
    assert "truncated" in report
    assert "<!-- @fleet-panorama:start -->" in report
    assert "<!-- @augment:start -->" in report
    assert merge_meta["extras"]["augment_sidecar"] is True
    assert merge_meta["augment"] == {"sidecar": "alpha_augment.yml"}


SCENARIO_NAMES = (
    "profile_max",
    "profile_summary",
    "profile_machine_lean",
    "plan_only",
    "code_only",
    "redaction",
    "meta_min",
    "meta_standard",
    "meta_full",
    "meta_none",
    "organism",
    "heatmap",
    "augment_delta",
    "artifact_refs",
    "extension_filter",
    "path_filter",
    "truncation",
    "multi_repo",
)


_DIFFERENTIAL_OPTIONS: dict[str, dict[str, object]] = {
    "profile_max": {},
    "profile_summary": {"level": "summary"},
    "profile_machine_lean": {"level": "machine-lean"},
    "plan_only": {"plan_only": True},
    "code_only": {"code_only": True},
    "redaction": {"redact_secrets": True},
    "meta_min": {"meta_density": "min"},
    "meta_standard": {"meta_density": "standard"},
    "meta_full": {"meta_density": "full"},
    "meta_none": {"meta_none": True},
    "organism": {"extras": merge.ExtrasConfig(organism_index=True)},
    "heatmap": {"extras": merge.ExtrasConfig(heatmap=True)},
    "augment_delta": {
        "extras": merge.ExtrasConfig(augment_sidecar=True, delta_reports=True),
        "delta_meta": {"summary": {"files_added": 1}},
    },
    "artifact_refs": {"artifact_refs": {"index_json_basename": "index.json"}},
    "extension_filter": {"ext_filter": [".py"]},
    "path_filter": {"path_filter": "src/"},
    "truncation": {"max_file_bytes": 24},
    "multi_repo": {},
}


def _differential_scenario(name: str, tmp_path: Path) -> dict[str, object]:
    kwargs = _common_kwargs() | {
        "level": "max",
        "plan_only": False,
    } | dict(_DIFFERENTIAL_OPTIONS[name])
    if name == "multi_repo":
        extra = tmp_path / "extra.py"
        extra.write_text("EXTRA = 1\n", encoding="utf-8")
        kwargs["files"] = _files() + [
            _file_info(extra, rel_path="extra.py", root_label="second-repo")
        ]
    return kwargs


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_18_scenario_differential_contract(name: str, tmp_path: Path) -> None:
    expected = json.loads(
        (GOLDEN_ROOT / "differential_scenarios.json").read_text(encoding="utf-8")
    )["scenarios"][name]
    blocks = _render_kwargs(_differential_scenario(name, tmp_path))
    actual = _block_manifest(blocks)
    assert actual["block_count"] == expected["block_count"]
    assert actual["joined_sha256"] == expected["joined_sha256"]
    assert [block["bytes"] for block in actual["blocks"]] == expected["block_bytes"]
    assert [block["sha256"] for block in actual["blocks"]] == expected["block_sha256"]


def test_differential_contract_declares_intentional_corrections() -> None:
    contract = json.loads(
        (GOLDEN_ROOT / "differential_scenarios.json").read_text(encoding="utf-8")
    )
    assert contract["scenario_count"] == 18
    assert contract["intentional_corrections"] == [
        "balanced empty manifest zone",
        "plan-only emitted-content coverage is zero",
        "redacted assignments preserve source syntax",
    ]
