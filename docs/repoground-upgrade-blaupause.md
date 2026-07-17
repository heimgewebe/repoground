# Blaupause: RepoGround-Optimierung zum deterministischen Knowledge-Compiler mit Query-Runtime

**Status:** Blaupause / Zielarchitektur
**Zweck:** Strategische Ausbauplanung für RepoGround
**Geltungsbereich:** Beschreibt Zielbild und empfohlene Evolutionspfade
**Nicht-Zweck:** Ist keine vollständige Beschreibung des aktuellen Implementierungsstands

> **Knowledge-Compiler:** Ein System, das Repositories deterministisch in versionierte, contract-validierte Wissensartefakte überführt, die für Retrieval, Diagnose und Agent-Kontext nutzbar sind.

---

## Statuswahrheit

- Kanonische Taskstatus: `docs/tasks/index.json`.
- Maschinenlesbare Reifeprojektion: `docs/status/repobrief-status-truth.v1.json`.
- Häkchen gelten nur für den jeweiligen Arbeitspunkt; ein Phasen-Gate bleibt davon unabhängig.
- Ein grüner Health- oder CI-Status beweist keine Produkt- oder Release-Reife.
- Diese Datei ist ein Ordnungs- oder Zieldokument und keine zweite Taskstatus-Autorität.

## 1 Zielbild

RepoGround entwickelt sich von

Repository-Analyse-Tool

zu einem

deterministischen Knowledge-Compiler mit Query-Runtime und portablem Knowledge-Bundle-Format.

Systemfunktion:

Repository
    ↓
Scan
    ↓
Extraction
    ↓
Chunking
    ↓
Indexing
    ↓
Knowledge Bundle
    ↓
Query Runtime / Agents

RepoGround bleibt dabei strikt:
* deterministisch
* reproduzierbar
* artefaktzentriert
* contracts-first.

---

## 2 Systemarchitektur

RepoGround besteht künftig aus sechs klar getrennten Schichten.

Schicht | Aufgabe
--- | ---
Repo Ingestion | Repository erfassen
Extraction | Strukturinformationen extrahieren
Segmentation | Kontextfähige Code-Chunks erzeugen
Indexing | Such- und Analyseindizes erzeugen
Compilation | Knowledge Bundle bauen
Runtime | Query / Agent Zugriff

---

## 3 Artefaktarchitektur

Alle Systemzustände werden ausschließlich über Artefakte dargestellt.

### Primäre Artefakte

* canonical_md
* chunk_index_jsonl
* chunk_index_sqlite
* index_sidecar_json
* dump_index_json
* derived_index_json
* bundle_manifest

Referenzstruktur des Bundles ist bereits im Manifest sichtbar.

### Erweiterte Artefakte

Neue Artefakte:

* artifact_graph_json
* graph_index_json
* context_bundle_json
* query_trace_json
* bundle_delta

---

## 3.1 Kanonische Begriffe / Namensdisziplin

Um Begriffsdrift zwischen Konzept und Implementierung zu vermeiden, gilt folgende Namensdisziplin:

| Konzeptioneller Begriff (Rolle) | Kanonischer Dateiname / Artefaktname | Status |
| :--- | :--- | :--- |
| `context_bundle_json` | `query_context_bundle.json` | Verbindlich geplant |
| `artifact_graph_json` | `artifact_graph.json` | Verbindlich geplant |
| `chunk_index_sqlite` | `chunk_index.index.sqlite` | Historisch etabliert, kanonisch |
| `query_trace_json` | `query_trace.json` | CLI-Export des Diagnoseobjekts (`query_trace`) |

*(Abstrakte Unterstrich-Begriffe wie `artifact_graph_json` bezeichnen die Artefaktrolle im Manifest, Punkt-Begriffe wie `artifact_graph.json` den tatsächlichen Dateinamen.)*

*Wichtige Architektur-Anmerkung zu `query_trace`:*
Das `query_trace`-Objekt ist **kein eigenständiges zweites Wahrheitsmodell**, sondern konzeptionell als **optionales Diagnosefeld** (`query_trace`) direkt in den `query-result.v1.schema.json`-Contract eingebettet.
Die Datei `query_trace.json` ist lediglich die Materialisierung (der CLI-Export) dieses Diagnoseobjekts, um bei Debugging-Läufen (z.B. über `--trace`) extern darauf zugreifen zu können.

---

## 4 Artifact-Graph (neue Kernstruktur)

RepoGround erhält eine explizite Build-Abhängigkeitsstruktur.

Artefakt:

`artifact_graph.json`

Schema:

* artifact
* producer
* depends_on
* hash
* created_at
* contract
* version

Beispiel:

```yaml
chunk_index_jsonl
  produced_by: chunker
  depends_on:
    - extraction_output
```

Nutzen:
* deterministische Pipeline
* reproduzierbare Bundles
* Drift-Detection.

---

## 5 Pipeline-Architektur

Die RepoGround-Pipeline wird formalisiert.

### 5.1 Repo-Scanner

Funktion:

Repository traversal.

Features:

* exclude_patterns
* max_depth
* max_entries
* max_file_size
* snapshot_id
* snapshot_compare

Output:

`repo_inventory.json`

### 5.2 Extraction Engine

Extrahiert:

* code blocks
* documentation
* metadata
* structure

Mechanismen:

* zone markers
* offset tracking
* file metadata

Output:

`extraction_index.json`

### 5.3 Range Resolver

Segmentiert Codekontext.

Beispiele:

function → class → module

Output:

`range_index.json`

### 5.4 Chunking Engine

Ziel:

LLM-kompatible Kontextblöcke.

Artefakte:

* `chunk_index.jsonl`
* `chunk_index.index.sqlite`

Chunk-Metadaten:

* chunk_id
* file_path
* offset
* content
* context

### 5.5 Index Layer

RepoGround erzeugt mehrere Indizes.

Text Index:

* SQLite FTS5
* BM25 ranking

Metadata Index:

* sidecar index

Dump Index:

* `dump_index.json`

---

## 6 Knowledge Bundle

Das Bundle ist das zentrale RepoGround-Produkt.

Bundle-Struktur:

```text
bundle/
 ├ canonical_md
 ├ chunk_index_jsonl
 ├ chunk_index_sqlite
 ├ index_sidecar_json
 ├ dump_index_json
 ├ derived_index_json
 └ bundle_manifest
```

Manifest:

Enthält:
* artifact role
* sha256
* bytes
* content_type
* contract
* contract_version

---

## 7 Retrieval Runtime

RepoGround erhält eine Query-Runtime.

Modul:

`retrieval/query_runtime.py`

Query Pipeline:

query
 ↓
candidate retrieval
 ↓
rerank
 ↓
context builder

Candidate Retrieval:

Basis:
* FTS5
* BM25

Top-K:
* 50

Re-Ranking:

Optional:
* embedding rerank
* graph penalty
* structure weighting

Context Builder:

Output:
`query_context_bundle.json`

Enthält:
* chunks
* file references
* ranges
* dependency context

---

## 8 Knowledge Graph Layer

RepoGround erhält einen strukturellen Graphindex.

Artefakt:

`graph_index.json`

Nodes:

* file
* module
* class
* function
* package

Edges:

* imports
* calls
* contains
* depends_on

Beispiel:

```text
module A
  imports B

class X
  contains function f
```

---

## 9 Cross-Repo-Analyse

RepoGround unterstützt Multi-Repo-Bundles.

Artefakt:

`cross_repo_graph.json`

Fähigkeiten:

* dependency mapping
* module linking
* service topology

---

## 10 Lens-System

Lens = Perspektive auf Repo-Daten.

Architecture Lens:

Zeigt:
* module topology
* dependency graph
* entrypoints

Retrieval Lens:

Zeigt:
* relevant files
* call chains
* context clusters

PR Lens:

Analysiert:
* diff impact
* dependency impact
* risk zones

---

## 11 Bundle Evolution

Bundles werden langfristig zu Wissensdistributionen.

### 11.1 Delta Bundles

Artefakt:

`bundle_delta.json`

enthält:
* changed chunks
* changed files
* changed graph edges

### 11.2 Streaming Bundles

Unterstützt:

* chunk streaming
* index streaming
* partial queries

### 11.3 Bundle Compression

Optimierung:

* chunk_index → parquet
* markdown → compressed

---

## 12 Agent-Integration

RepoGround wird Kontextsystem für Agenten.

Agent API:

Endpoint:
`repoground query`

Antwort:
`query_context_bundle.json`

Agent Features:

* semantic search
* dependency trace
* architecture context

---

## 13 IDE-Integration

Plugins für:

* VSCode
* Neovim
* JetBrains

Funktionen:

* repo navigation
* architecture view
* context extraction

---

## 14 CI-Integration

RepoGround wird Teil der Build-Pipeline.

Neue CI-Checks:

