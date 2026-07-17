"""Falsification tests for the hermetic validates_schema target-proof audit.

These tests prove the audit is not tautological: the receiver-resolved grammar
rejects foreign ``.validate`` calls, the facet classification is bound to the
base snapshot (not the working tree), and a tampered flow manifest makes the
audit fail closed.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "proofs" / "guard_relation_validates_schema_audit.py"
COMMITTED = REPO_ROOT / "docs" / "proofs" / "guard-relation-cards-v1b-validates-schema-audit.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("vsa_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # required for dataclass annotation resolution
    spec.loader.exec_module(module)
    return module


audit = _load_module()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    ).stdout


def _base_available() -> bool:
    if not COMMITTED.exists():
        return False
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    try:
        _git(REPO_ROOT, "cat-file", "-e", f"{base}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


real_repo = pytest.mark.skipif(not _base_available(), reason="base snapshot not available")


# --------------------------------------------------------------------------
# 1. Grammar: receiver-resolved, no generic .validate matching
# --------------------------------------------------------------------------
def _analyze(src: str):
    engines, metas, unresolved = audit.analyze(src, "x.py")
    return engines, metas, _UnresolvedView(unresolved)


class _UnresolvedView:
    def __init__(self, entries):
        self.entries = set(entries)

    def __iter__(self):
        return iter(self.entries)

    def __bool__(self):
        return bool(self.entries)

    def __contains__(self, item):
        if len(item) == 2:
            owner, line = item
            return any(
                entry_owner == owner and entry_line == line
                for entry_owner, entry_line, _kind in self.entries
            )
        return item in self.entries

    def __repr__(self):
        return repr(self.entries)


def test_module_alias_validate_is_engine():
    eng, _meta, _un = _analyze("import jsonschema\ndef f():\n    jsonschema.validate(a, b)\n")
    assert ("f", 3) in eng


def test_global_import_after_function_definition_is_late_bound():
    src = (
        "def check():\n"
        "    jsonschema.validate(data, schema)\n"
        "import jsonschema\n"
    )
    eng, _meta, un = _analyze(src)
    assert ("check", 2) in eng
    assert ("check", 2) not in un


def test_later_global_reassignment_invalidates_function_global_lookup():
    src = (
        "import jsonschema\n"
        "def check():\n"
        "    jsonschema.validate(data, schema)\n"
        "jsonschema = foreign_object\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 3) in un


def test_import_alias_validate_is_engine():
    eng, _m, _u = _analyze(
        "from jsonschema import validate as check\ndef f():\n    check(instance=a, schema=b)\n"
    )
    assert ("f", 3) in eng


def test_chained_draft_validator_is_engine():
    eng, _m, _u = _analyze(
        "from jsonschema import Draft7Validator\n"
        "def f():\n    return list(Draft7Validator(s).iter_errors(d))\n"
    )
    assert ("f", 3) in eng


def test_assigned_validator_var_is_engine():
    eng, _m, _u = _analyze(
        "import jsonschema\n"
        "def f():\n    v = jsonschema.Draft202012Validator(s)\n    return v.iter_errors(d)\n"
    )
    assert ("f", 4) in eng


def test_check_schema_is_meta_not_engine():
    eng, meta, _u = _analyze(
        "import jsonschema\ndef f():\n    jsonschema.Draft7Validator.check_schema(s)\n"
    )
    assert ("f", 3) in meta
    assert not eng


def test_foreign_validate_is_not_engine_but_unresolved():
    """A foreign object's .validate() must never be counted as a jsonschema flow."""
    eng, _m, un = _analyze("def f():\n    payment.validate()\n    model.iter_errors()\n")
    assert eng == set()
    assert ("f", 2) in un and ("f", 3) in un


def test_loader_indirection_is_unresolved_not_engine():
    """jsonschema obtained via a project-local loader is unresolved (manual review)."""
    src = (
        "def f():\n"
        "    jsonschema, _ = _load_jsonschema()\n"
        "    v = jsonschema.Draft7Validator(s)\n"
        "    return v.iter_errors(d)\n"
    )
    eng, _m, un = _analyze(src)
    # local `jsonschema` is not a module-alias binding -> not resolved
    assert eng == set()
    assert ("f", 4) in un


def test_nested_assignment_does_not_leak_to_outer_scope():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def outer():\n"
        "    def inner():\n"
        "        validator = Draft7Validator(schema)\n"
        "    return validator.iter_errors(data)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("outer", 5) in un


def test_use_before_assignment_is_not_resolved_retroactively():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def check():\n"
        "    validator.iter_errors(data)\n"
        "    validator = Draft7Validator(schema)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 3) in un


