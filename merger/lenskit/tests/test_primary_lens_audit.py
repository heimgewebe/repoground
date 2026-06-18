import json
from pathlib import Path

import pytest

from merger.lenskit.core.lens_audit import (
    DOES_NOT_ESTABLISH,
    KIND,
    VERSION,
    audit_primary_lenses,
    explain_primary_lens,
)
from merger.lenskit.core.lenses import LENS_IDS, infer_lens


def _schema() -> dict:
    schema_path = (
        Path(__file__).parent.parent / "contracts" / "primary-lens-audit.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def test_primary_lens_audit_schema_validates_minimal_report():
    jsonschema = pytest.importorskip("jsonschema")
    report = {
        "kind": KIND,
        "version": VERSION,
        "items": [
            {
                "path": "src/core/engine.py",
                "primary_lens": "core",
                "matched_rule": "core: core/logic/domain path segment",
                "possible_facets": [],
                "notes": [],
                "does_not_establish": list(DOES_NOT_ESTABLISH),
            }
        ],
        "summary": {
            "item_count": 1,
            "lens_counts": {"core": 1},
        },
        "does_not_establish": list(DOES_NOT_ESTABLISH),
    }

    jsonschema.validate(instance=report, schema=_schema())


def test_primary_lens_audit_schema_validates_generated_report():
    jsonschema = pytest.importorskip("jsonschema")
    report = audit_primary_lenses(
        [
            ".github/workflows/main.yml",
            "src/contracts/user.proto",
            "src/core/engine.py",
        ]
    )

    jsonschema.validate(instance=report, schema=_schema())


def test_primary_lens_audit_empty_input_is_valid():
    jsonschema = pytest.importorskip("jsonschema")
    report = audit_primary_lenses([])

    assert report["kind"] == KIND
    assert report["version"] == VERSION
    assert report["items"] == []
    assert report["summary"]["item_count"] == 0
    assert report["summary"]["lens_counts"] == {}
    assert report["does_not_establish"] == list(DOES_NOT_ESTABLISH)

    jsonschema.validate(instance=report, schema=_schema())


def test_primary_lens_audit_rejects_empty_paths():
    with pytest.raises(ValueError, match="path"):
        audit_primary_lenses([""])
    with pytest.raises(ValueError, match="path"):
        audit_primary_lenses(["   "])
    with pytest.raises(ValueError, match="path"):
        audit_primary_lenses(["."])


def test_primary_lens_audit_rejects_absolute_paths():
    with pytest.raises(ValueError, match="repo-relative"):
        audit_primary_lenses(["/tmp/lenskit/merger/lenskit/core/lenses.py"])


def test_primary_lens_audit_rejects_parent_traversal_paths():
    with pytest.raises(ValueError, match="parent traversal"):
        audit_primary_lenses(["../merger/lenskit/core/lenses.py"])
    with pytest.raises(ValueError, match="parent traversal"):
        audit_primary_lenses(["merger/../lenskit/core/lenses.py"])


def test_primary_lens_audit_rejects_windows_separators():
    with pytest.raises(ValueError, match="POSIX"):
        audit_primary_lenses([r"merger\lenskit\core\lenses.py"])


def test_primary_lens_audit_sorts_paths_deterministically():
    report = audit_primary_lenses(
        [
            "docs/readme.md",
            "merger/lenskit/core/lenses.py",
            ".github/workflows/ci.yml",
        ]
    )

    assert [item["path"] for item in report["items"]] == [
        ".github/workflows/ci.yml",
        "docs/readme.md",
        "merger/lenskit/core/lenses.py",
    ]


def test_primary_lens_audit_deduplicates_paths():
    report = audit_primary_lenses(
        [
            "docs/readme.md",
            Path("docs/readme.md"),
            "docs/readme.md",
        ]
    )

    assert [item["path"] for item in report["items"]] == ["docs/readme.md"]
    assert report["summary"]["item_count"] == 1


def test_primary_lens_audit_uses_existing_infer_lens():
    report = audit_primary_lenses(
        [
            ".github/workflows/main.yml",
            "src/contracts/user.proto",
            "src/pipelines/daily_sync.py",
            "src/__main__.py",
            "src/ui/button.tsx",
            "src/api/v1/users.py",
            "src/core/engine.py",
            "docs/README.md",
            "misc/unknown_file.xyz",
        ]
    )

    for item in report["items"]:
        assert item["primary_lens"] == infer_lens(Path(item["path"]))


def test_primary_lens_audit_only_uses_known_lens_ids():
    report = audit_primary_lenses(
        [
            ".github/workflows/main.yml",
            "src/contracts/user.proto",
            "src/pipelines/daily_sync.py",
            "src/__main__.py",
            "src/ui/button.tsx",
            "src/api/v1/users.py",
            "src/core/engine.py",
        ]
    )

    assert all(item["primary_lens"] in LENS_IDS for item in report["items"])


def test_primary_lens_audit_counts_lenses():
    report = audit_primary_lenses(
        [
            ".github/workflows/main.yml",
            "src/api/v1/users.py",
            "src/core/engine.py",
            "docs/README.md",
        ]
    )

    assert report["summary"]["item_count"] == 4
    assert report["summary"]["lens_counts"] == {
        "core": 1,
        "entrypoints": 1,
        "guards": 1,
        "interfaces": 1,
    }
    assert list(report["summary"]["lens_counts"]) == sorted(
        report["summary"]["lens_counts"]
    )


def test_primary_lens_audit_schema_rejects_unknown_lens_count_key():
    jsonschema = pytest.importorskip("jsonschema")
    report = audit_primary_lenses(["src/core/engine.py"])
    report["summary"]["lens_counts"]["bananen_lens"] = 7

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


@pytest.mark.parametrize(
    "bad_path",
    [
        "/tmp/lenskit/merger/lenskit/core/lenses.py",
        ".",
        "   ",
        "../merger/lenskit/core/lenses.py",
        "merger/../lenskit/core/lenses.py",
        r"merger\lenskit\core\lenses.py",
    ],
)
def test_primary_lens_audit_schema_rejects_invalid_paths(bad_path):
    jsonschema = pytest.importorskip("jsonschema")
    report = audit_primary_lenses(["src/core/engine.py"])
    report["items"][0]["path"] = bad_path

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=report, schema=_schema())