* bundle rebuild check
* artifact hash check
* schema validation

---

## 15 Determinism Guard

RepoGround garantiert:

same repo → same bundle

CI-Check:

`bundle_hash_equality`

---

## 16 Governance

Artefakt-Governance wird eingeführt.

Regeln:

* kein Artefakt ohne Contract
* kein Contract ohne Schema
* kein Schema ohne Version

---

## 17 Systemprinzipien

RepoGround folgt dauerhaft:

* deterministic analysis
* contracts first
* artifact centric
* reproducible bundles
* agent ready outputs

---

# RepoGround-Umsetzungsplan – Teil 1
Rahmen, Gates, Phase 0 bis Phase 2

---

## 1. Zielzustand der Umsetzung

Nicht bloß „mehr Features“, sondern ein System, das vier Eigenschaften gleichzeitig verbessert:
1. Determinismus
2. Artefakt-Kohärenz
3. Query-Nutzbarkeit
4. Ausbaufähigkeit für Graph und Agenten

Zielgleichung:

Repo
→ deterministische Extraktion
→ stabile Artefakte
→ prüfbare Query-Runtime
→ portable Knowledge-Bundles
→ spätere Agent-/Heimgewebe-Anbindung

---

## 2. Grundannahmen, die vor jeder Umsetzung explizit gelten müssen

Belegt:
* RepoGround besitzt bereits Scanner-, Extraction-, Chunk-, Bundle- und Index-Pfade.
* Bundle-/Manifest-Logik, Range-Mechanik, Graph-Artefakt und Retrieval-Eval sind im System vorhanden oder in jüngsten PRs konkretisiert.
* Es gibt eine große Testsuite; sie ist ein echter Hebel, kein Dekor.

Plausibel:
* Der größte Fortschritt entsteht nicht durch neue exotische Features, sondern durch Vereinheitlichung der bestehenden Pfade.
* Der kritischste Engpass liegt an den Übergängen: canonical_md ↔ chunks ↔ range_ref ↔ manifest ↔ query runtime.

Spekulativ:
* Ein späterer Agent-/Heimgewebe-Einsatz wird stark von Query-Trace, Context-Bundle und Graph-Stabilität abhängen.

---

## 3. Arbeitsprinzip für die Umsetzung

Die Umsetzung sollte nicht feature-basiert, sondern systemachsen-basiert organisiert werden.

Achsen:
1. Build-Achse: Scan → Extract → Chunk → Bundle → Derived Artifacts
2. Contract-Achse: Schemas, Manifestrollen, Sidecar-Strukturen, Range-Objekte
3. Runtime-Achse: Query, Eval, Explain, später Service/WebUI
4. Diagnose-Achse: Tests, Validierung, Determinismus, Drift-Checks

---

## 4. Harte Delivery-Regeln

Jede Phase endet nur dann erfolgreich, wenn vier Dinge vorliegen:

1. Technischer Beleg:
	* Tests grün
	* Artefakte erzeugt
	* Manifest konsistent
	* keine stillen Fallbacks ohne Markierung
2. Contract-Beleg:
	* Schema passt
	* Rollenbezeichnungen konsistent
	* kein Artefakt außerhalb des Contract-Raums
3. Runtime-Beleg:
	* Query/Eval/Resolver können das neue Artefakt tatsächlich nutzen
4. Dokumentations-Beleg:
	* Roadmap und Beispiele spiegeln exakt den Codezustand wider
	* kein Checkbox-Theater. Ein abgehakter Punkt ohne Code ist wie ein TÜV-Stempel auf einer Nebelbank.

---

## 5. Gesamtphasen

Ich empfehle 8 Phasen:

* Phase 0: Diagnose-Freeze und Invarianten
* Phase 1: Artefakt- und Contract-Konsolidierung
* Phase 2: Query-Runtime-Härtung
* Phase 3: Graph-Runtime-Konsolidierung
* Phase 4: Context-Bundle / Query-Trace
* Phase 5: Cross-Repo / Knowledge-Layer
* Phase 6: Agent- und UI-Anbindung
* Phase 7: UI / Service / Produktisierung
* Phase 8: Semantische Erweiterung

---

## 6. Phase 0 – Diagnose-Freeze und Invarianten

Ziel:

Vor jedem weiteren Ausbau muss RepoGround als System vermessen werden. Nicht raten, nicht romantisieren.

Deliverables:
- [x] RepoGround-Systemkarte
- [x] Artefakt-Inventar
- [x] Contract-Matrix
- [x] Runtime-Matrix
- [x] Test-Matrix
- [x] Offene Inkonsistenzen-Liste

### 6.1 Arbeitspaket: Systemkarte erstellen

Inhalt:
Erfasse alle relevanten Module und ordne sie einer Achse zu:
* core/merge.py
* core/range_resolver.py
* retrieval/query_core.py
* retrieval/eval_core.py
* retrieval/index_db.py
* architecture/graph_index.py
* relevante Contracts unter contracts/
* Tests unter merger/repoground/tests/

Output:
`docs/architecture/system-map.repoground.md`

Muss enthalten:
* Modul
* Zweck
* Inputs
* Outputs
* Artefaktrollen
* abhängige Schemas
* Runtime-Nutzer

### 6.2 Arbeitspaket: Artefakt-Inventar

Ziel:
Jedes Artefakt wird explizit erfasst.

Beispielstruktur:
artifact name, role, producer, consumer, schema, manifest visibility, runtime usage

Besonders wichtig:
* canonical_md
* chunk_index.jsonl
* *.index.sqlite
* dump_index.json
* derived_index.json
* graph_index.json
* retrieval_eval.json
* index_sidecar_json

Output:
`docs/architecture/artifact-inventory.md`

### 6.3 Arbeitspaket: Contract-Matrix

Ziel:
Alle Schema- und Enum-Abhängigkeiten sichtbar machen.

Fragen:
* Welche ArtifactRole-Werte existieren?
* In welchen Schemas werden sie verwendet?
* Wo droht Enum-Drift?
* Welche Felder sind Pflicht?
* Welche Pfade sind canonical?

Output:
`docs/contracts/contracts-matrix.md`

### 6.4 Arbeitspaket: Runtime-Matrix

Ziel:
Nicht nur, was gebaut wird, sondern was tatsächlich benutzt wird.

Spalten:
* Modul
* liest welches Artefakt?
* schreibt welches Artefakt?
* nutzt Manifest?
* nutzt Contract?
* nutzt Fallback?
* stiller oder expliziter Fehlerpfad?

Output:
`docs/architecture/runtime-matrix.md`

### 6.5 Arbeitspaket: Test-Matrix

Ziel:
Tests nicht nach Datei, sondern nach abgedeckter Invariante ordnen.

Kategorien:
* bundle integrity
* range integrity
* graph integrity
* retrieval integrity
* split-mode integrity
* backwards compatibility
* path security
* manifest/schema validity

Output:
`docs/testing/test-matrix.md`

### 6.6 Gate für Phase 0

- [ ] Phase 0 ist formal dokumentiert (strukturelles Audit liegt vor), das Gate bleibt jedoch offen, da im aktuellen Audit noch nicht end-to-end nachgewiesen ist, dass:
	* alle Kernartefakte inventarisiert sind
	* alle Rollen/Schemas dokumentiert sind
	* alle Runtime-Pfade erfasst sind
	* mindestens 10 zentrale Invarianten benannt und End-to-End durch Tests robust abgesichert sind

Zentrale Invarianten (Beispiele):
1. Ein Artefakt ohne Manifestrolle ist Drift.
2. Ein Manifesteintrag ohne gültiges Schema ist Drift.
3. content_range_ref darf nur gesetzt werden, wenn Resolver und Manifest ihn auflösen können.
4. derived_range_ref ist nie Ersatz für expliziten range_ref.
5. Split-Mode darf keine falschen canonical-Annahmen erzeugen.
6. Query-Explain muss dieselben Scores erklären, die das Ranking erzeugt.
7. Graph-Artefakt muss deterministisch erzeugt werden.
8. Eval darf Runtime-Pfade nicht anders behandeln als Query.
9. Backwards-Compatibility darf keine Scheinfakten erzeugen.
10. Docs dürfen den Codezustand nicht überholen.

---

## 7. Phase 1 – Artefakt- und Contract-Konsolidierung

Ziel:

RepoGround muss zuerst sich selbst widerspruchsfrei lesen können.

### 7.1 Schwerpunkt A: Canonical-Definition vereinheitlichen

Problem:
In den bisherigen Diffs war genau hier Drift sichtbar:
* mal erster MD-Part
* mal letzter MD-Part
* mal „canonical“ im Sidecar anders als im Chunk-Bezug

Zielzustand:
Es gibt genau eine Definition von canonical_md.

