# Citation Map Pipeline Emission Proof

- Datum: 2026-05-15
- Repo HEAD: 36553b82b201c3b6803ab6cb30e7809425b1b7df
- Dump stem: lenskit-max-260515-0952_merge
- Manifest-Pfad: /home/alex/repos/merges/lenskit-max-260515-0952_merge.bundle.manifest.json

## Output Health

- Datei: /home/alex/repos/merges/lenskit-max-260515-0952_merge.output_health.json
- verdict: pass
- errors: []
- warnings: []
- range_ref_resolution_status: ok

## Manifest-Artefaktliste (Auszug)

- canonical_md: lenskit-max-260515-0952_merge.md
- chunk_index_jsonl: lenskit-max-260515-0952_merge.chunk_index.jsonl
- citation_map_jsonl: lenskit-max-260515-0952_merge.citation_map.jsonl
- dump_index_json: lenskit-max-260515-0952_merge.dump_index.json
- derived_manifest_json: lenskit-max-260515-0952_merge.derived_index.json
- index_sidecar_json: lenskit-max-260515-0952_merge.json
- retrieval_eval_json: lenskit-max-260515-0952_merge.retrieval_eval.json
- sqlite_index: lenskit-max-260515-0952_merge.chunk_index.index.sqlite
- output_health: lenskit-max-260515-0952_merge.output_health.json

## Citation Map Presence

- role == citation_map_jsonl im Manifest: true
- authority: navigation_index
- canonicality: derived
- regenerable: true
- staleness_sensitive: true

## Count-Konsistenz

- citation_map_row_count: 613
- chunk_index_row_count: 613
- Ergebnis: gleich

## SHA/Bytes-Proof (citation_map_jsonl)

- Datei: /home/alex/repos/merges/lenskit-max-260515-0952_merge.citation_map.jsonl
- manifest bytes: 358146
- actual bytes: 358146
- manifest sha256: 53e72777e00c3b2d03bec8aaa34882f623390a772a611289ba3b59e9bbc8cf33
- actual sha256: 53e72777e00c3b2d03bec8aaa34882f623390a772a611289ba3b59e9bbc8cf33
- Ergebnis: identisch

## Canonical MD SHA Link

- canonical_md manifest sha256: ab0d6aadf9421dd8b1e0fa6d4b5137ed04871d1ccdbcb8a40e0c40de962fff03
- citation snapshot canonical_md_sha256: ab0d6aadf9421dd8b1e0fa6d4b5137ed04871d1ccdbcb8a40e0c40de962fff03
- Ergebnis: identisch

## Validator-Ergebnis

Befehl:

```bash
python3 -m merger.lenskit.cli.main citation validate \
  /home/alex/repos/merges/lenskit-max-260515-0952_merge.bundle.manifest.json --json
```

Ergebnis:

- status: ok
- error_kind: ok
- citation_id_count: 613
- citation_id_duplicate_count: 0
- canonical_range_hash_ok_count: 613
- errors: []

## Schema-Validierung

Befehl: Zeilenweise JSON-Schema-Validierung gegen merger/lenskit/contracts/citation-map.v1.schema.json

Ergebnis:

- schema_validated_rows: 613
- Fehler: keine

## Runtime-Artefakt-Regression

- Prüfung: Kein strukturierter Pfad unter .claude/worktrees in Citation Map oder Manifest.
- Ergebnis: keine Treffer.

## Commit-Hygiene

- Es wurden keine Dateien aus /home/alex/repos/merges committed.
- Es wurden keine lokalen Runtime-Dateien wie .claude/settings.local.json oder .claude/worktrees committed.
