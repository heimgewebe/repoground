"""Comprehensive semantic tests for T009 report-contract-hardening-v2.

These tests exercise full render paths and verify the hardened contracts
for plan-only, ext exclusion, anchors, markers, tags=None, redactor,
benchmark, evidence, delivery, and differential scenarios.
"""
from __future__ import annotations

import ast
import base64
import datetime
import hashlib
import json
import re
from pathlib import Path

import yaml

from merger.repoground.core import clock, merge
from merger.repoground.core.redactor import Redactor

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "report_renderer"
REPO_ROOT = FIXTURE_ROOT / "repo"
GOLDEN_ROOT = FIXTURE_ROOT / "golden"
PROOFS = Path(__file__).parents[3] / "docs" / "proofs"
FROZEN_TIME = datetime.datetime(2026, 7, 24, 12, 0, tzinfo=datetime.timezone.utc)


def _file_info(
    path: Path,
    *,
    rel_path: str,
    root_label: str = "report-fixture",
    category: str = "source",
    tags: list[str] | None = None,
    ext: str | None = None,
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
        ext=ext if ext is not None else path.suffix,
        content=None,
        inclusion_reason="normal",
    )


def _common_kwargs(files: list[merge.FileInfo] | None = None) -> dict[str, object]:
    return {
        "files": files or [],
        "max_file_bytes": 0,
        "sources": [REPO_ROOT],
        "debug": False,
    }


def _render_kwargs(kwargs: dict[str, object]) -> list[str]:
    with clock.frozen(FROZEN_TIME):
        return list(merge.iter_report_blocks(**kwargs))


def _yaml_meta(report: str) -> dict[str, object]:
    payload = report.split("```yaml\n", 1)[1].split("\n```", 1)[0]
    loaded = yaml.safe_load(payload)
    assert isinstance(loaded, dict)
    return loaded


# ---------------------------------------------------------------------------
# 1. plan-only: all sections verified
# ---------------------------------------------------------------------------
class TestPlanOnlyAllSections:
    """plan_only must produce header, meta, charter, plan; must NOT produce
    structure, index, manifest, or content blocks."""

    def test_plan_only_sections_present_and_absent(self, tmp_path: Path):
        path = tmp_path / "README.md"
        path.write_text("# Hello\n", encoding="utf-8")
        files = [_file_info(path, rel_path="README.md", category="doc")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": True}
            )
        )
        # Present sections
        assert "## Plan" in report
        assert "## Source & Profile" in report
        assert "**Plan Only:** true" in report
        # Absent sections
        assert "## 📁 Structure" not in report
        assert "## 🧾 Manifest" not in report
        assert "<!-- START_OF_CONTENT -->" not in report
        assert "<!-- FILE_START" not in report

    def test_plan_only_meta_yaml_content_present_false(self, tmp_path: Path):
        path = tmp_path / "doc.md"
        path.write_text("content\n", encoding="utf-8")
        files = [_file_info(path, rel_path="doc.md", category="doc")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": True}
            )
        )
        meta = _yaml_meta(report)
        assert meta["merge"]["content_present"] is False
        assert meta["merge"]["content"]["emitted_files"] == 0
        assert meta["merge"]["coverage"]["included_files"] == 0
        assert meta["merge"]["coverage"]["coverage_pct"] == 0.0


# ---------------------------------------------------------------------------
# 2. kein Content-Kontakt (plan_only contact ratio = 0)
# ---------------------------------------------------------------------------
class TestPlanOnlyNoContentContact:
    def test_plan_only_contact_ratio_zero(self, tmp_path: Path):
        path = tmp_path / "code.py"
        path.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(path, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": True}
            )
        )
        meta = _yaml_meta(report)
        # Contact ratio must be 0 in plan-only
        assert meta["merge"]["coverage"]["coverage_pct"] == 0.0
        assert "**Included Content:** 0 files" in report
        assert "**Coverage:** 0/" in report

    def test_plan_only_ep_risk_is_high(self, tmp_path: Path):
        path = tmp_path / "code.py"
        path.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(path, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": True}
            )
        )
        assert "**Risk Level:** high" in report


