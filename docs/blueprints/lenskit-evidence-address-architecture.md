# Komplettumbaublaupause: Lenskit Evidence Address Architecture

## 0. Belegter Ist-Zustand

Der Dump sagt verbindlich: `merge.md` ist kanonisch und vollständig; JSON ist nur Index, Metadaten und Einstieg, nicht Inhaltswahrheit. Außerdem ist die Abdeckung vollständig: 361/361 Dateien, Contact Ratio 100 %, Risk Level low.

Das Manifest trennt bereits die Rollen: `canonical_md` ist `canonical_content`/`content_source`; `chunk_index_jsonl` ist `retrieval_index`/`derived`; `derived_manifest_json`, `dump_index_json` und `index_sidecar_json` sind Navigation/Index; SQLite ist `runtime_cache`/`cache`.

`derived_manifest_json` ist die ArtifactRole; die zugehörige Datei heißt typischerweise `<base>.derived_index.json`.

Das Two-Layer-Pattern formuliert die passende Architekturregel: Index zeigt, Content beweist, Diagnose warnt, Cache beschleunigt, Runtime beobachtet; kein Artefakt darf still als ein anderes auftreten.

Der aktuelle `range-ref.v1` ist eine deterministische Referenz auf Byte-Ranges in Artefakten und verlangt `artifact_role`, `repo_id`, `file_path`, Byte-Range, Line-Range und `content_sha256`. Tests simulieren bereits `content_range_ref` mit `artifact_role: canonical_md`, Byte-/Line-Feldern und Hash.

Kernbefund: Die Architektur ist vorbereitet, aber semantisch nicht sauber genug für belastbare Citations.

---

## 1. Zielbild nach Umbau

### Neue Zuständigkeitsordnung

| Schicht | Artefakt | Aufgabe | Wahrheit? |
| --- | --- | --- | --- |
| Content | `canonical_md` | vollständiger Inhalt | ja |
| Segmentierung | `chunk_index_jsonl` | Retrieval-Chunks, Suchzugang | nein |
| Belegadresse | `citation_map_jsonl` | stabile Adresse zu Inhalt + Hash | nein, aber beweisnah |
| Registry | `bundle_manifest` | alle Artefakte, Rollen, Hashes | nein, Identität |
| Diagnose | `output_health` | Integritätsstatus | nein, Urteil über Zustand |
| Cache | `sqlite_index` | schneller Zugriff / FTS | nein |
| Legacy/View | `dump_index_json` | kompakter Einstieg | nein |
| Legacy/View | `derived_manifest_json` | abgeleitete Artefakte / Cache-View | nein |
| Semantik später | `evidence_use` | Aussageverwendung | nein, Bewertung |

Kurzform:

`canonical_md` trägt Inhalt.
`chunk_index` findet Stellen.
`citation_map` adressiert Stellen.
`range_ref` beschreibt Ranges.
`resolver` beweist Ranges.
`output_health` bewertet Integrität.
`sqlite` beschleunigt.
`query`/`ui` zeigt nur an.

---

## 2. Grundsatzentscheidungen

### Entscheidung A — `citation_map_jsonl` neu einführen

Nicht ersetzen:

- `chunk_index_jsonl`
- `range_ref`
- `sqlite_index`

Sondern ergänzen als:

```json
{
  "role": "citation_map_jsonl",
  "path": "lenskit-max-260506-1935_merge.citation_map.jsonl",
  "content_type": "application/x-ndjson",
  "bytes": 0,
  "sha256": "...",
  "contract": {
    "id": "citation-map",
    "version": "v1"
  },
  "interpretation": {
    "mode": "contract"
  },
  "authority": "navigation_index",
  "canonicality": "derived",
  "regenerable": true,
  "staleness_sensitive": true
}
```

`bytes` und `sha256` sind im Blueprint Platzhalter und werden vom Producer gesetzt.

### Entscheidung B — `bundle_manifest` wird zentrale Registry

