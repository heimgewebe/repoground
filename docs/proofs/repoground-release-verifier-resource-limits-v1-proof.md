# RepoGround release verifier resource limits v1 — Proof

## Scope

This change is bound to RepoGround base commit
`1634b55183447fa6e846e231a0b1e6880039fc17` and source candidate
`candidate-f25824e798612dae155979be`, event `1513`.

It hardens only release-candidate verification. It does not change the release
format, builder output, licensing decision, distribution status or product runtime.

## Limits

- compressed archive: 64 MiB
- one regular archive member: 16 MiB
- total regular-file bytes: 128 MiB
- expansion ratio: 200:1
- archived LICENSE read: 1 MiB

The current tracked tree is about 13.1 MiB and its largest file is below 0.31 MiB,
so these limits retain substantial headroom.

## Enforcement

Tar metadata is inspected incrementally. Oversized members and aggregate limits are
rejected before member payloads are read. Required member reads are chunked and
bounded; source-bound content comparison checks declared size before reading.

## Validation

- targeted release-packaging tests
- Ruff on changed Python files
- complete repository test and CI readback on the final PR head

## Non-claims

This proof does not establish absence of CPU exhaustion below the limits, safety of
arbitrary future archive formats, public exposure of the verifier, release readiness,
deployment authorization or merge readiness before final review and CI.
