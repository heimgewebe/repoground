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
        check=True, capture_output=True, text=True,
    ).stdout


def _base_available() -> bool:
    if not COMMITTED.exists():
        return False
    base = json.loads(COMMITTED.read_text())["base"]
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


# --------------------------------------------------------------------------
# 2. Hermeticity: infer_facets is bound to the base snapshot, not working tree
# --------------------------------------------------------------------------
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
    base = json.loads(COMMITTED.read_text())["base"]
    rc = audit.main([
        "--repo", str(REPO_ROOT), "--base-sha", base,
        "--manifest", str(COMMITTED), "--output", str(tmp_path / "out.json"),
    ])
    assert rc == 0


@real_repo
def test_determinism(tmp_path):
    base = json.loads(COMMITTED.read_text())["base"]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for out in (a, b):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(COMMITTED), "--output", str(out)])
    assert a.read_bytes() == b.read_bytes()
    # and it reproduces the committed report byte-for-byte
    assert a.read_bytes() == COMMITTED.read_bytes()


def _tamper(tmp_path, mutate) -> Path:
    data = json.loads(COMMITTED.read_text())
    mutate(data)
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@real_repo
def test_wrong_engine_line_rejected(tmp_path):
    base = json.loads(COMMITTED.read_text())["base"]
    manifest = _tamper(tmp_path, lambda d: d["flows"].__setitem__(
        0, d["flows"][0].replace("|39|", "|990|")))
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_nonexistent_schema_rejected(tmp_path):
    base = json.loads(COMMITTED.read_text())["base"]
    manifest = _tamper(tmp_path, lambda d: d["flows"].__setitem__(
        1, d["flows"][1].replace(
            "embedding-policy.v1.schema.json", "nope.v1.schema.json")))
    with pytest.raises(audit.AuditError):
        audit.main(["--repo", str(REPO_ROOT), "--base-sha", base,
                    "--manifest", str(manifest), "--output", str(tmp_path / "o.json")])


@real_repo
def test_dropping_manual_review_flow_rejected(tmp_path):
    """Removing a manual-review flow leaves an unresolved AST candidate uncovered."""
    base = json.loads(COMMITTED.read_text())["base"]
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
