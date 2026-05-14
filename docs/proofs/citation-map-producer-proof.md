# Citation Map Producer — Real-Dump-Proof

**Datum:** 2026-05-14  
**Status: PASS**

---

## Dump-Identität

- **Dump-Stem:** `lenskit-max-260514-0409_merge`
- **Manifest-Pfad:** `/home/alex/repos/merges/lenskit-max-260514-0409_merge.bundle.manifest.json`
- **run_id:** `lenskit-full-max-260514-0409`
- **created_at:** `2026-05-14T04:09:20Z`
- **Generator:** `rlens dev`

---

## Manifest-Artefakte (Iststand)

| Rolle | Pfad | Bytes | SHA256 |
|---|---|---|---|
| `canonical_md` | `lenskit-max-260514-0409_merge.md` | 3176159 | `05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df` |
| `chunk_index_jsonl` | `lenskit-max-260514-0409_merge.chunk_index.jsonl` | 720803 | `b1849a0649c82a99e44e9235c018e8acb8f08c2f86014d434f594805e93e3086` |
| `derived_manifest_json` | `lenskit-max-260514-0409_merge.derived_index.json` | 1182 | `2224d3f8dacaab95d69599e2929844cf152a40b26b1c84a005d13a086b6f0cc0` |
| `dump_index_json` | `lenskit-max-260514-0409_merge.dump_index.json` | 1781 | `0b3ad60702467eb10e68b57c8b08431465d19af5c35a97053ce0a9838fd2f221` |
| `index_sidecar_json` | `lenskit-max-260514-0409_merge.json` | 468359 | `9da8c1386fc363fa763bac4d7ca8eca6a3dfe4d71299e18b02b415af4312f6da` |
| `retrieval_eval_json` | `lenskit-max-260514-0409_merge.retrieval_eval.json` | 18167 | `1dbdab8344a484cfdd55412fda1285020614314b77a037128e5495957cfc6888` |
| `sqlite_index` | `lenskit-max-260514-0409_merge.chunk_index.index.sqlite` | 499712 | `f097196814472a8b5f55cc66b5a8100e5bd523766b074226fdc91c7063ae10dd` |

Alle 7 Manifest-Artefakte existieren. Kein Artefakt fehlt.

---

## SHA256-Verifikation Manifest vs. Actual

| Rolle | Manifest | Actual | Match |
|---|---|---|---|
| `canonical_md` | `05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df` | `05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df` | **✓** |
| `chunk_index_jsonl` | `b1849a0649c82a99e44e9235c018e8acb8f08c2f86014d434f594805e93e3086` | `b1849a0649c82a99e44e9235c018e8acb8f08c2f86014d434f594805e93e3086` | **✓** |
| `citation_map_jsonl` (Output) | _nicht im Manifest_ | `304a4d229217e9926d1b5b3f544720a17195932ea175af44d084364b9259ad08` | N/A (neu erzeugt) |

---

## Chunk-Index Scan (Iststand)

| Kennzahl | Wert |
|---|---|
| `chunk_count` | `541` |
| `canonical_range` vorhanden | `0` |
| `content_range_ref` vorhanden | `541` |
| `content_range_ref.artifact_role == "canonical_md"` | `541` |
| `source_range` vorhanden | `0` |
| Eindeutige `repo` (chunk-Feld) | `['lenskit']` |
| Eindeutige `repo_id` (search_keys) | `['lenskit']` |

Befund: Dieser Dump enthält ausschließlich `content_range_ref` (kein `canonical_range`). Die Normalisierungsregel greift: `content_range_ref` mit `artifact_role == "canonical_md"` wird als `canonical_range` behandelt.

---

## Producer-Run

```bash
python3 -m merger.lenskit.cli.main citation produce --json \
  /home/alex/repos/merges/lenskit-max-260514-0409_merge.bundle.manifest.json
```

---

## Producer-Ergebnis

| Kennzahl | Wert |
|---|---|
| `status` | `ok` |
| `error_kind` | `ok` |
| `chunk_count` | `541` |
| `valid_chunk_count` | `541` |
| `citation_map_row_count` | `541` |
| `citation_id_count` | `541` |
| `citation_id_duplicate_count` | `0` |
| `repo_id_source` | `range.repo_id` |
| `snapshot_source` | `bundle_manifest` |
| `output_bytes` | `313222` |
| `output_sha256` | `304a4d229217e9926d1b5b3f544720a17195932ea175af44d084364b9259ad08` |

---

## Quellen

| Feld | Quelle | Wert |
|---|---|---|
| `repo_id` | `content_range_ref.repo_id` (= `range.repo_id` nach Normalisierung) | `lenskit` |
| `snapshot.run_id` | Bundle-Manifest `run_id` | `lenskit-full-max-260514-0409` |
| `snapshot.canonical_md_path` | Manifest-Artefakt `role == "canonical_md"` → `path` | `lenskit-max-260514-0409_merge.md` |
| `snapshot.canonical_md_sha256` | Manifest-Artefakt `role == "canonical_md"` → `sha256` (verifiziert gegen Actual) | `05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df` |

