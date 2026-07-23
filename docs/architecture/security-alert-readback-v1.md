---
doc_type: architecture_decision
status: implemented
finding: candidate-52e48525291654cff4605a47
---

# Security-alert readback contract v1

## Problem

An audit that reads GitHub's live code-scanning alerts endpoint cannot tell "zero
alerts" apart from "the read failed": GitHub returns `404` both when code scanning
is disabled for the repository and when the caller lacks `security-events: read`
access, and any transport failure looks like silence, not a clean bill of health. A
prior audit observed exactly this: a live endpoint read returned `404` while the
required CodeQL check on the same commit was green. Nothing in the repository
distinguished "clean" from "unavailable/unauthorized," so the ambiguity could only
be resolved by guessing -- and guessing "clean" on missing evidence is a fail-open
bug.

## Decision

Classify readback evidence into one explicit, closed-vocabulary state instead of
inferring "clean" from absence:

`clean` | `alerts_present` | `unavailable` | `unauthorized` | `unknown`

Implementation:

- [`merger/repoground/retrieval/security_alert_summary.py`](../../merger/repoground/retrieval/security_alert_summary.py)
  -- pure, deterministic classifier (`classify_security_alert_state`).
- [`merger/repoground/contracts/security-alert-summary.v1.schema.json`](../../merger/repoground/contracts/security-alert-summary.v1.schema.json)
  -- the machine-readable contract for the summary object.
- [`scripts/ci/emit_security_alert_summary.py`](../../scripts/ci/emit_security_alert_summary.py)
  -- CLI that reads local evidence and writes the summary; exit code `0` only for
  `clean`.
- [`.github/workflows/codeql.yml`](../../.github/workflows/codeql.yml) -- emits and
  uploads `security-alert-summary.json` as a workflow artifact on every run of the
  `analyze` job, using `if: always()` so the artifact still reflects reality when an
  earlier step fails.

## Evidence sources and priority

1. **Repository-local SARIF (authoritative for the current CodeQL analysis boundary).** The `analyze` step's raw CodeQL SARIF
   output is read directly from disk in the same job that already produces it. This
   needs no additional permission beyond the job's existing `contents: read` and no
   network call, so it is the preferred, least-privilege evidence source. When it
   resolves to a definitive state (`clean` or `alerts_present`), it decides the
   summary even if a concurrent live-API read is unavailable or unauthorized -- a
   live `404` must never override a deterministic, CI-produced clean result.
2. **Live GitHub alerts API (optional, supplementary).** If a caller has separately
   captured a `GET /repos/{owner}/{repo}/code-scanning/alerts` response (status code
   and, for `200`, an open-alert count), it can be passed to the classifier as a
   small JSON file. A zero API count is `clean` only when exhaustive pagination is
   explicitly proven (`paginated=true`); an unpaginated zero fails closed to `unknown`.
   Any positive count is already sufficient for `alerts_present`. The script never performs this HTTP call itself and never
   handles a token; the caller owns the request and its credentials.
3. **Disagreement fails closed.** If both sources resolve to a definitive state and
   they disagree (e.g. SARIF says clean, the API says alerts are open), the result is
   `unknown`, not a silent pick of either side.
4. **No evidence at all resolves to `unknown`, never `clean`.**

## Required permissions

| Evidence path | Required permission |
| --- | --- |
| Repository-local SARIF | None beyond the analysis job's existing `contents: read`. No network call, no additional scope. |
| Live alerts API (optional) | `security-events: read` -- least privilege, read-only. Never request `security-events: write` for a readback; `write` is only needed to *upload* SARIF (already granted to the `analyze` step for that reason), not to read alert state. |

An external auditor with no repository write access can satisfy the entire
contract by reading the `security-alert-summary` workflow artifact produced by
`codeql.yml` on the commit under review -- no token beyond `actions: read` is
needed, and the live alerts API does not have to be called at all.

## States

| State | Meaning | Does not mean |
| --- | --- | --- |
| `clean` | current CodeQL SARIF reports zero findings for its analysis boundary, or an API read proves zero open alerts with exhaustive pagination; no other definitive source disagrees | absence of coverage gaps outside analyzed languages/paths |
| `alerts_present` | a definitive evidence source reports one or more alerts | severity, exploitability, or which specific alerts |
| `unavailable` | evidence was attempted but unreachable (missing/unreadable SARIF, API `404`, non-2xx/401/403 API response) | zero alerts |
| `unauthorized` | the live API responded `401`/`403` | zero alerts |
| `unknown` | no evidence was supplied, or two definitive sources disagree | zero alerts |

Only `clean` is a pass. `emit_security_alert_summary.py` exits `0` for `clean` and
non-zero for every other state, including `unknown` -- fail closed, not fail open.

## Non-goals

- Calling the GitHub REST API. This repository's tooling only classifies evidence
  handed to it; it never fetches credentials or makes the live request itself.
- Replacing `scripts/ci/assert_codeql_sarif_clean.py`, which already fails the
  `codeql.yml` job when raw SARIF contains results. This contract adds an
  explicit, exportable state for consumers *outside* that job (audits, other CI
  systems) who cannot see its pass/fail alone and need to know *why*.
- Determining severity, exploitability, or remediation priority of any alert.
- Registering as a required branch-protection status check; that decision belongs
  to repository governance, not this contract.
