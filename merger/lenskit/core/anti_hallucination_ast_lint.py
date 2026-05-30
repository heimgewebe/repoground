"""Anti-Hallucination AST Lint — Governance Track C, step C2.7 (experimental).

Minimal, *marker-gated* AST / code-path groundwork for the C1 anti-hallucination
lint rules **L1 / L2 / L4** (``docs/blueprints/lenskit-authority-risk-matrix.md``
§6), which the contract-static C2.4 stage
(``merger/lenskit/core/anti_hallucination_lint.py``) explicitly deferred because
they require Python AST / code-path analysis with a high false-positive surface.

This module is a deliberately small *Vorbau* (groundwork), not the full rules:

* **L1 — Forbidden semantic upgrade**: a value declared (via an opt-in marker) to
  carry ``diagnostic_signal`` authority gates an ``if`` whose body invokes a
  canonical-authority-requiring sink.
* **L2 — Authority escalation**: a value declared to carry a runtime / agent /
  diagnostic / external authority is passed as an argument to a
  canonical-authority-requiring sink.
* **L4 — Derived-artifact misuse**: a value declared to carry a navigation /
  derived / cache authority is passed as an argument to a
  canonical-authority-requiring sink.

**Marker-gated / opt-in by design.** The lint fires only on code that carries
explicit, lint-only governance markers (see ``MARKER_*`` below). It performs no
type inference and makes no guess about un-annotated names. Consequently it
produces **zero findings on the current, un-annotated tree** (asserted by
``test_anti_hallucination_ast_lint.py``), so it is safe to run without mass false
positives and is **not** wired into a blocking CI gate. The markers are
*static-analysis hints only* — they are **not** runtime annotations (C4 remains
open), are never emitted into artifacts, and change no contract.

Out of scope for this experimental stage (documented, not implemented):

* **L3 / L5** — contract-static; already enforced by C2.4.
* **L6** — export-risk = export-gate integration = Governance Track C5.
* **C4** — runtime annotation of artifacts — remains open and untouched.

A clean run does **not** prove the code is authority-safe; it only proves that no
*declared* low-authority value flows into a *declared* canonical sink. Lifting
this from marker-gated detection to real inference is the next slice (see
``docs/proofs/authority-risk-class-c2-7-ast-lint-proof.md``). The report is
itself a ``diagnostic_signal``.
"""
from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

# --- Marker grammar (lint-only, opt-in) -------------------------------------

# A value's authority is declared on its (possibly multi-line) assignment, e.g.:
#     result = produce()  # lenskit:authority=diagnostic_signal
MARKER_AUTHORITY = "lenskit:authority="
# A sink that requires canonical authority for its arguments is declared either
# on a call line:
#     trust(x)  # lenskit:requires-authority=canonical_content
# or on a function's ``def`` line (the function name becomes a sink), or via the
# ``@lenskit_requires_canonical`` decorator.
MARKER_REQUIRES = "lenskit:requires-authority="
DECORATOR_REQUIRES_CANONICAL = "lenskit_requires_canonical"
CANONICAL_AUTHORITY = "canonical_content"

# Low-authority classes that must not silently flow into canonical decisions.
# Navigation / derived / cache-like → L4 (derived-artifact misuse).
NAVIGATION_LIKE_AUTHORITIES: frozenset[str] = frozenset(
    {"navigation_index", "derived_projection", "retrieval_index", "runtime_cache", "cache"}
)
# Runtime / agent / diagnostic / external-like → L2 (authority escalation).
ESCALATION_LIKE_AUTHORITIES: frozenset[str] = frozenset(
    {
        "diagnostic_signal",
        "runtime_observation",
        "agent_context_projection",
        "agent_generated",
        "external_unverified",
    }
)
# Only ``diagnostic_signal`` gating an ``if`` → sink is L1 (blueprint §6 L1 example).
L1_GATING_AUTHORITIES: frozenset[str] = frozenset({"diagnostic_signal"})