# ---------------------------------------------------------------------------
# 3. keine toten Links (all internal #links have targets)
# ---------------------------------------------------------------------------
class TestNoDeadLinks:
    def test_all_internal_links_resolve(self, tmp_path: Path):
        path = tmp_path / "code.py"
        path.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(path, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False}
            )
        )
        # Extract all internal links
        internal_links = re.findall(r'\[.*?\]\(#([^)]+)\)', report)
        # Extract all anchors (id="..." or <a id="...">
        defined_anchors = set()
        for m in re.finditer(r'id="([^"]+)"', report):
            defined_anchors.add(m.group(1))
        # Also collect heading anchors from markdown headings
        for m in re.finditer(r'^#{1,6}\s+.*\{#([^}]+)\}', report, re.MULTILINE):
            defined_anchors.add(m.group(1))
        # Every internal link target must be in defined anchors
        for link_target in internal_links:
            assert link_target in defined_anchors, (
                f"dead link #{link_target} not found in anchors"
            )


# ---------------------------------------------------------------------------
# 4. ext exclusion
# ---------------------------------------------------------------------------
class TestExtExclusion:
    def test_ext_filter_removes_non_matching_files(self, tmp_path: Path):
        py = tmp_path / "main.py"
        md = tmp_path / "README.md"
        yml = tmp_path / "ci.yml"
        py.write_text("X = 1\n", encoding="utf-8")
        md.write_text("# README\n", encoding="utf-8")
        yml.write_text("name: ci\n", encoding="utf-8")
        files = [
            _file_info(py, rel_path="main.py"),
            _file_info(md, rel_path="README.md", category="doc"),
            _file_info(yml, rel_path="ci.yml", category="config"),
        ]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False, "ext_filter": [".py"]}
            )
        )
        # .py should be present
        assert "main.py" in report
        # README.md and ci.yml should NOT be in content/manifest
        assert 'FILE_START path="README.md"' not in report
        assert 'FILE_START path="ci.yml"' not in report

    def test_ext_filter_affects_sidecar_counts(self, tmp_path: Path):
        py = tmp_path / "a.py"
        md = tmp_path / "b.md"
        py.write_text("A = 1\n", encoding="utf-8")
        md.write_text("B\n", encoding="utf-8")
        files = [
            _file_info(py, rel_path="a.py"),
            _file_info(md, rel_path="b.md", category="doc"),
        ]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False, "ext_filter": [".py"]}
            )
        )
        meta = _yaml_meta(report)
        # selection.selected_files should only count .py files
        assert meta["merge"]["selection"]["selected_files"] == 1
        assert meta["merge"]["selection"]["text_files"] == 1


# ---------------------------------------------------------------------------
# 5. globale IDs (all file IDs are globally unique)
# ---------------------------------------------------------------------------
class TestGlobalIds:
    def test_all_file_anchors_unique(self, tmp_path: Path):
        files_list = []
        for i in range(5):
            p = tmp_path / f"file{i}.py"
            p.write_text(f"X{i} = {i}\n", encoding="utf-8")
            files_list.append(_file_info(p, rel_path=f"file{i}.py"))
        # Also add same-content files to test hash uniqueness
        for i in range(3):
            p = tmp_path / f"dup{i}.py"
            p.write_text("SAME = 1\n", encoding="utf-8")
            files_list.append(_file_info(p, rel_path=f"dup{i}.py"))
        report = "".join(
            _render_kwargs(
                _common_kwargs(files_list)
                | {"level": "max", "plan_only": False}
            )
        )
        # Collect all anchors from FILE_START comments
        anchors = re.findall(r'file:id="([^"]+)"', report)
        assert len(anchors) == len(set(anchors)), "non-unique file IDs detected"
        assert len(anchors) == len(files_list)