`bundle_manifest` ist künftig die einzige vollständige Artefakt-Registry. `dump_index_json` und `derived_manifest_json` dürfen nur Views sein.

### Entscheidung C — Range-Semantik wird gespalten

Nicht mehr ein Range-Feld für alles.

`canonical_range` = Position im `canonical_md`
`source_range` = Position in Originaldatei
`chunk_range` = Segmentierungsbereich
`semantic_boundary` = Aussagegrenze, später

### Entscheidung D — Citation-ID ist nicht chunkbasiert

Nicht:

```text
citation_id = hash(chunk_id)
```

Sondern:

```text
citation_id = cit_ + sha256(
  "lenskit.citation-map.v1:" +
  canonical_md_sha256 + ":" +
  start_byte + ":" +
  end_byte + ":" +
  content_sha256
)[0:16]
```

Warum: Chunking kann sich ändern; der Beleg hängt am canonical content/range/hash, nicht am Messer und nicht an `chunk_id`. Die Namespace-Version verhindert spätere Mehrdeutigkeit, falls Citation-ID-Regeln in v2 geändert werden.

---

## 3. Was wird ersetzt, genutzt, umgebaut?

### 3.1 `canonical_md`

Status: nutzen, nicht umbauen.

Bleibt einziger Inhaltsträger. Keine Diskussion. Wenn `canonical_md` fällt, fällt das ganze Beweissystem.

Umbau: nur Hilfsfunktion für Byte→Line-Mapping ergänzen.

```python
canonical_line_for_byte(md_bytes: bytes, byte_offset: int) -> int
```

Blueprint-Semantik für Byte-/Line-Mapping, ohne Implementierungspflicht in diesem PR:

- Byte offsets are UTF-8 byte offsets.
- `start_byte` is inclusive.
- `end_byte` is exclusive.
- `start_line` is 1-based and denotes the line containing `start_byte`.
- `end_line` is 1-based and denotes the line containing `end_byte - 1`.
- Empty ranges are invalid for `citation_map.v1`.

### 3.2 `chunk_index_jsonl`

Status: nutzen und später semantisch umbauen.

Der Chunk-Index bleibt Retrieval-Artefakt. Er liefert:

- `chunk_id`
- `path`
- `content_sha256`
- optional/fallback-only `content`
- source-local start/end
- `content_range_ref`
- semantic metadata

`content` darf für Citation-Map-Erzeugung nicht vorausgesetzt werden. Real erzeugte/optimierte Chunk-Indizes können kein Inline-Content-Feld enthalten oder leere Inhalte tragen. Citation-Erzeugung muss sich auf `content_sha256`, `canonical_range`/`content_range_ref` und die Auflösung gegen `canonical_md` stützen.

Aber seine Range-Semantik muss korrigiert werden. Tests zeigen aktuell, dass `content_range_ref` mit `artifact_role: canonical_md`, Byte-/Line-Feldern und Hash modelliert wird. Das ist als Konzept gut, aber als Architektur zu eng, weil Source- und Canonical-Positionen getrennt werden müssen.

Umbauziel v2.1/v3:

```json
{
  "canonical_range": {
    "artifact_role": "canonical_md",
    "start_byte": 123,
    "end_byte": 456,
    "start_line": 10,
    "end_line": 20,
    "content_sha256": "..."
  },
  "source_range": {
    "artifact_role": "source_file",
    "file_path": "merger/lenskit/core/merge.py",
    "start_byte": 0,
    "end_byte": 333,
    "start_line": 1,
    "end_line": 12,
    "status": "declared"
  }
}
```

Wichtig: `chunk_index` bleibt Input, wird aber nicht selbst Citation Map.

`source_range.status` wird für `citation_map.v1` so verstanden:

