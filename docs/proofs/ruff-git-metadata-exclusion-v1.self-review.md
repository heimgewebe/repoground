# Ruff Git Metadata Exclusion v1 Self-Review

PR: #950
Reviewed implementation head: `6f4dd2ae75699d556b0ebb8913df68997019dcb4`
Base: `b08733158ec5614e58771ef2230829ff51fe7da3`
Reviewed diff SHA-256: `bd09c443d548dbde8d16496eb571a4892921019e7b7940721631a5eed9c28943`
Reviewed diff bytes: `15945`
Source: Bureau live-register event `35`.

## Scope

Reviewed files:

- `ruff-ci.toml`
- `merger/lenskit/tests/test_ruff_ci_config.py`
- `CONTRIBUTING.md`
- `docs/proofs/ruff-scope-ratchet-v1-proof.md`
- `docs/architecture/inconsistencies.md`
- `docs/tasks/board.md`
- `docs/tasks/index.json`

Coverage: all implementation-diff files reviewed.

## Verdict

**PASS**, conditional on the final live PR diff and GitHub CI.

## Review

- `extend-exclude` adds Lenskit's intentional fixture pattern without replacing Ruff's built-in exclusions.
- The repo-wide `F401`/`F811` rule selection is unchanged.
- Bare path-scoped Ruff invocations remain outside `ruff-ci.toml` and retain their existing default rule selection.
- The regression test copies the real config into an isolated project root, places invalid Python-shaped files under `.git` and `tests/fixtures`, and proves that only an ordinary source file is discovered.
- Absolute and relative `--show-files` output is normalized before comparison.
- The test also runs a real Ruff check so parser errors expose either exclusion regressing.
- Board, task index, contributing instructions, architecture notes and the existing proof describe the same current contract.

## Validation

- Focused and planning-control tests: `174 passed`.
- Planning registration ratchet: zero current, new, invalid and control findings.
- `ruff check --config ruff-ci.toml .`: passed.
- Bare path-scoped Ruff check on the regression test: passed.
- `docs/tasks/index.json`: valid JSON.
- `git diff --check`: passed.

## Independent review

Codex CLI `0.142.2`, model `gpt-5.5`, reviewed the immutable diff packet without tools or repository access. Verdict: **PASS**, no findings.

## Non-claims

This change does not broaden the repo-wide lint rules, prove the full Ruff default rule set clean, change runtime behavior, validate every future Ruff release, or establish full-suite success or merge readiness by itself.