RULES_COVERED: tuple[str, ...] = ("L1", "L2", "L4")
RULES_OUT_OF_SCOPE: dict[str, str] = {
    "L3": "missing inference boundary — contract-static, enforced by C2.4",
    "L5": "unsupported truth language — contract-static, enforced by C2.4",
    "L6": "export-risk violations — export-gate integration is Governance Track C5",
    "C4": "runtime annotation of artifacts — out of scope, remains open",
}

# Directories excluded from the default tree scan (the authority-bearing runtime
# code is what matters; tests/fixtures legitimately *name* the markers/vocabulary).
DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {"__pycache__", "tests", "fixtures", "contracts", "examples", ".git"}
)


# --- Findings & report ------------------------------------------------------


@dataclass(frozen=True)
class AstLintFinding:
    """A single experimental AST-lint finding.

    ``severity`` is always ``"warning"`` for this stage: the lint is experimental
    and non-blocking. A finding marks a *declared* authority-flow violation, not a
    proven runtime defect.
    """

    rule: str
    severity: str
    file: str
    line: int
    symbol: str
    message: str

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "symbol": self.symbol,
            "message": self.message,
        }


@dataclass
class AstLintReport:
    """Structured result of an experimental marker-gated AST-lint run.

    The report is itself a ``diagnostic_signal``: a clean run does not prove the
    scanned code is authority-safe, only that no *declared* low-authority value
    flows into a *declared* canonical sink.
    """

    files_scanned: int
    files_skipped: int = 0
    findings: list[AstLintFinding] = field(default_factory=list)

    @property
    def status(self) -> str:
        # "warn" (not "fail") to signal the non-blocking, experimental nature.
        return "warn" if self.findings else "pass"

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    def to_dict(self) -> dict:
        return {
            "kind": "lenskit.anti_hallucination_ast_lint",
            "version": "0.1",
            "stage": "C2.7",
            "experimental": True,
            "blocking": False,
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "status": self.status,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
            "finding_count": self.finding_count,
            "rules_covered": list(RULES_COVERED),
            "rules_out_of_scope": dict(RULES_OUT_OF_SCOPE),
            "findings": [f.to_dict() for f in self.findings],
            "does_not_mean": [
                "ast_lint_pass_does_not_prove_code_is_authority_safe",
                "absence_of_finding_does_not_prove_absence_of_authority_escalation",
                "marker_gated_ast_lint_is_not_type_inference_or_runtime_annotation",
                "experimental_ast_lint_is_not_a_blocking_ci_gate",
            ],
        }


# --- Marker extraction ------------------------------------------------------


def _marker_value(comment_text: str, marker: str) -> str | None:
    """Return the lower-cased token after ``marker`` in a comment, or ``None``."""
    idx = comment_text.find(marker)
    if idx == -1:
        return None
    rest = comment_text[idx + len(marker):].strip()
    if not rest:
        return None
    token = rest.split()[0]
    return token.lower() or None


def _extract_markers(source: str) -> tuple[dict[int, str], dict[int, str]]:
    """Return ``(authority_by_line, requires_by_line)`` from COMMENT tokens.

    Uses :mod:`tokenize` (not a raw line regex) so marker text inside string
    literals is never matched. Never raises: a tokenization failure simply yields
    whatever markers were collected before the failure (the AST parse step is the
    authoritative error path).
    """
    authority_by_line: dict[int, str] = {}
    requires_by_line: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                continue
            line = tok.start[0]
            authority = _marker_value(tok.string, MARKER_AUTHORITY)
            if authority is not None:
                authority_by_line[line] = authority
            requires = _marker_value(tok.string, MARKER_REQUIRES)
            if requires is not None:
                requires_by_line[line] = requires
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return authority_by_line, requires_by_line
    return authority_by_line, requires_by_line


# --- AST helpers ------------------------------------------------------------


