"""Parity gate evaluation — production module.

Provides canonical, reusable evaluation of the two parity gates:

* ``content_parity_pass`` — source-equality conditions only.  Whether FTS
  indices are non-empty is deliberately *excluded*: two frontends producing
  identically-empty FTS (e.g. binary-only or source-excluded repos) still
  satisfy content parity.  FTS non-emptiness is a diagnostic / retrieval-
  capability condition, not a content-equality condition.

* ``diagnostic_parity_pass`` — requires content parity *plus* all hard
  diagnostic conditions, *plus* any conditional artifact expectations that
  the caller marks as required via ``*_expected`` flags.

Usage::

    from merger.lenskit.core.parity_gates import evaluate_parity_gates

    result = evaluate_parity_gates(state_dict)
    if result.content_parity_pass:
        ...
    if result.diagnostic_parity_pass:
        ...

``ParityGateResult`` is a ``NamedTuple`` so it is cheaply unpackable and
equality-comparable in tests.
"""
from __future__ import annotations

from typing import Mapping, NamedTuple


class ParityGateResult(NamedTuple):
    """Result of a parity gate evaluation.

    Attributes
    ----------
    content_parity_pass:
        True when all content-equality conditions are met.
    diagnostic_parity_pass:
        True when content parity passes *and* all required diagnostic
        conditions are met.
    content_reasons:
        Human-readable list of reasons why content_parity_pass is False.
        Empty when content_parity_pass is True.
    diagnostic_reasons:
        Human-readable list of reasons why diagnostic_parity_pass is False.
        Empty when diagnostic_parity_pass is True.
    """

    content_parity_pass: bool
    diagnostic_parity_pass: bool
    content_reasons: list[str]
    diagnostic_reasons: list[str]


def _is_true(state: Mapping[str, object], key: str) -> bool:
    """Return True only when state[key] is exactly True (strict boolean check).

    Rejects truthy non-bool values such as 1, "true", or non-empty strings that
    would otherwise be accepted by a plain ``state.get(key, False)`` test.
    Prevents 'string-False-is-truthy' bugs when state dicts originate from
    JSON deserialisation or CLI argument parsing.
    """
    return state.get(key) is True


def _expectation(state: Mapping[str, object], key: str) -> tuple[bool, str | None]:
    """Validate and interpret a ``*_expected`` flag from the state mapping.

    Returns a ``(required, error)`` pair:

    * ``(False, None)``  — key absent or explicitly False; artifact not required.
    * ``(True,  None)``  — key is exactly ``True``; artifact is required.
    * ``(False, msg)``   — key present but not a bool; caller should record
      ``msg`` as a diagnostic failure (fail-closed).

    Any non-bool value is treated as a configuration error rather than
    normalised silently, because silently treating ``"true"`` as "not required"
    would be fail-open behaviour for a gate field.
    """
    if key not in state:
        return False, None
    value = state[key]
    if value is True:
        return True, None
    if value is False:
        return False, None
    return False, f"{key} must be bool when provided, got {type(value).__name__!r}"


def evaluate_parity_gates(state: Mapping[str, object]) -> ParityGateResult:
    """Evaluate parity gates from a flat state mapping.

    Content gate — required keys (False if absent):
        source_paths_equal
        source_sha256_equal
        source_chunk_coverage_equal
        fts_logically_equal

    Diagnostic gate hard conditions (False if absent):
        output_health_verdict_pass
        range_ref_resolution_ok
        no_health_errors
        no_health_warnings
        manifest_hash_bytes_consistent

    Diagnostic gate conditional conditions (only checked when the
    corresponding ``*_expected`` flag is exactly True; absent or False means
    the artifact is not required; any non-bool value is a diagnostic failure):
        retrieval_eval_json_manifested  (checked if retrieval_eval_json_expected)
        citation_map_jsonl_valid        (checked if citation_map_jsonl_expected)
        fts_non_empty                   (checked if fts_non_empty_expected)

    Parameters
    ----------
    state:
        Flat mapping of field names to bool (or compatible) values.

    Returns
    -------
    ParityGateResult
    """
    content_reasons: list[str] = []

    if not _is_true(state, "source_paths_equal"):
        content_reasons.append("source_paths_equal is False or missing")
    if not _is_true(state, "source_sha256_equal"):
        content_reasons.append("source_sha256_equal is False or missing")
    if not _is_true(state, "source_chunk_coverage_equal"):
        content_reasons.append("source_chunk_coverage_equal is False or missing")
    if not _is_true(state, "fts_logically_equal"):
        content_reasons.append("fts_logically_equal is False or missing")

    content_parity_pass = len(content_reasons) == 0

    diagnostic_reasons: list[str] = []

    if not content_parity_pass:
        diagnostic_reasons.append("content_parity_pass is False")
    else:
        # Hard diagnostic conditions — always required when content passes.
        if not _is_true(state, "output_health_verdict_pass"):
            diagnostic_reasons.append("output_health_verdict_pass is False or missing")
        if not _is_true(state, "range_ref_resolution_ok"):
            diagnostic_reasons.append("range_ref_resolution_ok is False or missing")
        if not _is_true(state, "no_health_errors"):
            diagnostic_reasons.append("no_health_errors is False or missing")
        if not _is_true(state, "no_health_warnings"):
            diagnostic_reasons.append("no_health_warnings is False or missing")
        if not _is_true(state, "manifest_hash_bytes_consistent"):
            diagnostic_reasons.append("manifest_hash_bytes_consistent is False or missing")

        # Conditional: retrieval eval JSON — must be manifested in the bundle,
        # not merely present as a stray file.
        required, err = _expectation(state, "retrieval_eval_json_expected")
        if err:
            diagnostic_reasons.append(err)
        elif required:
            if not _is_true(state, "retrieval_eval_json_manifested"):
                diagnostic_reasons.append(
                    "retrieval_eval_json_expected=True but "
                    "retrieval_eval_json_manifested is False or missing"
                )

        # Conditional: citation map JSONL
        required, err = _expectation(state, "citation_map_jsonl_expected")
        if err:
            diagnostic_reasons.append(err)
        elif required:
            if not _is_true(state, "citation_map_jsonl_valid"):
                diagnostic_reasons.append(
                    "citation_map_jsonl_expected=True but "
                    "citation_map_jsonl_valid is False or missing"
                )

        # Conditional: FTS non-emptiness
        required, err = _expectation(state, "fts_non_empty_expected")
        if err:
            diagnostic_reasons.append(err)
        elif required:
            if not _is_true(state, "fts_non_empty"):
                diagnostic_reasons.append(
                    "fts_non_empty_expected=True but fts_non_empty is False or missing"
                )

    diagnostic_parity_pass = len(diagnostic_reasons) == 0

    return ParityGateResult(
        content_parity_pass=content_parity_pass,
        diagnostic_parity_pass=diagnostic_parity_pass,
        content_reasons=content_reasons,
        diagnostic_reasons=diagnostic_reasons,
    )
