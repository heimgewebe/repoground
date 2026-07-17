# Retrieval Recipes

> FTS5 + bm25 sind Voraussetzung für den FTS-Modus. Meta-only Queries (ohne Suchtext `--q`) funktionieren weiterhin ohne FTS.

## Manifest Policy
Um zirkuläre Hashes zu vermeiden, teilt RepoGround die Artefakte strikt in zwei Manifest-Schichten auf (basierend auf Suffix-Konventionen):
- `<base>.dump_index.json`: Kanonische Wahrheit (Markdown, JSON Sidecar, Chunk Index). Stabil und forensisch prüfbar.
- `<base>.derived_index.json`: Beschleunigungsschicht (SQLite Index, Retrieval Eval). Enthält `canonical_dump_sha256` als Rückreferenz auf das Hauptmanifest. `canonical_dump_sha256` dient als Bindeglied, um stale Indizes erkennen zu lassen (durch Vergleich gegen das aktuelle dump manifest).

## 1. Index Erstellen

Indexieren eines "<base>.dump_index.json" und "<base>.chunk_index.jsonl" Paares.

```bash
python -m merger.repoground.cli index \
  --dump output/<base>.dump_index.json \
  --chunk-index output/<base>.chunk_index.jsonl \
  --out output/<base>.chunk_index.index.sqlite
```

## 2. Index Prüfen

Überprüfen, ob ein Index aktuell (fresh) ist.

```bash
python -m merger.repoground.cli index --dump output/my_dump.json --chunk-index output/my_chunks.jsonl --verify
```

## 3. Einfache Suche

Suche nach einem Begriff in allen Dateien.

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "authentication"
```

## 4. Suche mit Repo-Filter

Suche nach "user" nur im Repository "backend".

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "user" --repo backend
```

## 5. Suche nach Dateityp

Suche nach "schema" nur in SQL-Dateien.

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "schema" --ext sql
```

## 6. Suche im Core-Layer

Suche nach "logging" nur im "core" Layer (Architektur).

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "logging" --layer core
```

## 7. Pfad-basierte Suche

Suche nach "config" in Dateien, deren Pfad "settings" enthält.

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "config" --path settings
```

## 8. JSON-Output für Agenten

Strukturierte Ausgabe für maschinelle Verarbeitung.

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "error" --emit json
```

## 9. Limitierte Ergebnisse

Nur die Top-3 Treffer anzeigen.

```bash
python -m merger.repoground.cli query --index output/my_index.sqlite --q "main" --k 3
```

## 10. Rebuild erzwingen

Index neu bauen, auch wenn er aktuell scheint.

```bash
python -m merger.repoground.cli index --dump output/my_dump.json --chunk-index output/my_chunks.jsonl --rebuild
```

## Retrieval Eval Claim Boundaries

Eval-Metriken (`recall@k`, `MRR`, `zero_hit_ratio`) sind maschinenlesbar, aber sie tragen eine implizite Richterrobe. Das `claim_boundaries`-Objekt macht die epistemischen Grenzen des Eval-Outputs explizit.

**Was Eval-Metriken beweisen:**
- Die Metriken wurden für dieses Eval-Set gegen diesen Index und diese Query-Pipeline berechnet.

**Was Eval-Metriken nicht beweisen:**
- Recall auf diesem Eval-Set beweist keine allgemeine Retrieval-Qualität.
- Zero-hit-Ratio beweist keine Abwesenheit relevanter Inhalte im Repository.
- MRR beweist keine semantische Korrektheit.
- Eval-Ergebnisse beweisen keinen aktuellen Live-Repository-Zustand.

`requires_live_check: true` gilt immer, weil Eval-Ergebnisse auf einem Index-Snapshot basieren. Für autoritative Aussagen über den aktuellen Repo-Zustand muss das Repository selbst geprüft werden.

`evidence_basis` listet die tatsächlich verwendeten Evidenzquellen. `graph_index` erscheint nur, wenn Graph-basiertes Scoring tatsächlich im Eval-Pfad verwendet wurde.

```json
{
  "claim_boundaries": {
    "proves": [
      "These metrics were computed for this eval set against this index and query pipeline."
    ],
    "does_not_prove": [
      "Recall on this eval set does not prove general retrieval quality.",
      "Zero-hit ratio does not prove absence of relevant repository content.",
      "MRR does not prove semantic correctness.",
      "Eval results do not prove live repository state."
    ],
    "evidence_basis": [
      "eval_queries",
      "expected_targets",
      "query_results",
      "index",
      "retrieval_metrics"
    ],
    "requires_live_check": true
  }
}
```

## Query Claim Boundaries

Das rohe Query-Ergebnis (`execute_query` / kein Output-Profile) enthält ein maschinenlesbares `claim_boundaries`-Objekt, das die epistemischen Grenzen des Treffers explizit macht.

**Was ein Treffer beweist:**
- Dieser Index lieferte unter dieser Query und diesen Filtern diese Treffer.

**Was ein Treffer nicht beweist:**
- Dass kein nicht gefundener Inhalt im Repository existiert (Abwesenheit eines Treffers ≠ Abwesenheit im Repo).
- Dass Ranking semantische Wichtigkeit beweist.
- Dass der Snapshot dem Live-Repository entspricht.
- Dass Explain-Ausgaben kanonische Wahrheit sind.

Das Feld `evidence_basis` listet die tatsächlich verwendeten Evidenzquellen (z.B. `query`, `fts_query`, `applied_filters`, `index`, `result_ranges`). `graph_index` erscheint in `evidence_basis`, wenn Graph-Scoring tatsächlich verwendet wurde.
`requires_live_check` ist bei Snapshot-basierten Query-Ergebnissen `true`, weil das Ergebnis nur den Indexzustand belegt. Für eine autoritative Aussage über den aktuellen Live-Repository-Zustand muss das Repository selbst geprüft werden.
`result_ranges` erscheint nur, wenn Treffer tatsächlich `range_ref` oder `derived_range_ref` enthalten.

Bei projizierten Output-Profilen kann die Rückgabeform ein Context Bundle oder Wrapper sein. Die Weitergabe von `claim_boundaries` in Projektionen ist ein separater Folge-PR, damit das Context-Bundle-Schema nicht still erweitert wird.

```json
{
  "claim_boundaries": {
    "proves": ["These hits were returned by this index under this query and these filters."],
    "does_not_prove": [
      "Absence of a hit does not prove absence in the repository.",
      "Ranking does not prove semantic importance.",
      "Snapshot query does not prove live repository state.",
      "Best-effort explain output is diagnostic, not canonical truth."
    ],
    "evidence_basis": ["query", "fts_query", "applied_filters", "index"],
    "requires_live_check": true
  }
}
```