Entscheidung:
canonical_md muss zentral festgelegt werden und an drei Stellen identisch sein:
1. MergeArtifacts / Rückgabeobjekt
2. bundle.manifest
3. sidecar / artifacts metadata

Umsetzung:
- [x] Einführen einer kleinen Hilfsfunktion: `resolve_canonical_md(md_parts) -> Path | None`
Diese Funktion wird die einzige Quelle für die canonical-Auswahl.

Betroffene Stellen:
* core/merge.py
* Manifest-Erzeugung
* JSON-Sidecar-Block
* Chunk-Erzeugung

Test:
* Single-part
* multi-part
* per-repo mode
* unified mode

### 7.2 Schwerpunkt B: ArtifactRole-Disziplin härten

Problem:
Neue Rollen wie graph_index_json, source_file oder ähnliche laufen Gefahr, nur halb eingeführt zu werden.

Zielzustand:
Jede Rolle ist an allen notwendigen Stellen konsistent:
1. core/constants.py
2. alle relevanten Schemas
3. manifest contract rules
4. range-ref schema, falls referenzierbar
5. tests

Umsetzung:
- [x] Ein „role completeness check“.

Idee:
Eigener Test oder Validator:
* liest ArtifactRole
* gleicht gegen Schemas/Enums ab
* meldet fehlende Rolleneinträge

Nutzen:
Verhindert die klassische KI-/Mensch-Kombinationskatastrophe:
„Rolle im Code vorhanden, im Schema vergessen.“

### 7.3 Schwerpunkt C: Range-Model sauber trennen

Ziel:
Drei Typen dürfen nie still vermischt werden:
1. expliziter bundle-backed range_ref
2. abgeleiteter source-backed derived_range_ref
3. kein Range-Bezug

Regel:
* range_ref nur bei explizit bundlegeprüftem Bezug
* derived_range_ref nur bei sauber markiertem Fallback
* niemals implizites Überschreiben

Umsetzung:
- [x] Hilfsfunktion für Range-Entscheidung
* Query-Core darf dies nicht inline improvisieren
* Resolver muss die Semantik kennen

Empfehlung:
Einführen von:
`build_explicit_range_ref(...)`
`build_derived_range_ref(...)`
statt verstreuter Dict-Zusammenbauten.

### 7.4 Schwerpunkt D: Split-Mode-Vertrag explizit machen

Problem:
Split-Mode ist systemisch heikel. Entweder: alle Parts sind voll referenzierbar, oder nur canonical part ist bundle-backed, oder es gibt zusätzliche Part-Rollen.

Aktueller sinnvoller Zwischenstand:
Nur das kanonische Bundle-Artefakt ist streng bundle-backed; spätere Parts bleiben bewusst außerhalb dieses Contracts.

Aber:
- [x] Das muss dann überall explizit sein:
* Roadmap
* Tests
* Query-Verhalten
* Schema-Erwartungen
* Resolver-Logik

### 7.5 Deliverables Phase 1
- [x] 1. canonical_md zentral vereinheitlicht
- [x] 2. Role-Completeness-Check
- [x] 3. Range-Builder-Helfer
- [x] 4. Split-Mode-Vertrag dokumentiert
- [x] 5. Docs/Beispiele synchronisiert

### 7.6 Gate für Phase 1
- [x] Phase 1 ist fertig, wenn:
* kein Widerspruch mehr zwischen manifest / sidecar / chunk / resolver bzgl. canonical_md existiert
* alle ArtifactRoles schema-konsistent sind
* range_ref und derived_range_ref logisch getrennt sind
* Split-Mode bewusst und testbar modelliert ist

---

## 8. Phase 2 – Query-Runtime-Härtung

Ziel:

RepoGround soll nicht nur Artefakte bauen, sondern eine vertrauenswürdige Query-Runtime bereitstellen.

### 8.1 Schwerpunkt A: Query-Core in klare Stufen zerlegen

Problem:
Query-Pfade neigen zu stiller Vermischung:
* candidate retrieval
* reranking
* graph influence
* explain
* range injection

Zielzustand:
- [x] `execute_query()` wird intern in klaren Stufen organisiert:
1. parse / validate input
2. load indices / optional artifacts
3. retrieve candidates
4. apply rerank
5. attach provenance
6. build explain
7. emit contract-compliant result

### 8.2 Schwerpunkt B: Explain und Ranking koppeln

Problem:
Ein Ranking ohne exakt passende Explain-Daten ist epistemisch Müll in hübschem JSON.

Ziel:
Jede Score-Komponente, die Ranking beeinflusst, muss im Explain wiederfindenbar sein.

Mussfelder:
* lexical score / bm25
* graph adjustment
* semantic adjustment
* tie-break decision
* final score

Umsetzung:
- [x] Interne strukturierte Score-Komponente:
```python
score_components = {
  lexical,
  semantic,
  graph,
  penalties,
  final
}
```
Diese Struktur wird sowohl fürs Ranking als auch fürs Explain genutzt.

### 8.3 Schwerpunkt C: Query-Result-Contract vervollständigen

Ziel:
- [x] Query-Ergebnisse sollen später für UI, Agenten und Eval stabil genug sein.

Muss enthalten:
* hit identity
* file/path/range
* score/final score
* explain block
* optional range_ref
* optional derived_range_ref
* graph metadata optional, aber sauber markiert

Zusatz: Versioniere diesen Vertrag strikt weiter. Keine halben Ad-hoc-Felder.

### 8.4 Schwerpunkt D: Fehlerpfade explizit machen

Problem:
Gerade bei optionalen Artefakten droht: stilles Schweigen, halbgare Fallbacks, falsche Plausibilität.

Ziel:
- [x] Jeder Fehlerpfad wird einer Klasse zugeordnet:
1. hard fail
2. soft fail with marker
3. fallback used
4. artifact unavailable

Beispiel:
Wenn graph_index.json fehlt:
* Query läuft weiter
* Explain enthält: `graph_status: "unavailable"`

Wenn Semantik crasht:
* je nach Policy fail oder ignore
* aber niemals unsichtbar

### 8.5 Schwerpunkt E: Eval an Query angleichen

Problem:
Viele Systeme haben eine Eval-Pipeline, die den echten Query-Pfad nicht sauber spiegelt.

Ziel:
- [x] Eval nutzt möglichst denselben internen Query-Mechanismus wie Runtime.

Umsetzung:
* eine gemeinsame Query-Ausführungsschicht
* Eval nur als Orchestrierung + Metrikberechnung
* keine zweite Logik

Ergebnis: Wenn Eval „gut“ sagt, meint es auch denselben Mechanismus, den später Nutzer sehen.

### 8.6 Schwerpunkt F: Query-Trace als neues Artefakt

Neues Artefakt:
- [x] `query_trace.json`

Zweck:
Für Debugging, Regression und Agentik.

Enthält:
* query input
* selected indices
* candidate count
* applied modifiers
* top hits
* fallback markers
* timings

### 8.7 Deliverables Phase 2
- [x] 1. Query-Pipeline intern gestuft
- [x] 2. Score/Explain konsistent
- [x] 3. Fehlerpfade markiert
- [x] 4. Eval nutzt denselben Query-Kern
- [x] 5. query_trace.json oder äquivalente interne Spur

### 8.8 Gate für Phase 2
- [x] Phase 2 ist fertig, wenn:
* Query-Ergebnisse contract-stabil sind
* Explain jede Ranking-Komponente abbildet
* Fehlerpfade nicht mehr still passieren
* Eval und Runtime denselben Kern teilen
* Regressionstests Query/Explain/Range/Graph gemeinsam absichern

*(Hinweis: Der Nachweis der Testerfüllung für dieses Gate basiert auf dem erfolgreich durchlaufenen, spezifischen Retrieval- und Evaluierungs-Test-Scope (`merger/repoground/tests/test_retrieval_query.py` und `merger/repoground/tests/test_retrieval_eval.py`). Eine vollständig fehlerfreie globale Testsuite wurde bewusst nicht forciert, um isolierte Scope-Prüfung zu gewährleisten und irrelevante Dependency-Installation in der Testumgebung zu vermeiden. Für die Reproduktion kann z.B. folgender Aufruf verwendet werden: `pytest merger/repoground/tests/test_retrieval_query.py merger/repoground/tests/test_retrieval_eval.py`.)*

---

# RepoGround-Umsetzungsplan – Teil 2
Phase 3 bis Phase 4 im Detail

---

## 1. Phase 3 – Graph-Runtime-Konsolidierung

Ziel:

Der Graph soll von einem „auch vorhandenen Artefakt“ zu einer kanonischen, prüfbaren und produktiv nutzbaren Runtime-Komponente werden.

Der relevante Sprung ist:
architecture graph artifact → graph_index.json → query/eval/runtime-consumable signal → erklärbare Ranking-Komponente

### 1.1 Ausgangslage

