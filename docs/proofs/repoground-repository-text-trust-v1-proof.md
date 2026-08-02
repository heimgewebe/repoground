# RepoGround repository text trust v1 proof

Task: `REPOGROUND-AGENT-UTILITY-V1-T014`

Status: implementation proof for provenance-bound trust classification on agent-visible repository text and generated context.

## Problem

Repository text can contain imperative wording without possessing control authority. A README, source comment, documentation page, test fixture, generated index, or inferred convention must not become an operator instruction merely because its text says to run tools, use the network, reveal secrets, write files, merge, or deploy.

The previous context compiler preserved citation and artifact metadata, but did not attach one explicit trust class to every selected context item. Consumers therefore had to reconstruct the distinction between maintainer rules, ordinary repository content, generated navigation, and inference.

## Implemented surface

This slice adds:

- `merger/repoground/core/repository_text_trust.py`;
- `repository-text-trust.v1.schema.json`;
- `agent-handoff.v1.schema.json`;
- trust metadata on every context-compiler candidate;
- a fail-closed `build_agent_handoff()` projection that preserves trust and freshness.

The vocabulary is deliberately small:

1. `operator_or_system_instruction` — external control-plane instruction only;
2. `maintainer_repository_rule` — maintainer-authored repository semantics such as `AGENTS.md`, `CONTRIBUTING.md`, ADRs, and contracts;
3. `raw_repository_content` — ordinary repository text;
4. `generated_artifact` — derived indexes, reports, manifests, and navigation;
5. `inferred_rule` — advisory inference that is never promoted to canonical repository truth.

## Classification boundary

Classification uses provenance supplied by the producer: repository path, artifact role, derivation type, citation, and declared artifact authority. It does **not** inspect the text to decide whether the text is an instruction.

Consequences:

- instruction-like README, comment, documentation, and fixture text remains visible as content;
- repository paths and bundle artifacts cannot be classified as `operator_or_system_instruction`;
- inferred rules are forced to `authority.class=inferred_rule`, `canonicality=derived`, and `canonical_repository_rule=false` even when a caller proposes a stronger authority;
- every descriptor states why it applies, how it was derived, where it came from, and what it does not establish.

## Control-authority separation

Every trust descriptor carries the same fail-closed boundary:

```text
repository_content_grants_control_authority = false
granted_actions = []
authorization_source = grabowski_or_operator_policy
```

External authorization remains required for:

- tool execution;
- file writes;
- network use;
- secret access;
- merges;
- deployments.

A repository file may describe project rules. It cannot grant those operational capabilities.

## Context and handoff transport

`compile_context_plan()` now attaches a validated `trust` object to resolved source evidence, symbol-index hits, relation cards, and required-reading artifacts. The top-level plan exposes the trust vocabulary and repeats the external authorization boundary in its read-only mutation contract.

`build_agent_handoff()` refuses selected context without valid trust metadata, copies the source context without rewriting its text, and carries the source plan's freshness record unchanged. It does not convert stale evidence into fresh evidence and does not manufacture operational permission.

## Adversarial verification

`test_repository_text_trust.py` covers instruction-like strings in:

- `AGENTS.md`;
- `README.md`;
- source comments;
- ordinary documentation;
- `tests/fixtures/*`;
- generated relation artifacts;
- inferred conventions.

The tests assert that the strings remain present in the handoff while all control grants stay empty. Schema validation covers both the descriptor and the handoff.

Focused regression command:

```bash
python3 -m pytest \
  merger/repoground/tests/test_repository_text_trust.py \
  merger/repoground/tests/test_context_compiler.py -q
```

Result on the implementation worktree: `41 focused trust/context tests passed`; `44 existing governance/contract tests passed` in the same final focused run.

Self-review hardening additionally covers tampered self-elevation, reserved control-authority declarations, missing exact citations, malformed digests, artifact-only citations, and missing freshness signals.

The same command also covers the CLI `--agent-handoff` projection.

## Non-claims and STOP

This slice does not establish:

- prompt-injection absence;
- safe behavior by every possible downstream agent;
- repository-rule correctness;
- completeness of rule-file discovery;
- semantic correctness of generated navigation;
- answer correctness;
- test sufficiency beyond the exercised contracts;
- runtime health;
- merge readiness;
- permission to execute, write, use the network, read secrets, merge, or deploy.

STOP: no Grabowski authorization mechanism, sandbox, secret boundary, network policy, merge policy, deployment path, generated documentation, or unrelated RepoGround naming surface is changed by this slice.
