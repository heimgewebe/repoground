# Lens Card v1 Proof

Status: draft PR implementation proof for `TASK-LENS-CARD-001`.

## Purpose and scope

This proof documents the smallest complete Lens Card v1 slice:

- a single-card JSON contract;
- deterministic single-card and batch producers;
- formal schema validation plus producer-coherence validation;
- focused Python and ECMAScript tests;
- static Agent Reading Pack guidance;
- Lens Model CI, architecture, blueprint and task reconciliation.

The slice deliberately does not add CLI, bundle emission, manifest roles,
consumer integration, Relations, States, Task Contexts, PR Delta Cards,
retrieval ranking, LLMs, embeddings, file-content analysis, git-history
analysis, review findings, safety verdicts or change-impact judgements.

## Target proof

Verified before patching on the main-derived branch point
`ae194c0bd36249b67a6510027b795ba38f78aa9e`.

Target state:

- Lens-Card contract: absent.
- Lens-Card producer: absent.
- Lens-Card validator: absent.
- Lens-Card tests: absent.
- `TASK-LENS-CARD-001`: absent from board and index.
- Parallel Lens-Card PRs/branches: absent.
- `origin/main`: no `lens-card` implementation files.
- Public Primary-Lens explanation API: present
  (`explain_primary_lens(path) -> (primary_lens, matched_rule)`).
- Public Facet API: present (`infer_facets(path)`).
- Facet-v1 path policy: enforced by the public `infer_facets()` call boundary;
  the core normalizer remains private and is not imported.
- Validator/dependency conventions: existing `status` rollups, named checks,
  `validation.mode/engine/reason` triads and `jsonschema_dependency()`.
- Lens-Model CI gate: path-scoped and extendable.

## Plan review

Preserved decisions:

- Lens Cards follow Primary Lens Audit and Facet Model v1.
- Primary Lens and Facets are composed, not reclassified.
- Cards are `authority=navigation_index` and `canonicality=derived`.
- No new Primary Lens, Facet taxonomy, CLI, bundle emission or review verdict is
  introduced.
- Contract, producer, validator and tests live in the same v1 slice.
- Agent Reading Pack guidance explains the authority boundary only.

Corrected from older planning sketches:

- Cardinality and identity are decided here, not treated as pre-existing norms.
- The contract describes one Card, not a report container.
- Validation recomputes the expected Card from existing producers; a formally
  valid but wrongly classified Card fails.
- The Card path pattern is exactly the Facet v1 pattern and is guarded in Node.
- `matched_rule` is included because the public Primary Lens Audit API returns it.
- The old non-normative blueprint sketch with free facet strings is replaced by
  the canonical single-card contract reference.

## Decision matrix

| Decision | v1 value |
| --- | --- |
| Contract unit | one Lens Card |
| Cardinality | exactly one Card per accepted repo path |
| Identity | `path` |
| Additional Card ID | none |
| Batch output | sorted, deduplicated in-memory list of Cards |
| Primary Lens | existing public Primary Lens explanation |
| Primary-Lens rule | `matched_rule` from the same public API |
| Facets | projection from `infer_facets()` |
| Facet fields | `facet`, `source_rule`, `derivation_type` |
| v1 derivation type | `direct` only |
| Facet-free path | valid Card with `facets: []` |
| Authority | `navigation_index` |
| Canonicality | `derived` |
| Navigation | exactly one `repo_path` reference to the same `path` |
| Negative semantics | fixed nine-term Lens-family baseline |
| Persistence | none |
| CLI | none |
| Bundle/manifest emission | none |

## Card cardinality and identity

Lens Card v1 uses exactly one Card per accepted repo path. `path` is the v1
identity because the Facet Model v1 path surface already defines a canonical
repo-relative POSIX path identity, including Unicode-scalar and non-canonical
lexeme rejection.

No separate Card ID is introduced. A second ID would duplicate the path identity
without adding a controlled reference model in this slice.

## Single-card contract decision

`merger/lenskit/contracts/lens-card.v1.schema.json` is a single-object
contract. It is not a report, stream, JSONL, manifest addition or bundle
container. Batch production returns a list of independently valid Cards only in
memory.

## Primary Lens composition

`produce_lens_card()` calls the public `explain_primary_lens()` API. It does not
import `infer_lens()` directly and does not copy the Primary Lens rule order.
The Card includes `matched_rule` because the current public explanation API
returns it.

## Facet projection

`produce_lens_card()` calls the public `infer_facets()` API. It projects only
`facet`, `source_rule` and `derivation_type`, then sorts the projected items
deterministically. It does not copy Facet rules and does not project
`does_not_establish` from facet items into each Card facet item.

Facet-free paths remain valid Cards with `facets: []`.

## Path semantics

The Card contract uses the exact Facet v1 path pattern. The Producer delegates
path acceptance to `infer_facets()` before composing the Card, so invalid paths
fail at the existing public Facet boundary even when no facet is produced.

The implementation does not import the private Facet `_normalize_path()` helper
and does not introduce a shared path utility refactor.

## Navigation-reference semantics

`navigation_refs` contains exactly one object:

```json
{"kind": "repo_path", "target": "<same path>"}
```

This is navigation only. It is not Evidence, does not create a second identity,
and does not imply that the file was read, cited, reviewed or changed.

## Contract guarantees

The contract guarantees strict shape only:

- `kind`, `version`, `authority` and `canonicality` constants;
- known Primary Lens IDs;
- non-empty `matched_rule`;
- controlled Facet v1 vocabulary and source-rule vocabulary;
- facet/source-rule binding;
- `derivation_type: direct`;
- empty `facets` allowed;
- duplicate JSON-equal facet assignments rejected;
- exactly one typed `repo_path` navigation ref;
- fixed nine-term `does_not_establish` tuple;
- `additionalProperties: false` on every object.

It intentionally contains no Relations, States, Task Contexts, Evidence refs,
confidence, score, priority, risk, severity, verdict, approval, safety,
coverage, impact, breakage or fix fields.

## Producer guarantees

The producer is deterministic and pure with respect to its inputs:

- no file I/O;
- no git;
- no network;
- no environment reads;
- no timestamps;
- no random values;
- no cache;
- no global mutable state;
- no input mutation;
- duplicate batch paths are deduplicated by canonical `path`;
- batch output is sorted by `path`;
- element errors are not swallowed.

## Validator guarantees

`validate_lens_card()` checks:

1. Draft-07 schema validity with `jsonschema`;
2. producer coherence by recomputing `produce_lens_card(card["path"])`.

It compares the recomputed `path`, `primary_lens`, `matched_rule`, full ordered
`facets`, `navigation_refs` and `does_not_establish`. Known but wrong values
therefore fail even when they are individually valid enum members.

The result shape uses repo-local conventions: top-level `status`, ordered
checks, `validation.mode/engine/reason` and dependency diagnostics.

## Dependency-degradation boundary

`jsonschema` is imported lazily. If unavailable, module import still succeeds
and validation returns `status: fail` with a machine-readable
`dependency_missing` check and `dependencies.jsonschema.effect =
validation_degraded`. Missing `jsonschema` never produces `pass` and no
mini-schema interpreter is built.

CI installs `jsonschema`, so contract tests are expected to run there rather
than skip.

## ECMAScript path-pattern parity

`merger/lenskit/tests/test_lens_facet_pattern_ecma.js` now loads both
`lens-facet.v1.schema.json` and `lens-card.v1.schema.json`, asserts exact
pattern equality, compiles both patterns with `new RegExp(pattern, "u")`, and
runs the same accept/reject matrix against both. It does not run Ajv and does
not duplicate the regex in test code.

## Determinism

Single-card output is stable for the same accepted input. Batch output accepts
generators, rejects a single path-like value as the batch argument, deduplicates
paths deterministically, sorts by `path`, and returns `[]` for empty input.

The fixed order of `does_not_establish` is a serialization rule, not semantic
priority.

## Repository projection snapshot

The final branch projection is measured with `git ls-files -z` and the public
Card producer/validator. It asserts:

- batch order independence;
- one Card per tracked path;
- every produced Card validates with `status: pass`;
- deterministic UTF-8 JSON serialization with sorted keys.

Measured branch snapshot after staging all intended files:

- tracked paths: 575
- cards: 575
- projection: pass

The numbers are a time-bound proof snapshot only and are not hard-coded.

## Agent Reading Pack boundary

The Agent Reading Pack adds static Lens-Card guidance only. It says Lens Cards
are optional `navigation_index` / `derived` projections of Primary Lens and
Facets; they do not replace `canonical_md` and do not prove truth, repo
understanding, review completeness, test sufficiency, runtime correctness,
regression absence, safety or change impact.

The pack does not read Card paths from a manifest, does not add a required
reading profile, does not claim Card emission, and does not create a Consumer
integration.

## CI gate

`.github/workflows/lens-model.yml` is extended so changes to Lens Card contract,
core, validator, tests, proof, architecture/blueprint and static Agent Reading
Pack guidance re-run the focused Lens Model gate. The gate meta-validates both
Facet and Card schemas, runs the Node path-pattern parity test, runs Primary
Lens / Audit / Facet / Card / Pack tests, and ruffs the focused files.

The workflow checks the formal surface. It does not prove the truth of proof
text, mergeability, review completeness, runtime correctness or Card usefulness.

## Validation

Local validation snapshot on this branch:

- `python -m pytest -q -ra merger/lenskit/tests/test_lens_cards.py merger/lenskit/tests/test_lens_card_validate.py` -> 92 passed.
- `node --check merger/lenskit/tests/test_lens_facet_pattern_ecma.js` -> syntax OK.
- `node merger/lenskit/tests/test_lens_facet_pattern_ecma.js` -> path parity OK.
- `python -m pytest -q -ra merger/lenskit/tests/test_agent_reading_pack.py merger/lenskit/tests/test_agent_reading_pack_usage_rules.py` -> 56 passed.
- Focused Ruff on new Card core/tests and Pack changes -> all checks passed.
- Repository projection over staged branch paths -> 575 Cards, projection pass.

Broader final validation is recorded in the PR validation section.

## Claim boundary

Lens Card v1 does not establish:

- truth or correctness;
- completeness;
- repo understanding;
- runtime behavior or runtime correctness;
- test sufficiency;
- regression absence;
- semantic importance;
- review priority or review completeness;
- safety;
- change impact;
- actual agent or retrieval usefulness.

It also does not establish a complete taxonomy, a new Artifact Role, CLI
availability, bundle/manifest emission, consumer integration, `possible_facets`
population, Relations, States, Task Contexts, PR Delta Cards or retrieval
ranking.