Belegt:
* graph_index.json wird erzeugt.
* Bundle-/Manifest-Einbindung ist vorhanden.
* Query/Eval können graph-aware arbeiten.
* Tests für Bundle-Integration und Graph-Runtime existieren.

Problemkern:
Der Graph ist noch gefährdet, nur formal vorhanden, aber nicht überall semantisch gleich interpretiert zu sein.

Typische Driftquellen:
1. Node-ID-Formate driften
2. Entrypoint-Definition driftet
3. Distanzbedeutung driftet
4. Query-Score nutzt Graph anders als Eval
5. Explain benennt andere Gründe als das Ranking tatsächlich verwendet

### 1.2 Zielzustand von Phase 3

Nach Phase 3 gilt:
1. graph_index.json ist kanonisch beschrieben
2. Graph-Signale haben klare mathematische Bedeutung
3. Query, Eval und Explain nutzen dieselbe Graph-Semantik
4. Graph-Effekte sind messbar, testbar, abschaltbar
5. Fehlende oder veraltete Graph-Artefakte erzeugen keine stillen Scheinfakten

### 1.3 Arbeitspaket A – Graph-Semantik explizit definieren

Ziel:
- [x] Dokumentieren, was der Graph überhaupt bedeutet.

Muss schriftlich festgehalten werden:
* Was ist ein Node?
* Was ist eine Edge?
* Was ist ein Entrypoint?
* Was bedeutet distance?
* Ist Distanz gerichtet oder ungerichtet?
* Wie werden nicht erreichbare Nodes behandelt?
* Wie beeinflusst Distanz das Ranking?

Output:
`docs/architecture/graph-runtime-contract.md`

Muss enthalten:
node identity, edge semantics, distance semantics, entrypoint semantics, runtime usage, known limitations

### 1.4 Arbeitspaket B – Graph-Index-Schema härten

Ziel:
- [x] graph_index.json soll nicht nur existieren, sondern contractuell erzwungen valide sein.

Umsetzung:
Falls noch nicht vorhanden bzw. unvollständig:
* eigenes Schema für architecture.graph_index v1
* Validierung beim Schreiben
* Validierung beim Laden in Query/Eval

Mussfelder:
* kind
* version
* nodes
* entrypoints
* distances
* optional Metadaten zu Erzeugungsbasis

Zusatz:
Ein graph_input_fingerprint wäre sinnvoll (Hash der Architektur-Inputs, Hash der Entrypoints, ggf. Generatorversion).

### 1.5 Arbeitspaket C – Graph-Loading zentralisieren

Problem:
Wenn Query und Eval jeweils separat laden/parsen/normalisieren, droht Drift.

Ziel:
- [x] Eine zentrale Ladefunktion: `load_graph_index(path) -> validated normalized graph object`

Aufgaben dieser Funktion:
* Existenz prüfen
* Schema validieren
* Struktur normalisieren
* Distanzwerte typisieren
* Fehlerklasse zurückgeben

Fehlerklassen:
* not_found
* invalid_schema
* invalid_json
* stale_or_mismatched
* ok

### 1.6 Arbeitspaket D – Graph-Scoring mathematisch stabilisieren

Problem:
„Graph beeinflusst Ranking“ ist noch zu grob. Es braucht eine definierte Formel.

Ziel:
- [x] Graph-Signal als klarer Score-Term.

Beispielhafte Form:
`graph_bonus = f(distance, weights, caps)`
`final_score = lexical + semantic + graph_bonus + penalties`

Zu definieren:
* Distanz 0 = was genau?
* Distanz 1 vs 2 = linear oder nichtlinear?
* Unreachable = 0 Bonus oder Strafe?
* Darf Graph lexikalische Evidenz überstimmen?
* Gibt es Caps?

Empfehlung:
Anfangs konservativ: Graph nur moderat tie-breakend / leicht verstärkend, nie dominanter als starker lexikalischer Treffer.

### 1.7 Arbeitspaket E – Explain mit Graph koppeln

Ziel:
- [x] Wenn der Graph etwas beeinflusst, muss Explain genau das zeigen.

Explain soll enthalten:
* graph_used: true/false
* graph_status: ok/unavailable/invalid/stale
* node_id
* distance
* graph_bonus
* entrypoint_reference optional

Testfragen:
* Zeigt Explain denselben distance, der fürs Ranking benutzt wurde?
* Wird graph_used=false gesetzt, wenn Graph fehlt?
* Ist ein ungültiger Graph sichtbar markiert?

### 1.8 Arbeitspaket F – Graph-Aware-Eval ausbauen

Ziel:
- [x] Eval soll nicht nur „mit Graph läuft“, sondern explizit zeigen, ob und wann der Graph etwas bringt.

Neue Eval-Sichten:
* baseline
* graph-enabled
* optional später semantic+graph

Output-Metriken:
* baseline_mrr
* graph_mrr
* delta_graph_mrr
* baseline_recall@k
* graph_recall@k
* per-query delta

Zusätzlich:
* Queries markieren, bei denen Graph half
* Queries markieren, bei denen Graph schadete

### 1.9 Arbeitspaket G – Graph-Staleness / Konsistenz prüfen

Ziel:
- [x] Ein Graph darf nicht still weiterverwendet werden, wenn seine Inputs nicht mehr passen.

Möglichkeiten:
1. Fingerprint der Inputs im Graph speichern
2. beim Laden gegen aktuelle Bundle-Artefakte prüfen
3. Status im Explain/Trace ausgeben

Bessere Variante: Hash von `architecture_graph.json`, Hash von `entrypoints.json`.

### 1.10 Tests Phase 3

Neue oder geschärfte Tests:
- [x] 1. test_graph_schema_validation
- [x] 2. test_graph_loader_normalizes_and_rejects_invalid
- [x] 3. test_query_explain_graph_fields_match_scoring
- [x] 4. test_eval_graph_delta_reporting
- [x] 5. test_graph_staleness_marker
- [x] 6. test_missing_graph_is_explicitly_reported
- [x] 7. test_graph_bonus_is_bounded

Besonders wichtig: Ein Test, der zeigt: Graph vorhanden -> Query-Ranking ändert sich -> Explain zeigt exakt denselben Grund.

### 1.11 Deliverables Phase 3
- [x] 1. Graph-Runtime-Contract-Doku (im Re-Audit formal belegt)
- [x] 2. zentrales Graph-Loader-Modul (im Re-Audit strukturell belegt)
- [x] 3. definierte Graph-Score-Formel (im Re-Audit strukturell belegt, mathematisch gecappt)
- [x] 4. Explain/Runtime-Kopplung (im Re-Audit strukturell belegt)
- [x] 5. graph-aware Eval mit Deltas (im Re-Audit strukturell belegt)
- [x] 6. Graph-Staleness-Marker (end-to-end durch echten Hash-Mismatch nachgewiesen; Marker- und Diagnostikpfad belegt)

### 1.12 Gate für Phase 3
- [ ] Phase 3 ist im Audit strukturell nachgewiesen (Marker-Propagation ist end-to-end belegt), aber das Gate bleibt offen:
* Graph semantisch dokumentiert ist [x]
* Query/Eval denselben Loader und dieselbe Semantik nutzen [x]
* Explain die tatsächliche Graph-Wirkung abbildet [x]
* Graph-Effekt messbar ist [x]
* Stale/missing Graph nicht mehr still durchrutscht [x] (als Marker sichtbar)
* **Offen:** Echte Staleness-Recovery / Policy für stale_or_mismatched im Ranking/Fallback ist nicht implementiert oder abschließend geklärt [ ]

---

## 2. Phase 4 – Context-Bundle / Query-Trace / Retrieval-Produktisierung

Ziel:

RepoGround soll nicht nur Trefferlisten liefern, sondern brauchbare, portable Kontextpakete für Menschen, UI und Agenten.

Der Sprung ist:
query → hits → kontextualisierte Evidenz → portable query artifact → nutzbar für Review / Agent / UI

### 2.1 Ausgangslage

Belegt:
* Bundle-Artefakte existieren
* Query und Range-Auflösung existieren
* Manifest- und Contract-Rahmen existieren
* Service/WebUI scheinen vorhanden oder vorbereitet

Fehlende Reife:
Es fehlt noch ein sauberer „Produkt-Layer“ über dem Retrieval: Was ist das portable Ergebnis einer Query? Wie bekommt ein Agent mehr als nur rohe Treffer? Wie wird nachvollziehbar, warum genau dieser Kontext geliefert wurde?

### 2.2 Zielzustand von Phase 4

Nach Phase 4 gibt es:
1. ein Context-Bundle-Artefakt
2. eine saubere Query-Trace
3. definierte Hit-/Context-Modelle
4. stabile Übergänge für UI und Agenten
5. klaren Unterschied zwischen: Hit, Evidence, Context, Decision support

### 2.3 Arbeitspaket A – Query-Trace einführen