- `declared` = aus Chunk-/Dump-Metadaten übernommen, aber nicht gegen eine separate Originaldatei validiert.
- `exact` = gegen eine eindeutig rekonstruierbare Quelle validiert.
- `derived` = rechnerisch abgeleitet, aber nicht vollständig source-verifiziert.
- `unavailable` = keine belastbare Source-Range verfügbar.

### 3.3 `content_range_ref`

Status: nicht löschen, aber deprecaten.

Aktuelle Bedeutung ist zu mehrdeutig:

`content_range_ref` = physische Range?
source range?
canonical range?
retrieval range?

Umbau:

Kurzfristig:

`content_range_ref` bleibt backward-compatible.
`citation_map` rechnet daraus `canonical_range` korrekt aus.

Mittelfristig:

`content_range_ref` → `legacy_content_range_ref`
`canonical_range` + `source_range` werden bevorzugt.

Langfristig:

`content_range_ref` nur noch Alias oder entfernt in chunk-index v3.

### 3.4 `range-ref.v1`

Status: nutzen, aber nicht aufblasen.

`range-ref.v1` ist formal sauber für eine Byte-Range in einem Artefakt. Es bleibt für Backcompat.

Umbau: keine sofortige Schema-Migration erzwingen. Stattdessen:

`range-ref.v1` = primitive physische Adresse
`citation-map.v1` = zusammengesetzte Belegadresse
`range-ref.v2` = späterer Boundary-Split

### 3.5 `bundle_manifest`

Status: stärken.

Aktuell schreibt `merge.py` das Bundle-Manifest und sortiert Artefakte deterministisch nach `(role, path)` für stabile machine diffs. Genau diese Eigenschaft muss für Citation Map genutzt werden.

Umbau:

- `role citation_map_jsonl`
- `contract citation-map/v1`
- role constraint tests
- artifact relation links

Neue Links:

```json
{
  "links": {
    "canonical_dump_index_sha256": "...",
    "canonical_md_sha256": "...",
    "chunk_index_sha256": "...",
    "citation_map_sha256": "..."
  }
}
```

### 3.6 `dump_index_json`

Status: herabstufen zu Legacy/View.

Aktuell ist es eine kompakte Artefaktliste mit `canonical_md`, `chunk_index_jsonl`, `index_sidecar_json`, `architecture_summary`.

Umbau:

`dump_index_json` darf bleiben,
aber darf nicht Registry-Wahrheit sein.

Künftig:

`bundle_manifest` = registry
`dump_index_json` = compact entry/view

### 3.7 `derived_manifest_json`

Status: umbauen oder langfristig folden.

Aktuell enthält `derived_manifest_json` im hochgeladenen Dump im Wesentlichen den SQLite-Index und Provenance-Felder.

Kurzfristig ideal:

`derived_manifest_json` wird echte Derived-Artefakt-View:

- `sqlite_index`
- `citation_map_jsonl`
- `output_health`
- `retrieval_eval_json`
- `graph_index_json`

Langfristig prüfen:

`derived_manifest_json` kann entfallen, wenn `bundle_manifest` + `artifact_lookup` alles abdeckt.

Nicht sofort löschen. Erst Konsumentenmatrix erstellen.

### 3.8 `sqlite_index`

Status: nutzen, nicht ersetzen.

SQLite bleibt Cache. Später optional:

```sql
CREATE TABLE citation_lookup (
  citation_id TEXT PRIMARY KEY,
  chunk_id TEXT,
  start_byte INTEGER,
  end_byte INTEGER,
  content_sha256 TEXT
);
```

Aber: SQLite darf nie Quelle der Citation-Wahrheit sein.

### 3.9 `output_health`

Status: zentral erweitern.

`output_health` prüft schon Konsistenzpfade wie FTS-Row-Count, Chunk-Count, Range-Ref-Resolution und Hash-/Resolution-Fälle; Tests erwarten Fail bei kaputtem Range-Ref.

Umbau: Citation Map wird direkt in Health aufgenommen.

