# Python Call Graph Goldset and Promotion Gate v1

Bureau task: `RPU-V1-T024`

## Scope

This slice evaluates the existing conservative Python call graph. It does not
change producer resolution rules or promote call-graph context into the default
agent route.

The fixed goldset covers 13 scored categories:

- direct calls;
- imported-name aliases and module aliases;
- direct recursion;
- same-class methods;
- lexical shadowing and callback parameters;
- decorator and default-argument calls;
- higher-order dynamic dispatch;
- an ambiguous negative control;
- a German Unicode identifier and UTF-8 literal;
- local constructor relations.

Python is the scored producer. The Unicode case checks encoding and identifier
handling; it is not evidence for a multilingual call-graph implementation.

## Metrics and gate

The evaluator reports these dimensions separately:

- S1 precision and target recall;
- false-positive classes, false negatives and unresolved share;
- serialized call-record bytes and measured build time;
- baseline versus graph context paths;
- baseline versus graph tool calls;
- deterministic fixed navigation-task outcomes.

The registered promotion checks are:

- S1 precision at least `0.97`;
- target recall `1.0` on the fixed goldset;
- at least `0.40` aggregate context-path reduction at equal or better recall;
- no scored case or navigation-task regression.

A wrong S1 target counts as both a false positive and a false negative. This
prevents a confidently resolved but incorrect edge from preserving either
precision or recall.

## Navigation-usefulness boundary

The navigation cases reuse the existing `agent_impact_eval` contract. They are
deterministic fixed navigation tasks, not an LLM quality experiment. The report
therefore records task outcomes and compression while explicitly refusing to
claim general agent-quality improvement or answer correctness.

The fixed path surface is expected to reduce aggregate context paths from `11`
to `5` and tool calls from `9` to `3`, with unchanged target recall. CI generates
the full JSON report so byte count and wall-clock build time remain observable
without turning machine-dependent timing into a committed exact baseline.

## Promotion semantics

Passing thresholds yields only `eligible_for_review=true`.
`default_promoted` remains `false` and the separate decision authority is the
Bureau. The report also preserves the nonclaims for completeness, runtime
reachability, dynamic dispatch, test sufficiency, review completeness and merge
readiness.

## Reproduction

```bash
python -m merger.repoground.architecture.call_graph_quality_eval \
  --goldset docs/retrieval/python_call_graph_goldset.v1.json \
  --out python-call-graph-quality-report.json
python -m pytest -q \
  merger/repoground/tests/test_python_call_graph_goldset.py \
  merger/repoground/tests/test_python_call_graph.py \
  merger/repoground/tests/test_agent_impact_refinement.py
```

The dedicated `Python Call Graph Goldset` workflow validates JSON, emits the
reviewable report, runs focused producer and impact-evaluator regressions,
checks Ruff and rejects structural diff errors.
