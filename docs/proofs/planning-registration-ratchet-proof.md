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
drift and control-file errors, plus (c) a contract-stable frontmatter exemption
flow. This task delivers that control plane without forcing "everything must be
perfect".

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
- **Baseline integrity (load-time, `load_baseline()`)**: because the CI runner
  does not install `jsonschema`, the runtime loader enforces the baseline
  contract invariants manually (the contract schema is still validated in
  tests). On any violation it raises `BaselineError` → **exit 2**:
  - `schema` and `generator` must equal the contract constants; `generated_at`
    must be an ISO-8601 UTC timestamp (`YYYY-MM-DDThh:mm:ssZ`).
  - No unexpected top-level fields and no unexpected per-entry fields
    (mirrors `additionalProperties: false`).
  - Every entry carries all required fields with non-empty `code`/`path`/`kind`.
  - **ID integrity**: `entry["id"]` must equal
    `compute_finding_id(code, path, kind)`. A pattern-valid but computationally
    wrong id is rejected, so a hand-edited/forged baseline cannot tolerate a
    finding under a foreign identity.
  - No duplicate entry ids; entries must already be in canonical
    `(path, code, id)` order.
- `--ratchet` partitions the current scan against the baseline:
  - `known_findings`: id present in baseline → tolerated.
  - `new_findings`: genuine new drift, id absent from baseline → **blocking**.
    `invalid_exceptions` and `control_errors` are **not** counted here; each is a
    separate blocking class.
  - `resolved_findings`: baseline id absent from the current scan → stale,
    **non-blocking** (surfaced for later baseline pruning).
  - `invalid_exceptions`: broken/expired frontmatter exemptions, always
    **blocking** (exit 1), regardless of baseline, **never** in `new_findings`.
  - `control_errors`: `CONTROL_FILE_MISSING` / `CONTROL_FILE_PARSE_ERROR`. The
    tool cannot read its own control structure, so the ratchet comparison is
    unreliable: these **always block with exit 2** (config-style), are excluded
    from `new`/`known`, and are never baseline-eligible. Surfaced in the report
    under the optional `control_errors` array.
- **`--update-baseline` never grandfathers a defective state**: if the current
  scan contains control errors it exits **2** and writes nothing; if it contains
  invalid exceptions it exits **1** and writes nothing. A baseline is written
  only from a clean scan, so a broken structure can never be stamped "resolved".
- CI does not enforce "all registered". It enforces **no new drift, no invalid
  exemptions, and no control-file errors**.

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
produced new drift, invalid exceptions, or a control/config error.

No network or GitHub-API dependency; no time-of-day logic in the gate.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | No new blocking findings, invalid exceptions, or control errors (ratchet); or scan/update-baseline success. |
| 1 | Ratchet: new findings or invalid exceptions present. |
| 2 | Config/control error: invalid baseline, control-file errors (missing/unparseable control files), schema mismatch, broken input, mutually exclusive flags, missing `--baseline`, or `--ratchet`/`--update-baseline` without `--baseline`. |

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

- `merger/lenskit/tests/test_planning_registration_ratchet.py`:
  scanner detection, line-number-independent ids, baseline toleration, new-drift
  blocking, resolved/stale handling, invalid/expired exemptions blocking (including
  the key invariant that `invalid_exceptions` do **not** appear in `new_findings`),
  direct `partition_ratchet()` invariant test with unfiltered `run_checks()` output,
  valid exemption suppression, JSON report schema validation (scan/ratchet/
  update_baseline modes), committed-baseline validated against the baseline
  contract schema, baseline eligibility enforcement (`build_baseline()` retains only
  `UNREGISTERED_PLANNING_ARTIFACT`; control-file codes and invalid exceptions
  excluded at write time and rejected at load time; baseline schema `const`
  rejects non-eligible codes), **baseline load-time integrity** (forged/mismatched
  entry id → exit 2; unexpected top-level field, wrong generator, malformed
  `generated_at`, unexpected entry field, duplicate ids, non-canonical order →
  exit 2; committed baseline loads under the hardened validator), **`--update-baseline`
  refuses defective state** (invalid exception → exit 1 & no file written; control
  error → exit 2 & no file written; invalid exception never grandfathered into
  entries), **control-file errors as their own class** (ratchet exit 2, excluded
  from `new`/`known` partition, surfaced in `control_errors`, report still validates
  against schema), workflow static wiring (step-isolated YAML assertions: ratchet
  step uses `python3 -m` module form, `code=0` init, `|| code=$?` capture, and
  `GITHUB_OUTPUT` write; enforce step is fail-closed with explicit missing-output
  check → exit 2 and `exit "${code}"` propagation), exit-code-2 config errors,
  `load_baseline()` runtime validation (empty code/path/kind, invalid id pattern,
  missing required field, non-eligible code → exit 2), Bash-semantics tests under
  `set -euo pipefail` (prove `|| code=$?` captures exit codes without aborting;
  enforce step exits 2 on empty output; enforce step propagates codes 0/1/2 unchanged).
- `scripts/docmeta/tests/test_check_planning_registration.py`: the
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
- Tab characters in `planning_registration:` block indentation are not detected
  or rejected; YAML prohibits tabs in indentation, so this is an authoring error.
  A malformed tab-indented block may be silently missed (not parsed as an
  exemption), which is conservative (drift detected rather than falsely exempted).
  Full YAML parsing is deferred to a follow-up parser-hardening task.

## Follow-up

- Auto-remediation: prune resolved baseline entries and/or post a PR comment with
  the report summary.
- Optionally widen scan coverage as new planning-doc locations appear.
- Promotion of additional planning-doc types into the `doc_type` filter set.

This task controls known drift and blocks new drift, invalid exceptions, and
control/config errors; it is **not** a claim that every planning artifact is
perfectly registered.
