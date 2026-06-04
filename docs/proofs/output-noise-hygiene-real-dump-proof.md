# TASK-NOISE-002 Proof: Real-Dump Noise Hygiene Runtime / Surface Check

## Problem

`TASK-NOISE-001` made the scanner/output path fixture-green for known local
scratch noise, especially:

```text
.tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json
```

A later operational `rlens` dump contradicted that expected state: the scratch
path was still visible in emitted artifacts, `output_health` did not expose
`checks.excluded_noise` / `checks.noise_hygiene`, and
`post_emit_health.noise_hygiene.available` was `false` while
`bundle_surface_validation` still passed. This task treats that contradiction as
runtime evidence first, not as a documentation problem.

## Diagnostic Gate Findings

Commands run in this workspace:

```bash
git status --short
git branch --show-current
git fetch --prune origin
git rev-parse HEAD
git log --oneline -8 --decorate
systemctl --user status rlens --no-pager || true
rg -n "_BUILD_AND_CACHE_DIRS|NOISE_HYGIENE|excluded_noise|noise_hygiene|\.tmp" \
  merger/lenskit/core/merge.py \
  merger/lenskit/core/output_health.py \
  merger/lenskit/core/post_emit_health.py
```

Observed in the container:

- `git status --short` was clean before patching.
- The branch was `work` at `7c1dd0cacdc32332f36b89c0af778c7d8688a133`, whose
  recent history includes `TASK-NOISE-001` (`826ef9c0 Add .tmp noise exclusion
  and bounded excluded_noise diagnostics`).
- `git fetch --prune origin` could not run because this checkout has no
  configured `origin` remote.
- `systemctl --user status rlens --no-pager` could not reach a user bus in this
  container (`Failed to connect to bus: No medium found`), so this environment
  cannot restart the real `rlens.service` or produce a real service dump.
- The expected code markers are present in the checkout: `_BUILD_AND_CACHE_DIRS`
  includes `.tmp`, `NOISE_HYGIENE_*` constants exist, `scan_repo()` records
  `excluded_noise`, `write_reports_v2()` passes it to `write_output_health()`,
  and `post_emit_health` consumes the validated output-health signal.

Because the real service is unavailable here, this proof does **not** claim a
fresh production `rlens.service` dump. It records a bounded code-path diagnosis
and adds a smoke guard that must be run on the operator host after restarting the
service.

## Runtime-Drift vs Codepath-Lücke Diagnosis

Code-path inspection commands:

```bash
git grep -n "scan_repo(" -- merger/lenskit/service merger/lenskit/core merger/lenskit/cli
git grep -n "write_reports_v2(" -- merger/lenskit/service merger/lenskit/core merger/lenskit/cli
git grep -n "prescan_repo\|scan_repo\|include_hidden\|SKIP_DIRS" -- merger/lenskit/service merger/lenskit/core
```

Findings:

1. The real service runner path is `merger/lenskit/service/runner.py`.
2. The runner calls `scan_repo()` from `merger/lenskit/core/merge.py` for each
   selected source and then passes those summaries into `write_reports_v2()`.
3. The web prescan endpoint calls `prescan_repo()` for UI structure previews,
   but the dump writer path does not use prescan output as the source of emitted
   artifacts.
4. `prescan_repo()` also builds its ignore set from `SKIP_DIRS`; therefore `.tmp`
   is ignored in the web preview path as well.
5. `reading_lenses.file_index`, `Structure`, `dump_index_json`, sidecar JSON,
   chunk index, canonical markdown, and the bundle manifest are produced by
   `write_reports_v2()` from the filtered `repo_summaries`.
6. `write_reports_v2()` aggregates `summary["excluded_noise"]` and passes the
   bounded diagnostic to `write_output_health(excluded_noise=...)`.
7. `post_emit_health` reads the `output_health` artifact from the manifest and
   surfaces `noise_hygiene` only when output-health supplied a validated signal;
   it does not synthesize the signal independently.

This supports **runtime drift as the likely root cause** for the observed
operator-host dump: a long-running `rlens.service` can keep emitting from an old
module snapshot even after the repository was updated. The container cannot
complete the final target proof because the real user service and merges
directory are not present.

## Fix Applied

No core scanner or writer code was changed in this slice. The smallest safe fix
in this environment is to harden the existing post-merge service smoke:

```text
scripts/rlens-post-merge-surface-smoke.sh
```

The smoke now additionally verifies the latest manifest under the supplied
merges directory:

- `.tmp/forensic-preflight-ci-canary` is absent as a structured emitted
  file/chunk/index path. The smoke parses JSON/JSONL path fields and selected
  Markdown file markers/tables; it does not fail merely because documentation or
  tests mention the scratch path as explanatory prose.
