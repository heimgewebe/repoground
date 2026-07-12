# RepoBrief Read-only Adapter without Mirror Authority v1 — proof

Status: local runtime validation complete
Technical commit: `052c1dcd1729d5c22bc7e4c298f7b0d7fa0cddfc`
Technical tree: `8dba34ac2b6bb9562bcce6b499d79ff297dbaa56`

## Implemented boundary

The protocol-neutral adapter accepts only exact manifests beneath explicit
allowed roots. Content reads are path-contained, size-bounded and checked
against manifest byte length and SHA-256. SQLite and symbol indices are verified
before and after delegated reads; a failed postflight discards the computed
result. Missing or altered evidence therefore fails closed. Adapter dispatch
contains no Git, shell, network, snapshot creation or write implementation.

## Real-bundle validation

A clean checkout at the technical commit produced a redacted `full-max` bundle:

```text
bundle manifest SHA-256  fb6250d5ab39bb0c8fee48067ab3cd67c3eab535745385c28c2cef28f9645df2
manifest artifacts       21
generated files          26
post-emit health          pass
surface validation       pass
agent export gate         pass
export safety             pass
```

The adapter listed exactly the one configured snapshot. Query and symbol reads
succeeded. Hash inventories of all bundle files before and after every read were
byte-identical. No SQLite WAL, SHM or journal file was created.

## Focused tests

The adapter/evaluation suite contains 19 passing tests. It covers root escape,
unknown registration, hidden unregistered manifests, integrity drift, read-only
SQLite use, absence of SQLite sidecars, forbidden action dispatch, CLI list/call,
goldset schema and bounded usefulness evaluation.

## Compatibility contract

`docs/contracts/repobrief-readonly-adapter-compatibility.v1.json` binds every
adapter action to its library method and CLI entry. It separately labels MCP
surfaces as shared, analogous or unbound. This prevents an undocumented claim
that a code-level adapter is already an MCP transport server.

## Non-claims

The proof does not establish MCP deployment, authentication, remote freshness,
repository understanding, answer correctness, test sufficiency, review
completeness, security completeness or merge readiness.
