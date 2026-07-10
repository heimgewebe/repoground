# Ruff Scope Ratchet v1 Proof

## Status

- Task: `TASK-LINT-RUFF-SCOPE-001`
- Slice type: repo-wide lint-scope ratchet, no broad cleanup
- Date: 2026-07-08

## Ausgangsbefund

`lint.yml` pinned Ruff at `ruff==0.15.13` and ran:

```bash
ruff check --select=F401,F811 --exclude='**/fixtures/**' .
```

`requirements-dev.txt` already pins the same Ruff version. The repository had no checked-in CI-specific Ruff configuration, so the repo-wide CI scope lived only in the workflow command.

## Entscheidung

This slice makes the current repo-wide CI gate explicit in a checked-in `ruff-ci.toml`:

- `target-version = "py312"`
- `extend-exclude = ["**/fixtures/**"]`
- `lint.select = ["F401", "F811"]`

The GitHub Actions repo-wide lint job and the local contributing instructions both run:

```bash
ruff check --config ruff-ci.toml .
```

That means the repo-wide local lint command and the repo-wide CI lint job use the same checked-in scope.

## Follow-up: preserve Ruff built-in exclusions (2026-07-10)

The first checked-in version used top-level `exclude`. Ruff treats that setting as a replacement
for its built-in exclusion list, which made `.git` discoverable when a ref or log path ended in
`.py`. The corrected configuration uses `extend-exclude` instead:

- Lenskit's intentional `**/fixtures/**` exclusion remains active.
- Ruff's built-in exclusions, including `.git`, remain active.
- The narrow `F401`/`F811` rule selection and the path-scoped-job boundary are unchanged.

A regression test creates invalid Python-shaped files under both `.git` and `tests/fixtures`,
then proves that Ruff discovers only the ordinary source file and completes successfully.

## Guardrail: no global narrowing

The narrow `F401`/`F811` ratchet is intentionally isolated in `ruff-ci.toml`. There is no global `ruff.toml` in this slice.

This preserves existing path-scoped CI jobs that run bare commands such as:

```bash
ruff check <paths>
```

Those jobs keep Ruff's default rule selection unless they explicitly opt into another config. The repo-wide ratchet therefore does not weaken path-scoped Ruff gates.

## Codex review follow-up

Codex flagged that a global `[lint].select = ["F401", "F811"]` would be inherited by every bare `ruff check`, including path-scoped jobs such as graph and lens model checks. That would unintentionally reduce those jobs from Ruff defaults to only `F401`/`F811`.

Addressed by moving the narrow selection from global `ruff.toml` to repo-wide-only `ruff-ci.toml`, and by making only `.github/workflows/lint.yml` call it explicitly.

## Ratchet-Grenze

The first ratchet step preserves the existing repo-wide gate: unused imports (`F401`) and redefined-while-unused (`F811`) outside fixtures.

The known broader repo-wide Ruff findings remain outside this PR. Any expansion to rules such as `E701`, `E402`, `E741`, `E731`, `F841`, `E711`, or `E712` needs a separate measured slice with its own proof and CI evidence.

## STOP / Nicht-Ziele

This proof does not establish:

- that default `ruff check` is clean repository-wide under Ruff's wider default rule set,
- that `E701`, `E402`, `E741`, `E731`, `F841`, `E711`, or `E712` are fixed repository-wide,
- that a formatting policy is introduced,
- that tests are sufficient,
- that runtime behavior is correct,
- that the repository is free of further lint debt,
- that path-scoped Ruff jobs should use the narrow repo-wide ratchet scope.

## Validation

Observed validation on 2026-07-08:

```bash
python3 -m json.tool docs/tasks/index.json >/tmp/lenskit-task-index.json
python3 -m pip install -r requirements-dev.txt
python3 -m ruff check --config ruff-ci.toml .
python3 -m ruff check merger/lenskit/architecture/graph_index.py merger/lenskit/architecture/graph_source_validation.py merger/lenskit/cli/cmd_architecture.py merger/lenskit/retrieval/query_core.py
git diff --check
```

Result: the repo-wide scoped Ruff gate passed with `ruff-ci.toml`, and the path-scoped bare Ruff check passed without relying on a global narrow config. No pytest run is claimed for this slice.

## Follow-up validation (2026-07-10)

```bash
python3 -m pytest -q merger/lenskit/tests/test_ruff_ci_config.py
ruff check --config ruff-ci.toml .
ruff check merger/lenskit/tests/test_ruff_ci_config.py
git diff --check
```

Result: `1 passed`; both Ruff commands reported `All checks passed!`. The focused test proves
that invalid `.py`-named files under `.git` and `tests/fixtures` are omitted while an ordinary
source file remains discoverable. No full pytest-suite result is claimed by this local follow-up.