Ziel:
- [x] Jede relevante Query kann als Diagnoseartefakt geschrieben werden.

Artefakt: `query_trace.json`

Inhalt:
* query input
* filters
* loaded artifacts
* candidate count
* ranking stages
* graph status
* semantic status
* fallback markers
* chosen hits
* timings

Designregel: Trace ist Diagnose, nicht Primärantwort.
*Hinweis (Hybridmodell)*: Das `query_trace` ist ein Teilfeld im regulären `query-result.v1.schema.json` Contract. `query_trace.json` ist lediglich ein optionaler CLI-Export dieses Feldes, kein isoliert erzeugtes Artefakt.

### 2.4 Arbeitspaket B – Context-Bundle definieren

Ziel:
- [x] Ein Treffer soll in ein portables Kontextpaket überführt werden.

Neues Artefakt: `query_context_bundle.json`

*Architektur-Anmerkung (Hybridmodell):*
Das Context-Bundle ist primär als optionales Feld `context_bundle` im `query-result.v1.schema.json` verankert.
Die Datei `query_context_bundle.json` bzw. das CLI-Output-Format beschreibt dessen projizierte JSON-Ausgabe. Es existieren keine zwei konkurrierenden Wahrheitsmodelle (wie schon bei `query_trace`).

Inhalt pro Hit:
* hit identity
* file/path/range
* score/explain
* resolved code snippet
* optional surrounding context
* optional graph context
* provenance (range_ref / derived_range_ref)
* bundle source references

Unterschied zum Query-Result:
Query-Result = Rankingantwort
Context-Bundle = Arbeitsmaterial

### 2.5 Arbeitspaket C – Hit/Evidence/Context trennen

Problem: Oft wird alles in einen JSON-Topf geworfen.

Ziel:
- [x] Saubere Begriffe:
* Hit: Ein geranktes Ergebnisobjekt
* Evidence: Der tatsächlich extrahierte belegende Ausschnitt
* Context: Zusätzliche umgebende oder strukturbezogene Information
* Recommendation/Interpretation: Kommt später und ist nicht Teil des Retrieval-Kerns

### 2.6 Arbeitspaket D – Context-Expansion definieren

Ziel:
- [x] Kontext wird regelbasiert und deterministisch erweitert.

Mögliche Modi:
1. exact snippet
2. enclosing block
3. surrounding lines
4. file-local summary
5. graph-neighbor summary optional

Konfigurierbar:
`context_mode = exact|block|window|file`
`context_window_lines = N`

Regel: Context-Expansion darf nie die Primärevidenz ersetzen, nur ergänzen.

### 2.7 Arbeitspaket E – Provenance first

Ziel:
- [x] Jeder Context-Bundle-Eintrag trägt seine Herkunft explizit.

Mussfelder:
* provenance_type: explicit|derived
* range_ref oder derived_range_ref
* bundle artifact reference
* resolver status

Besonders wichtig: Wenn Context nur source-backed ableitbar ist, muss das sichtbar bleiben. Kein stilles Aufhübschen.

### 2.8 Arbeitspaket F – Output-Profile für verschiedene Nutzer

Ziel:
- [x] RepoGround soll verschiedene Ausgabemodi liefern, ohne den Kern zu verbiegen.

Profile:
1. human_review (mehr Kontext, lesbare Explain-Struktur)
2. agent_minimal (kompakter, strikt contract-basiert)
3. ui_navigation (download-/jump-/preview-fähig)
4. eval_debug (maximal transparent)

Umsetzung: Nicht vier Engines, sondern ein gemeinsames internes Modell + Renderer/Emitter.

### 2.9 Arbeitspaket G – Service/API-Integration vorbereiten

Ziel:
- [x] Die Runtime-Artefakte müssen sauber in HTTP/API überführbar sein.

API-Ziele:
* query submit
* hit list
* context bundle retrieve
* trace retrieve
* diagnostics retrieve

Wichtig: API darf keine privaten internen Hilfsfelder ungefiltert nach außen leaken. Intern reich, extern diszipliniert.

### 2.10 Arbeitspaket H – WebUI minimal produktisieren

Ziel:
- [x] WebUI nicht als Spielzeug, sondern als Inspektionsoberfläche (strukturell erreicht, grundlegende DOM-Härtung abgeschlossen).

Minimale Features:
* Query eingeben
* Trefferliste
* Explain sichtbar
* Kontextvorschau
* Provenance sichtbar
* Artefakt-Downloads
* Graph-Status sichtbar

Sehr sinnvoll: Badge-System (lexical, graph, semantic, explicit provenance, derived provenance, fallback used).

### 2.11 Arbeitspaket I – Context-Bundle-Eval

Ziel:
- [x] Nicht nur Rankingqualität, sondern auch Kontextnutzbarkeit prüfen.

Deterministische Checks:
* context snippet passthrough / provenance consistency
* provenance validity
* context contains expected snippet
* no silent provenance downgrade

### 2.12 Tests Phase 4

Wichtige Tests:
- [x] 1. test_query_trace_contains_runtime_markers
- [x] 2. test_context_bundle_contains_evidence_and_context
- [x] 3. test_context_bundle_preserves_provenance
- [x] 4. test_context_expansion_exact_vs_block_vs_window
- [x] 5. test_ui_payload_excludes_internal_fields
- [x] 6. test_agent_minimal_profile_contract
- [x] 7. test_context_bundle_extracts_snippet_correctly

### 2.13 Deliverables Phase 4
- [x] 1. query_trace.json (projiziert / CLI)
- [x] 2. query_context_bundle.json (projiziert / CLI)
- [x] 3. Hit/Evidence/Context-Modell
- [x] 4. Context-Expansion-Regeln
- [x] 5. Provenance-first Output
- [x] 6. Output-Profile
- [x] 7. API/UI-ready Struktur

### 2.14 Gate für Phase 4
- [ ] Phase 4 ist fertig, wenn:
* eine Query mehr als rohe Treffer liefert
* Context-Bundles portabel und provenance-stabil sind
* Trace Diagnose ermöglicht
* Output-Profile definiert sind
* UI/Agent-Integration ohne Kernverbiegung möglich ist

---

# RepoGround-Umsetzungsplan – Teil 3
Phase 5 bis Phase 6 im Detail

---

## 1. Phase 5 – Cross-Repo-Knowledge-Layer

*(Architektonischer Ausbaupfad – nicht als bereits implementiert zu lesen. Bedarf separater Contract-/Implementierungs-PRs.)*

Ziel:

RepoGround soll von einem Bundle-Erzeuger pro Repo oder Run zu einem System werden, das mehrere Bundles systematisch in Beziehung setzen kann, ohne seine deterministische Natur zu verlieren.

Der Sprung ist:
repo bundle A + B + C → federated knowledge layer → cross-repo retrieval / structure / provenance

### 1.1 Ausgangslage

Belegt:
* RepoGround erzeugt portable Bundles
* Artefakte sind contract-basiert
* Architektur-/Graph-Artefakte existieren
* Retrieval funktioniert pro Bundle
* Sidecars und Manifeste machen Artefakte adressierbar

Epistemische Leerstelle:
Es fehlt derzeit eine saubere, explizite Schicht für: repo-übergreifende Identitäten, Beziehungen, föderierte Queries, Konflikt-/Widerspruchsmanagement zwischen Bundles.

### 1.2 Zielzustand von Phase 5

Nach Phase 5 gilt:
1. mehrere Bundles können formal zusammen adressiert werden
2. repo-übergreifende Queries sind möglich
3. Provenance bleibt bundle-scharf sichtbar
4. Identitäts- und Konfliktregeln sind definiert
5. RepoGround bleibt deterministisch, auch wenn mehrere Bundles beteiligt sind

### 1.3 Arbeitspaket A – Bundle-Föderationsmodell definieren

Ziel:
- [ ] Ein Modell, das mehrere Bundles verbindet, ohne sie zu vermischen.

Neues Artefakt: `federation_index.json`

Inhalt:
* federation id
* enthaltene Bundles
* bundle fingerprints
* repo names / repo ids
* optional Rollen oder Tags
* Cross-Repo-Navigationskanten
* Aktualitätsinformationen

Grundprinzip: Nicht „ein globaler Blob“, sondern strukturierte Föderation.

### 1.4 Arbeitspaket B – Identity Layer einführen

Problem: Cross-Repo-Wissen scheitert oft nicht an Suche, sondern an Identität.

Ziel:
- [ ] Explizite Regeln für:
* Repo-Identität
* Modul-Identität
* Pfad-Identität
* Symbol-Identität
* Entrypoint-Identität

Minimale Identitätsform: `bundle_id + repo_id + path + local_symbol`

### 1.5 Arbeitspaket C – Cross-Repo-Relationen explizit machen