# ---------------------------------------------------------------------------
# 6. slug collisions with identical content produce distinct anchors
# ---------------------------------------------------------------------------
class TestSlugIdenticalCollision:
    def test_identical_content_different_paths_distinct_anchors(self, tmp_path: Path):
        a = tmp_path / "a_b.py"
        b = tmp_path / "a-b.py"
        content = "X = 1\n"
        a.write_text(content, encoding="utf-8")
        b.write_text(content, encoding="utf-8")
        files = [
            _file_info(a, rel_path="a_b.py"),
            _file_info(b, rel_path="a-b.py"),
        ]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False}
            )
        )
        anchors = re.findall(r'file:id="([^"]+)"', report)
        assert len(anchors) == 2
        assert anchors[0] != anchors[1]
        colliding_alias = "file-report-fixture-a-b-py"
        assert f'<a id="{colliding_alias}"></a>' not in report

    def test_same_name_different_roots_distinct_anchors(self, tmp_path: Path):
        root_a = tmp_path / "repoA"
        root_b = tmp_path / "repoB"
        root_a.mkdir()
        root_b.mkdir()
        a = root_a / "code.py"
        b = root_b / "code.py"
        a.write_text("A = 1\n", encoding="utf-8")
        b.write_text("B = 1\n", encoding="utf-8")
        files = [
            _file_info(a, rel_path="code.py", root_label="repoA"),
            _file_info(b, rel_path="code.py", root_label="repoB"),
        ]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False}
            )
        )
        anchors = re.findall(r'file:id="([^"]+)"', report)
        assert len(anchors) == 2
        assert anchors[0] != anchors[1]


# ---------------------------------------------------------------------------
# 7. marker injection full render
# ---------------------------------------------------------------------------
class TestMarkerInjectionFullRender:
    @staticmethod
    def _decode(token: str) -> dict[str, object]:
        padded = token + "=" * (-len(token) % 4)
        payload = base64.urlsafe_b64decode(padded.encode("ascii"))
        loaded = json.loads(payload.decode("utf-8"))
        assert isinstance(loaded, dict)
        return loaded

    def test_machine_markers_are_single_line_and_round_trip_paths(
        self, tmp_path: Path
    ) -> None:
        unusual_paths = [
            'a"b.py',
            "a-->b.py",
            "ümlaut.py",
            " leading.py",
            "trailing.py ",
            "tab\tname.py",
            "carriage\rname.py",
            "line\nname.py",
            "control\x01name.py",
        ]
        for index, rel_path in enumerate(unusual_paths):
            source = tmp_path / f"source-{index}.py"
            source.write_text("X = 1\n", encoding="utf-8")
            file_info = _file_info(source, rel_path="placeholder.py")
            file_info.rel_path = Path(rel_path)
            report = "".join(
                _render_kwargs(
                    _common_kwargs([file_info])
                    | {
                        "level": "max",
                        "plan_only": False,
                        "meta_density": "full",
                    }
                )
            )

            assert report.count("<!-- FILE_START ") == 1
            assert report.count("<!-- FILE_END ") == 1
            start_line = next(
                line for line in report.splitlines() if line.startswith("<!-- FILE_START ")
            )
            end_line = next(
                line for line in report.splitlines() if line.startswith("<!-- FILE_END ")
            )
            file_meta_line = next(
                line for line in report.splitlines() if line.startswith("<!-- file_meta ")
            )
            for marker_line in (start_line, end_line, file_meta_line):
                assert marker_line.count("-->") == 1
                assert not any(ord(char) < 32 or ord(char) == 127 for char in marker_line)

            start_token = re.fullmatch(
                r'<!-- FILE_START path="[^"]*" meta="([A-Za-z0-9_-]+)" -->',
                start_line,
            )
            end_token = re.fullmatch(
                r'<!-- FILE_END path="[^"]*" meta="([A-Za-z0-9_-]+)" -->',
                end_line,
            )
            meta_token = re.fullmatch(
                r'<!-- file_meta meta="([A-Za-z0-9_-]+)" -->',
                file_meta_line,
            )
            assert start_token and end_token and meta_token
            assert self._decode(start_token.group(1))["path"] == rel_path
            assert self._decode(end_token.group(1))["path"] == rel_path
            assert self._decode(meta_token.group(1))["path"] == rel_path


