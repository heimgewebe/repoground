# Token Budget Report v1 Proof

Status: done  
Task: `TASK-TOKEN-BUDGET-REPORT-001`

## Result

This slice adds a diagnostic Token Budget Report for bundle manifests.

Implemented surfaces:

- `merger/lenskit/core/token_budget_report.py`
- `merger/lenskit/cli/cmd_token_budget.py`
- `lenskit token-budget report --bundle-manifest <path>`
- `merger/lenskit/tests/test_token_budget_report.py`

## Behavior

The report reads `artifacts[].bytes` from a bundle manifest and estimates rough token cost with a configurable byte divisor. The default estimate is deliberately simple: `ceil(bytes / 4.0)`.

It reports total artifact bytes, estimated tokens, budget remaining or overflow, per-role totals, largest artifacts, warnings when the estimate exceeds the configured context budget, and fail status for malformed artifact byte metadata.

## Boundaries

The report is diagnostic only. It does not use a model tokenizer, does not assert exact token counts, does not prove model-context fit, does not choose which artifacts to include, and does not establish repository understanding or answer correctness.

No bundle emission, manifest role, LLM integration, truncation policy or export decision is introduced in this slice.

## Validation

```text
python3 -m pytest -q merger/lenskit/tests/test_token_budget_report.py
# 5 passed

python3 -m py_compile merger/lenskit/core/token_budget_report.py merger/lenskit/cli/cmd_token_budget.py merger/lenskit/cli/main.py merger/lenskit/tests/test_token_budget_report.py
# passed
```

A focused Ruff command was attempted locally but blocked by the operational filter. CI remains the authoritative style gate for the PR.