Ziel:
- [ ] Repo-übergreifende Beziehungen werden nicht implizit erraten, sondern explizit modelliert.

Relationstypen: imports / references, contract producer / consumer, shared artifact family, shared path namespace, common entrypoint domain, bundle-to-bundle dependency, documentation-to-code relation.

Artefakt: `cross_repo_links.json`

Regeln: Jede Kante braucht source, target, relation_type, evidence, confidence class (explicit | inferred).

### 1.6 Arbeitspaket D – Föderierte Query einführen

Ziel:
- [ ] Eine Query kann über mehrere Bundles laufen.

Neues Modell: `federated_query`

Eingabe: query text, bundle scope, repo filter, relation expansion rules, ranking profile.
Ausgabe: Treffer pro Bundle, global sortierte Treffer, provenance pro Treffer, optional relation context.

Reihenfolge:
1. Query pro Bundle
2. Ergebnisnormalisierung
3. optionale Cross-Repo-Expansion
4. föderiertes Ranking
5. Context-Bundle je Treffer

### 1.7 Arbeitspaket E – Föderiertes Ranking definieren

Problem: Wie vergleicht man Treffer aus verschiedenen Bundles?

Ziel:
- [ ] Erste Version konservativ:
* lokale Scores bleiben erhalten
* globale Sortierung nur nach normalisiertem Profil
* bundle/source sichtbar ausweisen
* optional tie-breaker: exact path match, contract relevance, graph relevance, repo priority.

### 1.8 Arbeitspaket F – Widerspruchs- und Konfliktmodell

Ziel:
- [ ] Cross-Repo bedeutet fast zwangsläufig Konflikte. Diese müssen gemeldet werden.

Neues Artefakt: `federation_conflicts.json`

Konfliktklassen:
* duplicate_identity
* version_conflict
* ownership_conflict
* stale_bundle_conflict
* incompatible_contract_claim

Nutzen: Widersprüche werden nicht geglättet, sondern sichtbar.

### 1.9 Arbeitspaket G – Cross-Repo-Context-Bundle

Ziel:
- [ ] Ein Kontextpaket kann bundle-übergreifend erweitert werden.

Struktur:
`primary_evidence`
`related_evidence[]`
`relation_context[]`
`federation_trace`

Regel: Primärevidenz bleibt lokal. Cross-Repo-Kontext ist Ergänzung, nicht Überschreibung.

### 1.10 Arbeitspaket H – Föderationsdiagnostik

Ziel:
- [ ] Nicht nur Ergebnis, sondern auch Zustand der Föderation wird sichtbar.

Neue Diagnosen: bundle loaded / failed / stale, repo coverage, relation coverage, unresolved identities, conflict count.

Ausgabe: `federation_trace.json`

### 1.11 Tests Phase 5

Wichtige Tests:
- [x] 1. test_federation_index_builds_deterministically (kanonische Bundle-Sortierung und JSON-/Hash-Stabilität für identische Inhalte mit variierender Add-Reihenfolge abgesichert; kein vollumfänglicher E2E-Nachweis der gesamten Phase)
- [~] 2. test_cross_repo_links_are_provenance_backed (Minimaltest vorhanden: `test_cross_repo_links_evidence_refs_are_chunk_ids`, `test_cross_repo_links_schema_valid_when_multi_bundle`; echte strukturelle Provenance-Tiefe offen)
- [x] 3. test_federated_query_preserves_bundle_origin (als Minimaltest vorhanden)
- [ ] 4. test_federated_ranking_is_stable (Tie-Breaker implementiert, aber noch kein echtes föderiertes Relevanzmodell)
- [ ] 5. test_conflicts_are_reported_not_smoothed (derzeit nur einfache filename-Heuristik, keine Identity-Engine)
- [ ] 6. test_cross_repo_context_preserves_primary_evidence (derzeit ranking-basierte Primär-/Sekundärrollen, nicht semantisch inferiert)
- [x] 7. test_stale_bundle_is_marked_in_federation_trace

### 1.12 Deliverables Phase 5
- [x] 1. federation_index.json (Struktur angelegt und validiert, Bundle-Reihenfolge wird nun kanonisch über repo_id stabilisiert)
- [~] 2. cross_repo_links.json (Contract vorhanden, Root-Type auf `array` korrigiert; minimaler heuristischer Runtime-Producer `_build_cross_repo_links` implementiert: emittiert `co_occurrence`-Links mit `confidence: "inferred"` pro Repo-Paar in den finalen `results`; ganzes Artefakt-Array schema-validiert; CLI-Persistenz als `cross_repo_links.json` bei `--trace`; **`co_occurrence` beweist ausschließlich gemeinsame Query-Präsenz — keine Identität, keine Abhängigkeit, keine semantische Gleichheit; Ranking unverändert**; offen: semantisch belastbare Identity-Engine)
- [~] 3. federation_conflicts.json (teilweise: Runtime-Struktur vorhanden, minimale CLI-Persistenz im Trace-Pfad umgesetzt)
- [~] 4. `federation_trace` in zwei Formen: (a) **CLI-Dateiartefakt** `federation_trace.json` — bei `--trace` persistiert, schema-validiert ausschließlich gegen `federation-trace.v1.schema.json` (`additionalProperties: false` an Root- und Bundle-Item-Ebene), Shape: `query`, `timestamp`, `total_results`, `bundles[]`; (b) **Runtime-Inline-Form** — erzeugt von `execute_federated_query`, durch `output_projection.py` im Wrapper erhalten (Output-Profile verschlucken diese Form nicht), Shape: `queried_bundles_total`, `bundle_status`, `bundle_errors`, `bundle_traces`; bewusst kein eigenes JSON-Schema. **Trace beweist Ausführungs- und Aggregationsspur — keine semantische Identität, keine Ranking-Semantik.** Offen: Latenz-Telemetrie pro Bundle, Status `missing` wird nicht emittiert.
- [ ] 5. föderierte Query-Schnittstelle (als Minimal-Fan-out mit deterministischer Aggregation integriert, aber keine vollwertige Cross-Repo-Relevanz-Harmonisierung)
- [ ] 6. bundleübergreifendes Context-Bundle (derzeit nur Treffermarkierung, echte Struktur offen)
- [ ] 7. Identity-/Conflict-Regeln (derzeit minimale filename-basierte Heuristik, kein vollwertiges System)

### 1.13 Gate für Phase 5
- [ ] Phase 5 ist als Minimal-Fan-out angerissen, aber als Architekturphase noch offen.
* mehrere Bundles formal föderiert werden können [x]
* Cross-Repo-Queries deterministisch aggregiert werden [x] (als Minimal-Fan-out)
* provenance bundle-scharf bleibt [x]
* Konflikte explizit gemeldet werden [x] (als Minimalheuristik)
* kein stilles Vermischen konkurrierender Wahrheiten passiert [x]
* cross_repo_links schema-valide emittierbar [x] (als Minimalheuristik, noch keine belastbare Identity-Engine)
-> Hinweis: Der aktuelle Stand bietet praktische Föderationsnutzbarkeit (Aggregation), schließt Phase 5 aber architektonisch noch nicht vollständig ab (fehlende kanonische Trace-Artefakte, echtes Identity-System, tiefes Ranking-Alignment).


> **Epistemische Leerstelle: Federation-Staleness**
> Die Eigenschaft `stale_policy` wird am `/api/federation/query` Endpunkt aktuell nicht unterstützt und wurde aus dem Contract (`FederationQueryRequest`) entfernt. Der Versuch, `check_stale_index` auf ein Federation-JSON anzuwenden, war fachlich falsch (da es auf SQLite-Indizes ausgelegt ist). Eine übergreifende Staleness-Architektur für föderierte Bundles ist ungelöst.

### 1.14 Gate für Phase 6
Phase 6 darf erst beginnen, wenn die Minimalaggregation aus Phase 5 ausreichend diagnostizierbar ist:
* federation_trace Output liefert verlässliche Bundle-Zustände (missing, stale, error)
* Konflikte werden als Warnungen sichtbar (auch wenn nur heuristisch)
* Aggregations-Ranking ist reproduzierbar

---

## 2. Phase 6 – Agent-Anbindung / Control Surface

*(Architektonischer Ausbaupfad – nicht als bereits implementiert zu lesen. Bedarf separater Contract-/Implementierungs-PRs.)*

Ziel:

RepoGround soll Agenten bedienen können, ohne seine Deterministik und epistemische Disziplin zu verlieren.
Nicht: Agent fragt irgendwas, RepoGround spuckt irgendwas aus.
Sondern: Agent request → strict query contract → traceable retrieval → context bundle → bounded action surface.

### 2.1 Ausgangslage

Belegt:
* Sidecar-/Manifest-Strukturen existieren
* Bundle-Artefakte sind relativ agent-freundlich
* Service/UI-Schichten sind teilweise vorhanden
* Retrieval-Bausteine sind modular genug

