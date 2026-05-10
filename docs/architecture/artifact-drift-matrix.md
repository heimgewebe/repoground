# Artifact Drift Matrix

Diese Matrix dokumentiert paarweise Drift-Risiken zwischen Lenskit-Artefakten
und ordnet jeder Paarung Autorität, Guard-/Coverage-Status und
Regenerationspfad zu. Sie ist
zunächst **diagnostisch**: sie macht bestehende Ankerpunkte sichtbar, ohne
neue Blocking-Guards einzuführen.

Sie ergänzt das
[Two-Layer Artifact Pattern](./two-layer-artifact-pattern.md) und das
[Artefakt-Inventar](./artifact-inventory.md): das Pattern legt Schichten fest,
das Inventar listet Artefakte, diese Matrix beschreibt die Übergänge.

## Matrix

| Quelle A | Quelle B | Konfliktfall | Autorität | Guard / Test / Coverage-Status | Regeneration |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `canonical_md` | `index_sidecar_json` | Sidecar verweist auf fehlende oder verschobene Section | `canonical_md` für Inhalt, Sidecar nur Navigation | `test_sidecar_contracts.py`, `test_report_parsing.py` | Sidecar regenerieren |
| `bundle_manifest` | Artefakte | Manifest-SHA passt nicht zum Artefakt | Artefaktinhalt + Manifest müssen konsistent sein | Dedizierter SHA-Recompute-Guard: `test_bundle_manifest_artifact_hashes_match_files`, `test_bundle_manifest_hash_recompute_detects_artifact_drift` in `test_bundle_manifest_integration.py` | Manifest regenerieren |
| `dump_index_json` | `derived_manifest_json` | `canonical_dump_index_sha256` mismatch | `dump_index_json` | `canonical_dump_index_sha256` wird gegen `dump_index_json` rehashed: `test_bundle_manifest_canonical_dump_index_sha_matches_dump_index_artifact` in `test_bundle_manifest_integration.py`; vollständiger derived-manifest staleness Guard bleibt später | derived index regenerieren |
| `chunk_index_jsonl` | `sqlite_index` | SQLite aus altem Chunk-Index | `chunk_index_jsonl` | `test_stale_check.py`, `test_sqlite_capabilities.py` | SQLite regenerieren |
| `query_trace` | `context_bundle` | Trace beschreibt andere Treffer als Context Bundle | gemeinsame Run-ID und Query Trace | `test_artifact_lookup.py`, `test_trace_lookup.py`, `test_context_lookup.py` | Runtime-Artefakte neu erzeugen |
| `context_bundle` | `agent_query_session` | Session verweist auf anderen Kontext | `context_bundle` + `artifact_refs` | `test_agent_session_builder.py` | Session neu erzeugen |
| `architecture_summary` | architecture graph / `graph_index` | Summary behauptet nicht belegte Kante | Graph Contract / Graph Index, Summary nur Diagnose | Graph-Struktur-Anker: `test_graph_eval.py`, `test_graph_index.py`; dedizierter Summary-vs-Graph-Guard fehlt | Summary regenerieren |
| PR-Schau JSON | PR-Schau Markdown | JSON meldet vollständig, Markdown fehlt oder ist unvollständig | Markdown Content + Completeness Block | `pr_schau_verify` als Verifier-Pfad; dedizierter Completeness-Test fehlt. `test_pr_schau_consumer_gate.py` prüft nur Consumer-Zugriff | PR-Schau Bundle neu bauen |

## citation_map_jsonl — geplante Driftkanten (kein Producer vorhanden)

Die folgenden Driftkanten werden erst relevant, sobald ein `citation_map_jsonl`-Producer existiert.
Dieser PR erzeugt noch keine Citation Map und definiert keinen Guard.
Eingetragen als diagnostischer Vorgriff gemäß Rollout-Regel (Diagnose vor Blocking).

| Quelle A | Quelle B | Konfliktfall | Autorität | Guard / Test / Coverage-Status | Regeneration |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `canonical_md` | `citation_map_jsonl` | Citation Map verweist auf fehlende oder verschobene Passage | `canonical_md` für Inhalt, `citation_map_jsonl` nur Navigation | _(kein Guard; Producer fehlt)_ | Citation Map regenerieren |
| `chunk_index_jsonl` | `citation_map_jsonl` | Citation-Adressen basieren auf veraltetem Chunk-Index | `chunk_index_jsonl` | _(kein Guard; Producer fehlt)_ | Citation Map regenerieren |
| Bundle Manifest (Artefakt, nicht Role) | `citation_map_jsonl` | Manifest listet `citation_map_jsonl`, Datei fehlt oder SHA stimmt nicht | Manifest + Artefaktinhalt konsistent | _(kein Guard; Producer fehlt)_ | Manifest regenerieren |

## Rollout-Regel

Diese Matrix ist zunächst diagnostisch. Neue Blocking-Guards dürfen erst
entstehen, wenn:

1. der Producer stabil emittiert,
2. Fixtures aktualisiert sind,
3. mindestens ein diagnostischer Lauf grün war,
4. Consumer zusätzliche Felder tolerieren.

Eine Guard-Promotion (Diagnose → Blocking) erfolgt pro Zeile getrennt, nicht
für die gesamte Matrix auf einmal. Damit bleibt das Drift-Inventar wachsbar,
ohne die CI in einem Schritt zu verschärfen.
