---
doc_type: proof
status: active
task: TASK-OPS-CTL-005
---

# Proof: Planning Drift Ratchet Control Plane (TASK-OPS-CTL-005)

## Problem

The planning-registration guard (`scripts/docmeta/check_planning_registration.py`,
TASK-CTL-004) detected planning artifacts (blueprints, roadmap docs, planning
specs, status reports) that were not registered in a canonical planning register
— but it ran **report-only**: findings never failed CI, so nothing stopped a new
unregistered blueprint from accumulating as silent planning drift. The missing
pieces were (a) a way to tolerate known legacy drift while (b) blocking *new*
drift, plus (c) a contract-stable frontmatter exemption flow. This task delivers
that control plane without forcing "everything must be perfect".

## Policy

A planning artifact is drift-suspect when it is an active steering document
(blueprint / roadmap / plan / status / status-matrix spec) that is not present in
any canonical planning register:

- `docs/tasks/board.md`
- `docs/tasks/index.json` (task `evidence` entries)
- `docs/roadmap.md`
- a valid frontmatter exemption

Exemptions must be **complete**:

```yaml
---
planning_registration:
  status: exempt
  reason: "short justification"
  owner: "docs/tasks"
  expires: "YYYY-MM-DD"
---
```

Rules:

- `status: exempt` is valid only with non-empty `reason`, `owner`, and an ISO
  `expires` (`YYYY-MM-DD`).
- An expired `expires` is invalid.
- A `planning_registration:` block that asserts a non-`exempt` status is invalid
  (no silent typos).
- Invalid exemptions are reported as `invalid_exceptions` and **block** in
  ratchet mode. They are **never** written into the baseline (a broken or
  expired exemption can never be grandfathered).
- No filename-based or wildcard exemptions.

## Baseline / Ratchet semantics

- **Finding id** = `sha256(code + "\0" + normalized_path + "\0" + kind)[:16]`.
  Ids are independent of line numbers, so re-ordering headings does not move an
  id. Paths are normalized repo-relative with forward slashes.
- **Baseline** (`docs/tasks/planning-registration-baseline.json`,
  `lenskit.planning_registration_baseline.v1`) holds only known, currently
  tolerated findings, deterministically sorted by `(path, code, id)`. It may be
  empty; the ratchet still works. The initial scan of this repo produced **0**
  findings, so the committed baseline is empty.
- **Baseline eligibility**: only `UNREGISTERED_PLANNING_ARTIFACT` findings are
  written to or accepted from a baseline. `CONTROL_FILE_MISSING` and
  `CONTROL_FILE_PARSE_ERROR` signal a broken governance structure and must be
  fixed, not grandfathered. `INVALID_PLANNING_EXCEPTION` is handled as a
  separate blocking class and is never eligible. A baseline entry with a
  non-eligible code causes `load_baseline()` to raise `BaselineError` → exit 2.
  The baseline JSON schema enforces this with `"const": "UNREGISTERED_PLANNING_ARTIFACT"`
  on the `entries[].code` field.
- `--ratchet` partitions the current scan against the baseline:
  - `known_findings`: id present in baseline → tolerated.
  - `new_findings`: genuine new drift, id absent from baseline → **blocking**.
    `invalid_exceptions` are **not** counted here; they are a separate blocking class.
  - `resolved_findings`: baseline id absent from the current scan → stale,
    **non-blocking** (surfaced for later baseline pruning).
  - `invalid_exceptions`: kaputte/abgelaufene Frontmatter-Ausnahmen, always
    **blocking**, regardless of baseline, **never** in `new_findings`.
- CI does not enforce "all registered". It enforces **no new drift**.

## CI behavior

`.github/workflows/task-index.yml` (job `planning-registration`):

1. **Ratchet step** (`id: ratchet`): Runs the ratchet via `python3 -m scripts.docmeta.check_planning_registration --ratchet --baseline docs/tasks/planning-registration-baseline.json --format json`.
   - Redirects JSON to `planning-registration-report.json`.
   - Uses `|| code=$?` to capture the exit code (0, 1, or 2) without breaking
     under `set -uo pipefail`. Writes `exit_code=${code}` to `$GITHUB_OUTPUT`.
   - Does not `exit` or `set -e` immediately; allows downstream steps to run.
