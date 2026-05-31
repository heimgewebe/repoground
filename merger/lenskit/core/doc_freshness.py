"""Doc-Freshness Verifier — diagnostic v0.

Lenskit already has *drift awareness* (the artifact-drift-matrix, the two-layer
artifact pattern, proof obligations, the C2.x governance lints). What it lacked
is a machine-readable coupling between a **documentation claim** (a TODO, a
roadmap/spec statement) and the **code/test/proof evidence** that proves or
refutes it. Without that binding, "keep the docs current" stays a discipline
question; a spec can keep a ``### TODO`` block for a feature that is already
implemented (the ``ExtrasConfig`` case in ``repoLens-spec.md``) and nothing
notices.

This module closes the loop the diagnostic way the repo prefers:

* A declarative registry (``docs/doc-freshness-registry.yml``, validated against
  ``contracts/doc-freshness-registry.v1.schema.json``) binds each tracked claim
  to its ``status`` and a list of *verifiable* ``evidence`` refs
  (symbol/file/text/absent_text/proof/test).
* :func:`verify` resolves every evidence ref against the live tree and
  classifies each entry, flagging the cases where the declared status
  *contradicts* the code reality (the drift).
* :func:`render_markdown` regenerates a human-readable status view
  (``docs/_generated/doc-freshness.md``) from the verified registry — a document
  that is *automatically kept in sync*, rather than hand-maintained.
* :func:`restamp_last_verified` stamps the machine-readable ``last_verified``
  metadata for entries that verify, surgically (it never rewrites prose).

Mirrors C2.9's stance: a ``stale`` entry is a *known, declared* drift (like a
``declared_upgrade``) — surfaced and tracked, not silently suppressed, and not
auto-rewritten. Detection stays on; the registry only records reviewed intent.

**Out of scope (honest boundary).** This verifier does NOT rewrite normative
prose, does NOT judge whether a feature is *correct* (only whether the declared
status contradicts declared, mechanically checkable evidence), and introduces no
blocking CI gate (diagnostic-first; promotion is per-entry, like the drift
matrix). A green run does not prove the documentation is complete.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Iterable, Optional

from merger.lenskit.core.path_security import resolve_secure_path

# ``kind`` of evidence whose *presence* implies the work is implemented ("done").
_DONE_KINDS = frozenset({"symbol", "test", "proof"})

# Classifications that are NOT findings: the declared status matches reality, or
# is an explicitly tracked/declared state (stale_confirmed mirrors C2.9
# declared_upgrades — known and visible, not a warning).
_OK_CLASSIFICATIONS = frozenset(
    {"consistent", "partial_ok", "historical", "stale_confirmed"}
)


def repo_root_from_here() -> Path:
    """Best-effort repo root: ``merger/lenskit/core/doc_freshness.py`` → root."""
    return Path(__file__).resolve().parents[3]


# --- Evidence resolution ----------------------------------------------------


@dataclass(frozen=True)
class EvidenceRef:
    """One declared, mechanically checkable evidence pointer."""

    kind: str
    target: str
    implies: Optional[str] = None

    @property
    def effective_implies(self) -> Optional[str]:
        if self.implies is not None:
            return self.implies
        return "done" if self.kind in _DONE_KINDS else None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "target": self.target, "implies": self.implies}


@dataclass(frozen=True)
class EvidenceResult:
    ref: EvidenceRef
    satisfied: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "kind": self.ref.kind,
            "target": self.ref.target,
            "implies": self.ref.effective_implies,
            "satisfied": self.satisfied,
            "detail": self.detail,
        }


def _split_target(target: str) -> tuple[str, Optional[str]]:
    """Split ``relpath::needle`` into ``(relpath, needle)`` (needle optional)."""
    if "::" in target:
        path, _, needle = target.partition("::")
        return path.strip(), needle
    return target.strip(), None


def _python_defines(source: str, name: str) -> bool:
    """Whether ``name`` (last dotted segment) is defined anywhere in ``source``."""
    wanted = name.split(".")[-1]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fall back to a substring probe rather than crashing on unparsable code.
        return wanted in source
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            if node.name == wanted:
                return True
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == wanted:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == wanted:
                return True
    return False


def resolve_evidence(ref: EvidenceRef, repo_root: Path) -> EvidenceResult:
    """Resolve a single evidence ref against the live tree.

    ``satisfied`` means *the declared condition holds* (e.g. for ``absent_text``
    it means the forbidden needle is genuinely absent).
    """
    rel, needle = _split_target(ref.target)
    try:
        path = resolve_secure_path(repo_root, rel)
    except ValueError as exc:
        return EvidenceResult(ref, False, f"invalid path: {exc}")

    if ref.kind in ("file", "proof"):
        ok = path.is_file()
        return EvidenceResult(ref, ok, f"{'found' if ok else 'MISSING'}: {rel}")

    if ref.kind == "test":
        if not path.is_file():
            return EvidenceResult(ref, False, f"MISSING test file: {rel}")
        if needle:
            text = _read(path)
            pattern = rf"(?m)^\s*(?:async\s+def|def)\s+{re.escape(needle)}\b"
            ok = bool(re.search(pattern, text))
            return EvidenceResult(
                ref, ok, f"{'found' if ok else 'MISSING'} test {needle} in {rel}"
            )
        return EvidenceResult(ref, True, f"found test file: {rel}")

    if ref.kind == "symbol":
        if needle is None:
            return EvidenceResult(ref, False, f"symbol ref needs '::Name': {ref.target}")
        if not path.is_file():
            return EvidenceResult(ref, False, f"MISSING file for symbol: {rel}")
        text = _read(path)
        if rel.endswith(".py"):
            ok = _python_defines(text, needle)
        else:
            ok = needle in text
        return EvidenceResult(
            ref, ok, f"symbol {needle} {'defined' if ok else 'NOT defined'} in {rel}"
        )

    if ref.kind in ("text", "absent_text"):
        if needle is None:
            return EvidenceResult(ref, False, f"{ref.kind} ref needs '::needle'")
        if not path.is_file():
            return EvidenceResult(
                ref,
                False,
                f"MISSING file for {ref.kind} evidence: {rel}",
            )
        present = needle in _read(path)
        detail = f"needle {'present' if present else 'absent'} in {rel}"
        satisfied = present if ref.kind == "text" else (not present)
        return EvidenceResult(ref, satisfied, detail)

    return EvidenceResult(ref, False, f"unknown evidence kind: {ref.kind}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --- Entry classification ---------------------------------------------------


@dataclass
class EntryResult:
    entry_id: str
    doc: str
    claim: str
    declared_status: str
    normative: bool
    classification: str
    severity: str  # "ok" | "warning" | "error"
    message: str
    evidence: list[EvidenceResult] = field(default_factory=list)

    @property
    def is_finding(self) -> bool:
        return self.classification not in _OK_CLASSIFICATIONS

    def to_dict(self) -> dict:
        return {
            "id": self.entry_id,
            "doc": self.doc,
            "claim": self.claim,
            "declared_status": self.declared_status,
            "normative": self.normative,
            "classification": self.classification,
            "severity": self.severity,
            "message": self.message,
            "evidence": [e.to_dict() for e in self.evidence],
        }


def _has_present_done_evidence(results: Iterable[EvidenceResult]) -> bool:
    return any(
        r.satisfied and r.ref.effective_implies == "done" for r in results
    )


def _missing_done_evidence(results: Iterable[EvidenceResult]) -> list[EvidenceResult]:
    return [
        r for r in results if r.ref.effective_implies == "done" and not r.satisfied
    ]


def _unsatisfied_markers(results: Iterable[EvidenceResult]) -> list[EvidenceResult]:
    """absent_text refs whose forbidden needle is still present (stale marker)."""
    return [r for r in results if r.ref.kind == "absent_text" and not r.satisfied]


def _present_open_markers(results: Iterable[EvidenceResult]) -> list[EvidenceResult]:
    """text refs declared ``implies: open`` that are present (stale marker present)."""
    return [
        r
        for r in results
        if r.ref.kind == "text" and r.ref.effective_implies == "open" and r.satisfied
    ]


def _missing_open_markers(results: Iterable[EvidenceResult]) -> list[EvidenceResult]:
    """text refs declared ``implies: open`` that are NOT present (open marker gone)."""
    return [
        r
        for r in results
        if r.ref.kind == "text" and r.ref.effective_implies == "open" and not r.satisfied
    ]


def _hard_dangling(results: Iterable[EvidenceResult]) -> list[EvidenceResult]:
    """Evidence refs whose cited file/symbol/test/proof target is dangling."""
    return [
        r
        for r in results
        if (
            r.ref.kind in ("symbol", "file", "proof", "test")
            and not r.satisfied
        )
        or (
            r.ref.kind in ("text", "absent_text")
            and not r.satisfied
            and r.detail.startswith("MISSING file")
        )
    ]


def classify_entry(
    status: str, results: list[EvidenceResult]
) -> tuple[str, str, str]:
    """Return ``(classification, severity, message)`` for one entry.

    The core drift detection: does the *declared status* contradict the
    *mechanically verified evidence*?
    """
    dangling = _hard_dangling(results)
    stale_markers = _unsatisfied_markers(results) + _present_open_markers(results)
    done_present = _has_present_done_evidence(results)

    if status == "historical":
        # Archival/explanatory: owner-declared, not status-checked.
        return "historical", "ok", "historical (not status-checked)"

    if status == "none":
        if done_present:
            return (
                "understated",
                "warning",
                "doc presents this as not-started, but completion evidence exists "
                "(code/test/proof present) — likely drift; update the doc/status.",
            )
        return "consistent", "ok", "no completion evidence; matches 'none'"

    if status == "partial":
        # Owner-asserted mixed state (v1 done / rest open). Never auto-flag as
        # under/overstated; only a vanished hard evidence ref is a real problem.
        if dangling:
            return (
                "regressed",
                "error",
                "partial claim cites evidence that no longer exists: "
                + "; ".join(d.detail for d in dangling),
            )
        missing_open = _missing_open_markers(results)
        if missing_open:
            return (
                "partial_maybe_resolved",
                "warning",
                "partial claim's open marker(s) are gone; implementation may be "
                "complete — either promote to done, mark stale, or verify: "
                + "; ".join(m.detail for m in missing_open),
            )
        return "partial_ok", "ok", "partial (mixed state asserted by owner)"

    if status == "done":
        if dangling:
            return (
                "regressed",
                "error",
                "doc claims done, but cited evidence is missing: "
                + "; ".join(d.detail for d in dangling),
            )
        if stale_markers:
            return (
                "stale_marker_present",
                "warning",
                "doc claims done, but still literally contains the stale/TODO "
                "marker: " + "; ".join(m.detail for m in stale_markers),
            )
        return "consistent", "ok", "done and evidence verified"

    if status == "stale":
        # A known, *declared* drift (mirrors C2.9 declared_upgrades). Valid only
        # while it still reproduces: it IS done AND the doc still shows it open.
        reproduces = done_present and bool(stale_markers)
        if reproduces:
            return (
                "stale_confirmed",
                "ok",
                "KNOWN drift (declared stale): implemented in code, but the doc "
                "still presents it as open — tracked, not yet fixed.",
            )
        if not done_present:
            return (
                "regressed",
                "error",
                "declared stale, but no completion evidence — the premise (it is "
                "actually done) no longer holds; re-check the entry.",
            )
        # done_present and no stale marker → the drift is gone.
        return (
            "stale_resolved",
            "warning",
            "declared stale, but the stale/TODO marker is gone — drift resolved; "
            "promote this entry to status: done (or remove it).",
        )

    return "unknown_status", "error", f"unknown status: {status!r}"


# --- Report -----------------------------------------------------------------


@dataclass
class DocFreshnessReport:
    entries_scanned: int = 0
    results: list[EntryResult] = field(default_factory=list)
    strict: bool = False

    @property
    def findings(self) -> list[EntryResult]:
        out = [r for r in self.results if r.is_finding]
        if self.strict:
            # Promotion path: under --strict, a confirmed stale drift in a
            # normative doc is no longer merely "tracked" — it fails.
            out += [
                r
                for r in self.results
                if r.classification == "stale_confirmed" and r.normative
            ]
        return out

    @property
    def stale_confirmed(self) -> list[EntryResult]:
        return [r for r in self.results if r.classification == "stale_confirmed"]

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.findings if r.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.findings if r.severity == "warning")

    @property
    def status(self) -> str:
        if not self.findings:
            return "pass"
        if self.error_count:
            return "fail"
        # Enforcement: a KNOWN drift in a normative doc is a hard fail under
        # --strict (severity-"ok" stale_confirmed is otherwise only tracked).
        if self.strict and any(
            r.classification == "stale_confirmed" and r.normative
            for r in self.results
        ):
            return "fail"
        return "warn"

    def to_dict(self) -> dict:
        return {
            "kind": "lenskit.doc_freshness_report",
            "version": "1.0",
            "authority": "diagnostic_signal",
            "risk_class": "diagnostic",
            "blocking": False,
            "strict": self.strict,
            "status": self.status,
            "entries_scanned": self.entries_scanned,
            "finding_count": len(self.findings),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "stale_confirmed_count": len(self.stale_confirmed),
            "does_not_prove": [
                (
                    "a green run does not prove the documentation is complete or "
                    + "correct, only that no declared claim contradicts its declared "
                    + "evidence"
                ),
                "this report is a diagnostic_signal, not canonical content",
            ],
            "results": [r.to_dict() for r in self.results],
        }


# --- Registry loading / validation ------------------------------------------


def default_registry_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "doc-freshness-registry.yml"


def default_schema_path(repo_root: Path) -> Path:
    return (
        repo_root
        / "merger"
        / "lenskit"
        / "contracts"
        / "doc-freshness-registry.v1.schema.json"
    )


def default_generated_view_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "_generated" / "doc-freshness.md"


def load_registry(path: Path) -> dict:
    import yaml

    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"registry must be a YAML mapping: {path}")
    return data


def validate_registry(data: dict, schema_path: Path) -> list[str]:
    """Return schema-validation errors (empty == valid)."""
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in err.path) or "<root>"
        errors.append(f"[{loc}] {err.message}")
    return errors


def _entry_to_refs(entry: dict) -> list[EvidenceRef]:
    return [
        EvidenceRef(
            kind=e["kind"], target=e["target"], implies=e.get("implies")
        )
        for e in entry.get("evidence", [])
    ]


def verify(data: dict, repo_root: Path, strict: bool = False) -> DocFreshnessReport:
    """Verify every registry entry against the live tree."""
    report = DocFreshnessReport(strict=strict)
    for entry in data.get("entries", []):
        doc_path_rel = entry.get("doc", "")
        try:
            doc_path = resolve_secure_path(repo_root, doc_path_rel)
        except ValueError as exc:
            dangling_result = EntryResult(
                entry_id=entry.get("id", "<no-id>"),
                doc=doc_path_rel,
                claim=entry.get("claim", ""),
                declared_status=entry.get("status", ""),
                normative=bool(entry.get("normative", False)),
                classification="dangling_doc",
                severity="error",
                message=f"registry entry doc path is invalid: {exc}",
                evidence=[],
            )
            report.results.append(dangling_result)
            report.entries_scanned += 1
            continue

        if not doc_path.is_file():
            dangling_result = EntryResult(
                entry_id=entry.get("id", "<no-id>"),
                doc=doc_path_rel,
                claim=entry.get("claim", ""),
                declared_status=entry.get("status", ""),
                normative=bool(entry.get("normative", False)),
                classification="dangling_doc",
                severity="error",
                message=f"registry entry's doc does not exist: {doc_path_rel}",
                evidence=[],
            )
            report.results.append(dangling_result)
            report.entries_scanned += 1
            continue

        refs = _entry_to_refs(entry)
        results = [resolve_evidence(ref, repo_root) for ref in refs]
        classification, severity, message = classify_entry(
            entry.get("status", ""), results
        )
        report.results.append(
            EntryResult(
                entry_id=entry.get("id", "<no-id>"),
                doc=entry.get("doc", ""),
                claim=entry.get("claim", ""),
                declared_status=entry.get("status", ""),
                normative=bool(entry.get("normative", False)),
                classification=classification,
                severity=severity,
                message=message,
                evidence=results,
            )
        )
        report.entries_scanned += 1
    return report


# --- Generated view (automated document update) -----------------------------

_STATUS_BADGE = {
    "consistent": "✅ consistent",
    "partial_ok": "🟡 partial",
    "partial_maybe_resolved": "🟡 partial (maybe resolved)",
    "historical": "📜 historical",
    "stale_confirmed": "⚠️ stale (tracked)",
    "stale_marker_present": "⚠️ stale marker",
    "stale_resolved": "🔧 stale resolved",
    "understated": "⬆️ understated",
    "regressed": "❌ regressed",
    "dangling_doc": "❌ dangling doc",
}


def render_markdown(
    data: dict, report: DocFreshnessReport, generated_at: str
) -> str:
    """Render the human-readable generated view from a verified registry.

    This is the *automatically maintained* document: it is regenerated from the
    registry by ``doc-freshness update --write`` and checked in CI, so it never
    drifts from the source-of-truth registry.
    """
    by_id = {e.get("id"): e for e in data.get("entries", [])}
    lines: list[str] = []
    lines.append("# Doc-Freshness Status (generated)")
    lines.append("")
    lines.append(
        "<!-- GENERATED FILE — do not edit by hand. Regenerate with: "
        "`python -m merger.lenskit.cli.main doc-freshness update --write`. "
        "Source of truth: docs/doc-freshness-registry.yml. -->"
    )
    lines.append("")
    lines.append(f"- data current as of (max last_verified): {generated_at}")
    lines.append(f"- overall: **{report.status.upper()}**")
    lines.append(
        f"- entries: {report.entries_scanned} | findings: "
        f"{len(report.findings)} (errors {report.error_count}, "
        f"warnings {report.warning_count}) | stale tracked: "
        f"{len(report.stale_confirmed)}"
    )
    lines.append("")
    lines.append(
        "> Diagnostic signal. A green status does not prove the docs are "
        "complete — only that no tracked claim contradicts its declared "
        "evidence. See `docs/proofs/doc-freshness-registry-v0-proof.md`."
    )
    lines.append("")
    lines.append("| ID | Status | Verdict | Doc | Claim | last_verified |")
    lines.append("| :-- | :-- | :-- | :-- | :-- | :-- |")
    for r in sorted(report.results, key=lambda x: x.entry_id):
        entry = by_id.get(r.entry_id, {})
        last_verified = entry.get("last_verified", "—")
        badge = _STATUS_BADGE.get(r.classification, r.classification)
        claim = r.claim.replace("|", "\\|")
        lines.append(
            f"| `{r.entry_id}` | {r.declared_status} | {badge} | "
            f"`{r.doc}` | {claim} | {last_verified} |"
        )
    lines.append("")

    findings = report.findings
    if findings:
        lines.append("## Findings")
        lines.append("")
        for r in sorted(findings, key=lambda x: (x.severity, x.entry_id)):
            lines.append(f"- **[{r.severity}] `{r.entry_id}`** ({r.classification}): {r.message}")
        lines.append("")
    else:
        lines.append("_No findings: every tracked claim matches its evidence._")
        lines.append("")
    return "\n".join(lines)


# --- last_verified stamping (surgical; never touches prose) ------------------


def restamp_last_verified(
    registry_text: str, updates: dict[str, str]
) -> tuple[str, list[str]]:
    """Surgically replace ``last_verified:`` values per entry id in raw YAML.

    Operates on the raw text (preserves comments, order, formatting). ``updates``
    maps entry id → ISO date. Returns ``(new_text, changed_ids)``.
    """

    id_re = re.compile(r"^\s*-?\s*id:\s*(['\"]?)([A-Za-z0-9][A-Za-z0-9-]*)\1\s*$")
    lv_re = re.compile(r"^(?P<indent>\s*)last_verified:\s*.*$")

    out_lines: list[str] = []
    current_id: Optional[str] = None
    changed: list[str] = []
    for line in registry_text.splitlines():
        id_match = id_re.match(line)
        if id_match:
            current_id = id_match.group(2)
            out_lines.append(line)
            continue
        lv_match = lv_re.match(line)
        if lv_match and current_id in updates:
            new_date = updates[current_id]
            new_line = f"{lv_match.group('indent')}last_verified: \"{new_date}\""
            if new_line != line:
                changed.append(current_id)
            out_lines.append(new_line)
            continue
        out_lines.append(line)

    trailing_nl = "\n" if registry_text.endswith("\n") else ""
    return "\n".join(out_lines) + trailing_nl, changed


def verified_entry_ids(report: DocFreshnessReport) -> list[str]:
    """Entry ids whose state is OK (safe to stamp last_verified)."""
    return [r.entry_id for r in report.results if not r.is_finding]
