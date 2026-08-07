# RepoBrief Ask Frontdoor v1

Status: contract_design
Initiative: `REPOBRIEF-FRONTDOOR-GROUNDING-V1`
Task: `RBGV-V1-T004`

## Purpose

The Ask Frontdoor contract defines the read-only shape for preparing answer context from
existing RepoBrief artifacts.

It has two surfaces:

- `repobrief-ask-request.v1.schema.json` — input request;
- `repobrief-ask-context-pack.v1.schema.json` — prepared context and answer scaffold.

## Request contract

The request must declare:

- `query`;
- `task_profile`;
- `token_budget`;
- snapshot/freshness policy;
- output mode;
- forbidden operations;
- mandatory non-claims.

The only snapshot mode in v1 is `existing_snapshot_only`.

## Context-pack contract

The context pack must carry:

- snapshot reference;
- freshness status and caveats;
- availability status and caveats;
- required-reading result;
- retrieval-infrastructure state;
- retrieval hits;
- resolved ranges;
- answer scaffold;
- forbidden operations;
- mandatory non-claims.

`availability` describes the snapshot; `retrieval_infrastructure` describes the
search backend the pack queried. They are separate because a bundle can be
perfectly available while carrying no index to search — a pack that reports only
the former answers every query with zero hits and calls itself available, which
a caller cannot distinguish from a repository that genuinely holds no match. A
pack whose `retrieval_infrastructure.index_resolved` is false makes no claim
about what the repository contains.

## Read-only boundary

The contract forbids implicit refresh, Git mutation, snapshot creation on read, patch
application, pull-request mutation, shell execution and merge authorization.

## Answer scaffold

The scaffold makes citation obligations, caveats and non-claims visible to downstream
agents. It is not an answer and not a proof that any agent read or understood evidence.

## Non-claims

A valid request or context pack does not establish answer correctness, claim truth, actual
reading, complete context use, repository understanding, runtime correctness, test
sufficiency, merge readiness, security correctness, forensic readiness or regression absence.

## CLI prototype

`repobrief ask` is the minimal v1 producer for this context-pack shape. It reads an existing bundle manifest, queries the existing read-only index, resolves evidence ranges where available and emits either JSON or a human-readable context pack.

The emitted `budget` block reports `max_context_tokens`, `max_answer_tokens`, approximate context characters used and whether truncation happened. This is a constraint record, not a quality proof.