---

## Schema-Validierung

Alle 541 Zeilen der erzeugten `citation_map_jsonl` wurden gegen
`merger/lenskit/contracts/citation-map.v1.schema.json` (Draft-07) validiert.

- Schema-Fehler: `0`
- Schema-Validierung: **PASS**

---

## Drei Beispielzeilen

```json
{
  "citation_id": "cit_498625f8222aaa3c",
  "repo_id": "lenskit",
  "snapshot": {
    "run_id": "lenskit-full-max-260514-0409",
    "canonical_md_path": "lenskit-max-260514-0409_merge.md",
    "canonical_md_sha256": "05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df"
  },
  "canonical_range": {
    "file_path": "lenskit-max-260514-0409_merge.md",
    "start_byte": 123372,
    "end_byte": 124513,
    "start_line": 1,
    "end_line": 57,
    "content_sha256": "07d82137b0a8af1546a0c87ef8259c3a9da982b4e2a5d609aa790a63d6a10cb4"
  },
  "produced_by": "citation_map_producer/v1",
  "chunk_id": "a5b53ec3469b019615c5"
}
```

```json
{
  "citation_id": "cit_1cc6148d85771a88",
  "repo_id": "lenskit",
  "snapshot": {
    "run_id": "lenskit-full-max-260514-0409",
    "canonical_md_path": "lenskit-max-260514-0409_merge.md",
    "canonical_md_sha256": "05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df"
  },
  "canonical_range": {
    "file_path": "lenskit-max-260514-0409_merge.md",
    "start_byte": 125550,
    "end_byte": 127566,
    "start_line": 1,
    "end_line": 65,
    "content_sha256": "770dc60e8f9a04b5596f068d6813927c573f9351ce7f08e784211b5f61d74e99"
  },
  "produced_by": "citation_map_producer/v1",
  "chunk_id": "90c27c9a7c947495fd5d"
}
```

```json
{
  "citation_id": "cit_d8ea672755da5920",
  "repo_id": "lenskit",
  "snapshot": {
    "run_id": "lenskit-full-max-260514-0409",
    "canonical_md_path": "lenskit-max-260514-0409_merge.md",
    "canonical_md_sha256": "05e38a5aadf4becaac1952eca86246429f9dd6cf57b7593f4810155525cf95df"
  },
  "canonical_range": {
    "file_path": "lenskit-max-260514-0409_merge.md",
    "start_byte": 128607,
    "end_byte": 135091,
    "start_line": 1,
    "end_line": 190,
    "content_sha256": "2e2237dc13ee8ac56edb1425ad278a9671de0cd77faed1d61c151d85c19c5687"
  },
  "produced_by": "citation_map_producer/v1",
  "chunk_id": "ac8037619ccf86109969"
}
```

---

## Normalisierungsregel (angewendet)

Dieser Dump enthält `content_range_ref` statt `canonical_range`. Die Producer-Normalisierung:

1. Prüft `chunk["canonical_range"]`: nicht vorhanden → weiter
2. Prüft `chunk["content_range_ref"]` mit `artifact_role == "canonical_md"`: vorhanden → verwende als `canonical_range`
3. Output-Feld heißt immer `canonical_range` (Legacy-Input `content_range_ref` ist nicht im Output)

---

## Invarianten des Producers

- Producer schreibt; validiert nichts außer dem nötigen für die Produktion.
- Byte-Range-Hash jeder Range wird gegen `canonical_md` geprüft; Fehler → Zeile übersprungen.
- `make_citation_id(canonical_md_sha256, start_byte, end_byte, content_sha256)` wird für jede Zeile aufgerufen.
- `citation_map_jsonl` wird nie als `canonical_content` oder `content_source` eingestuft.
- Pfad-Traversal, absolute Pfade, Windows-Drive-Prefixe, UNC-Pfade werden abgelehnt.
- Duplikate werden als Fehler behandelt (Zeile wird übersprungen).

---

## Abgrenzung zu vorherigen Proofs

Dieser Proof ist der **Producer-Proof** (`citation_map_jsonl` erzeugen).

Der **Validator-Proof** (`docs/proofs/citation-readiness-validator-proof.md`) belegt
ausschließlich, dass `merger/lenskit/core/citation_validate.py` korrekt liest und validiert.
Er erzeugt kein `citation_map_jsonl`.

---

## Ergebnis

**PASS** — Real-Dump-Proof gegen `/home/alex/repos/merges/lenskit-max-260514-0409_merge.bundle.manifest.json` bestanden.

- 541 Chunks verarbeitet
- 541 schema-valide, hash-geprüfte, duplikatfreie Citation-Map-Zeilen erzeugt
- `repo_id`-Quelle eindeutig: `range.repo_id` (`content_range_ref.repo_id`)
- `snapshot`-Quelle eindeutig: Bundle-Manifest
