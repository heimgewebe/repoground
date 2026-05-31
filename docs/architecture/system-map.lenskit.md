# Lenskit Systemkarte

## 1. Systemachsen

Diese Karte ordnet die Kernmodule von Lenskit den architektonischen Systemachsen zu, basierend auf dem aktuellen Implementierungsstand im Repository (`merger/lenskit/`).

### Achse 1: Build & Ingestion (Scan → Extract → Chunk → Bundle)
- **`merger.lenskit.core.merge`**
  - **Zweck:** Orchestriert den gesamten Build-Prozess. Traversiert das Repository, filtert nach Pattern/Größe/Modus, stößt Extraktion und Chunking an und erzeugt die finalen Artefakte.
  - **Inputs:** Verzeichnisbaum (Dateien), Konfigurationsprofile, Regex-Muster, Output-Pfad.
  - **Outputs:** `canonical_md` (Markdown-Dump), `index_sidecar.json`, `.index.sqlite`.
  - **Abhängige Schemas:** `bundle-manifest.v1.schema.json`
  - **Runtime-Nutzer:** Indizierungs- und Agent-Systeme, Entwickler.

- **`merger.lenskit.core.chunker`**
  - **Zweck:** Bricht Code in LLM-kompatible Segmente herunter.
  - **Inputs:** Quelldateien, Block-Metadaten.
  - **Outputs:** Chunk-Artefakte (`chunk_index.jsonl`).
  - **Runtime-Nutzer:** Retrieval-Indizes (FTS5).

- **`merger.lenskit.core.extractor`**
  - **Zweck:** Analysiert Quelldateien und extrahiert strukturierte Daten (Klassen, Funktionen, Dokumentation).
  - **Inputs:** Quelldateien.
  - **Outputs:** Extrahierte Baumstrukturen, Token- und Zeilen-Offsets.
  - **Runtime-Nutzer:** Chunker, Range-Resolver.

- **`merger.lenskit.core.pr_schau_bundle`**
  - **Zweck:** Analysiert Git-Deltas und verknüpft sie mit Code-Chunks für Review-Ansichten.
  - **Inputs:** `git diff`, Quellcode.
  - **Outputs:** PR-Schau Delta Bundles (`pr-schau-delta.json`).
  - **Abhängige Schemas:** `pr-schau-delta.v1.schema.json`, `pr-schau.v1.schema.json`.

### Achse 2: Runtime & Retrieval (Query, Eval, Explain)
- **`merger.lenskit.retrieval.query_core`**
  - **Zweck:** Stellt die primäre Retrieval-Engine und Agent-Schnittstelle bereit. Führt die eigentliche Suche über Indizes aus, verarbeitet Graph-Signale, erzeugt Diagnostik-Spuren und wendet Output-Profile an.
  - **Inputs:** Query-String, `index.sqlite`, `graph_index.json`, Output-Profile, Filter.
  - **Outputs:** `query-result.v1.schema.json` compliant Dict, Context Bundles (inkl. `query_trace`).
  - **Abhängige Schemas:** `query-result.v1.schema.json`, `query-context-bundle.v1.schema.json`.
  - **Runtime-Nutzer:** API-Service (`merger.lenskit.service.app`), CLI (`cmd_query.py`), Evaluierung.

- **`merger.lenskit.retrieval.eval_core`**
  - **Zweck:** Orchestriert Retrieval-Evaluierungen über strukturierte Testsets. Erzeugt Deltas zwischen Baseline und erweiterten Pipelines (z.B. Graph).
  - **Inputs:** `eval_queries.md`, `index.sqlite`, `graph_index.json`.
  - **Outputs:** Metrik-Report (`retrieval-eval.v1.schema.json`).
  - **Abhängige Schemas:** `retrieval-eval.v1.schema.json`.
  - **Runtime-Nutzer:** CLI (`cmd_eval.py`), CI-Pipelines.

- **`merger.lenskit.retrieval.index_db`**
  - **Zweck:** Baut und verwaltet die SQLite FTS5 Datenbank aus den rohen Dump- oder Chunk-Indizes.
  - **Inputs:** `dump_index.json`, `chunk_index.jsonl`.
  - **Outputs:** `index.sqlite` (mit FTS5 Tabellen).
  - **Runtime-Nutzer:** `query_core`, `eval_core`.

- **`merger.lenskit.core.range_resolver`**
  - **Zweck:** Löst Quellcode-Ausschnitte über Dateigrenzen oder strukturelle Verweise (`range_ref`) präzise auf.
  - **Inputs:** Range References, File System (Source-backed) oder Bundle (Bundle-backed).
  - **Outputs:** Aufgelöste Code-Ausschnitte (Snippets), Provenienz-Typisierung (`explicit` vs `derived`).
  - **Abhängige Schemas:** `range-ref.v1.schema.json`.
  - **Runtime-Nutzer:** `query_core` (beim Bau des `context_bundle`), `merge.py`.

### Achse 3: Struktur & Graph
- **`merger.lenskit.architecture.graph_index`**
  - **Zweck:** Baut, persistiert und lädt den systemweiten Architektur-Graphen. Normalisiert Status und Schema.
  - **Inputs:** `architecture_graph.json` (bzw. Quellcode), Entrypoints.
  - **Outputs:** Normalisiertes Graph-Index Objekt (für Memory) bzw. `architecture.graph_index.v1.schema.json` Artefakt.
  - **Abhängige Schemas:** `architecture.graph_index.v1.schema.json`.
  - **Runtime-Nutzer:** `query_core`, `eval_core`.

### Achse 4: API, UI & Service
- **`merger.lenskit.service.app`**
  - **Zweck:** FastAPI Backend für die Lenskit-Dienste, Agenten-Integration und UI-Bereitstellung.
  - **Inputs:** HTTP Requests, persistierte Lenskit Bundles / Atlas Metarepos.
  - **Outputs:** HTTP Responses (JSON), statische UI Files.
  - **Runtime-Nutzer:** Agenten, WebUI, Pythonista RepoLens Frontend.

## 2. Abgedeckte Kernverträge (Contracts)
Die Systemkommunikation läuft über JSON Schemas in `merger/lenskit/contracts/`.
- `query-result.v1.schema.json` (Runtime → Consumer)
- `query-context-bundle.v1.schema.json` (Agent Context, oft eingebettet im Query Result)
- `bundle-manifest.v1.schema.json` (Build → Runtime)
- `architecture.graph_index.v1.schema.json` (Struktur → Retrieval)
- `range-ref.v1.schema.json` (Build/Resolver → Provenienz-Sicherheit)

## 3. Bekannte Lücken (Systemkarte)
- **Cross-Repo / Federation (Roadmap Phase 4):** Föderations-Module sind
  inzwischen vorhanden — `merger/lenskit/core/federation.py`,
  `merger/lenskit/retrieval/federation_query.py`,
  `merger/lenskit/cli/cmd_federation.py` sowie die Contracts
  `federation-index/cross-repo-links/federation-conflicts/federation-trace.v1`.
  Die *lokale* Query-Runtime (`query_core`) bleibt bewusst auf ein Index-Artefakt
  beschränkt; föderierte Abfragen laufen über `federation_query`. Offen bleibt
  das **Hardening** (Identity-Engine, Conflict-Behandlung) — siehe
  `docs/roadmap/lenskit-master-roadmap.md` (Phase 4).
  *(Korrigiert 2026-05-31: frühere Aussage „existieren derzeit nicht im
  Quellbaum" war veraltet; belegt in
  `docs/proofs/weiterentwicklungsplan-2026-05-reconciliation-proof.md`.)*