def test_local_import_does_not_leak_to_sibling_function():
    src = (
        "def first():\n"
        "    import jsonschema as js\n"
        "def second():\n"
        "    js.validate(data, schema)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("second", 4) in un


def test_parameter_shadows_module_alias():
    src = (
        "import jsonschema\n"
        "def check(jsonschema):\n"
        "    jsonschema.validate(data, schema)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 3) in un


def test_later_local_assignment_masks_global_for_whole_function():
    src = (
        "import jsonschema\n"
        "def check():\n"
        "    jsonschema.validate(data, schema)\n"
        "    jsonschema = foreign_object\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 3) in un


def test_reassignment_invalidates_validator_instance():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def check():\n"
        "    validator = Draft7Validator(schema)\n"
        "    validator = foreign_object\n"
        "    validator.iter_errors(data)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 5) in un


def test_class_method_owner_is_qualified():
    src = (
        "import jsonschema\n"
        "class MyValidator:\n"
        "    def check(self):\n"
        "        jsonschema.validate(data, schema)\n"
    )
    eng, _meta, _un = _analyze(src)
    assert ("MyValidator.check", 4) in eng


def test_class_local_does_not_leak_into_method_scope():
    src = (
        "from jsonschema import Draft7Validator\n"
        "class MyValidator:\n"
        "    validator = Draft7Validator(schema)\n"
        "    def check(self):\n"
        "        validator.iter_errors(data)\n"
    )
    eng, _meta, un = _analyze(src)
    assert ("MyValidator.check", 5) not in eng
    assert ("MyValidator.check", 5) in un


def test_lexical_closure_keeps_preceding_validator_binding():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def outer():\n"
        "    validator = Draft7Validator(schema)\n"
        "    def inner():\n"
        "        return validator.iter_errors(data)\n"
    )
    eng, _meta, _un = _analyze(src)
    assert ("outer.inner", 5) in eng


def test_later_closure_reassignment_invalidates_free_name():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def outer():\n"
        "    validator = Draft7Validator(schema)\n"
        "    def inner():\n"
        "        return validator.iter_errors(data)\n"
        "    validator = foreign_object\n"
    )
    eng, _meta, un = _analyze(src)
    assert ("outer.inner", 5) not in eng
    assert ("outer.inner", 5) in un


def test_optional_module_import_remains_resolved():
    src = (
        "try:\n"
        "    import jsonschema\n"
        "except ImportError:\n"
        "    jsonschema = None\n"
        "def check():\n"
        "    jsonschema.validate(data, schema)\n"
    )
    eng, _meta, _un = _analyze(src)
    assert ("check", 6) in eng


def test_one_sided_branch_assignment_is_unresolved_after_merge():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def check(flag):\n"
        "    if flag:\n"
        "        validator = Draft7Validator(schema)\n"
        "    validator.iter_errors(data)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 5) in un


@pytest.mark.parametrize(
    "source",
    [
        "import jsonschema\njsonschema.validators.validator_for(schema)(schema).iter_errors(data)\n",
        "import jsonschema.validators\njsonschema.validators.validator_for(schema)(schema).iter_errors(data)\n",
        "from jsonschema import validators as v\nv.validator_for(schema)(schema).iter_errors(data)\n",
        "from jsonschema.validators import validator_for as vf\nvf(schema)(schema).iter_errors(data)\n",
    ],
)
def test_validator_for_forms_are_resolved(source):
    eng, _meta, _un = _analyze(source)
    assert ("<module>", 2) in eng


def test_non_ascii_source_is_parsed_as_normal_text():
    eng, _meta, _un = _analyze(
        "import jsonschema\n# Grüße 🌍\njsonschema.validate(data, schema)\n"
    )
    assert ("<module>", 3) in eng


def test_comprehension_target_shadows_module_only_inside_comprehension():
    src = (
        "import jsonschema\n"
        "[jsonschema.validate(data, schema) for jsonschema in values]\n"
        "jsonschema.validate(data, schema)\n"
    )
    eng, _meta, un = _analyze(src)
    assert ("<module>", 2) not in eng
    assert ("<module>", 2) in un
    assert ("<module>", 3) in eng


def test_function_scoped_module_declaration_does_not_prove_execution():
    src = (
        "def configure():\n"
        "    global js\n"
        "    import jsonschema as js\n"
        "def check():\n"
        "    js.validate(data, schema)\n"
    )
    eng, _meta, un = _analyze(src)
    assert eng == set()
    assert ("check", 5) in un


def test_match_capture_invalidates_validator_after_conservative_merge():
    src = (
        "from jsonschema import Draft7Validator\n"
        "def check(value):\n"
        "    validator = Draft7Validator(schema)\n"
        "    match value:\n"
        "        case {'validator': validator}:\n"
        "            pass\n"
        "    validator.iter_errors(data)\n"
    )
    eng, _meta, un = _analyze(src)
    assert ("check", 7) not in eng
    assert ("check", 7) in un


# --------------------------------------------------------------------------
# 2. Hermeticity: infer_facets is bound to the base snapshot, not working tree
# --------------------------------------------------------------------------
def test_base_import_policy_allows_stdlib_only():
    audit.validate_base_import_policy(
        "from __future__ import annotations\nimport os\nfrom pathlib import Path\n",
        "lens_facets.py",
    )


@pytest.mark.parametrize(
    "source",
    [
        "from .constants import VALUE\n",
        "from merger.lenskit.core.constants import VALUE\n",
        "import third_party_package\n",
        "import importlib\nimportlib.import_module('merger.lenskit.core.constants')\n",
        "from importlib import import_module as load\nload('merger.lenskit.core.constants')\n",
    ],
)
def test_base_import_policy_rejects_live_or_dynamic_imports(source):
    with pytest.raises(audit.AuditError, match="base import policy"):
        audit.validate_base_import_policy(source, "lens_facets.py")


@pytest.mark.parametrize(
    ("code", "output", "expected"),
    [
        (0, "OK wrote /tmp/rejected.json", False),
        (1, "Traceback (most recent call last)", False),
        (2, "STOP: engine callsite mismatch", False),
        (2, "STOP: relation callsite mismatch", True),
    ],
)
def test_ci_negative_control_result_requires_exit_2_and_expected_gate(
    code, output, expected
):
    assert audit.negative_control_result_ok(
        code, output, "relation callsite mismatch"
    ) is expected


def test_workflow_negative_control_checks_relation_callsite_message():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "lens-model.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["validates-schema-target-proof"]["steps"]
    run = next(
        step["run"]
        for step in steps
        if step.get("name") == "Negative control (a tampered manifest must fail closed)"
    )
    compact_run = " ".join(run.split())
    assert "relation_call_line" in run
    assert 'endswith("/core/relation_card_validate.py")' in compact_run
    assert '== "validate_relation_card"' in compact_run
    assert '== "_schema_check"' in compact_run
    assert 'endswith( "/contracts/relation-card.v1.schema.json" )' in compact_run
    assert "len(matches) != 1" in run
    assert "validate_relation_card|226|_schema_check|159" not in run
    assert "code=$?" in run
    assert "relation callsite mismatch" in run


def test_infer_facets_loaded_from_base_snapshot(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    facets = repo / "merger" / "lenskit" / "core"
    facets.mkdir(parents=True)
    target = facets / "lens_facets.py"

    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    # base version: marks everything as a test facet
    target.write_text(
        "def infer_facets(path):\n    return [{'facet': 'test'}]\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    # working-tree drift: later version marks nothing
    target.write_text(
        "def infer_facets(path):\n    return []\n", encoding="utf-8"
    )

    infer = audit.load_base_infer_facets(str(repo), base)
    assert infer("anything.py") == [{"facet": "test"}]  # base behaviour, not drift


# --------------------------------------------------------------------------
# 3. Full audit against the real snapshot: clean passes, tampering fails
# --------------------------------------------------------------------------
@real_repo
def test_clean_manifest_passes(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    rc = audit.main([
        "--repo", str(REPO_ROOT), "--base-sha", base,
        "--manifest", str(COMMITTED), "--output", str(tmp_path / "out.json"),
    ])
    assert rc == 0


@real_repo
def test_determinism(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for out in (a, b):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(COMMITTED), "--output", str(out)])
    assert a.read_bytes() == b.read_bytes()
    # and it reproduces the committed report byte-for-byte
    assert a.read_bytes() == COMMITTED.read_bytes()


def _tamper(tmp_path, mutate) -> Path:
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _relation_card_flow_index(data: dict) -> int:
    fields = data["fields"]
    source_index = fields.index("source_path")
    relation_owner_index = fields.index("relation_owner_symbol")
    engine_owner_index = fields.index("engine_owner_symbol")
    schema_index = fields.index("schema_path")
    matches: list[int] = []
    for index, row in enumerate(data["flows"]):
        values = row.split("|")
        assert len(values) == len(fields), f"invalid flow width at index {index}"
        if (
            values[source_index].endswith("/core/relation_card_validate.py")
            and values[relation_owner_index] == "validate_relation_card"
            and values[engine_owner_index] == "_schema_check"
            and values[schema_index].endswith(
                "/contracts/relation-card.v1.schema.json"
            )
        ):
            matches.append(index)
    assert len(matches) == 1, f"expected one relation-card flow, found {matches}"
    return matches[0]


@real_repo
def test_missing_expected_parse_failures_rejected(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    manifest = _tamper(tmp_path, lambda data: data.pop("expected_parse_failures"))
    with pytest.raises(audit.AuditError, match="expected_parse_failures"):
        audit.main([
            "--repo", str(REPO_ROOT), "--base-sha", base,
            "--manifest", str(manifest), "--output", str(tmp_path / "o.json"),
        ])


@real_repo
def test_wrong_engine_line_rejected(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]

    def change_engine_line(data):
        line_index = data["fields"].index("engine_call_line")
        row_index = next(
            index
            for index, row in enumerate(data["flows"])
            if row.startswith(
                "merger/lenskit/architecture/graph_index.py|load_graph_index|"
            )
        )
        values = data["flows"][row_index].split("|")
        values[line_index] = str(int(values[line_index]) + 10_000)
        data["flows"][row_index] = "|".join(values)

    manifest = _tamper(tmp_path, change_engine_line)
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_wrong_relation_line_rejected_by_relation_gate(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]

    def change_relation_line(data):
        line_index = data["fields"].index("relation_call_line")
        row_index = _relation_card_flow_index(data)
        values = data["flows"][row_index].split("|")
        values[line_index] = str(int(values[line_index]) + 10_000)
        data["flows"][row_index] = "|".join(values)

    manifest = _tamper(tmp_path, change_relation_line)
    with pytest.raises(audit.AuditError, match="relation callsite mismatch"):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_wrong_relation_owner_rejected_by_relation_gate(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]

    def change_relation_owner(data):
        owner_index = data["fields"].index("relation_owner_symbol")
        row_index = _relation_card_flow_index(data)
        values = data["flows"][row_index].split("|")
        values[owner_index] = "validate_relation_card_wrong_owner"
        data["flows"][row_index] = "|".join(values)

    manifest = _tamper(tmp_path, change_relation_owner)
    with pytest.raises(audit.AuditError, match="relation callsite mismatch"):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_wrong_delegated_helper_rejected_by_relation_gate(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]

    def change_helper(data):
        helper_index = data["fields"].index("engine_owner_symbol")
        row_index = _relation_card_flow_index(data)
        values = data["flows"][row_index].split("|")
        values[helper_index] = "_wrong_schema_check"
        data["flows"][row_index] = "|".join(values)

    manifest = _tamper(tmp_path, change_helper)
    with pytest.raises(audit.AuditError, match="relation callsite mismatch"):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_nonexistent_schema_rejected(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    manifest = _tamper(tmp_path, lambda d: d["flows"].__setitem__(
        1, d["flows"][1].replace(
            "embedding-policy.v1.schema.json", "nope.v1.schema.json")))
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


def test_foreign_method_candidate_is_not_automatic_manual_jsonschema():
    _eng, _meta, un = _analyze("def check():\n    payment.validate()\n")
    candidates = {("x.py", owner, line, kind) for owner, line, kind in un}
    partition = audit.partition_unresolved_candidates(
        candidates,
        {
            "engine": [
                {
                    "source_path": "x.py",
                    "owner_symbol": "check",
                    "call_line": 2,
                    "disposition": "foreign_non_jsonschema",
                    "reason": "payment object is not a jsonschema validator",
                }
            ],
            "meta": [],
        },
        reviewed_engine=set(),
        reviewed_meta=set(),
    )
    assert partition.manual_engine == set()
    assert partition.foreign_engine == {("x.py", "check", 2)}


def test_unresolved_candidate_without_disposition_fails_closed():
    with pytest.raises(audit.AuditError, match="unresolved candidate disposition mismatch"):
        audit.partition_unresolved_candidates(
            {("x.py", "check", 2, "unresolved_engine")},
            {"engine": [], "meta": []},
            reviewed_engine=set(),
            reviewed_meta=set(),
        )


def test_foreign_candidate_cannot_be_labeled_manual_jsonschema_without_reviewed_flow():
    with pytest.raises(audit.AuditError, match="manual_jsonschema disposition without reviewed flow"):
        audit.partition_unresolved_candidates(
            {("x.py", "check", 2, "unresolved_engine")},
            {
                "engine": [
                    {
                        "source_path": "x.py",
                        "owner_symbol": "check",
                        "call_line": 2,
                        "disposition": "manual_jsonschema",
                        "reason": "wrongly treated as jsonschema",
                    }
                ],
                "meta": [],
            },
            reviewed_engine=set(),
            reviewed_meta=set(),
        )


@real_repo
def test_dropping_manual_review_flow_rejected(tmp_path):
    """Removing a manual-review flow leaves an unresolved AST candidate uncovered."""
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    manifest = _tamper(tmp_path, lambda d: d.__setitem__(
        "flows", [r for r in d["flows"]
                  if not r.startswith("merger/lenskit/core/lens_card_validate.py")]))
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_base_mismatch_rejected(tmp_path):
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", "0" * 40,
                    "--manifest", str(COMMITTED), "--output", str(tmp_path / "o.json")])
