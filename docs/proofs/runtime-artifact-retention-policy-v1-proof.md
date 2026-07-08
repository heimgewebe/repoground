# Runtime Artifact Retention Policy v1 proof

Task: `TASK-RUNTIME-ARTIFACT-RETENTION-001` / Bureau `RPU-V1-T008`.

Status: explicit deferral of TTL, garbage collection and deletion for query runtime artifacts, encoded as machine-readable policy.

## Implemented policy surface

The policy surface is:

```text
merger/lenskit/service/runtime_artifact_retention.py
```

It exposes:

```text
runtime_artifact_retention_policy()
runtime_artifact_metadata_table()
runtime_artifact_metadata_for(artifact_type)
```

The policy applies to:

```text
query_trace
context_bundle
agent_query_session
```

## Current decision

The current retention decision is explicit:

```json
{
  "policy_id": "runtime-artifact-retention.v1",
  "status": "explicitly_deferred",
  "default_retention_policy": "unbounded_currently",
  "ttl": { "enabled": false, "default_ttl_seconds": null },
  "gc": { "enabled": false, "automatic_delete": false },
  "no_surprise_delete": {
    "existing_artifacts_deleted_by_this_policy": false,
    "store_write_path_deletes_existing_entries": false,
    "lookup_deletes_expired_entries": false
  }
}
```

This means the store remains unbounded. That is intentional in this slice. The previous implicit state is now a machine-readable decision rather than a comment-only limitation.

## Store integration

`QueryArtifactStore` derives `_RUNTIME_ARTIFACT_METADATA` from `runtime_artifact_metadata_table()`.

New entries carry the same lifecycle fields as before and now also carry the policy-only fields:

```text
ttl_enabled: false
ttl_seconds: null
gc_enabled: false
gc_mode: not_implemented
deletion_mode: not_supported_by_policy
```

Store diagnostics expose:

```text
retention_policy_id: runtime-artifact-retention.v1
retention_policy_status: explicitly_deferred
gc_enabled: false
ttl_enabled: false
```

## Backward compatibility

Legacy entries are backfilled on read and are not rewritten by lookup or diagnostics. No migration is required.

## No-surprise-delete boundary

This slice adds no deletion API, no cleanup API, no scheduler, no TTL expiry enforcement and no GC pass. Existing artifacts are not silently removed.

## Validation scope

Tests cover:

- machine-readable policy shape;
- policy coverage for all valid runtime artifact types;
- unknown artifact type rejection;
- stored entries carrying policy-derived no-TTL/no-GC fields;
- diagnostics exposing policy identity without mutating the store file;
- legacy entry read-backfill without rewrite.

## Non-claims

This proof does not establish:

- TTL is active;
- GC is active;
- automatic deletion exists;
- storage is bounded;
- artifacts are fresh;
- migration has run;
- operator cleanup is safe.
