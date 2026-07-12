# RepoBrief Workbench Usefulness Evaluation v2 — proof

Status: deterministic navigation evaluation complete
Technical commit: `052c1dcd1729d5c22bc7e4c298f7b0d7fa0cddfc`

## Question

Does the bounded read-only Workbench help an agent locate fixed code targets
that are not reliably visible in the compact Agent Reading Pack?

This is a navigation question. It is not a claim about natural-language answer
quality or patch correctness.

## Method

The same redacted, healthy `full-max` bundle was used for both lanes:

1. **Baseline:** literal visibility of expected paths and symbols in the complete
   `agent_reading_pack`.
2. **Workbench:** query over the existing read-only SQLite index plus exact
   search over the existing Python symbol index.

The committed goldset contains eight fixed questions covering adapter identity,
dispatch, snapshot status, index query, symbol search, MCP resource listing,
latest-complete freshness and release-decision checking.

Goldset:
`docs/retrieval/repobrief_workbench_usefulness_goldset.v1.json`

## Result

```text
questions                         8
baseline path recall              0.375
baseline symbol recall            0.125
baseline combined target recall   0.250
workbench path recall             1.000
workbench symbol recall           1.000
workbench combined target recall  1.000
combined advantage                +0.750
query availability                1.000
symbol availability               1.000
bundle mutation                   none
```

All eight Workbench questions found every expected path and symbol. The
acceptance threshold was an advantage of at least `0.20`, no path or symbol
regression, and complete availability of both read channels.

## Decision

The experiment establishes **bounded navigation utility for this committed
Goldset**. It does not promote the Workbench as default required reading. Raw
card volume and broad diagnostic surfaces remain task-scoped rather than default
context.

The evaluator exposes missing-path and missing-symbol lists for every question.
Both the reading pack and Workbench expose the required non-claims, so the
measured guardrail omission rate is zero in both lanes; this does **not** measure
what an agent believes. The Workbench produced a complete structured answer
context for all eight questions. Natural-language agent answers were not
produced, so behavioral false confidence and actual answer compliance remain
explicitly unmeasured.

Machine-readable report:
`docs/diagnostics/repobrief-workbench-usefulness-eval-20260712T2053Z.json`

Report SHA-256:
`03b2416c239860a91021c572a5addced7b0194ba6e581742d6ee9d34fd89f326`

## Non-claims

The result does not establish agent-quality improvement, answer correctness,
repository understanding, patch correctness, test sufficiency, review
completeness, general retrieval quality, merge readiness or default-promotion
readiness.
