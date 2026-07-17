---
doc_type: architecture_decision
status: implemented
task: BUREAU-LENSKIT-AUDIT-LANES-002
---

# Citation-bound audit finding adapter v1

## Purpose

The adapter turns untrusted audit-lane candidate claims into a deterministic diagnostic
result set. It does not decide repository truth. It records whether a candidate belongs
to a selected lane, points at resolvable Lenskit citations and was reviewed against the
same repository revision that is current at adaptation time.

## Priority order

A later signal may not silently override a stronger safety boundary:

1. malformed input is rejected;
2. revision mismatch yields `stale`;
3. an unknown citation yields `unresolved`;
4. only a fresh, citation-resolved candidate may receive a verifier state;
5. without a verifier state it remains `candidate`.

A preserved verification record is marked `verification_applied=false` when revision or
citation freshness blocks it. This prevents evidence loss while avoiding a false verified
state.

## States

| State | Meaning | Does not mean |
| --- | --- | --- |
| `candidate` | syntactically admitted and evidence-addressed, not independently decided | defect exists |
| `verified` | recorded verifier accepted the claim under the exact current revision and resolvable citations | repository truth or completeness |
| `stale` | reviewed and current revisions differ | claim is wrong |
| `wrong` | recorded verifier rejected the claim | surrounding code is correct |
| `unresolved` | evidence address is missing or verifier could not decide | claim is false |

## Identity

`finding_id` is derived from the normalized lane id, normalized claim text and sorted
unique citation ids. Input order therefore cannot change identity or output ordering.
Duplicate semantic candidates are rejected instead of being counted twice.

## Citation boundary

Citation ids must use the existing `cit_<16 lower-hex>` address form. The adapter consumes
an explicit registry of citation ids that the caller already resolved from a validated
Lenskit citation map. It does not invent citations and does not claim that a structurally
valid citation proves the candidate.

## Authority

The output declares:

- `authority=diagnostic_signal`
- `risk_class=diagnostic`

It forbids inference of repository truth, review completeness, runtime correctness,
severity correctness or permission to mutate GitHub or a repository.

## Non-goals

- running an LLM or verifier
- reading repository files or bundle contents
- creating issues, patches, commits, pushes or merges
- assigning severity
- deciding whether audit lanes improve review quality

The isolated runner remains BUREAU-LENSKIT-AUDIT-LANES-003. Measurement and promotion
remain BUREAU-LENSKIT-AUDIT-LANES-004.
