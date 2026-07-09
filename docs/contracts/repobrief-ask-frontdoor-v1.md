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
- retrieval hits;
- resolved ranges;
- answer scaffold;
- forbidden operations;
- mandatory non-claims.

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