```json
{
  "citation_map": {
    "present": true,
    "valid": true,
    "entries": 554,
    "hash_mismatch_count": 0,
    "duplicate_id_count": 0,
    "canonical_line_computed_pct": 100.0,
    "source_range_status": {
      "exact": 0,
      "declared": 554,
      "derived": 0,
      "unavailable": 0
    }
  }
}
```

---

## 4. Neue Zielarchitektur

```text
             ┌─────────────────────┐
             │ canonical_md         │
             │ Content Source       │
             └─────────┬───────────┘
                       │ byte/hash proof
                       ▼
             ┌─────────────────────┐
             │ citation_map_jsonl   │
             │ Evidence Address     │
             └───────┬──────┬──────┘
                     │      │
        chunk link   │      │ manifest role/hash
                     ▼      ▼
          ┌────────────┐   ┌────────────────┐
          │ chunk_index │   │ bundle_manifest│
          │ retrieval   │   │ registry       │
          └─────┬──────┘   └──────┬─────────┘
                │                 │
                ▼                 ▼
          ┌────────────┐   ┌────────────────┐
          │ sqlite     │   │ output_health   │
          │ cache      │   │ diagnosis       │
          └────────────┘   └────────────────┘
```

Alternative Sinnachse: Nicht fragen „welches Artefakt ersetzt welches?“, sondern „welche Wahrheit darf ein Artefakt tragen?“. Diese Achse verhindert, dass ein Cache plötzlich Priester wird. Software liebt solche Beförderungen; man schaut kurz weg, und die SQLite-Datei hält eine Grundsatzrede.

---

## 5. PR-Plan: kompletter Umbau ohne Drift

### Phase 0 — Diagnose-Gate

#### PR 0.1 — Artefakt-Fit-Audit

Neue Datei:

`docs/proofs/citation-map-artifact-fit.md`

Muss belegen:

- `canonical_md` ist Inhaltsträger
- `chunk_index_jsonl` ist Retrieval-Index
- `bundle_manifest` ist beste Registry-Basis
- `dump_index_json` ist View
- `derived_manifest_json` ist dünne Derived-View
- `output_health` kann Citation-Health aufnehmen
- `content_range_ref` braucht Range-Semantik-Split

Stop-Kriterium: Keine Implementierung vor dokumentierter Zuständigkeit.

---

### Phase 1 — Contract- und Rollenumbau

#### PR 1.1 — `citation-map.v1.schema.json`

Neue Dateien:

- `merger/lenskit/contracts/citation-map.v1.schema.json`
- `merger/lenskit/contracts/examples/valid_citation_map_entry.json`
- `merger/lenskit/contracts/examples/invalid_citation_map_missing_hash.json`
- `merger/lenskit/tests/test_citation_map_schema.py`
- `docs/architecture/citation-map.md`

Minimaler Eintrag:

```json
{
  "citation_id": "cit_abcd1234abcd1234",
  "snapshot": {
    "run_id": "lenskit-full-max-260506-1935",
    "canonical_md_path": "lenskit-max-260506-1935_merge.md",
    "canonical_md_sha256": "..."
  },
  "canonical_range": {
    "start_byte": 123,
    "end_byte": 456,
    "start_line": 10,
    "end_line": 20,
    "content_sha256": "..."
  },
  "source_range": {
    "file_path": "merger/lenskit/core/merge.py",
    "start_byte": 0,
    "end_byte": 333,
    "start_line": 1,
    "end_line": 12,
    "status": "declared"
  },
  "chunk_link": {
    "chunk_id": "chunk_...",
    "chunk_index_sha256": "...",
    "status": "linked"
  },
  "verification": {
    "canonical_hash": "verified",
    "canonical_bytes": "verified",
    "canonical_lines": "computed",
    "content_hash": "verified",
    "source_range": "declared",
    "chunk_link": "linked"
  },
  "status": "valid"
}
```

#### PR 1.2 — Manifest Role

Ändern:

- `merger/lenskit/contracts/bundle-manifest.v1.schema.json`
- `merger/lenskit/tests/test_role_completeness.py`
- `merger/lenskit/tests/test_bundle_manifest_schema.py`
- `docs/architecture/artifact-inventory.md`
- `docs/architecture/artifact-drift-matrix.md`
- `docs/contracts/contracts-matrix.md`

Regel:

`citation_map_jsonl` darf nur `navigation_index`/`derived` sein.

#### PR 1.3 — Derived Registry View

Entscheidung:

`derived_manifest_json` bleibt, wird aber als generated derived-view dokumentiert.

Erweitern um:

```json
{
  "artifacts": {
    "sqlite_index": {},
    "citation_map_jsonl": {},
    "output_health": {}
  }
}
```

---

### Phase 2 — Range-Semantik-Umbau

#### PR 2.1 — Range Taxonomy Doc

Neue Datei:

`docs/architecture/range-semantics.md`

Begriffe:

`canonical_range` = Position im `canonical_md`
`source_range` = Position in Originaldatei
`chunk_range` = Segmentierungsbereich
`semantic_boundary` = Aussage-/Evidence-Grenze, später

#### PR 2.2 — Chunk-Index Backcompat Layer

In `core/chunker.py` / `core/merge.py`:

`content_range_ref` bleibt.
`canonical_range` wird zusätzlich erzeugt.
`source_range` wird zusätzlich erzeugt.

Wichtig: Noch kein Breaking Change.

#### PR 2.3 — Tests für Line-Semantik

Neue Tests:

- `test_chunk_index_canonical_lines_are_global`
- `test_chunk_index_source_lines_are_source_local`
- `test_content_range_ref_legacy_still_present`
- `test_canonical_range_hash_roundtrip`

---

### Phase 3 — Citation Producer

#### PR 3.1 — `core/citation_map.py`

Neue Datei:

`merger/lenskit/core/citation_map.py`

Funktionen:

```python
compute_line_offsets(md_bytes: bytes) -> list[int]
line_for_byte(offsets: list[int], byte: int) -> int
make_citation_id(canonical_md_sha, start_byte, end_byte, content_sha256) -> str
build_citation_map(manifest, canonical_md, chunk_index) -> Iterator[dict]
validate_citation_entry(entry, canonical_md) -> ValidationResult
```

#### PR 3.2 — Producer in Merge-Pipeline

In `merge.py`:

`canonical_md` erzeugen
`chunk_index` erzeugen
`citation_map` aus `canonical_md` + `chunk_index` erzeugen
Manifest mit `citation_map` ergänzen
`output_health` mit `citation_map` ergänzen

Wichtig: Citation Map kommt nach `canonical_md` und `chunk_index`, aber vor finalem Manifest-Write oder mit Manifest-Rewrite. Da das Manifest deterministisch sortiert wird, bleibt Diff-Stabilität erhalten.

#### PR 3.3 — Determinismus

Test:

same input → same `citation_map` sha256
same canonical bytes → same `citation_id`
changed `chunk_id` → same `citation_id`
changed canonical byte range → changed `citation_id`

---

### Phase 4 — Validator und Health

#### PR 4.1 — Citation Validator

CLI:

```text
lenskit citation validate <bundle_manifest>
lenskit citation resolve <citation_id>
lenskit citation inspect <path-or-byte-range>
```

Neue Dateien:

- `merger/lenskit/cli/cmd_citation.py`
- `merger/lenskit/tests/test_citation_cli.py`

#### PR 4.2 — Output Health Erweiterung

Erweitern:

- `merger/lenskit/core/output_health.py`
- `merger/lenskit/contracts/output-health.v1.schema.json`
- `merger/lenskit/tests/test_output_health_citation_map.py`

Health-Gates:

- `hash_mismatch_count == 0`
- `duplicate_id_count == 0`
- `canonical_line_computed_pct == 100`
- `citation_entries == chunk_entries_with_content_range`