# ---------------------------------------------------------------------------
# 8. tags=None full render path
# ---------------------------------------------------------------------------
class TestTagsNoneFullRender:
    def test_tags_none_renders_safely(self, tmp_path: Path):
        p = tmp_path / "untagged.py"
        p.write_text("VALUE = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="untagged.py", tags=None)]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False}
            )
        )
        assert "untagged.py" in report
        # tags=None must not leak as the literal string "None"
        assert "Tags: None" not in report
        assert "Tag: None" not in report

    def test_tags_none_in_manifest(self, tmp_path: Path):
        p = tmp_path / "untagged.py"
        p.write_text("VALUE = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="untagged.py", tags=None)]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False}
            )
        )
        # In manifest, tags=None should render as "-" not "None"
        manifest_segment = report.split("Manifest")[1] if "Manifest" in report else ""
        assert "Tags: None" not in manifest_segment


# ---------------------------------------------------------------------------
# 9. repeat render does not mutate original FileInfo objects
# ---------------------------------------------------------------------------
class TestRepeatNoMutation:
    def test_two_renders_preserve_original_fields(self, tmp_path: Path):
        p = tmp_path / "code.py"
        p.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="code.py")]
        # Snapshot ALL slots before any render
        original_slot_values = {
            slot: getattr(files[0], slot) for slot in merge.FileInfo.__slots__
        }
        # Render twice with different modes
        _render_kwargs(
            _common_kwargs(files)
            | {"level": "max", "plan_only": False}
        )
        _render_kwargs(
            _common_kwargs(files)
            | {"level": "summary", "plan_only": True}
        )
        # ALL original fields must be unchanged after two renders
        for slot in merge.FileInfo.__slots__:
            assert getattr(files[0], slot) == original_slot_values[slot], (
                f"original FileInfo.{slot} was mutated by render"
            )

    def test_identical_options_produce_byteidentical_output(self, tmp_path: Path):
        p = tmp_path / "code.py"
        p.write_text("X = 1\n", encoding="utf-8")
        files1 = [_file_info(p, rel_path="code.py")]
        files2 = [_file_info(p, rel_path="code.py")]
        kwargs = _common_kwargs() | {"level": "max", "plan_only": False}
        report1 = "".join(_render_kwargs(kwargs | {"files": files1}))
        report2 = "".join(_render_kwargs(kwargs | {"files": files2}))
        assert report1 == report2


# ---------------------------------------------------------------------------
# 10. redactor: quoted/unquoted syntax preservation
# ---------------------------------------------------------------------------
class TestRedactorQuotedUnquoted:
    def test_quoted_api_key_preserves_syntax(self):
        redactor = Redactor()
        text = 'API_KEY = "ABCDEFGHIJKLMNOPQRST12345678"'
        redacted, modified = redactor.redact(text)
        assert modified is True
        assert "ABCDEFGHIJKLMNOPQRST12345678" not in redacted
        # Closing quote must be preserved
        assert redacted.endswith('"')
        # Must be valid Python
        ast.parse(redacted)

    def test_unquoted_api_key_with_dots(self):
        redactor = Redactor()
        text = "api_key = abc.def.ghi.jkl.mno.pqr.stu.vwx.yz1234"
        redacted, modified = redactor.redact(text)
        assert modified is True
        assert "abc.def.ghi.jkl.mno" not in redacted

    def test_unquoted_api_key_with_slashes(self):
        redactor = Redactor()
        text = "secret_key = abc/def/ghi/jkl/mno/pqr/stu/vwx/yz1234"
        redacted, modified = redactor.redact(text)
        assert modified is True

    def test_password_with_special_chars(self):
        redactor = Redactor()
        text = 'password = "p@ss+w0rd/123=ok"'
        redacted, modified = redactor.redact(text)
        assert modified is True
        assert "p@ss+w0rd" not in redacted
        ast.parse(redacted)

    def test_normal_identifier_not_false_positive(self):
        redactor = Redactor()
        # A normal variable assignment with a long value should NOT be redacted
        # by key/password patterns (no key= or password= prefix)
        text = "result = some_function_call_with_long_name_and_many_args"
        redacted, _ = redactor.redact(text)
        assert "result" in redacted


