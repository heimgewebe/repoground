# Citation Readiness Validator — Proof / STOP-Bericht

**Datum:** 2026-05-13
**Branch:** `claude/build-validator-consumer-1Q7p0`
**Validator-Rolle:** Konsument / Readiness-Gate. Kein Producer.

---

## Status: STOP — Real-Dump lokal nicht verfügbar

### Fehlende Dateien

Der Real-Dump `lenskit-max-260513-0642` ist auf dem aktuellen System **nicht** vorhanden.

Erwartet (alle relativ zum Dump-Verzeichnis):

| Datei | Wofür benötigt |
|-------|----------------|
| `lenskit-max-260513-0642_merge.bundle.manifest.json` | Einstiegspunkt für Validator; enthält Artifact-Rollen und SHA256-Hashes |
| `lenskit-max-260513-0642_merge.md` | Canonical-MD-Quelle; Byte-Ranges werden daraus gelesen und SHA256-geprüft |
| `lenskit-max-260513-0642_chunk_index.jsonl` | 585 erwartete Chunk-Zeilen mit `canonical_range`, `source_range`, `content_range_ref` |

Ohne diese drei Dateien kann der Validator nicht ausgeführt werden.
Die Implementierung ist vollständig; der Proof-Run steht aus.

---

## Implementierungsstand (zum Zeitpunkt dieses Berichts)

### Neue Dateien

| Datei | Rolle |
|-------|-------|
| `merger/lenskit/core/citation_validate.py` | Core-Validator-Logik |
| `merger/lenskit/cli/cmd_citation.py` | CLI-Befehl `lenskit citation validate` |
| `merger/lenskit/tests/test_citation_validate.py` | Unit-Tests mit synthetischen Fixtures |
| `merger/lenskit/tests/test_cli_citation.py` | CLI-Tests mit synthetischen Fixtures |

### Geänderte Dateien

| Datei | Änderung |
|-------|----------|
| `merger/lenskit/cli/main.py` | `citation`-Subcommand registriert |
| `docs/roadmap/lenskit-master-roadmap.md` | Validator-Status ergänzt |

---

## Voraussetzungen für den Real-Dump-Proof

Sobald der Dump lokal verfügbar ist:

```
lenskit citation validate \
  /path/to/lenskit-max-260513-0642_merge.bundle.manifest.json
```

oder mit JSON-Report:

```
lenskit citation validate --json \
  /path/to/lenskit-max-260513-0642_merge.bundle.manifest.json
```

Der Report muss enthalten:

- `bundle_manifest_path`: verwendeter Pfad
- `error_kind`: `ok` | `validation_error` | `path_read_error`
- `bundle_run_id`: `run_id` aus dem Manifest
- `validation_run_id`: eindeutige UUID des Validator-Laufs
- `canonical_md_sha256`: aus Manifest
- `chunk_index_sha256`: aus Manifest
- `chunk_count`: erwartet 585
- `canonical_range_count`: erwartet 585
- `citation_id_count`: erwartet 585 (bei duplikatefreien validen Ranges)
- Falls `citation_id_count` kleiner als `chunk_count`/`canonical_range_count` ist, signalisiert das Fehler oder übersprungene Zeilen (kein valider Duplikatfall).
- `citation_id_duplicate_count`: erwartet 0
- `status`: `ok` oder `fail` mit Fehlerliste
- Zusätzlich für Hash-Diagnosen: `canonical_md_actual_sha256` und `chunk_index_actual_sha256` (berechnet aus Dateien).

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
