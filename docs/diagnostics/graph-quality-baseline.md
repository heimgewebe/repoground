# Graph Resolution and Layer Goldset v1 Baseline

## Status

This is the committed diagnostic baseline for the first G4 implementation slice. G4a changes the static Python graph producer, then regenerates the same versioned goldset result without changing graph ranking or enabling graph use by default.

## Measurement surface

The versioned goldset is `docs/retrieval/graph_quality_goldset.v1.json`. Its fixture repository covers:

- absolute local `from` imports from CLI, tests, and a worker;
- one relative local import;
- external modules that must remain external;
- path-based target layers `cli`, `core`, `test`, `infra`, and `unknown`.

The evaluator is `merger/lenskit/architecture/graph_quality_eval.py`. It emits deterministic case-level results and aggregate metrics. The committed machine-readable result is `docs/diagnostics/graph-quality-baseline.v1.json`.

## Before and after G4a

| Metric | Before | G4a |
| --- | ---: | ---: |
| Local resolution recall | 1 / 4 = 0.25 | 4 / 4 = 1.0 |
| External preservation accuracy | 2 / 2 = 1.0 | 2 / 2 = 1.0 |
| Layer assignment accuracy | 1 / 6 = 0.166667 | 6 / 6 = 1.0 |
| Unknown layer share among file nodes | 1.0 | 1 / 6 = 0.166667 |

All declared local-resolution cases now produce `file:` edges. The two external controls remain `module:` nodes. Five explicit path categories receive their expected layer; the unmatched `misc/helpers.py` control remains `unknown`.

## Implemented boundary

Local resolution is deliberately conservative:

- Python paths are indexed by repository-relative module name;
- both `<module>.py` and `<package>/__init__.py` participate;
- a name resolves locally only when exactly one path claims it;
- ambiguous names remain external rather than selecting an arbitrary file;
- unresolved absolute and relative imports retain external module representations;
- imported symbols are not treated as modules unless a matching local module path exists.

Layer assignment uses explicit path segments with deterministic precedence: test paths first, then `cli`, `core`, and infrastructure segments (`infra`, `scripts`, `tools`). Other paths remain `unknown`.

The goldset metric `unknown_file_share` counts file nodes only. The existing architecture-graph field `coverage.unknown_layer_share` retains its broader historical meaning and may also count external nodes; G4a does not silently redefine that contract.

## Interpretation

The goldset is now saturated, so a larger number alone cannot justify additional heuristics. G4b should first add falsifiable cases for `src/` layouts, namespace packages, package imports, ambiguous roots, and invalid syntax. Only then should the producer expand beyond this boundary.

This small synthetic goldset is a contract-like regression surface, not a representative measurement of all Python packaging layouts. Perfect fixture scores do not establish general graph quality.

## Non-claims

This baseline does not establish runtime import behavior, runtime causality, graph completeness, layer ontology completeness, retrieval benefit, change impact, test sufficiency, or readiness to enable graph ranking by default.
