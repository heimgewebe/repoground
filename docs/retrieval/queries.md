# Retrieval Gold Queries

Die folgenden 15 "Gold Queries" definieren die Zielwerte (Benchmarks) für das RepoGround Retrieval-System.

## Benchmark-Zielwerte
- **TTR (Time-to-Relevant):** < 2 Sekunden für CLI-Output.
- **Recall@10:** Anteil der Queries mit mindestens einem relevanten Treffer in den Top-10 (0–100%).
- **Explainability:** Mindestens Engine + Filter + Query-Mode (Token-Matches optional).

> Zielwert wird separat festgelegt; diese Datei definiert Metrik + Queryset.
> Hinweis: `accept_criteria` in `queries.v1.json` sind Ratios (0.0–1.0). `recall@k` im Eval-Output ist in Prozent (0.0–100.0).
> Ein Beispiel-Report liegt unter `docs/retrieval/retrieval_eval.example.json` (nicht kanonisch).
> Hinweis: `Expected` Patterns werden strikt als Substring-Match ausgewertet (keine regulären Ausdrücke).

## Query Liste

### Generic / Self-Hosting (Priority)

1.  **"index"**
    *   *Intent:* (Self-Reflexive) Suche nach dem Code, der den Index baut.
    *   *Expected:* `index_db.py`, `build_index`

2.  **"merge"**
    *   *Intent:* Suche nach der Hauptlogik für das Mergen von Reports.
    *   *Expected:* `merge.py`, `iter_report_blocks`

3.  **"chunk"**
    *   *Intent:* Suche nach dem Chunker-Algorithmus.
    *   *Expected:* `chunker.py`, `Chunker`

4.  **"cli"**
    *   *Intent:* Suche nach CLI-Commands.
    *   *Expected:* `argparse`, `main.py`, `cli/`
    *   *Filter:* `layer=cli` (optional)

5.  **"test"**
    *   *Intent:* Suche nach Test-Daten oder Setup-Code.
    *   *Expected:* `conftest.py`, `fixtures/`
    *   *Filter:* `layer=test` (optional)

### Web-App / Standard (Future Targets)

6.  **"find auth logic"**
    *   *Intent:* Suche nach Authentifizierungs-Code.
    *   *Expected:* `auth.py`, `login`

7.  **"find database schema"**
    *   *Intent:* Suche nach Tabellendefinitionen.
    *   *Expected:* `models.py`, `schema.sql`

8.  **"find api routes"**
    *   *Intent:* Suche nach REST-Endpunkten.
    *   *Expected:* `routes.py`, `urls.py`, `@app.get`

9.  **"find error handling"**
    *   *Intent:* Suche nach Exception-Klassen.
    *   *Expected:* `exceptions.py`, `error_handler`

10. **"find logging setup"**
    *   *Intent:* Suche nach Logger-Initialisierung.
    *   *Expected:* `logging.config`, `structlog`

11. **"find user model"**
    *   *Intent:* Suche nach der Definition des Users.
    *   *Expected:* `class User`

12. **"find config parsing"**
    *   *Intent:* Suche nach Logik, die Konfigurationen liest.
    *   *Expected:* `config.py`, `settings.py`

13. **"find rate limiting"**
    *   *Intent:* Suche nach Drosselungs-Logik.
    *   *Expected:* `ratelimit`

14. **"find dependency definition"**
    *   *Intent:* Suche nach externen Abhängigkeiten.
    *   *Expected:* `requirements.txt`, `pyproject.toml`

15. **"find docker configuration"**
    *   *Intent:* Suche nach Container-Setup.
    *   *Expected:* `Dockerfile`