2. **Step summary** (`if: always()`): Writes a human-readable summary to
   `$GITHUB_STEP_SUMMARY` with current / baseline / known / new / resolved
   findings and invalid exceptions (or "no new drift" if clean).
3. **Upload artifact** (`if: always()`): Uploads `planning-registration-report.json`
   to GitHub Artifacts, even if ratchet found findings.
4. **Enforce step** (`if: always()`):
   - Reads `steps.ratchet.outputs.exit_code` from the ratchet step.
   - **Fail-closed**: If the output is missing or empty, exits with code 2
     (config error, workflow problem).
   - Otherwise, exits with the captured ratchet code (0, 1, or 2).
   - This ensures the workflow only passes when ratchet code is 0; blocks on
     code 1 (new drift) or code 2 (config error).

Result: Report and summary are always published; the gate blocks iff the ratchet
produced new drift or a config error.

No network or GitHub-API dependency; no time-of-day logic in the gate.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | No new blocking findings (ratchet), or scan/update-baseline success. |
| 1 | Ratchet: new findings or invalid exceptions present. |
| 2 | Usage/config error: invalid baseline, schema mismatch, broken input, mutually exclusive flags (`--ratchet` + `--update-baseline`), or `--ratchet`/`--update-baseline` without `--baseline`. |

JSON (`--format json`) is emitted on **stdout only**; human-readable output goes
to **stderr** in JSON mode so stdout stays parseable.

# Local commands

```bash
# Refresh the baseline from the current tree (deterministic, exit 0)
python3 -m scripts.docmeta.check_planning_registration \
  --update-baseline \
  --baseline docs/tasks/planning-registration-baseline.json \
  --format json

# Run the ratchet exactly like CI
python3 -m scripts.docmeta.check_planning_registration \
  --ratchet \
  --baseline docs/tasks/planning-registration-baseline.json \
  --format json \
  > /tmp/planning-registration-report.json
python3 -m json.tool /tmp/planning-registration-report.json >/dev/null
```

## Test evidence

- `merger/lenskit/tests/test_planning_registration_ratchet.py` (47 tests):
  scanner detection, line-number-independent ids, baseline toleration, new-drift
  blocking, resolved/stale handling, invalid/expired exemptions blocking (including
  the key invariant that `invalid_exceptions` do **not** appear in `new_findings`),
  direct `partition_ratchet()` invariant test with unfiltered `run_checks()` output,
  valid exemption suppression, JSON report schema validation (scan/ratchet/
  update_baseline modes), committed-baseline validated against the baseline
  contract schema, baseline eligibility enforcement (`build_baseline()` retains only
  `UNREGISTERED_PLANNING_ARTIFACT`; control-file codes and invalid exceptions
  excluded at write time and rejected at load time; baseline schema `const`
  rejects non-eligible codes), workflow static wiring (ratchet step uses `|| code=$?`
  to capture exit code under GitHub Actions errexit semantics; enforce step is
  fail-closed with explicit missing-output detection), exit-code-2 config errors,
  `load_baseline()` runtime validation (empty code/path/kind → exit 2, invalid id
  pattern → exit 2, missing required field → exit 2, non-eligible code → exit 2),
  and Bash-semantics tests (prove that `|| code=$?` correctly captures exit codes
  and that enforce step exits 2 on missing output).
- `scripts/docmeta/tests/test_check_planning_registration.py` (27 tests): the
  pre-existing scanner contract, unchanged and still green.
- Real-repo ratchet run: exit 0, report validates against
  `merger/lenskit/contracts/planning-registration-report.v1.schema.json`.
- Committed baseline validates against
  `merger/lenskit/contracts/planning-registration-baseline.v1.schema.json`.
- `governance lint`: 43 contracts scanned, 0 errors (both new contracts included).

## Known limits

- The scanner stays heuristic: explicit glob patterns plus a `doc_type` filter
  for `docs/specs/`. It does not perform full content classification, so a novel
  planning-doc location outside the known globs is out of scope until added.
- Resolved/stale baseline entries are surfaced but not auto-pruned.
- Invalid exemptions block but are not auto-fixed.

## Follow-up

- Auto-remediation: prune resolved baseline entries and/or post a PR comment with
  the report summary.
- Optionally widen scan coverage as new planning-doc locations appear.
- Promotion of additional planning-doc types into the `doc_type` filter set.

This task controls known drift and blocks new drift; it is **not** a claim that
every planning artifact is perfectly registered.
