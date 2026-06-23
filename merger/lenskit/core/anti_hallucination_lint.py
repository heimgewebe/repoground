"""Anti-Hallucination Contract Lint — Governance Track C, step C2.4.

Contract-static subset of the C1 anti-hallucination lint rules
(``docs/blueprints/lenskit-authority-risk-matrix.md`` §6). This module is the
"Vorbereitung der Lint-Regeln als spätere CI-Stufe" called out by the C2a gap
audit (``docs/proofs/authority-contract-gap-audit.md`` §8): it implements the
two rules that are *mechanically decidable from contract schemas alone* and that
are already clean on the current contract set, so the lint is a green,
drift-catching CI gate without forcing premature contract migration.

Implemented (blocking):

* **L3 — Missing Inference Boundary**: a contract whose *root* object
  self-declares an authority class that warns-but-does-not-prove
  (``diagnostic_signal``, ``runtime_observation``, or the
  ``agent_context_projection`` session authority) MUST declare a machine-readable
  boundary declaration at the root (``does_not_prove`` / ``does_not_mean`` / ``does_not_establish`` arrays,
  or a ``claim_boundaries`` object). Known, deliberately deferred gaps are tracked in
  :data:`DEFERRED_BOUNDARY_CONTRACTS` and reported as non-blocking ``deferred``
  findings rather than silently ignored or force-fixed.

* **L5 — Unsupported Truth Language**: forbidden truth-asserting *property names*
  (e.g. ``understanding_score``, ``agent_safe``, ``proven``) may not appear as
  schema property keys, and forbidden truth tokens (e.g. ``proven``,
  ``verified``) may not appear as ``enum`` or ``const`` values of verdict-like fields.
  Exact-match only — never substring — and disclaimer-array *values*
  (``does_not_*`` / ``*_inferences``) are never scanned, because they
  legitimately *name* the forbidden inferences as negatives.

Out of scope for the contract-static C2.4 stage (documented, not implemented):

* **L1 / L2 / L4** — require Python AST / code-path static analysis (high
  false-positive surface per blueprint §6); a later AST lint stage.
* **L6** — Export-Risk = export-gate integration = Governance Track C5.

This module performs **no** runtime annotation, **no** contract mutation, and
**no** claim-truth evaluation. The lint report is itself a ``diagnostic_signal``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Mapping

# --- Stabilized C2.4 lint vocabulary (deferred from C2.3) -------------------

# L5 — forbidden as PROPERTY NAMES (exact key match). These names assert a
# truth/safety/completeness verdict that no Lenskit artifact below
# ``canonical_content`` can establish (blueprint §6 L5). Status tokens such as
# ``complete`` / ``true`` / ``false`` / ``green`` are deliberately NOT here: they
# are only forbidden as *verdict values* (handled separately) and otherwise
# appear legitimately as status/enum tokens (e.g. ``projection_status: complete``).
FORBIDDEN_TRUTH_PROPERTY_NAMES: frozenset[str] = frozenset(
    {
        "understanding_health",
        "understanding_score",
        "context_score",
        "agent_safe",
        "agent_ready",
        "proven",
        "supported",
        "unsupported",
        "verified",
        "correct",
    }
)

# L5 — forbidden as ``enum``/``const`` VALUES of verdict-like fields (exact match). These
# verdict tokens would turn a diagnostic field into an implicit truth verdict.
FORBIDDEN_VERDICT_VALUES: frozenset[str] = frozenset(
    {
        "proven",
        "supported",
        "unsupported",
        "verified",
        "safe",
        "unsafe",
        "green",
        "yellow",
        "red",
    }
)

# L3 — authority self-declarations that REQUIRE a machine-readable boundary.
BOUNDARY_REQUIRING_AUTHORITIES: frozenset[str] = frozenset(
    {
        "diagnostic_signal",
        "runtime_observation",
        "agent_context_projection",
    }
)
AUTHORITY_FIELD_NAMES: tuple[str, ...] = ("authority", "session_authority")
BOUNDARY_ARRAY_PROPERTY_NAMES: frozenset[str] = frozenset(
    {
        "does_not_prove",
        "does_not_mean",
        "does_not_establish",
    }
)
BOUNDARY_OBJECT_PROPERTY_NAMES: frozenset[str] = frozenset(
    {"claim_boundaries"}
)
BOUNDARY_PROPERTY_NAMES: frozenset[str] = (
    BOUNDARY_ARRAY_PROPERTY_NAMES | BOUNDARY_OBJECT_PROPERTY_NAMES
)

# L3 — explicitly deferred contracts: they self-declare a boundary-requiring
# authority but predate boundary normalization. Tracked here (not silently
# skipped, not force-migrated) so the gap is honest rather than ignored, and
# :func:`audit_deferral_registry` guards the list against rot.
#
# Currently empty: the sole former entry — ``retrieval-eval-diagnostics.v1`` —
# was resolved by the C2.6 boundary-normalizing follow-up that gave the contract
# a required root ``does_not_prove`` boundary (and producer emission). The mechanism
# is kept for any future contract that must be deferred with a documented rationale.
DEFERRED_BOUNDARY_CONTRACTS: dict[str, str] = {}

# Rules documented as out-of-scope for the contract-static C2.4 stage.
OUT_OF_SCOPE_RULES: dict[str, str] = {
    "L1": "forbidden semantic upgrades — requires Python AST / code-path analysis (future AST lint stage)",
    "L2": "authority escalation detection — requires interface-type static analysis (future AST lint stage)",
    "L4": "derived artifact misuse — requires call-path analysis (future AST lint stage)",
    "L6": "export-risk violations — export-gate integration is Governance Track C5",
}

ENFORCED_RULES: tuple[str, ...] = ("L3", "L5")


def _is_verdict_field(name: str) -> bool:
    """Whether ``name`` denotes a verdict-like field whose enum values are
    subject to the L5 verdict-value check."""
    return name == "verdict" or name == "status" or name.endswith("_verdict")


# --- Findings & report ------------------------------------------------------


@dataclass(frozen=True)
class LintFinding:
    """A single lint finding.

    ``severity`` is ``"error"`` (blocking) or ``"deferred"`` (tracked,
    non-blocking — a known gap with a documented rationale).
    """

    rule: str
    severity: str
    contract: str
    location: str
    message: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "contract": self.contract,
            "location": self.location,
            "message": self.message,
        }


@dataclass
class LintReport:
    """Structured result of an anti-hallucination contract lint run.

    The report is itself a ``diagnostic_signal``: a clean run does not prove the
    contracts are *truthful*, only that the contract-static rules found no
    forbidden truth-language and no un-deferred missing boundary.
    """

    contracts_scanned: int
    findings: list[LintFinding] = field(default_factory=list)  # blocking errors
    deferred: list[LintFinding] = field(default_factory=list)  # tracked, non-blocking

    @property
    def status(self) -> str:
        return "fail" if self.findings else "pass"

    @property
    def error_count(self) -> int:
        return len(self.findings)

    @property
    def deferred_count(self) -> int:
        return len(self.deferred)

    def to_dict(self) -> dict:
        return {
            "kind": "lenskit.anti_hallucination_lint",
            "version": "1.0",
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "status": self.status,
            "contracts_scanned": self.contracts_scanned,
            "error_count": self.error_count,
            "deferred_count": self.deferred_count,
            "rules_enforced": list(ENFORCED_RULES),
            "rules_out_of_scope": dict(OUT_OF_SCOPE_RULES),
            "findings": [f.to_dict() for f in self.findings],
            "deferred": [f.to_dict() for f in self.deferred],
            "does_not_mean": [
                "contract_lint_pass_does_not_prove_artifacts_are_truthful",
                "absence_of_finding_does_not_prove_absence_of_drift",
                "lint_is_contract_static_not_runtime_or_ast",
            ],
        }


# --- Schema traversal -------------------------------------------------------


def _walk_dict_nodes(node: object) -> Iterator[dict]:
    """Yield every ``dict`` node in a parsed JSON-Schema tree (depth-first)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_dict_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_dict_nodes(item)


