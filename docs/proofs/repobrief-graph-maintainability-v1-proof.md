# RepoBrief Graph and Maintainability Ratchets v1 — Proof

## Binding

- Base commit: `0d601df241e2dab9915bf3df6ebd023f410b1750`
- Policy: `config/repobrief-graph-maintainability.v1.json`
- C901 baseline: `config/repobrief-c901-baseline.v1.json`
- Bound measurement: `docs/proofs/repobrief-graph-maintainability-v1.measurement.json`
- Gate: `scripts/ci/check_graph_maintainability.py`

## Established

- The pre-change repository measurement had 507 file nodes, 64 unknown file layers and an unknown-file share of `0.126232741617357` (12.62%).
- The candidate measurement has 512 file nodes, zero unknown file layers and zero unknown product layers.
- External modules remain distinct nodes: 251 external nodes versus 512 file nodes.
- Entrypoints are projected separately as product (15), test (20), fixture (3) and script (23); the projection sum equals the total of 61.
- The entrypoint scanner was decomposed so the new code has no C901 finding.
- The repository's 213 existing C901 findings are frozen function-by-function with a current maximum of 170. This records debt; it does not declare the debt acceptable.
- The ratchet permits findings to disappear or improve, but rejects duplicate or unsorted baseline identities, malformed summary values, new C901 functions and increased complexity of existing functions.

## Verification commands

```text
python3 -m pytest -q merger/lenskit/tests/test_graph_maintainability.py
python3 -m pytest -q merger/lenskit/tests/test_architecture_entrypoints.py merger/lenskit/tests/test_architecture_import_graph.py merger/lenskit/tests/test_path_classification.py
python3 -m ruff check scripts/ci/check_graph_maintainability.py merger/lenskit/architecture/graph_maintainability.py merger/lenskit/architecture/path_classification.py merger/lenskit/architecture/entrypoints.py
python3 scripts/ci/check_graph_maintainability.py --root . --format json
python3 -m ruff check --config ruff-ci.toml .
git diff --check
```

Observed result: 29 focused tests passed, both Ruff invocations passed, the graph-maintainability report returned `pass`, and `git diff --check` passed.

## Does not establish

- runtime reachability;
- complete entrypoint discovery;
- semantic truth of inferred layers;
- general maintainability;
- test completeness;
- absence of maintainability problems below the C901 threshold.
