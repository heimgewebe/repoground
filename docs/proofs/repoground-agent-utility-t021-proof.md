# RepoGround Agent Utility T021 — Rust/Bash Structure Adapters

## Binding

- Product revision: `70b3145b532fa627087c084be011f18566c87e8a`
- Baseline revision: `c3b4390af09e4eac30439098d9e3d19a06ebd502`
- Goldset: `repoground-agent-utility-t021-goldset-v1`
- Canonical goldset SHA-256: `66bbe6cd2dcd07984e4ab8b7274d8d92f8a2ad99df066579c8943d622661041b`
- Measurement environment: CPython 3.10.12, Linux x86_64, 32 logical CPUs
- Repository binding: HEAD equalled the product revision; the worktree and all
  fixture paths were clean; the benchmark used no network.

The measurement was produced locally with:

```bash
python -m merger.repoground.core.language_structure_benchmark \
  --goldset docs/retrieval/repoground_agent_utility_t021_goldset.v1.json \
  --repo-root . \
  --source-revision 70b3145b532fa627087c084be011f18566c87e8a
```

The command refuses a non-matching HEAD, a dirty or untracked worktree, unsafe
fixture roots, malformed/nonfinite inputs, and mismatched benefit evidence.

## Architecture decision

T021 adds no required parser, compiler, model, service, download or package.
`bash-static-structure` and `rust-static-structure` are conservative bounded
lexers that emit S0 navigation evidence. Rust can additionally consume an
already-normalized, local, commit-bound SCIP document as S1 evidence; RepoGround
does not invoke or install an indexer.

The sidecar is opt-in (`language_structure`, default false), single-repository,
commit-bound, derived and noncanonical. Dirty or unbound repositories do not
emit it. The stable reader checks manifest role/contract, bytes, hashes, commit,
run, dump identity, adapter semantics, record IDs, ranges, summaries and
degradations before projecting the exact manifest hash into selected hits.

Text excerpts and whole Rust/Bash records share one exact UTF-8 evidence byte
budget in the ask context pack. Records are never shortened to fit: range,
adapter, version, confidence, provenance and uncertainty remain intact, while
whole-item omissions carry a reason. The read-only workbench role and the
agent-impact composition expose the same integrity-checked records to context
composition consumers.

## Goldset and quality measurement

Each language has a small positive repository, a medium positive repository,
an ambiguous case, a dynamic case and a true-null repository. The dynamic and
ambiguous fixtures exercise Bash `eval`/command substitution/dynamic source,
duplicate Bash functions, Rust macros and duplicate Rust functions.

| Lane | Bash | Rust | Aggregate |
|---|---:|---:|---:|
| Symbol TP / actual / expected | 10 / 10 / 10 | 14 / 14 / 14 | 24 / 24 / 24 |
| Relation TP / actual / expected | 5 / 5 / 5 | 4 / 4 / 4 | 9 / 9 / 9 |
| Exact-range TP / actual / expected | 15 / 15 / 15 | 18 / 18 / 18 | 33 / 33 / 33 |
| Symbol recall | 1.0 | 1.0 | 1.0 |
| Relation precision / recall | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |
| Exact-range precision / recall | 1.0 / 1.0 | 1.0 / 1.0 | 1.0 / 1.0 |

Both true-null cases passed with zero emitted records and zero false positives.
Repeated semantic projections were equal. Every expected degradation appeared,
and no unexpected degradation appeared. These perfect fixture metrics describe
only the declared lexical subset; they are not evidence of complete language
semantics or performance on arbitrary repositories.

## Cost measurement

| Cost | Bash | Rust | Aggregate |
|---|---:|---:|---:|
| Median latency | 0.712095 ms | 0.830406 ms | 0.792101 ms |
| p95 latency | 5.356904 ms | 1.310948 ms | 5.356904 ms |
| Maximum traced peak memory | 166,251 B | 22,332 B | 166,251 B |
| Total serialized index size | 25,252 B | 29,561 B | 54,813 B |
| Maximum case index size | 8,107 B | 10,470 B | 10,470 B |

Latency and traced-memory values are environment observations, not
cross-machine guarantees. Maintenance cost is bounded by keeping the adapters
dependency-free, language-specific and intentionally incomplete; supporting
more syntax would require new reviewed contract and goldset cases rather than
silently widening semantics.

### Rust harmless-line boundedness readback

The review regression was reproduced on the clean prior product head
`bb5e11c3ed1c3401b8fabbe6ea86712962798323` and repeated on the clean product
revision above. Each sample called `_rust_call_evidence` for 20 identical
`let x = 1;` lines, used 100/500/1000/2000 known same-file functions, purged
Python's regular-expression cache before the sample, and reported the median
of five repetitions:

| Known functions | Before (`bb5e11c`) | After (`70b3145b`) |
|---:|---:|---:|
| 100 | 7.677839 ms | 0.019140 ms |
| 500 | 34.014489 ms | 0.019220 ms |
| 1000 | 1016.132462 ms | 0.018530 ms |
| 2000 | 1999.550303 ms | 0.018320 ms |

These wall-clock observations are measurement evidence, not a flaky test
threshold. The algorithmic regression instead supplies a mapping that rejects
iteration, `keys()` and size inspection while allowing lookup of the one
scanned call candidate. Additional tests preserve lexicographic record order,
first-occurrence range selection, at most one record per callee and line, and
omission of unknown candidates. The adapter still does not newly claim method,
macro, generic or multiline-call semantics.

## Promotion result

The report returned:

```text
status: keep_optional
broad_activation_eligible: false
default_promoted: false
reason: revision_bound_agent_benefit_missing
```

The fixture measurement establishes useful, precise navigation within the
declared subsets. It does not establish a downstream agent-success improvement
over the text/FTS fallback. Consequently T021 does not enable the adapters by
default or in a broad task profile. A future comparison must bind candidate and
fallback routes to this revision and goldset, measure actual task success, and
still pass quality, null, determinism, latency, memory and index-size gates.

## Verification

- Focused affected surface after the boundedness fix: `255 passed` across the
  adapter/integration/Doctor, context-pack/snapshot/impact,
  contract/manifest/merge, and Pythonista groups
- Full canonical non-browser/non-live-doc suite after self-review fix:
  `5547 passed, 12 skipped, 13 deselected`
- `ruff check --config ruff-ci.toml .`: pass
- graph maintainability ratchet: pass, 0 new findings
- module reachability: pass, 0 findings/unproven modules
- workflow control-plane: pass, 21 workflows classified
- entry-doc links: pass, 0 broken links
- anti-hallucination contract lint: pass, 101 contracts
- doc-freshness inspect: pass, 0 findings
- doc-freshness blocking unit/schema lane: `36 passed, 3 deselected`
- `python3 tools/parity_guard.py`: pass
- all 5 WebUI Node regression files: pass
- forbidden test-stub guard: pass
- `git diff --check`: pass

## Does not establish

- complete Rust or Bash symbol/call/dependency semantics;
- macro expansion, generated-code coverage, shell evaluation or runtime reachability;
- Python-AST equivalence;
- cross-machine cost equivalence;
- downstream agent-success improvement over text/FTS;
- test sufficiency, merge readiness or default activation.
