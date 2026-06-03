# A2 Proof: Output Noise Hygiene / Cache Exclusion Guard

**PR:** #694  
**Branch:** `claude/laughing-shannon-k7n2O`

## Problem Statement

Prior to A2, skip/noise directory logic existed in two parallel forms with no binding constraint:
- `SKIP_DIRS` in `merge.py`: authoritative set used during repo traversal
- Inline `noisy_dirs` tuple in `is_noise_file()`: parallel classification heuristic

This created silent drift: cache/tool directories like `.mypy_cache`, `.ruff_cache`, `.cache`, `coverage` were in one list but not the other, leaving output surfaces (canonical_md, chunk_index, agent_reading_pack) vulnerable to inconsistent filtering.

## Solution

**Single canonical source:** `_BUILD_AND_CACHE_DIRS` (frozenset)

All build-artefact and tool-cache directory names are defined once:
```python
_BUILD_AND_CACHE_DIRS: frozenset[str] = frozenset({
    ".tmp", "node_modules", ".svelte-kit", ".next",
    "dist", "build", "target",
    ".venv", "venv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "coverage",
})
```

Both downstream uses are now **derived**, not duplicated:
- `SKIP_DIRS: frozenset[str] = _BUILD_AND_CACHE_DIRS | frozenset({".git", ".idea", ".DS_Store"})`  
  (adds VCS/IDE/system noise dirs that are skip-only, not noise-classified)
- `is_noise_file()` uses `_BUILD_AND_CACHE_DIRS` directly via exact parent-directory component matching  
  (prevents substring false positives like `src/mycoverage/` matching `coverage`)

Drift is now structurally **impossible**: changing `_BUILD_AND_CACHE_DIRS` automatically propagates to both uses.

### Included Cache/Scratch Dirs

All of the following are now excluded from traversal and marked as noise:
- `.tmp/` (local scratch and CI-canary artifacts)
- `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` (Python tooling)
- `.cache/` (generic cache)
- `coverage/` (test coverage artifacts)
- `node_modules/`, `.svelte-kit/`, `.next/` (frontend tooling)
- `dist/`, `build/`, `target/`, `venv/`, `.venv/` (build outputs and virtual envs)
- `__pycache__/` (Python bytecode)

### Intentionally Preserved

The following **are not** broadly excluded and remain in output when `include_hidden=True`:
- `.github/workflows/`, `.github/CODEOWNERS` (CI/automation config)
- `.wgx/` (Wgx agent config)
- `.ai-context.yml` (AI context hints)
- Other repo config/metadata files

This prevents over-filtering that would remove meaningful project context.

## Validation

### Traversal Exclusion (scan_repo)

Test: `test_scan_repo_excludes_cache_dirs`

Creates a real temp filesystem with all the cache dirs above plus a real source file (`src/main.py`).  
Calls `scan_repo()` and verifies:
- ✅ Source file is in the result
- ✅ No cache dir files appear in the result

This directly proves that `canonical_md` and `chunk_index` (built from scan_repo output) are clean.

### Hidden-Path Preservation

Test: `test_scan_repo_preserves_intentional_hidden_paths`

Creates `.github/workflows/ci.yml`, `.wgx/config.yml`, `.ai-context.yml` and verifies they appear when `include_hidden=True`.

### Manifest Annotation

Test: `test_manifest_annotates_noise_files_that_bypass_traversal`

Documents that belt-and-suspenders `(noise)` annotation in manifest applies only to files explicitly passed to `iter_report_blocks()` (e.g., in plan-only or test contexts).  
Primary protection is SKIP_DIRS at traversal level.

### False-Positive Prevention

Test: `test_is_noise_file_does_not_match_false_positives_with_substring_names`

Verifies that path-component matching (not substring) prevents misclassification:
- `src/mycoverage/report.md` → NOT noise (even though "coverage" is in `_BUILD_AND_CACHE_DIRS`)
- `src/rebuild/tool.py` → NOT noise (even though "build" is in `_BUILD_AND_CACHE_DIRS`)
- `src/distributions/file.txt` → NOT noise (even though "dist" is in `_BUILD_AND_CACHE_DIRS`)

Ensures that only actual parent-directory names trigger noise classification.

### Bundle-Surface Integration (canonical_md + chunk_index)

Test: `test_noise_dirs_absent_from_generated_bundle_surfaces`

Uses `write_reports_v2()` to generate a complete bundle from a synthetic repo containing:
- `src/main.py` (real source)
- `.cache/pip_wheels.txt` and `coverage/lcov.info` (A2-new noise dirs, with distinct sentinels)
- `.github/workflows/ci.yml`, `.wgx/config.yml`, `.ai-context.yml` (intentional hidden context)