Fehlerpolitik:

hash mismatch → hard fail
duplicate `citation_id` → hard fail
missing `citation_map` when expected → hard fail only if:

- `bundle_manifest` declares a `citation_map_jsonl` artifact, or
- the run/profile explicitly enables evidence-address generation, or
- `output_health` declares `citation_map.required = true`.

Alte Bundles ohne Citation Map dürfen dadurch nicht rückwirkend fehlschlagen.
`source_range` unavailable → warning
`semantic_boundary` missing → not applicable in v1

---

### Phase 5 — Registry-Konsolidierung

#### PR 5.1 — Manifest-first

Doku:

`docs/architecture/artifact-registry.md`

Regel:

`bundle_manifest` = vollständige Registry
`dump_index_json` = compact view
`derived_manifest_json` = derived/cache view

#### PR 5.2 — Artifact Lookup Umbau

`artifact_lookup` soll aus `bundle_manifest` lesen, nicht aus mehreren konkurrierenden Indexen.

#### PR 5.3 — Drift Matrix

Neue Driftkanten:

- `canonical_md` ↔ `citation_map_jsonl`
- `chunk_index_jsonl` ↔ `citation_map_jsonl`
- `citation_map_jsonl` ↔ `output_health`
- `citation_map_jsonl` ↔ `sqlite_index`
- `bundle_manifest` ↔ `citation_map_jsonl`

---

### Phase 6 — Chunk-Index v3

Erst nach stabiler Citation Map.

Breaking Change vorbereiten:

`chunk-index v2` = legacy `content_range_ref`
`chunk-index v2.1` = adds `canonical_range`/`source_range`
`chunk-index v3` = removes ambiguous `content_range_ref` or makes it alias

Tests:

- `test_legacy_chunk_index_v2_still_loads`
- `test_chunk_index_v3_requires_canonical_range`
- `test_chunk_index_v3_requires_source_range_status`

---

### Phase 7 — SQLite Cache optional

Nicht vorher.

`retrieval/index_db.py` kann Citation-Felder indexieren:

```sql
CREATE TABLE citations (
  citation_id TEXT PRIMARY KEY,
  chunk_id TEXT,
  start_byte INTEGER,
  end_byte INTEGER,
  content_sha256 TEXT,
  source_file_path TEXT
);
```

Regel:

SQLite darf Citation Map spiegeln, aber nicht erzeugen.

---

### Phase 8 — Query / Context / Agent Pack

Erst nach Real-Dump-Proof.

Query-Hit:

```json
{
  "chunk_id": "...",
  "citation_id": "cit_...",
  "canonical_ref": "lenskit-max-..._merge.md:1200-1210",
  "source_ref": "merger/lenskit/core/merge.py:1-12",
  "citation_status": "valid"
}
```

Context Bundle:

context kann Citations referenzieren,
aber nicht selbst neue Citations erfinden.

Agent Evidence Pack:

`query_result.json`
`context_bundle.json`
`citation_map.slice.jsonl`
`evidence.md`
`hashes.txt`

---

### Phase 9 — Evidence Use als separater Track

Nicht in Citation Map.

Neuer Contract später:

`evidence-use.v1.schema.json`

Zweck:

Welche Aussage wird durch welche Citation wie stark gestützt?

Das verhindert die Fußnotenwaschanlage: eine richtige Fundstelle macht noch keine richtige Schlussfolgerung.

---

## 6. Migration ohne Drift

### Migrationszustände

| Zustand | Bedeutung |
| --- | --- |
| `legacy_only` | nur `content_range_ref` |
| `dual_range` | `content_range_ref` + `canonical_range` + `source_range` |
| `citation_ready` | Citation Map erzeugbar |
| `citation_validated` | Citation Map + Health grün |
| `registry_consolidated` | Manifest-first umgesetzt |
| `chunk_v3_ready` | Legacy-Alias optional |

