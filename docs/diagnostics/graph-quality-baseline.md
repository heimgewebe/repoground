# Graph Resolution and Layer Goldset v1.2 Baseline

## Status

G4c-2 connects the explicit source-root contract to the static Python graph producer. The goldset supplies `duplicate_case`, `namespace_case`, `package_case`, and `src_layout/src` as additional import roots. No root is inferred from a directory name.

The repository root remains implicit. Declared roots add module-name candidates relative to their directories. The producer validates the roots against the selected repository and sorts them before use, so list order has no precedence meaning.

## Measured transition

| Metric | G4b v1.1 | G4c v1.2 |
| --- | ---: | ---: |
| Local resolution recall | 5 / 7 = 0.714286 | 7 / 7 = 1.0 |
| External preservation accuracy | 3 / 3 = 1.0 | 3 / 3 = 1.0 |
| Layer assignment accuracy | 8 / 8 = 1.0 | 8 / 8 = 1.0 |
| Unknown file-layer share | 10 / 17 = 0.588235 | 10 / 17 = 0.588235 |
| Parse failures handled | 1 / 1 = 1.0 | 1 / 1 = 1.0 |

The two new local hits are bounded:

- `acme.service` resolves to `src_layout/src/acme/service.py`;
- `acme.alpha` resolves to `namespace_case/acme/alpha.py`.

Existing external, layer, and parse-failure cases remain green.

## Ambiguity rule

Both `duplicate_case` and `package_case` expose a distinct `mod.py` as module `mod`. A local target is emitted only when one repository file claims the module name. Therefore `import mod` remains `module:mod`, and reversing root order produces the same graph.

## Validation boundary

A declaration fails closed when a root is empty, duplicated, absolute, noncanonical, missing, or outside the repository after path resolution. An omitted or empty declaration preserves previous graph semantics apart from `generated_at`.

Relative-import source context remains repository-relative. This slice adds absolute module-name candidates only.

## Non-claims

This baseline does not establish runtime import behavior, effective `sys.path`, installed-package state, runtime causality, graph completeness, retrieval benefit, change impact, test sufficiency, automatic bundle configuration, or default-ranking readiness.
