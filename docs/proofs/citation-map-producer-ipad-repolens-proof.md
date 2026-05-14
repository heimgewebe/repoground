# Citation Map Producer — iPad repolens Dump Proof

**Datum:** 2026-05-14  
**Ergebnis:** PASS (WARN akzeptabel)  
**Dump-Identität:** `lenskit-max-260514-0847_merge` / run_id `lenskit-full-max-260514-0847`  
**Generator:** repolens / ios (Pythonista auf iPad) — version: unknown  
**Abgrenzung:** Dieser Proof belegt iPad-repolens-Dump-Kompatibilität. Er belegt **nicht** Heim-PC-rlens-Reproduzierbarkeit. `citation_map_jsonl` ist noch nicht automatisches Manifest-Artefakt; Pipeline-Emission bleibt separates Thema.

---

## 1. Dump-Dateien

Alle 8 Pflicht-Dateien gefunden unter `/home/alex/repos/merges/`:

| Datei | Status |
|---|---|
| `lenskit-max-260514-0847_merge.bundle.manifest.json` | OK |
| `lenskit-max-260514-0847_merge.md` | OK |
| `lenskit-max-260514-0847_merge.chunk_index.jsonl` | OK |
| `lenskit-max-260514-0847_merge.chunk_index.index.sqlite` | OK |
| `lenskit-max-260514-0847_merge.output_health.json` | OK |
| `lenskit-max-260514-0847_merge.json` | OK |
| `lenskit-max-260514-0847_merge.dump_index.json` | OK |
| `lenskit-max-260514-0847_merge.derived_index.json` | OK |

---

## 2. Phase 1 — Repo- und Branch-Proof

```
cwd:    /home/alex/repos/lenskit
branch: local-citation-map-producer
HEAD:   dc6aa983d41331eb963c3843bd982cae4285c7a6
```

`citation produce` verfügbar:

```
usage: lenskit citation produce [-h] [--output OUTPUT_PATH] [--json]
                                bundle_manifest
```

**Stop-Kriterium erfüllt: `citation produce` verfügbar.**

---

## 3. Phase 2 — Manifest-Artefakt-Tabelle

Manifest: 7 Artefakte, kein `citation_map_jsonl` (erwartet, Pipeline-Emission noch offen).

| role | bytes_manifest | bytes_actual | sha_match | exists | Status |
|---|---|---|---|---|---|
| canonical_md | 3626209 | 3626209 | True | True | OK |
| chunk_index_jsonl | 1159096 | 1159096 | True | True | OK |
| derived_manifest_json | 873 | 873 | True | True | OK |
| dump_index_json | 1759 | 1759 | True | True | OK |
| index_sidecar_json | 510883 | 510883 | True | True | OK |
| output_health | 1452 | 1452 | True | True | OK |
| sqlite_index | 5025792 | 5025792 | True | True | OK |

**Alle 7 Artefakte: SHA256 + Bytes korrekt.**

---

## 4. Phase 3 — Chunk-Index-Befund

| Metrik | Erwartet | Tatsächlich |
|---|---|---|
| Chunk-Zeilen | 606 | 606 |
| invalid JSON | 0 | 0 |
| missing chunk_id | 0 | 0 |
| canonical_range | 606/606 | 606/606 |
| source_range | 606/606 | 606/606 |
| content_range_ref | 606/606 | 606/606 |
| `.claude/worktrees` Pfade | 0 | 0 |
| Absolute/suspicious Pfade | 0 | 0 |

**artifact_role-Verteilung:**
- `canonical_range.artifact_role`: canonical_md × 606
- `content_range_ref.artifact_role`: canonical_md × 606
- `source_range.artifact_role`: MISSING (kein `artifact_role`-Feld in source_range) — dokumentiert, kein Blocker

**repo_id-Quellen:**
- `chunk.repo`: lenskit (in Top-Level-Feld)
- `search_keys.repo_id`: lenskit
- `canonical_range.repo_id`: lenskit (Produzenten-Kurzform: `range.repo_id`)
- `range.repo_id` (Top-Level): nicht vorhanden

---

## 5. Phase 4 — Range-Hash-Proof

Für alle 606 Chunks: `md_bytes[start_byte:end_byte]` SHA256 == `canonical_range.content_sha256`.

**Stichproben (erste 3 Chunks):**

| lineno | chunk_id (Prefix) | bytes | lines | sha_ok | file_path |
|---|---|---|---|---|---|
| 1 | a5b53ec3469b019615c5 | [131355:132496] | 1511–1567 | True | lenskit-max-260514-0847_merge.md |
| 2 | 90c27c9a7c947495fd5d | [133533:135549] | 1600–1664 | True | lenskit-max-260514-0847_merge.md |
| 3 | ac8037619ccf86109969 | [136590:143074] | 1696–1885 | True | lenskit-max-260514-0847_merge.md |

**file_path-Abweichungen: 0**  
**Ergebnis: 606/606 PASS**

---

## 6. Phase 5 — SQLite/FTS-Proof