def test_primary_lens_audit_includes_does_not_establish_top_level_and_items():
    report = audit_primary_lenses(["src/core/engine.py"])

    assert report["does_not_establish"] == list(DOES_NOT_ESTABLISH)
    assert report["items"][0]["does_not_establish"] == list(DOES_NOT_ESTABLISH)


def test_primary_lens_audit_emits_possible_facets_and_notes():
    report = audit_primary_lenses(["src/core/engine.py"])
    item = report["items"][0]

    assert item["possible_facets"] == []
    assert item["notes"] == []


def test_primary_lens_audit_contains_no_positive_review_or_truth_claims():
    report = audit_primary_lenses(
        [
            ".github/workflows/main.yml",
            "src/core/engine.py",
        ]
    )
    payload = json.dumps(report, sort_keys=True)

    forbidden_fragments = (
        '"verdict"',
        '"approved"',
        '"requires_fix"',
        '"safe": true',
        '"complete": true',
        '"covered": true',
        '"critical": true',
        '"impact": true',
    )
    for fragment in forbidden_fragments:
        assert fragment not in payload


@pytest.mark.parametrize(
    ("path", "expected_lens", "expected_rule_fragment"),
    [
        (".github/workflows/main.yml", "guards", ".github/wgx/guards"),
        ("src/contracts/user.proto", "data_models", "contracts/schemas/models/types"),
        ("src/pipelines/daily_sync.py", "pipelines", "pipelines/jobs/orchestration"),
        ("src/__main__.py", "entrypoints", "canonical entrypoint filename"),
        ("src/ui/button.tsx", "ui", "ui/app/web/frontend/views"),
        ("src/api/v1/users.py", "interfaces", "adapters/interfaces/api/ports/routes"),
        ("src/core/engine.py", "core", "core/logic/domain"),
        ("src/core/service/logic.py", "core", "core/logic/domain"),
        ("docs/README.md", "entrypoints", "docs path fallback"),
        ("misc/unknown_file.xyz", "core", "ultimate fallback"),
    ],
)
def test_explain_primary_lens_matches_existing_precedence_examples(
    path, expected_lens, expected_rule_fragment
):
    lens, matched_rule = explain_primary_lens(path)

    assert lens == expected_lens
    assert lens == infer_lens(Path(path))
    assert expected_rule_fragment in matched_rule


def test_explain_primary_lens_never_overrides_infer_lens():
    paths = [
        ".github/workflows/main.yml",
        "src/contracts/user.proto",
        "src/pipelines/daily_sync.py",
        "src/__main__.py",
        "src/ui/button.tsx",
        "src/api/v1/users.py",
        "src/core/engine.py",
        "src/core/service/logic.py",
        "docs/README.md",
        "misc/unknown_file.xyz",
    ]

    for path in paths:
        explained_lens, matched_rule = explain_primary_lens(path)
        assert explained_lens == infer_lens(Path(path))
        assert matched_rule