Problem:
Ein Agent braucht nicht nur Daten, sondern eine sichere Bedienoberfläche.

### 2.2 Zielzustand von Phase 6

Nach Phase 6 gilt:
1. Agenten sprechen RepoGround über eine enge, klare API
2. alle Antworten sind provenance-fähig
3. Query- und Kontextprofile sind steuerbar
4. Diagnosen sind maschinenlesbar
5. Agenten können RepoGround nicht mit stillen Annahmen missbrauchen

### 2.3 Arbeitspaket A – Agent Query Contract

Ziel:
- [x] Ein formales Request/Response-Modell für Agenten (strukturell über QueryRequest und API Contracts belegt, bedarf e2e-Härtung).

Request: intent, query, scope, output_profile, context_mode, explain_level, diagnostics.
Response: hits, context bundle, provenance, trace reference, warnings, uncertainty markers.

Wichtig: Agenten sollen keine versteckten Default-Zauber triggern. Jeder relevante Hebel muss explizit sein.

### 2.4 Arbeitspaket B – Output-Profile für Agenten

Ziel:
- [x] Nicht jeder Agent braucht dieselbe Antwortform (Profile wie agent_minimal existieren und strippen überflüssige Felder, andere Profile bedürfen Ausbau).

Profile:
* lookup_minimal
* review_context
* architecture_probe
* contract_trace
* federated_search
* debug_trace

### 2.5 Arbeitspaket C – Bounded Tool Surface
Ziel:
- [~] RepoGround soll als Werkzeug präzise Grenzen haben.
  erfüllt: HTTP-seitig repo-belegt vorhanden: `/api/query`, `/api/federation/query`, `/api/artifact_lookup`, `/api/trace_lookup`, `/api/context_lookup`, `/api/diagnostics`; logisch entspricht dies den Endpunkten `/query`, `/federation/query`, `/artifact`, `/trace`, `/context`, `/diagnostics`.
  fehlt: offen bleiben nachgelagerte Produktisierungsaspekte (UI/Diagnostic Views, Lifecycle/Retention, MCP-Anbindung).

Operationen:
- [x] 1. query (logisch vorgesehen als `/query`; HTTP-seitig repo-belegt via `/api/query`)
- [~] 2. context_bundle (`POST /api/context_lookup` implementiert für gespeicherte `context_bundle`-Artefakte; Contract `context-lookup.v1.schema.json`; Request strict (`extra="forbid"`); offen: Lifecycle/Retention, raw-vs.-projizierte Artefaktform, Federation-Artefakte, MCP-Anbindung)
- [~] 3. trace_lookup (`POST /api/trace_lookup` implementiert für gespeicherte `query_trace`-Artefakte; Contract `trace-lookup.v1.schema.json`; Request strict (`extra="forbid"`); offen: Federation-Trace, Retention/Lifecycle, raw-vs.-projizierte Trace-Semantik, MCP-Anbindung)
- [~] 4. artifact_lookup (`POST /api/artifact_lookup` implementiert für Query-Runtime-Artefakte: `query_trace`, `context_bundle`, `agent_query_session`; Contract `artifact-lookup.v1.schema.json`; offen: Lifecycle/Retention, raw-vs.-projizierte Artefaktform, Federation-Artefakte, MCP-Anbindung)
- [x] 5. federation_query (logisch vorgesehen als `/federation/query`; HTTP-seitig repo-belegt via `/api/federation/query`)
- [x] 6. diagnostics (GET `/api/diagnostics` als read-only Snapshot-Lookup implementiert; Contract `diagnostics-lookup.v1.schema.json`; offen: UI/Diagnostic Views und ggf. tiefere Runtime-Diagnostik)

Nicht direkt zulassen: freie Dateisystemnavigation ohne Scope, implizites Zusammenmischen beliebiger Bundles, ungebundene „find everything about X“-Operationen ohne Grenzen.

### 2.6 Arbeitspaket D – Uncertainty / Provenance maschinenlesbar machen
Ziel:
- [~] Agenten sollen nicht nur Ergebnisse, sondern auch deren epistemischen Status sehen.
  erfüllt: `epistemics` Contract definiert und für lokale Basisdaten getestet.
  fehlt: Komplexe Status werden noch nicht durchgängig aus allen Pfaden in den Contract überführt (z.B. `semantic_status` bleibt konservativ `unknown`).

Felder: provenance_type, bundle_origin, resolver_status, graph_status, semantic_status, federation_status, uncertainty, interpolation.

### 2.7 Arbeitspaket E – Decision-Support von Retrieval trennen
Ziel:
- [ ] RepoGround bleibt Retrieval- und Evidenzsystem, kein Entscheidungsautomat.

Trennung:
* RepoGround liefert: hits, evidence, context, diagnostics
* Agent / Orchestrator entscheidet: was relevant ist, welche Handlung folgt, welche Synthese gebildet wird.

### 2.8 Arbeitspaket F – Agent Traceability
Ziel:
- [~] Jede Agent-Nutzung ist nachvollziehbar.
  CLI: nutzt physisches Artefakt `agent_query_session.json` (v1-Contract). Es bündelt Request-, Bundle-, Trace- und Diagnose-Bezüge.
  API (Provenienz gehärtet): liefert v2-Session als Inline-Payload **und** speichert sie als Runtime-Artefakt.
  Gespeicherter Stand (belegt durch `test_api_query_agent_session_artifact_refs_crosscheck` und `test_api_federation_query_agent_session_artifact_refs_crosscheck`):
  - `/api/query` (trace=true): speichert `query_trace`; `context_bundle` und `agent_query_session` werden gespeichert, wenn ein Context Bundle im Ergebnis vorhanden ist, die Session gebaut wird und `QueryArtifactStore` konfiguriert ist. Store-IDs erscheinen in `artifact_ids`.
  - `/api/federation/query` (trace=true): speichert `context_bundle` und `agent_query_session` nur, wenn ein Context Bundle vorhanden ist, die Session gebaut wird und `QueryArtifactStore` konfiguriert ist. Es gibt keinen standalone `query_trace`; `artifact_refs.query_trace_id` bleibt bewusst null.
  - `artifact_refs.agent_query_session_id` bleibt **immer null** im Payload (Zirkel-Self-ID); die Store-ID liegt ausschließlich in `artifact_ids.agent_query_session`.
  - `/api/artifact_lookup` löst gespeicherte `agent_query_session`-Artefakte per `artifact_ids.agent_query_session` auf.
  Offen (nicht strukturell belegt): physischer Trace-Layer für Orchestrierungs-/Feedback-Schleifen, MCP-Anbindung, UI-Nutzung.

### 2.9 Arbeitspaket G – Service-Endpunkte / MCP-fähige Form
Ziel:
- [~] RepoGround soll sich sauber an Orchestratoren oder MCP-artige Systeme andocken lassen.
  erfüllt: HTTP-Servicepfade (siehe 2.5) vorhanden.
  fehlt: MCP Protocol Bindings (z.B. mcp-server) fehlen.

Endpunkte logisch: `/query`, `/context`, `/trace`, `/artifact`, `/federation/query`, `/diagnostics`

### 2.10 Arbeitspaket H – Guardrails für Agenten
Ziel:
- [~] RepoGround soll problematische Zustände aktiv markieren.
  repo-belegt: Guardrail-Klasse `low_result_coverage` (emittiert `"Low result coverage"`).
  noch offen (nicht strukturell belegt): `stale_bundle`, `invalid_graph`, `missing_provenance`, `cross_repo_conflict`.

### 2.11 Arbeitspaket I – Evaluierung der Agent-Nutzung
Ziel:
- [ ] Nicht nur Query-Qualität, sondern Agent-Tauglichkeit prüfen.

Tests:
- [x] 1. test_agent_query_contract_roundtrip
- [x] 2. test_agent_profile_lookup_minimal
- [x] 3. test_agent_profile_review_context
- [~] 4. Agent Session Traceability (Provenienz gehärtet: `test_api_query_agent_session_artifact_refs_crosscheck` und `test_api_federation_query_agent_session_artifact_refs_crosscheck` belegen artifact_refs-Crosscheck, Roundtrip über `/api/artifact_lookup` und bewussten null-Self-ID-Kontrakt; offen: Orchestrierungs-/Feedback-Schleifen, MCP-Anbindung, UI-Nutzung).
- [x] 5. test_agent_response_surfaces_uncertainty
- [x] 6. test_agent_federated_conflict_warning