# ---------------------------------------------------------------------------
# 11. wrong before identity (benchmark validation)
# ---------------------------------------------------------------------------
class TestBenchmarkBeforeIdentity:
    def test_validate_before_fails_on_mismatch(self, tmp_path: Path):
        from scripts.benchmarks.compare_repoground_core_paths import (
            _validate_before_content_binding,
        )
        # Create a fake before_root with a git repo but wrong commit
        fake_root = tmp_path / "fake"
        fake_root.mkdir()
        # Initialize a minimal git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=fake_root, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=fake_root, capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "test"],
            cwd=fake_root, capture_output=True, check=False,
        )
        # Create and commit a file
        script_dir = fake_root / "scripts" / "benchmarks"
        script_dir.mkdir(parents=True)
        (script_dir / "repoground_core_paths.py").write_text("# fake\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."], cwd=fake_root, capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=fake_root, capture_output=True, check=False,
        )
        result = _validate_before_content_binding(
            fake_root,
            "0000000000000000000000000000000000000000",
            "0000000000000000000000000000000000000000",
            "scripts/benchmarks/repoground_core_paths.py",
        )
        assert result["status"] == "fail"
        assert len(result["findings"]) > 0

    def test_validate_before_fails_on_dirty(self, tmp_path: Path):
        from scripts.benchmarks.compare_repoground_core_paths import (
            _validate_before_content_binding,
        )
        fake_root = tmp_path / "fake"
        fake_root.mkdir()
        import subprocess
        subprocess.run(["git", "init"], cwd=fake_root, capture_output=True, check=False)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=fake_root, capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "test"],
            cwd=fake_root, capture_output=True, check=False,
        )
        script_dir = fake_root / "scripts" / "benchmarks"
        script_dir.mkdir(parents=True)
        (script_dir / "repoground_core_paths.py").write_text("# fake\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."], cwd=fake_root, capture_output=True, check=False,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=fake_root, capture_output=True, check=False,
        )
        # Get the committed tree hash
        tree_hash = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=fake_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        commit_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=fake_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        # Make worktree dirty
        (fake_root / "dirty.txt").write_text("dirty", encoding="utf-8")
        result = _validate_before_content_binding(
            fake_root, commit_hash, tree_hash,
            "scripts/benchmarks/repoground_core_paths.py",
        )
        assert result["status"] == "fail"
        assert any("dirty" in f for f in result["findings"])


# ---------------------------------------------------------------------------
# 12. shallow no false PASS
# ---------------------------------------------------------------------------
class TestShallowNoFalsePass:
    def test_evidence_test_uses_pytest_skip(self):
        """Verify the evidence contract test uses pytest.skip for shallow clones,
        not silent return (which would produce a PASS)."""
        from merger.repoground.tests.test_t009_evidence_contract import (
            _assert_git_object_available_or_fail_closed,
        )
        import inspect
        source = inspect.getsource(_assert_git_object_available_or_fail_closed)
        assert "pytest.skip" in source, (
            "shallow clone handling must use pytest.skip, not silent return"
        )
        assert "return" not in source.split("pytest.skip")[0].split("shallow")[-1], (
            "no silent return before pytest.skip for shallow clone"
        )


# ---------------------------------------------------------------------------
# 13. missing Evidence/Receipt
# ---------------------------------------------------------------------------
class TestMissingEvidenceReceipt:
    def test_delivery_v2_exists_and_has_status_pending(self):
        v2_path = PROOFS / "repoground-legacy-t009-delivery.evidence-v2.json"
        assert v2_path.exists(), "corrective v2 evidence file must exist"
        payload = json.loads(v2_path.read_text(encoding="utf-8"))
        assert payload["status"] == "pending"
        assert payload["verification_status"] == "pass"
        assert payload["delivery_status"] == "pending"
        assert payload.get("_corrective") is True

    def test_original_evidence_not_modified(self):
        """The original delivery evidence must remain unchanged (historical truth).
        The original has status=pass with no delivery_status field — the
        historical contradiction is preserved as-is, NOT patched."""
        original = PROOFS / "repoground-legacy-t009-delivery.evidence.json"
        assert original.exists()
        payload = json.loads(original.read_text(encoding="utf-8"))
        assert payload["status"] == "pass"
        assert "delivery_status" not in payload, (
            "original evidence must not have delivery_status; "
            "use the corrective v2 file for corrected status"
        )