| Metrik | Erwartet | Tatsächlich |
|---|---|---|
| chunks-Rows | 606 | 606 |
| FTS-Tabelle | chunks_fts | vorhanden |
| FTS-Rows | 606 | 606 |
| leere FTS-Content-Rows | 0 | 0 |
| FTS content min/avg/max (bytes) | — | 9 / 5085 / 8192 |

Tabellen im SQLite: `chunks`, `chunks_fts`, `chunks_fts_config`, `chunks_fts_content`, `chunks_fts_data`, `chunks_fts_docsize`, `chunks_fts_idx`, `index_meta`

**Ergebnis: PASS**

---

## 7. Phase 6 — Output-Health-Befund

```json
{
  "verdict": "warn",
  "errors": [],
  "warnings": ["range_ref schema validation skipped: jsonschema unavailable"],
  "chunk_count": 606,
  "sqlite_row_count": 606,
  "sqlite_fts_row_count": 606,
  "fts_content_non_empty": true,
  "fts_empty_row_count": 0,
  "range_ref_resolution_status": "environment_error"
}
```

`verdict=warn` akzeptabel: einzige Warning ist `jsonschema unavailable` (environment_error, kein Inhaltsfehler).  
`errors = []` — kein blockierender Befund.

**Ergebnis: WARN (akzeptabel)**

---

## 8. Phase 7 — Citation Producer Run

**Kommando:**
```bash
python3 -m merger.lenskit.cli.main citation produce --json \
  /home/alex/repos/merges/lenskit-max-260514-0847_merge.bundle.manifest.json \
  --output /home/alex/.claude/jobs/2561146b/lenskit-max-260514-0847_merge.citation_map.jsonl
```

**Producer-Report (Auszug):**

| Feld | Wert |
|---|---|
| status | ok |
| chunk_count | 606 |
| valid_chunk_count | 606 |
| citation_map_row_count | 606 |
| citation_id_duplicate_count | 0 |
| repo_id_source | range.repo_id (= canonical_range.repo_id) |
| snapshot_source | bundle_manifest |
| output_bytes | 354043 |
| output_sha256 | 96a00ed5747434c36cdccd2f1b21c44778663f14b688ffdc11ae3fab9bc603ff |
| errors | [] |
| warnings | [] |

**SHA256-Verifikation:** Actual == Reported — MATCH.

**Stichprobe (erste Zeile):**
```json
{
  "citation_id": "cit_758219a992c2ee22",
  "repo_id": "lenskit",
  "snapshot": {
    "run_id": "lenskit-full-max-260514-0847",
    "canonical_md_path": "lenskit-max-260514-0847_merge.md",
    "canonical_md_sha256": "bf7fb5a15bb864af0b6c22ff379b8f0369e53903460f2ccb4d8ebeaa7bcdeae8"
  },
  "canonical_range": {
    "file_path": "lenskit-max-260514-0847_merge.md",
    "start_byte": 131355,
    "end_byte": 132496,
    "start_line": 1511,
    "end_line": 1567,
    "content_sha256": "07d82137b0a8af1546a0c87ef8259c3a9da982b4e2a5d609aa790a63d6a10cb4"
  },
  "produced_by": "citation_map_producer/v1",
  "chunk_id": "a5b53ec3469b019615c5"
}
```

---

## 9. Schema-Validierung

`jsonschema` lokal verfügbar. Validierung gegen `merger/lenskit/contracts/citation-map.v1.schema.json`:

| Metrik | Wert |
|---|---|
| Validierte Zeilen | 606 |
| Schema-Fehler | 0 |

**Ergebnis: 606/606 PASS**

---

## 10. Gesamturteil

**PASS** (mit WARN für `jsonschema unavailable` im iPad-seitigen output_health — kein Blocker)

| Phase | Status |
|---|---|
| Phase 1: Repo + CLI | PASS |
| Phase 2: Manifest-Integrität | PASS |
| Phase 3: Chunk-Index | PASS |
| Phase 4: Range-Hash-Proof | PASS (606/606) |
| Phase 5: SQLite/FTS | PASS |
| Phase 6: output_health | WARN (akzeptabel) |
| Phase 7: Citation Producer | PASS |
| Phase 8: Schema-Validierung | PASS (606/606) |

---

## 11. Offene Punkte (nicht in diesem Proof)

1. **`source_range.artifact_role` fehlt** in allen 606 Chunks — kein Fehler laut aktuellem Schema, aber dokumentiert.
2. **Heim-PC-rlens-Reproduzierbarkeit** — separater Folgeauftrag: Heim-PC-Dump gegen dieselben Invarianten laufen lassen.
3. **Pipeline-Emission** — `citation_map_jsonl` noch nicht automatisches Manifest-Artefakt. Separate Verdrahtung via `_add_artifact(citation_map_path, ArtifactRole.CITATION_MAP_JSONL, ...)` steht aus.
4. **Top-Level `range.repo_id`** fehlt — Producer verwendet `canonical_range.repo_id` (Kurzform `range.repo_id`). Kein funktionaler Fehler.
