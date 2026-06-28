# Graph Resolution and Layer Goldset v1 Baseline

## Status

This is the committed diagnostic baseline required before G4 changes local-module resolution or graph layers. It measures the current static Python graph producer without changing its behavior.

## Measurement surface

The versioned goldset is `docs/retrieval/graph_quality_goldset.v1.json`. Its fixture repository covers:

- absolute local `from` imports from CLI, tests, and a worker;
- one relative local import already handled by the current heuristic;
- external modules that must remain external;
- path-based target layers `cli`, `core`, `test`, `infra`, and `unknown`.

The evaluator is `merger/lenskit/architecture/graph_quality_eval.py`. It emits deterministic case-level results and aggregate metrics. The committed machine-readable result is `docs/diagnostics/graph-quality-baseline.v1.json`.

## Baseline

| Metric | Result |
| --- | ---: |
| Local resolution recall | 1 / 4 = 0.25 |
| External preservation accuracy | 2 / 2 = 1.0 |
| Layer assignment accuracy | 1 / 6 = 0.166667 |
| Unknown layer share among file nodes | 1.0 |

The only resolved local case is `from .utils import helper`. Absolute local imports remain represented as external module strings. Every file node is currently assigned `unknown`; the single layer hit is the fixture whose expected layer is intentionally `unknown`.

## Interpretation

The next G4 implementation may improve local resolution or layer assignment only by updating the producer and regenerating this baseline. A metric increase is not sufficient by itself: external preservation must not regress, and every changed case must remain inspectable.

This small synthetic goldset is a contract-like regression surface, not a representative measurement of all Python packaging layouts. Later versions should add namespace packages, `src/` layouts, package `__init__.py` imports, ambiguous module names, and invalid syntax only when each case has an explicit expected semantic outcome.

## Non-claims

This baseline does not establish runtime import behavior, runtime causality, graph completeness, layer ontology completeness, retrieval benefit, change impact, test sufficiency, or readiness to enable graph ranking by default.