def _marker_in_range(node: ast.AST, by_line: dict[int, str]) -> str | None:
    """Return the marker value whose line falls within ``node``'s line span."""
    start = getattr(node, "lineno", None)
    if start is None:
        return None
    end = getattr(node, "end_lineno", start) or start
    for line, value in by_line.items():
        if start <= line <= end:
            return value
    return None


def _target_names(target: ast.expr) -> Iterator[str]:
    """Yield bound ``Name`` ids from an assignment target (incl. tuple/list)."""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _target_names(elt)
    # Attribute / Subscript targets are intentionally not tracked (minimal Vorbau).


def _decorator_name(dec: ast.expr) -> str | None:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return None


def _has_requires_canonical_decorator(node: ast.AST) -> bool:
    decorators = getattr(node, "decorator_list", [])
    for dec in decorators:
        name = _decorator_name(dec)
        if name is not None and name.endswith(DECORATOR_REQUIRES_CANONICAL):
            return True
    return False


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _call_arg_values(call: ast.Call) -> Iterator[ast.expr]:
    yield from call.args
    for kw in call.keywords:
        yield kw.value


# --- Analysis passes --------------------------------------------------------


def _collect_canonical_sink_functions(
    tree: ast.AST, requires_by_line: dict[int, str]
) -> set[str]:
    """Names of functions declared as canonical-authority sinks (decorator or
    ``requires-authority=canonical_content`` marker on the ``def`` line)."""
    sinks: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _has_requires_canonical_decorator(node):
                sinks.add(node.name)
            elif requires_by_line.get(node.lineno) == CANONICAL_AUTHORITY:
                sinks.add(node.name)
    return sinks


def _collect_name_authorities(
    tree: ast.AST, authority_by_line: dict[int, str]
) -> dict[str, str]:
    """Map ``name -> authority class`` for marker-annotated assignments.

    File-scoped over-approximation: a name annotated anywhere in the file carries
    that authority for the whole file. This is sound for the opt-in markers (they
    do not occur on un-annotated code) and keeps the Vorbau small; precise
    per-function / SSA flow is a documented future refinement.
    """
    name_authority: dict[str, str] = {}
    if not authority_by_line:
        return name_authority
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        cls = _marker_in_range(node, authority_by_line)
        if cls is None:
            continue
        for target in targets:
            for name in _target_names(target):
                name_authority[name] = cls
    return name_authority


def _is_canonical_sink_call(
    call: ast.Call, sinks: set[str], requires_by_line: dict[int, str]
) -> bool:
    name = _call_name(call)
    if name is not None and name in sinks:
        return True
    return _marker_in_range(call, requires_by_line) == CANONICAL_AUTHORITY


def _check_call_arg_flow(
    call: ast.Call, name_authority: dict[str, str], filename: str
) -> Iterator[AstLintFinding]:
    """L2 / L4 — a declared low-authority name passed to a canonical sink call."""
    sink = _call_name(call) or "<call>"
    for arg in _call_arg_values(call):
        if not isinstance(arg, ast.Name):
            continue
        cls = name_authority.get(arg.id)
        if cls is None:
            continue
        line = getattr(arg, "lineno", call.lineno)
        if cls in NAVIGATION_LIKE_AUTHORITIES:
            yield AstLintFinding(
                rule="L4",
                severity="warning",
                file=filename,
                line=line,
                symbol=arg.id,
                message=(
                    f"navigation/derived value '{arg.id}' (authority={cls}) is passed to "
                    f"canonical-authority sink '{sink}'. A navigation/derived artifact must "
                    f"be resolved to canonical_md before use as content (blueprint §6 L4)."
                ),
            )
        elif cls in ESCALATION_LIKE_AUTHORITIES:
            yield AstLintFinding(
                rule="L2",
                severity="warning",
                file=filename,
                line=line,
                symbol=arg.id,
                message=(
                    f"low-authority value '{arg.id}' (authority={cls}) is passed to "
                    f"canonical-authority sink '{sink}'. Authority is never inherited; this "
                    f"is a silent authority escalation (blueprint §6 L2)."
                ),
            )