### Reihenfolge

`legacy_only`
→ `dual_range`
→ `citation_ready`
→ `citation_validated`
→ `registry_consolidated`
→ `chunk_v3_ready`

Nicht überspringen. Architektur ist kein Hürdenlauf mit verbundenen Augen, auch wenn manche Buildsysteme das anders sehen.

---

## 7. Konkreter Idealplan in PRs

### Minimal zwingend

PR 0 `citation-map-artifact-fit.md`
PR 1 `citation-map.v1.schema.json`
PR 2 bundle-manifest role + docs
PR 3 `range-semantics.md` + dual canonical/source range
PR 4 `citation_map.py` producer
PR 5 validator + `output_health` citation section
PR 6 real dump proof

### Danach sinnvoll

PR 7 manifest-first registry docs + `artifact_lookup`
PR 8 `derived_manifest_json` as derived-view
PR 9 chunk-index v2.1/v3 migration
PR 10 sqlite citation cache
PR 11 query/context citation refs
PR 12 agent evidence pack
PR 13 evidence-use separate track
PR 14 webui review surface

---

## 8. Harte Stop-Kriterien

### Globale Stop-Kriterien

Diese gelten immer:

- `citation_map_jsonl` darf nie `canonical_content` oder `content_source` behaupten.
- SQLite darf nie Citation-Wahrheit tragen.
- `canonical_md` bleibt einziger Content Source.
- keine Implementierungsphase ohne dokumentierte Range-Zuständigkeit.

### Ab `dual_range`

Gilt erst, sobald `canonical_range`/`source_range` eingeführt werden:

- `chunk_index has no clear canonical/source split`
- `canonical_range` darf keine source-local lines als canonical lines ausgeben.
- `source_range.status` muss gesetzt sein.

### Ab `citation_ready`

Gilt erst, sobald Citation Map erzeugt werden soll:

- `citation_map not in manifest`
- `citation_duplicate_id_count > 0`
- `canonical_range hash mismatch > 0`

missing `citation_map` when expected → hard fail only if:

- `bundle_manifest` declares a `citation_map_jsonl` artifact, or
- the run/profile explicitly enables evidence-address generation, or
- `output_health` declares `citation_map.required = true`.

Alte Bundles ohne Citation Map dürfen nicht rückwirkend fehlschlagen.

### Ab `citation_validated`

Gilt erst, sobald Output Health Citation Map prüft:

- `output_health lacks citation section`
- `hash_mismatch_count > 0`
- `duplicate_id_count > 0`
- `citation_entries != chunk_entries_with_content_range`, sofern evidence-address generation für diesen Lauf erwartet wird.

Soft warnings:

- `source_range exact unavailable`
- `source_range only declared`
- `semantic_boundary missing`
- `citation not yet in query output`
- `sqlite citation cache missing`

---

## 9. Typische Fehlannahmen

### Fehler 1: „Citation Map ersetzt Chunk Index“

Nein. `chunk_index` findet; `citation_map` belegt.

### Fehler 2: „Line Numbers reichen“

Nein. Zeilen ohne Hash sind höfliche Gerüchte mit Monospace-Schrift.

### Fehler 3: „SQLite kann die Citation-Wahrheit tragen“

Nein. SQLite darf beschleunigen, nicht kanonisieren.

### Fehler 4: „content_range_ref ist schon genug“

Fast. Es ist ein guter Rohstoff, aber die Range-Semantik muss gespalten werden.

---

## 10. Belegt / plausibel / spekulativ

Belegt:
`merge.md` ist kanonisch und vollständig; JSON ist Navigation/Metadaten. Das Manifest trennt `canonical_md`, `chunk_index_jsonl`, Navigation/Index und SQLite-Cache klar. Das Two-Layer-Pattern trennt Index, Content, Diagnose, Cache und Runtime als Rollenmodell. `range-ref.v1` ist eine deterministische Byte-Range-Referenz mit Hash. Output-Health testet bereits Range-Ref-Resolution als Fail-Kriterium.

