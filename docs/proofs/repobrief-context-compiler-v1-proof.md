# RepoBrief Context Compiler v1 proof

Task: `RPU-V1-T004`

Status: implementation proof for a deterministic token-budget context compiler over existing RepoBrief bundle artifacts.

## Implemented surface

This slice adds:

```text
repobrief.context_compiler
```

and the CLI command:

```bash
python -m merger.lenskit.cli.main repobrief context compile \
  --bundle-manifest <manifest> \
  --task <task> \
  --task-profile <required-reading-profile> \
  --context-budget <tokens>
```

Optional controls:

```bash
--query <retrieval-or-symbol-query>
--signal-k <max-signal-hits>
--bytes-per-token <rough-byte-divisor>
--strict
```

## Selection model

The compiler reads an existing bundle manifest and then builds bounded candidates from:

1. resolved evidence query results with source ranges and citation projection;
2. Python Symbol Index hits when `python_symbol_index_json` is present;
3. Required Reading roles for the selected task profile;
4. recommended reading roles when available.

Candidates are ordered deterministically by priority, estimated token count and id:

```text
resolved evidence -> symbol index -> required reading -> recommended reading
```

Token estimates use a byte-based approximation. No exact tokenizer or model-specific fit claim is made.

## Output contract

The compiler emits:

- `selected_context`: ordered context entries that fit into the token budget;
- `omitted_context`: entries skipped because their estimated tokens would exceed the remaining budget;
- `gaps`: missing or degraded signals such as missing retrieval, symbol, graph, freshness or required-reading surfaces;
- `signals`: bounded status for resolved evidence, symbol index, required reading and availability;
- `fallback_context`: canonical/front-door required reading roles available as fallback;
- `selection_trace`: priority bands and omission reasons;
- `mutation_boundary`: explicit read-only boundary.

Selected context entries carry source path/range data and citation/range references where available. This supports answer-compliance workflows, but it does not prove answer correctness.

## Read-only boundary

The compiler must not:

- refresh snapshots;
- create or mutate bundle artifacts;
- mutate Git;
- create pull requests;
- import or execute target repository code;
- update latest-complete registries.

## Validation scope

Tests cover:

- ordered resolved-evidence selection with source range/citation payload;
- symbol-index candidates;
- relation-card candidates from `relation_cards_jsonl`;
- fallback to canonical/agent required reading when retrieval, relation and symbol signals are missing;
- visible omitted candidates under small budgets;
- invalid budget and estimator input handling;
- CLI JSON output.

Manual smoke covered compiling context from a freshly generated tiny RepoBrief snapshot.

## Non-claims

The context compiler does not establish:

- exact token count;
- model context fit;
- best possible context;
- all relevant context used;
- answer correctness;
- repo understanding;
- claims truth;
- runtime behavior;
- test sufficiency;
- review completeness;
- merge readiness;
- agent quality improvement.
