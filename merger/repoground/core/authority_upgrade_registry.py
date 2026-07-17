"""Authority-Upgrade Registry — Governance Track C, step C2.9 (experimental).

The C2.7 marker-gated AST lint (``anti_hallucination_ast_lint.py``) detects when a
*declared* low-authority value flows into a *declared* canonical sink (rules
L1/L2/L4). The C2.8 adoption pilot showed that some of those flows are **not bugs**
but **legitimate, reviewed authority upgrades** — most prominently the four
``derived_projection`` ``md_parts`` values that flow into ``resolve_canonical_md``
in ``core/merge.py``: that function *is* the canonical-selection step, so the
crossing is its purpose, not an accidental escalation.

Before C2.9 the lint could not tell an *intentional upgrade* apart from a *real*
L4 finding. This module adds the smallest machine-readable mechanism to declare
the intentional ones:

* :class:`AuthorityUpgrade` — one declared, allowed upgrade
  (``source_authority`` → ``target_authority`` at a named ``sink``, for a given
  ``rule``, with a mandatory ``reason``; an optional ``symbol`` narrows the
  declaration to a single variable name).
* :data:`AUTHORITY_UPGRADE_REGISTRY` — the (tiny) set of declared upgrades.
* :func:`classify_findings` — partitions raw AST-lint findings into *real*
  warnings (no declaration matches) and :class:`DeclaredUpgrade` records
  (a declaration matches).

**Not a suppression mechanism.** Detection is unchanged: the AST lint still fires
on every declared low-authority → canonical flow. The registry only *reclassifies*
a fired detection as a declared, human-reviewed upgrade — and that reclassification
stays **visible** in the report (``declared_upgrades`` + the full
``authority_upgrade_registry`` are emitted). The smoke detector is not switched
off; the alarm is annotated with a reviewed, machine-readable reason.

**Not silently lenient.** Every entry is validated (:func:`validate_registry`): an
unknown rule, a source class that cannot produce that rule, a non-canonical
target, an empty sink, or a missing/token ``reason`` raises rather than being
quietly accepted. A finding with *no* matching declaration stays a warning.

Out of scope (unchanged from C2.7/C2.8): no runtime annotation (C4 stays open),
no type inference, no dataflow/alias analysis, no contract/schema mutation, no new
blocking CI gate. A declared upgrade records *reviewed intent*; it does **not**
prove the upgrade is runtime-correct.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

from .anti_hallucination_ast_lint import (
    CANONICAL_AUTHORITY,
    ESCALATION_LIKE_AUTHORITIES,
    L1_GATING_AUTHORITIES,
    NAVIGATION_LIKE_AUTHORITIES,
    RULES_COVERED,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import cycle
    from .anti_hallucination_ast_lint import AstLintFinding

# Which low-authority classes can legitimately produce each AST-lint rule. A
# declaration whose (rule, source_authority) pair is impossible can never match a
# real finding, so it is rejected rather than accepted as a silent no-op.
RULE_SOURCE_CLASSES: dict[str, frozenset[str]] = {
    "L1": L1_GATING_AUTHORITIES,
    "L2": ESCALATION_LIKE_AUTHORITIES,
    "L4": NAVIGATION_LIKE_AUTHORITIES,
}

# Minimum substantive length for a rationale. Empty / token reasons ("ok", "n/a")
# are not accepted: a declared upgrade must carry an auditable justification.
_MIN_REASON_LEN = 12


@dataclass(frozen=True)
class AuthorityUpgrade:
    """One declared, allowed authority upgrade.

    A finding is treated as a declared upgrade (not a warning) when its rule,
    source authority, sink, and file suffix match this entry. ``symbol`` is
    optional: ``None`` matches any variable name, a concrete value narrows the
    declaration to that single name.
    """

    rule: str
    source_authority: str
    target_authority: str
    sink: str
    file_suffix: str
    reason: str
    symbol: str | None = None

    def validation_errors(self) -> list[str]:
        """Return human-readable reasons this entry is invalid (empty == valid)."""
        errors: list[str] = []

        allowed_sources = RULE_SOURCE_CLASSES.get(self.rule)
        if allowed_sources is None:
            errors.append(
                f"rule {self.rule!r} is not one of the covered AST rules "
                f"{tuple(RULES_COVERED)}"
            )
        elif self.source_authority not in allowed_sources:
            errors.append(
                f"source_authority {self.source_authority!r} can never produce a "
                f"{self.rule} finding (expected one of {sorted(allowed_sources)})"
            )

        if self.target_authority != CANONICAL_AUTHORITY:
            errors.append(
                f"target_authority {self.target_authority!r} must be "
                f"{CANONICAL_AUTHORITY!r} (the only sink authority the AST lint models)"
            )

        if not self.sink or not self.sink.strip():
            errors.append("sink must be a non-empty canonical-sink name")

        if not self.file_suffix or not self.file_suffix.strip():
            errors.append("file_suffix must be a non-empty file constraint")

        if self.symbol is not None and not self.symbol.strip():
            errors.append(
                "symbol, when set, must be a non-empty name (use None to match any)"
            )

        if len((self.reason or "").strip()) < _MIN_REASON_LEN:
            errors.append(
                "reason must be a substantive rationale "
                f"(>= {_MIN_REASON_LEN} chars); empty/token reasons are not accepted"
            )

        return errors

    def matches(self, finding: "AstLintFinding") -> bool:
        """Whether ``finding`` is an instance of this declared upgrade."""
        return (
            self.rule == finding.rule
            and self.source_authority == finding.authority
            and self.sink == finding.sink
            and finding.file.endswith(self.file_suffix)
            and (self.symbol is None or self.symbol == finding.symbol)
        )

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "source_authority": self.source_authority,
            "target_authority": self.target_authority,
            "sink": self.sink,
            "file_suffix": self.file_suffix,
            "symbol": self.symbol,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DeclaredUpgrade:
    """A raw AST-lint finding that matched a declared :class:`AuthorityUpgrade`.

    Carries both the original detection and the declaration that allows it, so the
    report can show *what* was detected and *why* it is allowed — without
    suppressing the information.
    """

    finding: "AstLintFinding"
    declaration: AuthorityUpgrade

    def to_dict(self) -> dict:
        return {
            "status": "declared_upgrade",
            "rule": self.finding.rule,
            "file": self.finding.file,
            "line": self.finding.line,
            "symbol": self.finding.symbol,
            "source_authority": self.declaration.source_authority,
            "target_authority": self.declaration.target_authority,
            "sink": self.declaration.sink,
            "reason": self.declaration.reason,
            "note": (
                "intentional authority upgrade: detected by the AST lint and "
                "explicitly declared in the authority-upgrade registry (not "
                "suppressed). The detector still fired; the registry records the "
                "human-reviewed intent. A declaration is reviewed intent, not a "
                "runtime-correctness proof."
            ),
        }


# --- The registry -----------------------------------------------------------

# C2.9 v0: the single class of intentional upgrade revealed by the C2.8 pilot.
# ``resolve_canonical_md()`` is the canonical-selection function in the bundle
# pipeline; passing the derived_projection list of generated markdown paths into
# it IS the deliberate derived -> canonical upgrade, not an accidental escalation.
# File-scoped + sink-scoped (no ``symbol``): this declaration applies only to
# merge.py call sites where derived_projection flows into resolve_canonical_md.
AUTHORITY_UPGRADE_REGISTRY: tuple[AuthorityUpgrade, ...] = (
    AuthorityUpgrade(
        rule="L4",
        source_authority="derived_projection",
        target_authority=CANONICAL_AUTHORITY,
        sink="resolve_canonical_md",
        file_suffix="merger/repoground/core/merge.py",
        reason=(
            "resolve_canonical_md() is the canonical-selection step: by bundle "
            "contract it selects md_parts[0] as the single canonical markdown "
            "source of truth. Passing the derived_projection list of generated md "
            "paths into it IS the deliberate, reviewed authority upgrade "
            "(derived_projection -> canonical_content), not an accidental "
            "escalation. See docs/proofs/"
            "authority-risk-class-c2-9-authority-upgrade-registry-proof.md."
        ),
    ),
)


# --- Validation & matching --------------------------------------------------


def validate_registry(
    registry: Iterable[AuthorityUpgrade] = AUTHORITY_UPGRADE_REGISTRY,
) -> list[str]:
    """Return all validation errors across ``registry`` (empty == all valid)."""
    errors: list[str] = []
    for index, entry in enumerate(registry):
        if not isinstance(entry, AuthorityUpgrade):
            errors.append(
                f"registry[{index}] ({type(entry).__name__}): "
                "entry must be an AuthorityUpgrade"
            )
            continue
        for problem in entry.validation_errors():
            errors.append(f"registry[{index}] ({entry.sink!r}): {problem}")
    return errors


def _ensure_valid(registry: Sequence[AuthorityUpgrade]) -> None:
    errors = validate_registry(registry)
    if errors:
        raise ValueError(
            "invalid authority-upgrade registry — refusing to silently accept "
            "malformed declarations: " + "; ".join(errors)
        )


def match_upgrade(
    finding: "AstLintFinding",
    *,
    registry: Sequence[AuthorityUpgrade] = AUTHORITY_UPGRADE_REGISTRY,
) -> AuthorityUpgrade | None:
    """Return the declared upgrade that allows ``finding``, or ``None``.

    Raises ``ValueError`` if any registry entry is malformed (never silently
    accepted).
    """
    _ensure_valid(registry)
    for entry in registry:
        if entry.matches(finding):
            return entry
    return None


def classify_findings(
    findings: Iterable["AstLintFinding"],
    *,
    registry: Sequence[AuthorityUpgrade] = AUTHORITY_UPGRADE_REGISTRY,
) -> tuple[list["AstLintFinding"], list[DeclaredUpgrade]]:
    """Partition ``findings`` into ``(real_warnings, declared_upgrades)``.

    A finding with no matching declaration is a real warning; one that matches a
    (valid) declaration becomes a :class:`DeclaredUpgrade`. Raises ``ValueError``
    on a malformed registry.
    """
    _ensure_valid(registry)
    real: list["AstLintFinding"] = []
    declared: list[DeclaredUpgrade] = []
    for finding in findings:
        match = next((e for e in registry if e.matches(finding)), None)
        if match is None:
            real.append(finding)
        else:
            declared.append(DeclaredUpgrade(finding=finding, declaration=match))
    return real, declared
