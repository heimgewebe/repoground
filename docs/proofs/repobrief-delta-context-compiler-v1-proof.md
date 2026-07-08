# RepoBrief Delta Context Compiler v1 proof

Task: `RPU-V1-T005`

Status: implementation proof for a deterministic, read-only PR/revision delta context compiler.

## Implemented surface

This slice adds:

```text
repobrief.delta_context_compiler
```

and the CLI command:

```bash
python -m merger.lenskit.cli.main repobrief delta-context compile \
  --diff <unified.diff> \
  [--bundle-manifest <manifest>] \
  [--task <task>] \
  [--context-budget <tokens>]
```

## Input model

The compiler accepts a unified Git diff. A RepoBrief bundle manifest is optional.

Without a bundle, the compiler still emits changed files, changed hunk ranges,
surrounding line windows and simple likely-reference hints. This satisfies the
"no full repo dump required for every review" condition at the delta layer.

With a bundle, the compiler also attempts bounded read-only hints from:

- `python_symbol_index_json`;
- `relation_cards_jsonl`;
- resolved evidence via the existing RepoBrief query/source-citation path;
- bundle availability, freshness and graph availability status.

Missing, stale, invalid or empty signals are reported as `gaps`; they are not
silently regenerated and do not block representation of the diff itself.

## Output contract

The compiler emits:

- `changed_files`: parsed file-level delta records;
- per-hunk `old_range`, `new_range`, `changed_range` and `surrounding_range`;
- `review_context`: token-budget-selected context entries;
- `omitted_context`: candidates skipped because the rough budget was exhausted;
- `signals`: bundle, symbol, relation and resolved-evidence signal status;
- `gaps`: missing/degraded/stale/empty signal observations with `severity`;
- `input_validity`, `signal_quality` and `context_completeness`: separated status dimensions;
- `selection_trace`: deterministic ordering and omission reasons;
- `review_boundary`: explicit context-only non-verdict;
- `mutation_boundary`: explicit read-only boundary.


## Bounded signal handling

Optional bundle signals are allowed to be absent or empty. Empty symbol, relation
and resolved-evidence hits are represented as informational gaps rather than
automatic warnings. Warnings are reserved for degraded/invalid signals, bounded
scan limits or budget truncation.

Relation-card scanning is bounded by artifact size, row count and per-line byte
length. The scan uses a file iterator instead of loading all JSONL rows into
memory, and it prefilters lines by changed path before JSON parsing.

Changed paths are deduplicated before symbol and resolved-evidence lookups to
avoid repeated expensive queries for repeated diff sections.

## Read-only boundary

The compiler must not:

- apply the diff;
- inspect or mutate the working tree;
- run Git commands;
- create or update pull requests;
- refresh or create RepoBrief bundles;
- update latest-complete registries;
- run tests or shell commands on target code;
- approve, reject, score, or authorize a merge.

## Validation scope

Tests cover:

- unified diff parsing for modified, added, renamed, deleted, binary and no-prefix files;
- changed hunk ranges and surrounding context windows;
- diff-only operation without a bundle;
- optional bundle signals for symbols, relation cards and resolved evidence;
- small-budget omission behavior;
- empty invalid diff classification;
- optional empty symbol/relation/resolved-evidence hits as informational rather than toxic warnings;
- nested test path likely-reference hints that do not point back to the same test file;
- deduplication of repeated changed paths before expensive signal queries;
- lazy bounded relation-card scanning with invalid-row reporting;
- CLI JSON output;
- explicit review-boundary non-verdict fields.

## Non-claims

The delta context compiler does not establish:

- review verdict;
- approval or rejection;
- merge readiness;
- correctness;
- test sufficiency;
- regression absence;
- runtime behavior;
- security correctness;
- risk score;
- blast-radius completeness;
- all relevant context used;
- repo understanding;
- claims truth.