Verifies on generated `canonical_md` and `chunk_index` (JSONL format):
- ✅ `.cache` and `coverage` sentinel content absent from both surfaces
- ✅ `.cache` and `coverage` absent as path components in markdown file markers
- ✅ `pip_wheels.txt` and `lcov.info` filenames absent from all paths
- ✅ `src/main.py` present in both canonical_md and chunk_index file paths
- ✅ Hidden context files (`.github/workflows/ci.yml`, `.wgx/config.yml`, `.ai-context.yml`) present in both surfaces — direct proof, not deferred to scan_repo test

This closes the A2 proof gap from "traversal is clean" to "generated bundle surfaces are demonstrably clean".

### Output Noise Hygiene A2 Regression

Test: `test_standard_dump_excludes_tmp_noise_but_keeps_repo_dotdirs`

Uses `scan_repo()` plus `write_reports_v2()` to generate a complete bundle from a synthetic repo containing:
- `README.md` and `src/app.py` (real content)
- `.tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json` (the observed real-dump leak)
- `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, and `__pycache__/` (tool/cache noise)
- `.github/workflows/guard.yml` and `.wgx/profile.yml` (intentional repository dotdirs)

The test verifies:
- ✅ `.tmp/forensic-preflight-ci-canary/artifacts/forensic-preflight-canary.json` is absent from `canonical_md`, `chunk_index`, the JSON sidecar index, and `agent_reading_pack`
- ✅ `.github/` and `.wgx/` remain present in generated output
- ✅ `output_health.checks.excluded_noise` reports count, samples, and patterns, including `.tmp/`
- ✅ `output_health.checks.noise_hygiene.available=true` when scan diagnostics are supplied; direct `compute_output_health()` callers without scanner context report `available=false`
- ✅ `post_emit_health.noise_hygiene.available=true` and carries the `excluded_noise_count` from validated `output_health`
- ✅ symlinked noise directories (for example `repo/.tmp -> /outside`) are counted as excluded without walking or sampling external target filenames

This closes the earlier deferred diagnostic gap: `.gitignore` can keep local scratch files out of Git, but Lenskit scans the filesystem directly, so dump policy is enforced in scanner traversal and reported in health diagnostics.

## Scope

### What Changed
- Consolidated skip/noise definition via `_BUILD_AND_CACHE_DIRS`
- Added `.cache` and `coverage` to `_BUILD_AND_CACHE_DIRS` / `SKIP_DIRS` (were missing)
- Added `.tmp` to `_BUILD_AND_CACHE_DIRS` / `SKIP_DIRS` for local scratch and CI-canary artifacts
- Updated `is_noise_file()` to use `_BUILD_AND_CACHE_DIRS` via exact parent-directory component matching, preventing substring false positives (e.g., `src/mycoverage/` does not match `coverage`)
- Added bounded `excluded_noise` scan diagnostics (count + capped samples + patterns) surfaced through `output_health.checks.excluded_noise` and `output_health.checks.noise_hygiene`
- Updated `post_emit_health` to inherit validated `output_health` noise-hygiene diagnostics
- Added regression tests covering noise classification, traversal exclusion, hidden-path preservation, manifest annotation, single-source validation, substring false-positive prevention, and `.tmp` exclusion across canonical/chunk/sidecar/agent-pack surfaces

### What Did NOT Change
- Redaction enforcement, detection, or gates
- A5 export behavior or profiles
- `post_emit_health` status model or verdict semantics
- Bundle manifest schema
- Citation or range-ref semantics
- Retrieval ranking or query scoring
- Agent export gates or agent_safe/agent_ready signals

## Boundaries / Deferred Follow-Up

- Full `.gitignore` semantics are intentionally not implemented. Git ignore rules are not automatically dump policy.
- There is no broad “exclude every dotdir” rule; `.github/` and `.wgx/` remain dumpable repository context.
- `excluded_noise` diagnostics are bounded (count cap + sample cap) so large vendor/cache trees do not create unbounded health payloads; skipped noise symlinks are sampled only as repo-relative directory paths and are not traversed.
- A future noise-ratchet or CI-blocking policy for new noise patterns remains a follow-up; this slice only excludes known local scratch/cache directories and reports the exclusion.

## Tests Run

```
pytest merger/lenskit/tests/test_merge_filtering.py       # passed
pytest merger/lenskit/tests/test_output_health.py         # passed
pytest merger/lenskit/tests/test_agent_reading_pack.py    # passed
pytest merger/lenskit/tests/test_retrieval_index.py       # passed
pytest merger/lenskit/tests/test_bundle_manifest_integration.py  # passed
pytest merger/lenskit/tests/test_post_emit_health.py      # passed
pytest merger/lenskit/tests/test_output_noise_hygiene.py   # passed
```

**All listed checks passed.**

(Includes tests for false-positive prevention, single-source validation, and bundle-surface integration.)

---

*Proof document for A2 closure. See PR #694 for commit details.*