def _l1_gating_name(test: ast.expr, name_authority: dict[str, str]) -> str | None:
    for sub in ast.walk(test):
        if isinstance(sub, ast.Name) and name_authority.get(sub.id) in L1_GATING_AUTHORITIES:
            return sub.id
    return None


def _check_if_gate(
    node: ast.If,
    name_authority: dict[str, str],
    sinks: set[str],
    requires_by_line: dict[int, str],
    filename: str,
) -> Iterator[AstLintFinding]:
    """L1 — a diagnostic_signal value gates an ``if`` whose body invokes a sink."""
    gating = _l1_gating_name(node.test, name_authority)
    if gating is None:
        return
    for stmt in node.body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call) and _is_canonical_sink_call(
                sub, sinks, requires_by_line
            ):
                yield AstLintFinding(
                    rule="L1",
                    severity="warning",
                    file=filename,
                    line=node.lineno,
                    symbol=gating,
                    message=(
                        f"diagnostic_signal value '{gating}' gates a branch that invokes "
                        f"canonical-authority sink '{_call_name(sub) or '<call>'}'. A "
                        f"diagnostic verdict does not prove content truth (blueprint §6 L1)."
                    ),
                )
                return  # one L1 finding per ``if`` is enough


# --- Public API -------------------------------------------------------------


def lint_source(source: str, *, filename: str = "<source>") -> list[AstLintFinding]:
    """Run the experimental marker-gated L1/L2/L4 AST lint on one source string.

    Returns ``[]`` for un-annotated or unparseable sources.
    """
    # Cheap pre-filter: without any marker token there is nothing to check, so the
    # un-annotated common case never pays for tokenize/parse.
    if (
        MARKER_AUTHORITY not in source
        and MARKER_REQUIRES not in source
        and DECORATOR_REQUIRES_CANONICAL not in source
    ):
        return []

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []

    authority_by_line, requires_by_line = _extract_markers(source)
    name_authority = _collect_name_authorities(tree, authority_by_line)
    if not name_authority:
        # No declared low-authority values → no flow to check (e.g. marker text
        # appeared only inside a string literal).
        return []
    sinks = _collect_canonical_sink_functions(tree, requires_by_line)

    findings: list[AstLintFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _is_canonical_sink_call(node, sinks, requires_by_line):
                findings.extend(_check_call_arg_flow(node, name_authority, filename))
        elif isinstance(node, ast.If):
            findings.extend(
                _check_if_gate(node, name_authority, sinks, requires_by_line, filename)
            )

    findings.sort(key=lambda f: (f.line, f.rule, f.symbol))
    return findings


def lint_file(path: Path) -> list[AstLintFinding]:
    """Lint a single ``*.py`` file. Unreadable files yield ``[]``."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return lint_source(source, filename=str(path))


def iter_python_files(
    root: Path, skip_dirs: Iterable[str] = DEFAULT_SKIP_DIRS
) -> Iterator[Path]:
    skip = set(skip_dirs)
    for path in sorted(root.rglob("*.py")):
        if any(part in skip for part in path.parts):
            continue
        yield path


def lint_tree(
    root: Path, *, skip_dirs: Iterable[str] = DEFAULT_SKIP_DIRS
) -> AstLintReport:
    """Lint every ``*.py`` under ``root`` (skipping ``skip_dirs``)."""
    report = AstLintReport(files_scanned=0)
    for path in iter_python_files(root, skip_dirs):
        report.files_scanned += 1
        try:
            report.findings.extend(lint_file(path))
        except RecursionError:
            report.files_skipped += 1
    return report


def default_scan_root() -> Path:
    """The packaged lenskit package root (authority-bearing runtime code)."""
    return Path(__file__).resolve().parent.parent


def lint_default_tree() -> AstLintReport:
    """Lint the packaged lenskit package (minus tests/fixtures/contracts)."""
    return lint_tree(default_scan_root())
