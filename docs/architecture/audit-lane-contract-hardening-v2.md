---
doc_type: architecture_decision
status: implemented
task: BUREAU-LENSKIT-AUDIT-LANES-005
---

# Audit-lane planner and evidence contract hardening

## Decision

The planning-only core remains deterministic and non-executing, but its inputs and
semantic boundaries are now fail-closed rather than permissively normalized.

## Planner boundary

- Paths must already be canonical relative POSIX paths. Spellings containing repeated
  separators, `.` segments, parent traversal, trailing separators, backslashes, control
  separators or duplicates are rejected.
- The planner does not resolve symlinks. That would require filesystem access and would
  violate the planning-only contract. A later executor must bind and verify the actual
  repository root separately.
- Input is bounded to 5,000 paths, 4,096 characters per path, 2 MiB aggregate path text
  and 8,192 review-query characters.
- Path evidence has weight three. Free-text query hints have weight one because they are
  untrusted routing input.
- Unicode is normalized with NFKC and case folding. Bounded English and German aliases
  cover known routing vocabulary without adding NLP libraries or fuzzy matching.
- Tokenization over many paths uses a non-language separator so phrase aliases cannot be
  manufactured across file boundaries.

## Contract boundary

`does_not_establish`, `does_not_prove` and `allowed_inferences` are no longer arbitrary
string arrays. Draft-07 `contains: const`, exact cardinality and an enum bind every
required sentence while allowing order-independent serialization.

## Finding identity and verifier interface

The current finding output is `audit_finding_set.v2`.

- IDs use the `lenskit.audit_finding_id.v2` domain and the `af2_` prefix.
- Candidate normalization happens once; an internal builder hashes only prevalidated
  values.
- Verifiers submit `audit_verification_record.v1`, bound to one finding and the exact
  reviewed revision.
- The neutral decisions are `accepted`, `rejected` and `unresolved`. The adapter, not the
  verifier, maps them to diagnostic finding states.
- A stale revision or unresolved citation still takes precedence. The record remains
  visible and `verification_disposition` states whether it was applied or blocked.
- Claims, records, notes, citation sets, candidate counts and citation registries are
  bounded.

The old `audit_finding_set.v1` schema remains available for historical artifacts, but its
negative semantics are hardened to the exact legacy sentences. New producers emit v2.

## Rejected alternatives

- `PurePosixPath.resolve()` does not exist and filesystem resolution is out of scope.
- NLTK, spaCy, embeddings and Levenshtein matching add dependency, nondeterminism and
  false-positive surfaces without measured benefit.
- Data-driven lane catalogs, path-type weights and overlap reduction remain Phase-4
  evaluation subjects rather than unmeasured default changes.