def _root_properties(schema: object) -> dict:
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            return props
    return {}


# --- L5: Unsupported Truth Language -----------------------------------------


def _check_l5(schema: object, contract_name: str) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for node in _walk_dict_nodes(schema):
        props = node.get("properties")
        if not isinstance(props, dict):
            continue

        for pname, psub in props.items():
            if pname in FORBIDDEN_TRUTH_PROPERTY_NAMES:
                findings.append(
                    LintFinding(
                        rule="L5",
                        severity="error",
                        contract=contract_name,
                        location=f"properties.{pname}",
                        message=(
                            f"forbidden truth-language property name '{pname}': asserts a "
                            f"truth/safety/completeness verdict that no artifact below "
                            f"canonical_content may establish (blueprint §6 L5)."
                        ),
                    )
                )

            if _is_verdict_field(pname) and isinstance(psub, dict):
                for value in _verdict_values(psub):
                    if value in FORBIDDEN_VERDICT_VALUES:
                        findings.append(
                            LintFinding(
                                rule="L5",
                                severity="error",
                                contract=contract_name,
                                location=f"properties.{pname}",
                                message=(
                                    f"forbidden verdict value '{value}' in verdict-like "
                                    f"field '{pname}': turns a diagnostic field into an "
                                    f"implicit truth verdict (blueprint §6 L5)."
                                ),
                            )
                        )

    return findings


