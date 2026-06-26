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
    return engines, metas, {(o, ln) for o, ln, _k in unresolved}


def test_module_alias_validate_is_engine():
    eng, _meta, _un = _analyze("import jsonschema\ndef f():\n    jsonschema.validate(a, b)\n")
    assert ("f", 3) in eng


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
    assert any(ln == 4 for _o, ln in un)


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
def test_nonexistent_schema_rejected(tmp_path):
    base = json.loads(COMMITTED.read_text(encoding="utf-8"))["base"]
    manifest = _tamper(tmp_path, lambda d: d["flows"].__setitem__(
        1, d["flows"][1].replace(
            "embedding-policy.v1.schema.json", "nope.v1.schema.json")))
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


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
