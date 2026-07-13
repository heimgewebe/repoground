# RepoBrief MCP stdio and live freshness v1 proof

Status: implementation candidate; repository CI and final head-bound review pending.  
Bureau: `heimgewebe/bureau#468`  
Branch: `feat/repobrief-mcp-stdio-freshness-v1`

## Result

This slice adds the missing local protocol binding between MCP clients and the existing
RepoBrief code-level surfaces:

- newline-delimited JSON-RPC stdio lifecycle;
- `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`,
  `resources/templates/list`, and `resources/read`;
- bindings for existing `ask_context`, `grounding_verify`, and resource handlers;
- opt-in binding for the existing explicit `snapshot_create` write handler;
- a separate live-freshness result that compares one snapshot with one configured checkout.

## Freshness contract

A snapshot is `fresh` only when:

1. snapshot Git provenance is present;
2. snapshot cleanliness is explicitly `false`;
3. current Git provenance is present;
4. current cleanliness is explicitly `false`;
5. snapshot commit and current `HEAD` match.

A mismatch or dirty state is `stale`. Missing evidence is not promoted to fresh.
No result performs an implicit rebuild or network operation.

## Security boundary

- MCP manifest arguments remain inside the configured bundle root.
- Citation-map overrides remain inside the selected bundle directory.
- The MCP server never trusts a manifest-recorded path as permission to probe an arbitrary
  checkout; live Git inspection runs only when the operator starts the server with
  `--repo-root`.
- Git inspection is direct, read-only, time-bounded, network-free, and disables optional
  locks, fsmonitor, global/system Git configuration, and terminal prompts.
- `snapshot_create` is absent from `tools/list` unless explicitly enabled at server startup.
- No TCP/HTTP listener, Git mutation, shell, patch, PR, secret, review, fix, or merge authority
  is introduced.

## Pre-publication validation

The implementation and its tests were loaded in an isolated package simulation and executed:

```text
17 passed
```

This checks Python loading, the JSON-RPC lifecycle, tool exposure, bundle-root binding,
resource metadata, freshness state transitions, newline framing, and parse-error handling.
It is not a substitute for the repository's full CI. Final validation evidence must be bound
to the published PR head.

## Does not establish

This proof does not establish network transport security, authentication, remote freshness,
repository truth, answer correctness, complete code understanding, runtime correctness, test
sufficiency, review completeness, regression absence, release readiness, or merge readiness.