def _verdict_values(field_schema: dict) -> Iterator[str]:
    """Yield string verdict values from a verdict field schema.

    Covers direct and composed ``const`` / ``enum`` declarations, including
    nested ``oneOf`` / ``anyOf`` / ``allOf`` branches and array ``items``.
    Non-string values are ignored because L5 only governs exact forbidden
    truth-language tokens.
    """
    yield from _schema_const_enum_values(field_schema)


def _schema_const_enum_values(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        const = node.get("const")
        if isinstance(const, str):
            yield const

        enum = node.get("enum")
        if isinstance(enum, list):
            yield from (value for value in enum if isinstance(value, str))

        for value in node.values():
            yield from _schema_const_enum_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_const_enum_values(item)


# --- L3: Missing Inference Boundary -----------------------------------------


def _self_declared_authority(schema: object) -> tuple[str | None, str | None]:
    """Return ``(field_name, const_value)`` when the *root* object self-declares a
    boundary-requiring authority via an ``authority`` / ``session_authority``
    const; otherwise ``(None, None)``.

    Only the root declaration counts: ``bundle-manifest.v1`` assigns authority to
    *other* artifacts per-role (nested) and is therefore correctly excluded — it
    is a registry, not a self-declaring diagnostic artifact.
    """
    props = _root_properties(schema)
    for fname in AUTHORITY_FIELD_NAMES:
        fdef = props.get(fname)
        if isinstance(fdef, dict):
            const = fdef.get("const")
            if const in BOUNDARY_REQUIRING_AUTHORITIES:
                return fname, const
    return None, None


def _schema_declares_type(schema_node: object, expected_type: str) -> bool:
    if not isinstance(schema_node, dict):
        return False
    declared = schema_node.get("type")
    return declared == expected_type or (
        isinstance(declared, list) and expected_type in declared
    )


_LOCAL_DEFINITION_PREFIX = "#/definitions/"


def _resolve_schema_node(schema: object, node: object) -> object:
    """Resolve one direct local Draft-07 definitions ref for boundary inspection.

    Unsupported or malformed refs are returned unchanged so the normal
    boundary-type check fails closed instead of crashing.
    """
    if not isinstance(schema, dict) or not isinstance(node, dict):
        return node

    ref_path = node.get("$ref")
    if not isinstance(ref_path, str):
        return node

    if not ref_path.startswith(_LOCAL_DEFINITION_PREFIX):
        return node

    definition_name = ref_path[len(_LOCAL_DEFINITION_PREFIX) :]
    if not definition_name or "/" in definition_name:
        return node

    definitions = schema.get("definitions")
    if not isinstance(definitions, dict):
        return node

    resolved = definitions.get(definition_name)
    return resolved if isinstance(resolved, dict) else node


def _has_root_boundary(schema: object) -> bool:
    props = _root_properties(schema)

    for name in BOUNDARY_ARRAY_PROPERTY_NAMES:
        if _schema_declares_type(_resolve_schema_node(schema, props.get(name)), "array"):
            return True

    for name in BOUNDARY_OBJECT_PROPERTY_NAMES:
        if _schema_declares_type(_resolve_schema_node(schema, props.get(name)), "object"):
            return True

    return False


def _check_l3(schema: object, contract_name: str) -> list[LintFinding]:
    fname, const = _self_declared_authority(schema)
    if const is None:
        return []
    if _has_root_boundary(schema):
        return []

    deferral_reason = DEFERRED_BOUNDARY_CONTRACTS.get(contract_name)
    if deferral_reason is not None:
        return [
            LintFinding(
                rule="L3",
                severity="deferred",
                contract=contract_name,
                location=f"root.{fname}",
                message=(
                    f"self-declares {fname}={const} without a root boundary array; "
                    f"deferred: {deferral_reason}"
                ),
            )
        ]

    boundary_names = "/".join(sorted(BOUNDARY_PROPERTY_NAMES))
    return [
        LintFinding(
            rule="L3",
            severity="error",
            contract=contract_name,
            location=f"root.{fname}",
            message=(
                f"self-declares {fname}={const} (boundary-requiring authority) but declares "
                f"no valid root boundary declaration ({boundary_names}). Add a "
                f"does_not_prove / does_not_mean / does_not_establish array or a claim_boundaries object, "
                f"or register an explicit deferral with rationale in "
                f"DEFERRED_BOUNDARY_CONTRACTS."
            ),
        )
    ]


# --- Public API -------------------------------------------------------------


def lint_contract_schema(schema: dict, *, contract_name: str) -> list[LintFinding]:
    """Run the contract-static C2.4 rules (L3, L5) on a single parsed schema."""
    findings: list[LintFinding] = []
    findings.extend(_check_l3(schema, contract_name))
    findings.extend(_check_l5(schema, contract_name))
    return findings


def lint_contracts(schemas: Mapping[str, dict]) -> LintReport:
    """Lint an in-memory mapping of ``{contract_name: parsed_schema}``."""
    report = LintReport(contracts_scanned=len(schemas))
    for name in sorted(schemas):
        for finding in lint_contract_schema(schemas[name], contract_name=name):
            if finding.severity == "deferred":
                report.deferred.append(finding)
            else:
                report.findings.append(finding)
    return report


def default_contracts_dir() -> Path:
    """Path to the packaged contracts directory."""
    return Path(__file__).resolve().parent.parent / "contracts"


def load_contract_schemas(contracts_dir: Path) -> dict[str, dict]:
    """Load all ``*.schema.json`` files in ``contracts_dir`` (non-recursive)."""
    if not contracts_dir.exists():
        raise ValueError(f"contracts dir does not exist: {contracts_dir}")
    if not contracts_dir.is_dir():
        raise ValueError(f"contracts dir is not a directory: {contracts_dir}")

    paths = sorted(contracts_dir.glob("*.schema.json"))
    if not paths:
        raise ValueError(f"no *.schema.json files found in contracts dir: {contracts_dir}")

    schemas: dict[str, dict] = {}
    for path in paths:
        try:
            schemas[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"failed to load contract schema {path.name}: {exc}") from exc
    return schemas


def lint_contracts_dir(contracts_dir: Path | None = None) -> LintReport:
    """Load and lint every contract schema in ``contracts_dir`` (defaults to the
    packaged contracts directory)."""
    contracts_dir = contracts_dir or default_contracts_dir()
    return lint_contracts(load_contract_schemas(contracts_dir))


def audit_deferral_registry(schemas: Mapping[str, dict]) -> list[str]:
    """Return reasons why :data:`DEFERRED_BOUNDARY_CONTRACTS` entries are stale.

    Keeps the deferral list honest: a deferral is stale if its contract is absent
    from the scanned set, or is actually compliant (has a boundary) or does not
    self-declare a boundary-requiring authority — in which case the entry should
    be removed.
    """
    stale: list[str] = []
    for name in DEFERRED_BOUNDARY_CONTRACTS:
        schema = schemas.get(name)
        if schema is None:
            stale.append(f"{name}: listed as deferred but not present in contracts dir")
            continue
        _, const = _self_declared_authority(schema)
        if const is None:
            stale.append(
                f"{name}: listed as deferred but does not self-declare a boundary-requiring authority"
            )
        elif _has_root_boundary(schema):
            stale.append(
                f"{name}: listed as deferred but now carries a root boundary array (remove the deferral)"
            )
    return stale
