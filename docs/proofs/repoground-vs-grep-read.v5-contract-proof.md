# RepoGround vs grep/read v5 — measurement-contract proof

Scope: default question-contract selection for the existing bounded comparator.
This version does **not** change RepoGround retrieval, grep/read ranking, the
question text, goldset contents, evidence binding, compaction accounting, or
freshness rules.

## Why v5 is required

v4 deliberately kept `docs/retrieval/review_queries.v1.json` as the CLI default.
Its legacy `expected_patterns` field is defined as `all=>path` for backward
compatibility. That field predates the distinction between a file locator and
source evidence such as a symbol name.

After PR #1186 fixed the measured `agent_pack` source-role regression, the exact
v4 readback at `4001703e4aa0318d58135025a19406b74c1edb92` exposed the remaining
v1 artifact cleanly. The v1 `agent_pack` cases still reported two missing targets
and two false-confidence cases even though the expected implementation/test files
were present. The remaining "missing" values were the symbols
`produce_agent_reading_pack` and `REQUIRED_READING_BY_TASK`, which v1 must score
as paths under its frozen contract. Re-ranking product retrieval to manufacture
files with those names would optimize for a measurement artifact rather than
repository usefulness.

`review_queries.v2.json` already resolves that ambiguity without changing the 20
questions or their path targets: it separates `expected_paths` from
`expected_evidence`. The committed goldset contract tests prove that every v2
question/category/filter/acceptance tuple matches v1 and that each v2 path target
is exactly the path-shaped subset of the corresponding v1 patterns.

Changing the default question contract is itself a measurement-contract change.
It is therefore emitted as **v5** instead of silently redefining v4. The v4 proof
and historical v4 reports remain evidence for v4 only.

## v5 contract

All v4 comparator and safety rules remain unchanged. v5 changes only question
contract selection and explicit report metadata:

- CLI default: `docs/retrieval/review_queries.v2.json`;
- default question contract: `expected_paths+expected_evidence`;
- explicit legacy path: `docs/retrieval/review_queries.v1.json`;
- legacy question contract: `expected_patterns`;
- legacy v1 `expected_patterns` semantics remain `all=>path` when selected;
- report version is `v5`;
- reports expose `default_questions_path` and `legacy_questions_path` so the
  selection is machine-visible rather than inferred from prose.

No goldset file is modified by this promotion.

## Promotion evidence before v5

The earlier default-promotion diagnostic from 2026-07-08 passed all measured
non-regression gates — global recall/MRR, expected-target recall, every category,
miss count, fallback, graph health, and range/citation health — but explicitly
refused to mutate the default automatically. Its decision text required a later
explicit promotion decision even when all gates passed.

After PR #1186, v4 was rerun against the healthy publication at
`4001703e4aa0318d58135025a19406b74c1edb92` with SQLite index SHA-256
`4498a417ad88cbb13d49f393c1751c123d3a22b48b4a06af1ad74a357acafe29`.
The explicit v2 report SHA-256 was
`52860b81d7830f7b0182045e26d25ca76397442e6d9262e04c1cc253112227a9`:
status `pass`, RepoGround 22 missing targets versus grep/read 51, RepoGround 15
false-confidence cases versus grep/read 18, aggregate compaction 93.91%, and
`agent_pack` at zero missing targets / zero false-confidence with
`evidence_safe=true` and no quality regression.

The corresponding explicit v1 v4 report SHA-256 was
`9fc6306e2cb5a20e9d24b131438a12465d2abf91d38c7f2aff01cacfd2a78a2d`:
status `pass`, but its `agent_pack` category retained the two structural
symbol-as-path misses described above.

## v5 exact-current readback

While the v5 change was being prepared, RepoGround `main` advanced through the
Ruff 0.16.2 and sentence-transformers 5.7.0 dependency updates. Neither touches
the benchmark implementation or goldsets. The final promotion readback therefore
uses the newer healthy exact-current publication at
`add5ec5bfa0880eac8fb98ce5dded2331b5d3a6f`, not the earlier #1186 snapshot.

Both v5 runs use the same clean source snapshot, the same index, `k=10`, and the
same comparator implementation:

- SQLite index SHA-256:
  `a4226bfaa5fe3d09ddf5862e403b1815dd9e7ed10a153f68b67563ca913416a5`;
- repository-tree SHA-256:
  `eebed2ebaffe7f248a427478e508f634032bcea3e83093c0e7f7780845e05068`;
- v5 benchmark script SHA-256:
  `be8e3b3fe98ded5e2b0cc17b210e162bd0cc6d2806bf0a7017ae95255233e490`;
- RepoGround source-index freshness: **20/20 fresh** in both runs.

Canonical default invocation, with **no `--questions` argument**:

- report SHA-256:
  `c58d64dc65f3921901d0414ebb9f01321a5f9e3d407550c7c80fe70fc2852bd9`;
- report version: `v5`;
- status: `pass`;
- `default_questions_path`: `docs/retrieval/review_queries.v2.json`;
- `legacy_question_contract`: `expected_patterns`;
- v2 question-set SHA-256:
  `47c6aed16294e8543f65324f26342a846b89951e918e6e7880d3d7ea1e6754e9`;
- RepoGround missing targets: **22**; grep/read: **51**;
- RepoGround false-confidence cases: **15**; grep/read: **18**;
- RepoGround aggregate compaction: **93.91%**, all cases pass;
- `agent_pack`: zero missing targets, zero false-confidence cases,
  `evidence_safe=true`, no quality regression.

Explicit legacy invocation with `--questions docs/retrieval/review_queries.v1.json`:

- report SHA-256:
  `f1879b2cd01d583c8b125bee45616d14d0ac09bda2bb022debec3216b21ebf6d`;
- report version: `v5`;
- status: `pass`;
- v1 question-set SHA-256 remains
  `47f562e6c5b5b63205930e92186d406d33029f7330796312ca5844a177fc3f77`;
- `legacy_expected_pattern_contract` remains `all=>path`;
- RepoGround missing targets: **29**; grep/read: **53**;
- RepoGround false-confidence cases: **19**; grep/read: **20**.

## Decision boundary

v5 becomes the canonical benchmark contract because it measures file location and
source evidence as different things while preserving the same questions and v1
file targets. v1 remains explicitly runnable for historical compatibility; v4
remains historically frozen. This promotion does not establish repository
understanding, answer correctness, unmeasured-query quality, or that every
category is evidence-safe. It establishes only that the current default uses the
more explicit question contract and that the legacy path remains reproducible.
