# Citation Readiness Validator — Real-Dump-Proof

**Datum:** 2026-05-13  
**Validator-Rolle:** Konsument / Readiness-Gate. Kein Producer.

---

## Status: PASS — gegen echten aktuellen Dump verifiziert

Der Proof wurde gegen einen real mit dem aktuellen Merger erzeugten Dump ausgeführt:

- Manifest: `/tmp/lenskit-hub/merges/lenskit-max-260513-1503_merge.bundle.manifest.json`
- Canonical MD: `/tmp/lenskit-hub/merges/lenskit-max-260513-1503_merge.md`
- Chunk Index: `/tmp/lenskit-hub/merges/lenskit-max-260513-1503_merge.chunk_index.jsonl`

Repo-belegte Korrektur gegenüber dem alten STOP-Bericht:

- Der reale Chunk-Index-Dateiname ist `lenskit-max-260513-1503_merge.chunk_index.jsonl`, **nicht** `..._chunk_index.jsonl`.
- Die reale Chunk-Zahl ist **594**, **nicht 585**.
- Der Validator funktioniert gegen die reale Bundle-Struktur **unverändert korrekt**.

---

## Real-Dump-Iststand

### Manifest-Identität

- `run_id`: `lenskit-full-max-260513-1503`
- `created_at`: `2026-05-13T15:03:52Z`

### Reale Artifact-Rollen im Bundle

| Rolle | Pfad | SHA256 |
|---|---|---|
| `canonical_md` | `lenskit-max-260513-1503_merge.md` | `94503fb079ae26d263ef056959a10ba34557183a988ec4b7233e4e5cdf4bd8d4` |
| `chunk_index_jsonl` | `lenskit-max-260513-1503_merge.chunk_index.jsonl` | `7071b6816612c7c7e4fe536a4f9acff5a82a1285c8f5872ce69b4caf8beb657a` |
| `derived_manifest_json` | `lenskit-max-260513-1503_merge.derived_index.json` | `d880548822d9c235305c6dcdf7600a48bc61b4394e090a540684896a60cece32` |
| `dump_index_json` | `lenskit-max-260513-1503_merge.dump_index.json` | `7bf1e04450b25d63b19527a24ed93ff50c6df206c4076ec33e57e2b253430fd4` |
| `index_sidecar_json` | `lenskit-max-260513-1503_merge.json` | `178322965d5613b323cb5ce992ec9d864a79ddd3db70970f11a6b51a5f901e56` |
| `output_health` | `lenskit-max-260513-1503_merge.output_health.json` | `0f127cf83af7db714c9b07790babfc1e8e9c3379cf3a8cb85b1af7ecef3d199e` |
| `retrieval_eval_json` | `lenskit-max-260513-1503_merge.retrieval_eval.json` | `77b8a2b461669475f602077887ad3c7de5f104ee32eb9de90fa96306bba50bbf` |
| `sqlite_index` | `lenskit-max-260513-1503_merge.chunk_index.index.sqlite` | `fe71c0e9d95eb1b8c38de09499732a48a48a9e83e0ae2d1a59707cc88474ed88` |

Manifest- und Dateihashes stimmen für die vom Validator verwendeten Artefakte exakt überein:

- `canonical_md`: Manifest = Actual = `94503fb079ae26d263ef056959a10ba34557183a988ec4b7233e4e5cdf4bd8d4`
- `chunk_index_jsonl`: Manifest = Actual = `7071b6816612c7c7e4fe536a4f9acff5a82a1285c8f5872ce69b4caf8beb657a`

### Reale Chunk-Struktur

Gemessener Iststand des echten `chunk_index.jsonl`:

- `chunk_count`: `594`
- `canonical_range_count`: `594`
- `source_range_count`: `594`
- `content_range_ref_count`: `594`
- `canonical_range.artifact_role`: in allen Chunks `canonical_md`
- `content_range_ref.artifact_role`: in allen Chunks `canonical_md`

Belegtes Strukturbeispiel:

- `canonical_range`:
  - `artifact_role`: `canonical_md`
  - `file_path`: `lenskit-max-260513-1503_merge.md`
  - `start_byte`: `130446`
  - `end_byte`: `131587`
  - `content_sha256`: `07d82137b0a8af1546a0c87ef8259c3a9da982b4e2a5d609aa790a63d6a10cb4`
- `source_range`:
  - `file_path`: `.ai-context.yml`
  - `status`: `declared`
  - `start_byte`: `0`
  - `end_byte`: `1141`
  - `content_sha256`: `07d82137b0a8af1546a0c87ef8259c3a9da982b4e2a5d609aa790a63d6a10cb4`
- `content_range_ref`:
  - `artifact_role`: `canonical_md`
  - `file_path`: `lenskit-max-260513-1503_merge.md`
  - `start_byte`: `130446`
  - `end_byte`: `131587`
  - `content_sha256`: `07d82137b0a8af1546a0c87ef8259c3a9da982b4e2a5d609aa790a63d6a10cb4`

---

## Validator-Run

Ausgeführt wurde derselbe CLI-Pfad über das Repo-Entrypoint-Modul:

```bash
python3 -m merger.lenskit.cli.main citation validate --json \
  /tmp/lenskit-hub/merges/lenskit-max-260513-1503_merge.bundle.manifest.json
```

Ergebnis:

- `status`: `ok`
- `error_kind`: `ok`
- `bundle_run_id`: `lenskit-full-max-260513-1503`
- `chunk_count`: `594`
- `canonical_range_count`: `594`
- `citation_id_count`: `594`
- `citation_id_duplicate_count`: `0`
- `canonical_range_hash_ok_count`: `594`
- `errors`: `[]`
- `warnings`: `[]`

Beispielhafte abgeleitete `citation_id`s:

- `cit_d2f401c0588a4655`
- `cit_f9202e15f45e2e24`
- `cit_6e2c91283d8309db`
- `cit_1c1274a83c8104bb`
- `cit_23b4907ba9319cdb`

---

## Diagnose

Es wurde **keine reale Abweichung** zwischen Implementierung und tatsächlicher Bundle-Struktur gefunden.

Der einzige belegte Korrekturbedarf lag in der Dokumentation des alten STOP-Berichts:

1. Real-Dump war inzwischen verfügbar bzw. reproduzierbar.
2. Der dokumentierte Chunk-Index-Dateiname war veraltet/falsch.
3. Die dokumentierte Erwartung `585` ist durch den real gemessenen Wert `594` ersetzt.

Es gibt aus diesem Proof **keinen** belegten Anlass für einen Code-Patch am Validator.

---

## Invarianten des Validators

- Validator liest; erzeugt nichts.
- Kein `citation_map_jsonl`-Artefakt.
- Kein Manifest-Wiring für `citation_map_jsonl`.
- `canonical_range` ist autoritativ; `source_range` und `content_range_ref` werden nur berichtet.
- Pfad-Traversal, absolute Pfade, Windows-Drive-Prefixe und UNC-Pfade werden abgelehnt.
- SHA256 von `canonical_md` und `chunk_index_jsonl` wird gegen Manifest-Hashes geprüft.
- `make_citation_id(canonical_md_sha256, start_byte, end_byte, content_sha256)` wird pro Chunk aufgerufen.
- Duplikate werden als Fehler berichtet.
- Exit-Code 0 = ok, 1 = Validierungsfehler, 2 = Pfad-/Lesefehler.