# ---------------------------------------------------------------------------
# 14. top status pending
# ---------------------------------------------------------------------------
class TestTopStatusPending:
    def test_v2_top_status_pending(self):
        v2_path = PROOFS / "repoground-legacy-t009-delivery.evidence-v2.json"
        payload = json.loads(v2_path.read_text(encoding="utf-8"))
        assert payload["status"] == "pending", (
            "corrective v2 top-level status must be pending until merge/runtime"
        )


# ---------------------------------------------------------------------------
# 15. two-revision differential
# ---------------------------------------------------------------------------
class TestTwoRevisionDifferential:
    def test_target_goldens_do_not_claim_historical_parity(self) -> None:
        contract = json.loads(
            (GOLDEN_ROOT / "differential_scenarios.json").read_text(encoding="utf-8")
        )
        assert contract["purpose"] == "target_revision_regression_golden"
        assert contract["does_not_establish"] == ["historical_output_parity"]
        assert contract["historical_comparison_tool"] == (
            "scripts/ci/compare_report_renderer_revisions.py"
        )

    def test_real_comparator_uses_distinct_revisions_and_allowlist(self) -> None:
        from merger.repoground.tests.test_t009_evidence_contract import (
            _assert_git_object_available_or_fail_closed,
        )
        from scripts.ci.compare_report_renderer_revisions import compare_revisions

        root = Path(__file__).parents[3]
        base = "2afc2836fa1a49a593c7b57eda43086844e8fb2b"
        _assert_git_object_available_or_fail_closed(f"{base}^{{commit}}")
        result = compare_revisions(root, base, root)
        assert result["base"]["commit"] != result["target"]["commit"] or result["target"]["dirty"]
        assert result["base"]["module_sha256"] != result["target"]["module_sha256"]
        assert result["intentional_corrections"]
        assert result["unapproved_differences"] == {}

    def test_plan_only_repo_snapshot_shows_zero_emitted(self, tmp_path: Path):
        p = tmp_path / "code.py"
        p.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": True}
            )
        )
        assert "0 with content" in report


# ---------------------------------------------------------------------------
# 16. structured_warnings in YAML meta
# ---------------------------------------------------------------------------
class TestStructuredWarnings:
    def test_plan_only_warning_in_yaml_meta(self, tmp_path: Path):
        """Plan-only mode must emit a plan_only_mode warning in diagnostics."""
        p = tmp_path / "code.py"
        p.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": True}
            )
        )
        meta = _yaml_meta(report)
        assert "diagnostics" in meta
        warnings = meta["diagnostics"]["warnings"]
        codes = [w["code"] for w in warnings]
        assert "plan_only_mode" in codes

    def test_filter_warning_in_yaml_meta(self, tmp_path: Path):
        """Active filters must emit a scope_filter_active warning."""
        p = tmp_path / "code.py"
        p.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False, "path_filter": "src/"}
            )
        )
        meta = _yaml_meta(report)
        assert "diagnostics" in meta
        warnings = meta["diagnostics"]["warnings"]
        codes = [w["code"] for w in warnings]
        assert "scope_filter_active" in codes

    def test_no_warnings_when_no_conditions(self, tmp_path: Path):
        """No warnings when level=max, no filters, not plan_only."""
        p = tmp_path / "code.py"
        p.write_text("X = 1\n", encoding="utf-8")
        files = [_file_info(p, rel_path="code.py")]
        report = "".join(
            _render_kwargs(
                _common_kwargs(files)
                | {"level": "max", "plan_only": False}
            )
        )
        meta = _yaml_meta(report)
        assert "diagnostics" not in meta
