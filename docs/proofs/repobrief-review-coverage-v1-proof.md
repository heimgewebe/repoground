# RepoBrief Review Coverage v1 proof

Task: `RPU-V1-T006`

Status: implementation proof for a proof-of-reading coverage report over RepoBrief delta-context output and review artifacts.

## Implemented surface

This slice adds:

```text
repobrief.review_coverage
```

and the CLI command:

```bash
python -m merger.lenskit.cli.main repobrief review-coverage compile \
  --delta-context <delta-context.json> \
  --review <review.md-or-json> \
  [--min-range-coverage 0.6] \
  [--policy-name advisory]
```

## Input model

The report reads:

1. a `repobrief.delta_context_compiler` JSON object, normally produced by `repobrief delta-context compile`;
2. a review artifact, either text/Markdown or JSON.

Delta-context `changed_files[*].hunks[*].changed_range` entries become task-relevant line ranges. Changed files without hunks, for example binary files, become file-level relevant ranges.

Review citations are extracted from:

- text forms such as `path#L10-L13`, `path:L10-L13`, `path:10-13`, and `path lines 10-13`, including root-level files such as `README.md#L1-L3`;
- JSON objects containing `path`/`file_path`/`source_path` plus `start_line`/`end_line`, `line_range`, `range`, or nested `source_range`;
- file mentions for file-level relevant ranges only.

A file-only citation or mention does not cover a concrete line range.

## Output contract

The report emits:

- `coverage`: totals and ratios for cited vs relevant ranges and cited line intersections;
- `relevant_ranges`: all changed/task-relevant ranges considered;
- `cited_ranges`: relevant ranges with matching citations;
- `uncovered_ranges`: relevant ranges without matching citations;
- `citations`: extracted line citations and file mentions;
- `thresholds`: advisory configurable thresholds;
- `bureau_evidence`: explicit evidence-only boundary for later Bureau consumption;
- `mutation_boundary`: explicit read-only boundary.

## Threshold semantics

Thresholds are configurable and advisory by default. A below-threshold report may return `status: warn`, but this is not a merge gate by itself. Gating requires an external Bureau/CI policy that explicitly chooses to consume this report.

## Read-only boundary

The report must not:

- mutate Git;
- mutate pull requests;
- mutate patches;
- inspect or mutate the source working tree;
- refresh or create RepoBrief bundle artifacts;
- update Bureau registry state;
- approve, reject, score or authorize a merge.

## Validation scope

Tests cover:

- text citation extraction and uncovered range reporting;
- threshold-met and below-threshold behavior;
- JSON `source_range` / `line_range` citation extraction;
- no-citation warning behavior;
- invalid delta-context handling;
- invalid threshold rejection;
- file-only citation not covering concrete line ranges;
- root-level file citations;
- parent `path` plus nested `source_range` JSON citations;
- partial line-intersection accounting so one cited line does not count an entire large hunk;
- CLI JSON output and advisory warning exit behavior.

## Non-claims

The review coverage report does not establish:

- review correctness;
- review completeness;
- test sufficiency;
- security correctness;
- runtime behavior;
- regression absence;
- merge readiness;
- approval or rejection;
- risk score;
- all relevant context used;
- claims truth.