- `output_health` exists and has `checks.excluded_noise` plus
  `checks.noise_hygiene`.
- `output_health.checks.excluded_noise.count` is explicitly present and is an
  exact integer (JSON booleans are not accepted as counts); it may be `0` for a
  clean repository.
- `output_health.checks.noise_hygiene.available` must be `true` whenever the
  current writer path is active, and
  `output_health.checks.noise_hygiene.excluded_noise_count` must be an integer
  matching `output_health.checks.excluded_noise.count`.
- `post_emit_health.noise_hygiene` exists,
  `post_emit_health.noise_hygiene.available` must be `true`, and its
  `excluded_noise_count` must match the output-health count.

The smoke does **not** require `excluded_noise.count > 0`; a clean repository can
legitimately have no excluded noise. `count=0` means the diagnostic path ran and
found no known noise to exclude. It does not make `noise_hygiene.available=false`
acceptable. The smoke verifies that the new diagnostic surface is complete, typed,
and internally consistent when the current writer path is active.

## Local Runner-Equivalent Proof

Since `systemctl --user` is unavailable in this container, the smoke was tested
against a runner-equivalent temporary bundle generated through the same core
calls used by the service runner (`scan_repo()` + `write_reports_v2()`). The
fixture included:

- `.tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json`
- `.github/workflows/guard.yml`
- `.wgx/profile.yml`

Command shape:

```bash
python3 - /tmp/<tmpdir> <<'PY'
# create fixture repo with .tmp, .github, and .wgx
# call scan_repo(..., include_hidden=True)
# call write_reports_v2(..., extras=ExtrasConfig(json_sidecar=True), output_mode="dual")
PY
bash scripts/rlens-post-merge-surface-smoke.sh /tmp/<tmpdir>/merges
```

Observed smoke output included:

```json
{
  "noise_surface_check": "pass",
  "structured_path_absent": ".tmp/forensic-preflight-ci-canary",
  "checked_roles": [
    "agent_reading_pack",
    "canonical_md",
    "chunk_index_jsonl",
    "dump_index_json",
    "index_sidecar_json"
  ],
  "excluded_noise_count": 1,
  "output_health_noise_available": true,
  "post_emit_health_noise_available": true
}
```

This proves the hardened smoke detects the current-code surface, tolerates
legitimate prose references to the canary path, and would fail a fresh dump that
still leaks the canary scratch path as a structured file/chunk/index path.

## Operator Target Proof — PASS

The missing operator-host proof was completed on 2026-06-04.

Observed sequence on the operator host:

```text
repo: /home/alex/repos/lenskit
branch: main
HEAD: ea8059c57fa550d077bcde811580ebcc82daeba3
git pull --ff-only: Bereits aktuell.
rlens.service restart: 2026-06-04 09:04:48 CEST
new service PID: 1724029
new manifest: /home/alex/repos/merges/lenskit-max-260604-0705_merge.bundle.manifest.json
manifest_mtime: 2026-06-04 09:05:17.204580167 +0200
```

The post-merge surface smoke was then run against the real merges directory:

```bash
bash scripts/rlens-post-merge-surface-smoke.sh /home/alex/repos/merges
```

The smoke passed and reported:

```json
{
  "noise_surface_check": "pass",
  "structured_path_absent": ".tmp/forensic-preflight-ci-canary",
  "checked_roles": [
    "agent_reading_pack",
    "canonical_md",
    "chunk_index_jsonl",
    "dump_index_json",
    "index_sidecar_json"
  ],
  "excluded_noise_count": 450,
  "output_health_noise_available": true,
  "post_emit_health_noise_available": true
}
```

The manifest runtime block showed the restarted service loading from the expected
checkout:

```text
module_file: /home/alex/repos/lenskit/merger/lenskit/core/merge.py
package_root: /home/alex/repos/lenskit
python_version: 3.10.12
git_commit: ea8059c57fa550d077bcde811580ebcc82daeba3
git_dirty: false
```

Conclusion: the observed stale real dump was explained by runtime drift from a
long-running `rlens.service`. After restart, the current service path emits the
Noise-Hygiene surface correctly. No additional core scanner/writer change was
needed for this task.


## Boundaries

- No full `.gitignore` semantics were added.
- No retrieval-ranking changes were made.
- No `forensic_strict` blocking promotion was made.
- No claim-map contract changes were made.
- No broad dotdir exclusion was added; `.github/` and `.wgx/` remain dumpable
  repository context.
- This proof is intentionally marked as environment-limited until a real
  operator-host `rlens.service` dump is produced after restart.
