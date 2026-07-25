# REPOGROUND-LEGACY-RECONCILIATION-V1-T009 proof

## Scope and decision

T009 decomposes `iter_report_blocks` and hardens the resulting renderer contract.
The umbrella task T004 remains open. The final implementation measured here is
bound to commit `44013f1fdc75a584a618076bc03d50650a24c7dc` and tree `e08503047d30eb2397e09d70cbafb850f3a5f9e5` on
base `24eee84dd845fcf5f3a4a82c9e42e64428e76d6d` / tree `b3dca00e531b57f0b04841d69e64ce919957e9e1`.

The review was not treated as an all-or-nothing architecture mandate. Functional
correctness, reproducible evidence and bounded performance were required for this
slice. A larger `_ReportRenderState` split and `slots=True` were not added because
they would expand scope without a demonstrated T009 benefit.

## Corrected defects

- `tags=None` is safe in WGX, fleet and priority tag checks.
- An empty manifest now emits exactly one opening and one closing zone marker.
- The caller-provided file list is copied before sorting; its order remains
  unchanged. `FileInfo.anchor`, `anchor_alias` and `roles` are still intentionally
  enriched during preparation and are not claimed immutable.
- Redaction preserves Python assignment syntax. The canonical regression requires
  `API_KEY = "[REDACTED]"`, rejects the broken form and parses the source with
  `ast.parse`.
- Plan-only reports distinguish selected files from emitted content and report
  zero emitted files / zero content coverage.

## Structural result

The ratcheted C901 budget and observed clean-archive measurement are identical:

| Dimension | Before ceiling | Final ceiling and observation |
| --- | ---: | ---: |
| Findings | 198 | 197 |
| Excess mass | 2,533 | 2,395 |
| Maximum | 148 | 138 |

Roles are computed once during preparation. Category indexing is one-pass and
manifest rows use a pre-grouped root index rather than repeatedly filtering the
full list. Explicit extras use `is not None` semantics. No new C901 finding was
introduced.

## Byte, streaming and edge-case evidence

The CI test suite now contains a checked-in 18-scenario differential contract.
It compares block count, block order, exact block bytes, individual SHA-256
values and joined SHA-256. Intentional corrected differences are declared for:

1. balanced empty-manifest zones,
2. zero emitted-content coverage in plan-only mode,
3. syntactically valid redacted assignments.

Full report goldens are stored as real UTF-8 `.txt` files rather than one-line
JSON strings. PyYAML 6.0.3 is exactly pinned and asserted because YAML bytes are
part of the golden contract. Laziness is proven through `START_OF_CONTENT`; the
first real file block triggers exactly the first expected content read.

## Performance decision

The comparison uses identical benchmark-script bytes, the same host and Python,
two alternating before/after rounds, five samples per round, one fixed warm-up
per revision and median as the primary timing statistic. All measured cases are
included. The predeclared maximum regression is 5 percent for median time and
traced peak allocation.

| Case | Median time change | Peak traced memory change | Result |
| --- | ---: | ---: | --- |
| bundle archive | +1.788% | -0.147% | pass |
| bundle dual | +0.539% | -0.355% | pass |
| retrieval index build | -1.366% | 0.000% | pass |
| retrieval query | -2.960% | 0.000% | pass |
| service app import | -0.330% | +0.279% | pass |
| optional atlas | identical skip contract | identical | skip |

A regex-based replacement for `splitlines()` initially caused a measured 7.028
percent archive regression and was therefore removed. T009 deliberately retains
the canonical `splitlines()` implementation instead of shipping an optimization
that failed its own gate.

## Revision-bound receipts

- targeted renderer and benchmark-contract tests: 42 passed, 0 skipped; receipt
  `0a35715ec6838ceae2f9e0d43e69bad0380fa8e1876a937e5998b276fa0bd86b`
- changed-file Ruff: pass; receipt
  `cdb8ff7eaa4fd33e15ab5ad61955917f590de5912c8e660eaac60a11cebe56c5`
- complexity clean-archive measurement: pass; receipt
  `a5c5b75fbf75d5357f7e5bbc48a886be0a014fc7726d1b5c26e364ddb2d75cd0`
- alternating performance comparison: pass; receipt
  `00dfcdfbcf1ee0313ff684f6588ce30fa4a9453723940239f3e14da7b8bbbb14`

The repository evidence intentionally stops before claiming final delivery. The
complete repository suite and all GitHub required checks must run on the later
final evidence head. Their exact head/tree and lifecycle receipts belong in the
canonical final delivery and Bureau closeout evidence.

## Does not establish

- completion of umbrella task T004,
- correctness of every legacy path in `merge.py`,
- performance freedom outside the measured paths,
- semantics of untested dynamic imports or plugin paths,
- deployment of the later merge commit.