Plausibel:
`citation_map_jsonl` als abgeleitete Belegadresse reduziert lokale Ableitungsdrift zwischen Query, UI, Agent Pack und Review.

Spekulativ:
Ob `derived_manifest_json` langfristig entfallen sollte. Dafür fehlt eine Konsumentenmatrix.

---

## 11. Risiko- und Nutzenabschätzung

Nutzen:
Stabile Citations, weniger Line-Verwirrung, bessere LLM-Belege, robustere PR-Reviews, klare Artefaktrollen, weniger Drift zwischen Index und Inhalt.

Risiko:
Zu großer Umbau kann Backcompat brechen. Falsch migrierte Range-Semantik kann kaputte Citations konservieren. Manifest-first kann Konsumenten stören, wenn sie bisher direkt `dump_index_json` oder `derived_manifest_json` lesen.

Gegenmittel:
Dual-Range-Phase, Legacy-Aliase, Real-Dump-Proof, Health-Gates, Konsumentenmatrix vor Entfernung alter Views.

---

## 12. Für Dummies

Stell dir Lenskit wie ein Buchsystem vor:

`merge.md` ist das Buch.
`chunk_index` ist das Suchregister.
`citation_map` ist die Belegnummernliste: „Beleg cit_123 zeigt auf genau diese Stelle im Buch, mit diesem Hash.“
`bundle_manifest` ist die Bibliothekskarte: „Welche Dateien gehören zum Buchpaket?“
`output_health` ist der Prüfer: „Sind die Belegnummern kaputt oder sauber?“
SQLite ist der schnelle Suchautomat am Eingang. Praktisch, aber nicht die Wahrheit.

---

## 13. Optimierungsgrad

Was: Belegbarkeit, Drift-Resistenz, Artefaktordnung, Agentenlesbarkeit.
Wie: Citation Map einführen, Range-Semantik trennen, Manifest-first, Health-Gates, Chunk-Index-Migration.
Wodurch: klare Zuständigkeit pro Artefakt und hashbasierte Belegprüfung.
Wirkung: sehr hoch für Evidenzqualität; mittel für Retrieval; hoch für spätere Query-/Agentenqualität.

Optimierungsgrad: 0.93
Nebenwirkungen: mehr Contracts, mehr Tests, Übergangsphase mit Dual-Feldern.

---

## Unsicherheit / Interpolation

Unsicherheitsgrad: 0.13
Ursachen: Die zentralen Artefaktrollen, Reading Policy, Range-Ref-Contract und Health-Pfade sind belegt. Offen bleibt nur, welche externen oder internen Konsumenten direkt `dump_index_json` und `derived_manifest_json` lesen.

Interpolationsgrad: 0.17
Hauptannahmen: Die genaue PR-Reihenfolge und langfristige Herabstufung von `derived_manifest_json` sind Architekturvorschläge, nicht bereits im Repo beschlossen.

Epistemische Leere:
Eine Konsumentenmatrix fehlt: Wer liest aktuell `dump_index_json`, `derived_manifest_json`, `index_sidecar_json`, `bundle_manifest`, `sqlite_index` direkt? Nötig für die endgültige Entscheidung „View behalten“ vs. „View später entfernen“.

---

## Essenz

Hebel: Zuständigkeiten entflechten, nicht Artefakte blind ersetzen.
Entscheidung: `citation_map_jsonl` neu; `chunk_index_jsonl` nutzen und semantisch spalten; `bundle_manifest` zur Registry stärken; `dump_index_json`/`derived_manifest_json` zu Views herabstufen; `output_health` sofort integrieren.
Nächste Aktion: PR 0 erstellen: `docs/proofs/citation-map-artifact-fit.md` plus `docs/architecture/range-semantics.md` als Diagnose- und Entscheidungsbasis. Erst dann Contracts.
