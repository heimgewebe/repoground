from __future__ import annotations

from pathlib import Path
from typing import Any

from merger.repoground.architecture.call_graph import extract_python_calls


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _single(
    calls: list[dict[str, Any]],
    expression: str,
    *,
    caller: str | None = None,
) -> dict[str, Any]:
    matches = [
        call
        for call in calls
        if call["callee_expression"] == expression
        and (caller is None or call["caller_qualified_name"] == caller)
    ]
    assert len(matches) == 1, matches
    return matches[0]


def _assert_s1_precision(
    calls: list[dict[str, Any]],
    expected: dict[str, tuple[str, str]],
) -> None:
    by_reason: dict[str, list[bool]] = {}
    for expression, (reason, target_id) in expected.items():
        call = _single(calls, expression)
        assert call["evidence_level"] == "S1"
        assert call["resolution_status"] == "resolved"
        assert call["resolution_reason"] == reason
        correct = call["resolved_target_ids"] == [target_id]
        by_reason.setdefault(reason, []).append(correct)
    assert by_reason
    for outcomes in by_reason.values():
        precision = sum(outcomes) / len(outcomes)
        assert precision == 1.0
        assert precision >= 0.97


def test_promoted_reason_classes_have_fixed_goldset_precision(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "model.py",
        """class Base:
    def target(self):
        return 1


class Child(Base):
    def inherited(self):
        return self.target()

    def aliased(self):
        receiver = self
        return receiver.target()

    def via_super(self):
        return super().target()
""",
    )
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/impl.py",
        """def target():
    return 1
""",
    )
    _write(
        tmp_path,
        "pkg/reexport.py",
        "from pkg.impl import target\n",
    )
    _write(
        tmp_path,
        "transitive.py",
        "from pkg.reexport import target\ntarget()\n",
    )

    calls, skipped_count, skipped_errors = extract_python_calls(tmp_path)
    assert skipped_count == 0
    assert skipped_errors == []
    _assert_s1_precision(
        calls,
        {
            "self.target": (
                "self_single_inheritance_method",
                "py:model.py:function:Base.target",
            ),
            "receiver.target": (
                "receiver_alias_single_inheritance_method",
                "py:model.py:function:Base.target",
            ),
            "super().target": (
                "super_single_inheritance_method",
                "py:model.py:function:Base.target",
            ),
            "target": (
                "transitive_imported_internal_name",
                "py:pkg:impl.py:function:target",
            ),
        },
    )


def test_mixin_precedence_remains_explicit_s0(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "mixins.py",
        """class Left:
    def target(self):
        return 1


class Right:
    def target(self):
        return 2


class Combined(Left, Right):
    def call(self):
        return self.target()
""",
    )

    calls, skipped_count, skipped_errors = extract_python_calls(tmp_path)
    assert skipped_count == 0
    assert skipped_errors == []
    call = _single(calls, "self.target")
    assert call["evidence_level"] == "S0"
    assert call["resolution_status"] == "unresolved"
    assert call["resolution_reason"] == "mixin_or_multiple_inheritance_not_promoted"
    assert call["resolved_target_ids"] == []


def test_star_import_and_module_getattr_remain_explicit_s0(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py", "")
    _write(
        tmp_path,
        "pkg/star.py",
        """__all__ = ["exported"]


def exported():
    return 1
""",
    )
    _write(
        tmp_path,
        "pkg/dynamic.py",
        """def __getattr__(name):
    return lambda: name
""",
    )
    _write(
        tmp_path,
        "star_user.py",
        "from pkg.star import *\nexported()\n",
    )
    _write(
        tmp_path,
        "dynamic_user.py",
        "import pkg.dynamic as dyn\ndyn.missing()\n",
    )

    calls, skipped_count, skipped_errors = extract_python_calls(tmp_path)
    assert skipped_count == 0
    assert skipped_errors == []
    star = _single(calls, "exported")
    assert star["evidence_level"] == "S0"
    assert star["resolution_reason"] == "star_import_unresolved"
    assert star["resolved_target_ids"] == []
    dynamic = _single(calls, "dyn.missing")
    assert dynamic["evidence_level"] == "S0"
    assert dynamic["resolution_reason"] == "module_alias_call_module_getattr_dispatch"
    assert dynamic["resolved_target_ids"] == []


def test_alias_rebinding_and_monkey_patch_do_not_promote(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "dynamic.py",
        """class Base:
    def target(self):
        return 1


class Child(Base):
    def rebound(self):
        receiver = self
        receiver = object()
        return receiver.target()


Child.target = lambda self: 2
Child().target()
""",
    )

    calls, skipped_count, skipped_errors = extract_python_calls(tmp_path)
    assert skipped_count == 0
    assert skipped_errors == []
    rebound = _single(calls, "receiver.target")
    assert rebound["evidence_level"] == "S0"
    assert rebound["resolution_reason"] == "attribute_root_lexically_shadowed_name"
    assert rebound["resolved_target_ids"] == []
    monkey_patch = _single(calls, "Child().target")
    assert monkey_patch["evidence_level"] == "S0"
    assert monkey_patch["resolution_reason"] == "dynamic_callee_expression"
    assert monkey_patch["resolved_target_ids"] == []
