# Validation Note — RepoBrief Workbench Usefulness Diagnostic v1

Prepared in a GitHub connector session without access to `/home/alex/repos/lenskit`.

## Performed

- Reset PR branch to `main` to remove redundant connector marker files.
- Re-created the clean core evidence set.
- Validated the diagnostic JSON text locally before writing it.
- Computed report SHA-256 from the exact JSON text prepared for the file.

## JSON validation

```bash
python3 -m json.tool docs/diagnostics/repobrief-workbench-usefulness-eval-20260709T030000Z.json >/dev/null
```

Result: pass on the prepared JSON text.

Report SHA-256:

```text
216c9d18114e73db94f90f155749cebb2062579e478d838f45d5a132e0636498
```

## Not performed

- No local `pytest` run.
- No local `git diff --check` run.
- No bundle generation.
- No agent answer comparison.
- No merge.

## Required before merge

```bash
git diff --check
```

CI and/or a local checkout should be treated as the merge gate.
