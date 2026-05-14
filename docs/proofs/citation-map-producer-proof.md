# Citation Map Producer — Real-Dump-Proof

**Datum:** 2026-05-14 (Hardening-Patch 2026-05-14)  
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
| `citation_map_jsonl` (Output) | _nicht im Manifest_ | `f7a7e62b01042149dfe59734e006d5ddbb876adb3d3d2cce0f42cc9d169b9c69` | N/A (neu erzeugt) |

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
| `output_bytes` | `316003` |
| `output_sha256` | `f7a7e62b01042149dfe59734e006d5ddbb876adb3d3d2cce0f42cc9d169b9c69` |

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
    "start_line": 1445,
    "end_line": 1501,
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
    "start_line": 1534,
    "end_line": 1598,
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
    "start_line": 1630,
    "end_line": 1819,
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

## Hardening-Patches (2026-05-14)

Folgende Punkte wurden nach dem initialen Proof gepatcht:

| Punkt | Patch |
|---|---|
| H1: Kein partieller Output bei Fehlern | Output wird nur geschrieben, wenn `errors == []`. `output_path=None` bei `status=fail`. |
| H2: Default-Output-Pfad sicher | `_default_output_path()` prüft `.bundle.manifest.json`-Suffix; Manifest-/Artefakt-Kollision → `status=fail`. |
| H3: `run_id` leer → Fehler | Manifest-`run_id` wird vor Nutzung als nicht-leerer String validiert. |
| H4: `repo_id`-Konflikte → Fehler | `resolve_repo_id()` sammelt alle Quellen; unterschiedliche Werte → `CitationMapError`. |
| H5: `start_line`/`end_line`-Semantik | `byte_range_to_line_range()` implementiert; Producer berechnet globale Zeilen aus `canonical_md`-Bytes. Input-Werte werden ignoriert. |
| H6: Registry-Tests ohne `inspect.getsource()` | `ARTIFACT_CONTRACT_REGISTRY` und `ARTIFACT_AUTHORITY_REGISTRY` auf Modulebene in `merge.py` hochgezogen; Tests importieren sie direkt. |

Der Output-SHA nach H1–H4/H6-Hardening war identisch mit dem Initialwert. Nach H5-Patch ändert sich der Output-SHA, da `start_line`/`end_line` jetzt canonical_md-global sind (statt quell-lokal).

## `start_line`/`end_line`-Semantik (H5 — Code-Patch)

**Contract-Entscheidung:** `canonical_range.description` im Schema lautet explizit „Position inside canonical_md. Authoritative locator for the citation." Damit sind `start_line`/`end_line` canonical_md-globale Positionen, keine quell-lokalen Werte.

**Implementierung:** `byte_range_to_line_range(canonical_md_bytes, start_byte, end_byte) -> (int, int)`

- Zählt `b"\n"`-Bytes direkt, ohne Dekodierung.
- `start_line = 1 + canonical_md_bytes.count(b"\n", 0, start_byte)`
- `end_line = 1 + canonical_md_bytes.count(b"\n", 0, end_byte - 1)`
- Ein `\n`-Byte gehört zur Zeile, die es terminiert.
- Input-`start_line`/`end_line` werden vollständig ignoriert; Produktion schlägt auch dann nicht fehl, wenn sie fehlen.

**Auswirkung auf den Real-Dump:** Der Dump `max-260514-0409` enthielt nur `content_range_ref` mit `start_line=1` bei allen 541 Chunks (quell-lokale Werte). Nach dem Patch liefern dieselben Byte-Ranges ihre kanonischen Positionen in `canonical_md`:

| Beispiel | start_byte | end_byte | alt (quell-lokal) | neu (canonical_md-global) |
|---|---|---|---|---|
| Zeile 1 | 123372 | 124513 | `1`–`57` | `1445`–`1501` |
| Zeile 2 | 125550 | 127566 | `1`–`65` | `1534`–`1598` |
| Zeile 3 | 128607 | 135091 | `1`–`190` | `1630`–`1819` |

Die `citation_id`-Werte sind identisch (sie hängen nicht von `start_line`/`end_line` ab).
Output-SHA änderte sich von `304a4d22...` auf `f7a7e62b...` — ausschließlich wegen korrigierter Zeilennummern.

## Manifest-Wiring (H6): Registry vorbereitet — Pipeline-Integration offen

`ARTIFACT_CONTRACT_REGISTRY[ArtifactRole.CITATION_MAP_JSONL]` und `ARTIFACT_AUTHORITY_REGISTRY[ArtifactRole.CITATION_MAP_JSONL]` sind in `merger/lenskit/core/merge.py` auf Modulebene definiert und werden von `write_reports_v2` referenziert.

`_add_artifact(citation_map_path, ArtifactRole.CITATION_MAP_JSONL, …)` wird in der Pipeline (Merger-Lauf) **noch nicht** automatisch aufgerufen — der Producer läuft separat via CLI. Die Registries sind vorbereitet, damit ein späterer Pipeline-Integrationsschritt die korrekten Manifest-Felder erhält.

Beim CLI-Lauf erzeugt der Producer die Datei, berechnet SHA256 und Bytes korrekt. Ein separater Schritt muss diese Werte ins Bundle-Manifest schreiben; das ist Phase-2-Arbeit.

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
