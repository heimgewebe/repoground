# Range Semantics

## Zweck

Definiere die Range-Begriffe für RepoGround, damit Chunking, Range-Resolver, Citation Map,
Query Runtime und spätere Evidence-Auswertung nicht dieselben Felder unterschiedlich
interpretieren.

## Begriffe

### canonical_range

- Position im `canonical_md`.
- Belegbasis für spätere `citation_map_jsonl`.
- Hash-Prüfung bezieht sich auf den canonical byte slice.
- Darf nicht mit source-local ranges verwechselt werden.

### source_range

- Position in der ursprünglichen Quelldatei.
- Status muss sichtbar sein:
  - `declared`: aus vorhandenen Metadaten übernommen, nicht separat validiert.
  - `exact`: gegen eindeutig rekonstruierbare Quelle validiert.
  - `derived`: rechnerisch abgeleitet, nicht vollständig source-verifiziert.
  - `unavailable`: keine belastbare Source-Range verfügbar.

### chunk_range

- Segmentierungsbereich eines Retrieval-Chunks.
- Hilft beim Finden.
- Ist nicht automatisch Belegwahrheit.

### content_range_ref

- Bestehender legacy-kompatibler Range-Verweis.
- Bleibt gültig.
- Wird nicht gelöscht.
- Reicht allein nicht als Zukunftsmodell, weil canonical/source/chunk/semantic Bedeutungen
  getrennt werden müssen.
- Darf später nicht blind als vollständige `canonical_range` oder `source_range` übernommen
  werden; Producer müssen canonical/source/chunk-Bedeutungen explizit trennen und validieren.

### semantic_boundary

- Spätere Aussage-/Evidence-Grenze.
- Nicht Teil von Citation Map v1.
- Nicht in diesem PR implementieren.

## Feldnamen

Verwende für Range-Objekte und Range-Refs die im Repo etablierte Terminologie:

- `start_byte`
- `end_byte`
- `start_line`
- `end_line`
- `file_path`

Bestehende Chunk-Records in `chunk_index_jsonl` können weiterhin `path` als Chunk-/Source-Pfadfeld
verwenden. Diese Benennung bleibt für Chunk-Records unverändert; `file_path` meint hier
Range-Objekte und Range-Refs wie `range-ref.v1` / `content_range_ref`.

## Invarianten

- `start_byte` ist inklusiv.
- `end_byte` ist exklusiv.
- `start_line` und `end_line` sind 1-basiert.
- `end_line` bezeichnet die Zeile, die `end_byte - 1` enthält.
- Empty ranges sind für spätere Citation Map v1 ungültig.
- `canonical_range.content_sha256` bezieht sich auf den canonical byte slice.
- `source_range.status` ist Pflicht, sobald `source_range` vorhanden ist.

## Migration

- `range-ref.v1` bleibt kompatibel.
- `content_range_ref` bleibt erhalten.
- `canonical_range` und `source_range` werden später zusätzlich erzeugt.
- Dieser PR erzeugt keine Breaking Changes.

## Nicht-Ziele

- Kein `range-ref.v2`-Schema.
- Keine Citation Map.
- Keine Manifest-Role.
- Kein Producer.
- Kein Query-/UI-/Agent-Anschluss.