### 2.12 Deliverables Phase 6
- [x] 1. Agent Query Contract (minimaler HTTP-Roundtrip über `/api/query` repo-belegt und getestet)
- [x] 2. Agent Output Profiles (strukturell existierend via `output_profile` wie `agent_minimal`, `lookup_minimal`, `review_context`)
- [~] 3. bounded API/tool surface (Query-/Federation-Pfade sowie `POST /api/artifact_lookup`, `POST /api/trace_lookup`, `POST /api/context_lookup` und `GET /api/diagnostics` vorhanden; offen: Lifecycle/Retention, Federation-Vertiefung, MCP-Anbindung)
- [~] 4. maschinenlesbare uncertainty/provenance Felder (Contract existiert, komplexe Status fehlen)
- [~] 5. `agent_query_session.json` (CLI nutzt v1-Artefakt; API liefert v2-Inline-Session und speichert sie als Runtime-Artefakt; Provenienz-Härtung belegt; offen: Agent-Orchestrierung, UI-Nutzung, Lifecycle/Retention)
- [~] 6. service-/MCP-fähige Schnittstellenlogik (API Servicepfade existieren, MCP Protokoll fehlt)
- [~] 7. Agent-Guardrails (teilweise: Guardrail-Heuristik "low result coverage" belegt, Härtung offen)

### 2.13 Gate für Phase 6
- [ ] Phase 6 ist fertig, wenn:
* Agenten RepoGround formal statt improvisiert ansprechen
* provenance und uncertainty maschinenlesbar mitlaufen
* Output-Profile stabil sind
* Sessions/Traces nachvollziehbar sind
* RepoGround Retrieval bleibt und nicht heimlich zum Bauchredner des Agenten wird

---

## 3. Empfohlene PR-Schnitte

Mittlere, semantisch saubere PR-Schnitte:

- [ ] **PR 1 – Graph Runtime Contract** (Graph-Doku, Loader, Explain/Score-Konsistenz, graph-aware Eval)
- [ ] **PR 2 – Query Trace + Context Bundle** (query_trace, query_context_bundle, Hit/Evidence/Context-Trennung, Output-Profile intern)
- [ ] **PR 3 – Federation Foundation** (federation_index, Identity-Regeln, Cross-Repo-Links, Konfliktartefakte)
- [ ] **PR 4 – Federated Query** (föderierte Query, föderiertes Ranking, federation trace, Cross-Repo-Context)
- [ ] **PR 5 – Agent Control Surface** (Agent Query Contract, API surface, Agent Session Trace, Guardrails)
- [ ] **PR 6 – UI / Service Produktisierung** (WebUI-Anschluss, Diagnostics/Oberflächen, Download-/Preview-Flows, Endpunkt-Härtung)

---

## Phase 7 – UI / Service / Produktisierung

*(Architektonischer Ausbaupfad – nicht als bereits implementiert zu lesen. Bedarf separater Contract-/Implementierungs-PRs.)*

Ziel:

Die vorhandene Infrastruktur wird benutzbar, ohne die Architektur zu verwässern.

Arbeitspakete:
- [ ] **7.1 WebUI-Konsolidierung:** Bundle-Navigation, Trace-Ansicht, Explain-Ansicht, Artifact-Explorer.
- [ ] **7.2 Diagnostic Views:** graph health, federation conflicts, bundle provenance, query trace.
- [~] **7.3 Service-Endpunkte:**
  logisch vorgesehen: `/query`, `/context`, `/trace`, `/artifact`, `/federation/query`, `/diagnostics`.
  repo-belegt vorhanden: `/api/query`, `/api/federation/query`, `/api/artifact_lookup`, `/api/trace_lookup`, `/api/context_lookup`, `/api/diagnostics`.
- [ ] **7.4 Download-/Inspection-Flows:** bundle parts, traces, context bundles, diagnostics.

Deliverables:
- [ ] UI für Retrieval + Diagnose
- [ ] stabile Service-Endpunkte
- [ ] Download-/Trace-Workflows

Gate:
- [ ] Phase 7 ist fertig, wenn RepoGround nicht nur korrekt, sondern auch operativ nutzbar ist.

---

## Phase 8 – Semantische Erweiterung

*(Architektonischer Ausbaupfad – nicht als bereits implementiert zu lesen. Bedarf separater Contract-/Implementierungs-PRs.)*

Ziel:

Semantik wird erst auf eine bereits stabile, tracebare Architektur aufgesetzt.

Arbeitspakete:
- [ ] **8.1 Semantischer Reranker produktionsreif:** echtes Modell, deterministische Policy, Fallback-Regeln.
- [ ] **8.2 Symbolische Auflösung:** bessere Symbol-Identitäten, Referenzketten, Cross-Repo-Symbolbezüge.
- [ ] **8.3 Semantik + Graph kombiniert:** relation-aware rerank, architecture-aware expansion.
- [ ] **8.4 Eval-Härtung:** baseline vs semantic, graph vs non-graph, federated vs local.

Deliverables:
- [ ] echter semantischer Rerank
- [ ] kombinierte Graph-/Semantikpfade
- [ ] belastbare Eval-Metriken

Gate:
- [ ] Phase 8 ist fertig, wenn Semantik die Architektur verbessert und nicht nur beeindruckender klingt.

---

## Empfohlene PR-Reihenfolge (Gesamt)

- [x] PR 1: Contract-/Provenance-Härtung
- [ ] PR 2: Query Trace + Context Bundle (im Re-Audit strukturell belegt, E2E noch offen)
- [ ] PR 3: Graph Runtime Konsolidierung (teilweise gehärtet: Diagnostik E2E belegt, Recovery/Policy noch offen)
- [x] PR 4: Federation Foundation (Init + Contract + minimale Federation-Verwaltung/CLI)
- [ ] PR 5: Federated Query + Ranking (angerissen: minimale föderierte Query-Aggregation vorhanden)
- [ ] PR 6: Agent Control Surface
- [ ] PR 7: UI / Service Konsolidierung
- [ ] PR 8: Semantische Erweiterung

---

## Priorisierung & Phasenabhängigkeiten

| Phase | Braucht zwingend | Profitiert von | Darf nicht vorziehen |
| :--- | :--- | :--- | :--- |
| **Phase 1** | - | - | - |
| **Phase 2** | Phase 1 | - | - |
| **Phase 3** | Phase 1 | Phase 2 | Phase 4 |
| **Phase 4** | Phase 1, 2, 3 | - | Phase 5 |
| **Phase 5** | Phase 1, 2, 3, 4 | Phase 3 | Phase 6 |
| **Phase 6** | Phase 1, 2, 3, 4, 5 | Phase 3 | Phase 7 |
| **Phase 7** | Phase 2, 4 | Phase 3, 6 | Phase 8 |
| **Phase 8** | Phase 2, 3 | Phase 4, 5 | (Endstufe) |

---

## Nicht-Ziele der nächsten Etappen

- kein vorschneller globaler Knowledge-Graph
- keine freie Agenten-Orchestrierung ohne Verträge
- keine UI-getriebene Architektur
- keine semantische Magie ohne Evaluationsdisziplin

---

## Risiken

Technisch:
- Contract-Fragmentierung
- Bundle-/Federation-Drift
- Score-Scheingenauigkeit

Semantisch:
- implizite Identitäten
- stille Konfliktglättung
- vermischte Provenance

Organisatorisch:
- zu große PRs
- zu viel Parallelentwicklung
- UI zieht Kernarchitektur in falsche Richtung

Schutzmaßnahmen:
- contracts first
- provenance first
- conflict explicit
- diagnostics built-in
- bounded interfaces

---

## Messbare Meilensteine

- [x] M1: Alle Kernartefakte contract-validiert und provenance-klar
- [ ] M2: Query Trace + Context Bundle vorhanden (im aktuellen Audit strukturell belegt, Gate bleibt offen)
- [ ] M3: Graph-Runtime diagnostizierbar (teilweise gehärtet; Gate bleibt wegen unklarer Recovery-Policy offen)
- [ ] M4: Bundles föderierbar
- [ ] M5: Föderierte Queries stabil
- [ ] M6: Agent Control Surface nutzbar
  - [x] `agent_query_session` Provenienz-Härtung + `/api/artifact_lookup`-Roundtrip
  - [x] Runtime-Artefakt-Lifecycle Metadata v1: `lifecycle_status: "active"`, `expires_at: null` — Vorarbeit für Retention/MCP/Agent-Orchestrierung. Noch kein GC, kein TTL, keine automatische Löschung.
- [ ] M7: UI/Service konsolidiert
- [ ] M8: Semantischer Layer produktionsreif

---

## Essenz

Die Roadmap lautet nicht:

mehr Features, mehr UI, mehr KI

sondern:

mehr Belegbarkeit, mehr Struktur, mehr kontrollierte Anschlussfähigkeit

RepoGround sollte zuerst zum verlässlichen Wissensorgan werden und erst danach zur schöneren Oberfläche oder schlaueren Suchmaschine.

*Der trockene Witz der Architektur lautet: Ein unreifes System will Antworten geben. Ein reifes System kann erklären, warum diese Antwort dort überhaupt wohnen darf.*
