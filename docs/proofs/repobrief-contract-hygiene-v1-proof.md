# RepoBrief contract hygiene v1 proof

Task: `RPU-V1-T019`
Status: implementation proof for small contract/output-shape repairs.

## Repairs

### Citation map range refs

Newly produced `citation_map_jsonl` rows now include a strict `range_ref` object that can be passed directly to RepoBrief range resolution. The field mirrors the row's canonical range:

- `artifact_role: canonical_md`
- `repo_id`
- `file_path`
- `start_byte`
- `end_byte`
- `start_line`
- `end_line`
- `content_sha256`
- optional `chunk_id`

The field remains optional in `citation-map.v1.schema.json` so older bundles remain readable. RepoBrief access synthesizes the same `range_ref` for legacy citation-map rows when the row is otherwise valid.

### Query JSON line and source metadata

Raw `query --emit json` results now preserve direct source and range fields in each hit:

- `source_path`
- `line_range`
- `start_line`
- `end_line`
- `byte_range`
- `start_byte`
- `end_byte`

The legacy string field `range` remains for compatibility.

### Agent Reading Pack top chunk spans

`TOP_CHUNK_SPANS` now reports an explicit status:

- `available` when canonical chunk spans are present;
- `not_applicable` with `reason_code` when the surface cannot be populated.

This avoids treating an empty section as a silent success or as implicit absence evidence.

## Validation surface

Focused tests cover:

- direct `citation_map.range_ref` production and `range_get` consumption;
- schema validation for optional `range_ref` and backwards compatibility when absent;
- legacy citation-map synthesis through `query_existing_index(..., resolve_evidence=True)`;
- `query --emit json` direct line/source/byte metadata;
- `TOP_CHUNK_SPANS` available and explicit `not_applicable` states.

## Non-claims

This proof does not establish:

- runtime correctness;
- test sufficiency beyond the checked scope;
- review completeness;
- merge readiness;
- repo understanding;
- claim truth;
- agent quality improvement.
