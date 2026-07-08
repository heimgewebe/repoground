# RPU-V1-T016 — Federated fleet bundle search proof

Status: implemented
Date: 2026-07-08

## Scope

This proof covers `RPU-V1-T016`: federated RepoBrief bundle search over multiple
repository bundles with explicit per-bundle freshness and authority boundaries.

The change keeps federation in the existing read-only retrieval layer. It does
not create snapshots, refresh bundles, mutate Git, run shells, open PRs, apply
patches or assert runtime truth.

## Implemented surfaces

### Registry-backed query

Existing persisted federation index queries remain supported:

```text
lenskit federation query --index federation_index.json -q "query text" --trace
```

The persisted `federation_index.json` is still schema-validated before bundle
access.

### Inline multi-bundle query

Federated search can now run directly over repeated bundle roots without writing
a `federation_index.json`:

```text
lenskit federation query \
  --bundle repo_a=/path/to/repo-a-bundle \
  --bundle repo_b=/path/to/repo-b-bundle \
  --federation-id local-fleet \
  -q "query text" \
  --trace
```

Each `--bundle` uses `REPO_ID=PATH`. The inline input is converted to a transient,
schema-validated federation object in memory only.

## Result provenance

Returned hits now carry both the legacy bundle tag and a structured origin object:

```json
{
  "federation_bundle": "repo_a",
  "federation_bundle_status": "ok",
  "federation_freshness_status": "unverified",
  "federation_origin": {
    "repo_id": "repo_a",
    "bundle_path": "/path/to/repo-a-bundle",
    "availability_status": "ok",
    "freshness_status": "unverified",
    "expected_fingerprint": null,
    "observed_fingerprint": null
  }
}
```

When a bundle is stale according to `last_fingerprint` versus the local SQLite
index metadata, hits from that bundle remain queryable but are explicitly marked:

```json
{
  "federation_bundle_status": "stale",
  "federation_freshness_status": "stale",
  "federation_origin": {
    "availability_status": "stale",
    "freshness_status": "stale"
  }
}
```

This prevents stale bundle results from being silently promoted as ordinary
fresh/current evidence.

## Acceptance mapping

- `rpu-v1-t016-multi-bundle`: satisfied by
  `execute_federated_query_from_bundles` and CLI repeated `--bundle` support;
  persisted `--index` queries remain supported.
- `rpu-v1-t016-freshness`: satisfied by per-hit
  `federation_bundle_status`, `federation_freshness_status` and
  `federation_origin` fields, including stale-hit tests.
- `rpu-v1-t016-no-global-truth`: preserved by read-only federation inputs,
  schema validation, explicit non-claims and unchanged heuristic boundaries for
  `cross_repo_links` and `federation_conflicts`.

## Validation

Targeted tests:

```text
python3 -m pytest -q \
  merger/lenskit/tests/test_federation_*.py \
  merger/lenskit/tests/test_api_federation.py
# 93 passed
```

Additional validation before merge should include the normal focused lint and
contract checks for the changed modules.

## Non-claims

This proof does not establish:

- ecosystem completeness;
- semantic identity between repositories;
- dependency relationships between repositories;
- runtime correctness;
- test sufficiency;
- review completeness;
- merge readiness;
- production query quality;
- global ranking correctness beyond the existing deterministic minimal ranking.
