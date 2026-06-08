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
- `--ratchet` partitions the current scan against the baseline:
  - `known_findings`: id present in baseline → tolerated.
  - `new_findings`: id absent from baseline → **blocking**.
  - `resolved_findings`: baseline id absent from the current scan → stale,
    **non-blocking** (surfaced for later baseline pruning).
  - `invalid_exceptions`: always **blocking**, regardless of baseline.
- CI does not enforce "all registered". It enforces **no new drift**.

## CI behavior

`.github/workflows/task-index.yml` (job `planning-registration`):

1. Runs the ratchet:
   `check_planning_registration.py --ratchet --baseline docs/tasks/planning-registration-baseline.json --format json`,
   capturing the exit code without aborting the job.
2. Writes a GitHub step summary with current / baseline / known / new / resolved
   findings and invalid exceptions.
3. Uploads `planning-registration-report.json` as a build artifact.
4. Re-exits with the captured ratchet code, so the report/summary are always
   published even when the gate fails.

No network or GitHub-API dependency; no time-of-day logic in the gate.

## Exit codes

| Code | Meaning |
| ---- | ------- |
| 0 | No new blocking findings (ratchet), or scan/update-baseline success. |
| 1 | Ratchet: new findings or invalid exceptions present. |
| 2 | Usage/config error: invalid baseline, schema mismatch, broken input, mutually exclusive flags (`--ratchet` + `--update-baseline`), or `--ratchet`/`--update-baseline` without `--baseline`. |

JSON (`--format json`) is emitted on **stdout only**; human-readable output goes
to **stderr** in JSON mode so stdout stays parseable.

## Local commands

```bash
# Refresh the baseline from the current tree (deterministic, exit 0)
python3 scripts/docmeta/check_planning_registration.py \
  --update-baseline \
  --baseline docs/tasks/planning-registration-baseline.json \
  --format json

# Run the ratchet exactly like CI
python3 scripts/docmeta/check_planning_registration.py \
  --ratchet \
  --baseline docs/tasks/planning-registration-baseline.json \
  --format json \
  > /tmp/planning-registration-report.json
python3 -m json.tool /tmp/planning-registration-report.json >/dev/null
```

## Test evidence

- `merger/lenskit/tests/test_planning_registration_ratchet.py` (20 tests):
  scanner detection, line-number-independent ids, baseline toleration, new-drift
  blocking, resolved/stale handling, invalid/expired exemptions blocking, valid
  exemption suppression, JSON report schema validation (scan/ratchet/
  update_baseline modes), workflow static wiring, and exit-code-2 config errors.
- `scripts/docmeta/tests/test_check_planning_registration.py` (27 tests): the
  pre-existing scanner contract, unchanged and still green.
- Real-repo ratchet run: exit 0, report validates against
  `merger/lenskit/contracts/planning-registration-report.v1.schema.json`.
- `governance lint`: 42 contracts scanned, 0 errors (new report contract
  included).

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
