# Lenskit Agent Operationalization Roadmap

Stand: 2026-06-29

## Zweck

Diese Roadmap pflegt den aktuellen Agent-, Lens-, Graph- und Retrieval-Plan als Planartefakt ins Repo ein. Sie ersetzt keine bestehenden Contracts, Producer, Validatoren oder Proofs. Sie ordnet die offenen Arbeiten danach, was bereits gebaut ist und was noch angeschlossen werden muss.

Leitentscheidung: Lenskit bleibt ein deterministischer Linsenapparat fuer LLMs und Coding Agents. Der Kern erzeugt keine Review-Urteile, keine Patches, keine Commits, keine Embeddings und kein LLM-Reranking. `canonical_md` bleibt einzige Inhaltswahrheit; Sidecars bleiben Navigation, Diagnose, Evidence-Index oder Cache.

## These / Antithese / Synthese

These: Der alte Komplettplan war als Ordnungssystem sinnvoll: erst Leseregeln, dann Nachweis, dann Diagnose, dann Cards, Relations, Graph und Retrieval.

Antithese: Als aktueller Umsetzungsplan ist er teilweise ueberholt. Mehrere Punkte, die dort noch als P0/P1/P2 erschienen, sind inzwischen als Core-, Contract-, Test- oder Diagnose-Slices vorhanden. Ein weiterer Contract ohne Emission, Manifest-Registrierung oder Consumer-Anschluss wuerde Scheinnutzen erzeugen.

Synthese: Die neue Sinnachse lautet nicht mehr: "Welche Artefakte bauen?" Sondern: "Welche vorhandenen Artefakte werden emittiert, im Manifest sichtbar, von Agenten gefunden, von Consumer-Code genutzt und erst danach eventuell zum Default erhoben?"

## Statusreklassifikation

Nicht mehr als neue Grundaufgaben behandeln:

- Agent Reading Pack v1.1 Front Door.
- Required Reading, Answer Compliance, Agent Consumption Trace und Agent Consumption CLI.
- Deterministic Lens Model Docs.
- Facet Model v1.
- Lens Cards v1 Core und Validation.
- PR Delta Cards v1 Core und Validation.
- Review Retrieval Goldset, Baseline und Miss Diagnostics.
- Review-Intent Router v1 opt-in und Hardening.
- Relation Cards v1 imports-only.
- Graph Current-State Audit.
- Graph stale baseline fallback.
- Graph provenance-coherent compilation.
- Bundle-bound graph source production.
- Graph quality goldset and source-roots contract.

Offen ist vor allem Operationalisierung:

- saubere Repo-/Worktree-Drift-Kontrolle vor Umsetzung,
- automatische oder optionale Emission,
- Bundle-Manifest-Registrierung,
- Agent Reading Pack v2 als Index,
- Export-Safety-Wiring,
- Consumer-/CLI-Frontdoors,
- Range-/Citation-Audit fuer Query-Ergebnisse,
- Graph-Source-Roots-Reconciliation nach G4c-2,
- Guard-Relation-Goldset vor Persistenz,
- Retrieval-v2-Promotion nur nach Messung.

## Gate 0 - Repo-Hygiene und Drift-Bereinigung

Ziel: Feature- oder Planarbeit erfolgt auf aktuellem `origin/main`; lokale Altzustaende werden nicht als Repo-Wahrheit behandelt.

Aufgaben:

1. Hauptcheckout-Status dokumentieren.
2. Untracked Runtime-Artefakte, Core-Dumps oder Crash-Dateien klassifizieren.
3. Feature-Arbeit in sauberem Worktree von `origin/main` ausfuehren.
4. Nach Merge-/Fetch-Drift fokussierte Testsets ausfuehren.
5. Frischen Dump gegen den Planstand abgleichen.

Nichtziele: kein Loeschen unklassifizierter lokaler Artefakte, keine Feature-Arbeit im schmutzigen Hauptcheckout, kein Trust in alte Merge-Dumps ohne Drift-Hinweis.

## P0 - Operationalisierung vorhandener Agent-Surfaces

### TASK-AGENT-ENTRY-MANIFEST-001 - Agent Entry Manifest Emission

Status: umgesetzt. Der Slice ist als CLI- und Bundle-Emission verdrahtet; die Agent Entry Manifest bleibt navigation_index/derived und self-excluding gegen zirkulaere Hash-Claims.

Ziel: Eine kleine, maschinenlesbare Front Door fuer Agenten schaffen, die vorhandene Agent-, Reading-, Trace-, Export- und Card-Surfaces auffindbar macht.

Erlaubt: CLI `agent-entry manifest`, optionales Bundle-Artefakt, Manifest-Rolle `navigation_index`, Verweise auf vorhandene Contracts und Reports.

Nicht erlaubt: Wahrheitsgate, Antwort-Scoring, Review-Urteil, Consumer-Zwang.

Akzeptanz: stdout und `--out` funktionieren; Manifest-Registrierung ist deterministisch; fehlende empfohlene Artefakte werden diagnostisch markiert; `does_not_establish` ist vollstaendig.

### TASK-AGENT-READING-PACK-V2-INDEX-001 - Agent Reading Pack v2 Indexes

Status: umgesetzt. Das Reading Pack indexiert Agent Entry, Consumption Contracts, Export Safety, Cards, Relations, Graph und Retrieval als Navigation ohne Review-/Truth-Claims.

Ziel: Das Agent Reading Pack indexiert vorhandene Agent-, Card-, Relation-, Export-, Graph- und Retrieval-Artefakte, ohne sie inhaltlich zu ersetzen.

Neue Abschnitte: `AGENT_ENTRY_MANIFEST`, `AGENT_CONSUMPTION_CONTRACTS`, `EXPORT_SAFETY_REPORT`, `LENS_CARD_INDEX`, `PR_DELTA_CARD_INDEX`, `RELATION_CARD_INDEX`, `GRAPH_DIAGNOSTICS`, `RETRIEVAL_DIAGNOSTICS`, `WHAT_THIS_DOES_NOT_PROVE`.

Nicht erlaubt: freie Review-Zusammenfassung, Fix-Empfehlung, Impact-Sprache, Aussagen wie "sicher", "kritisch", "vollstaendig", "Tests reichen".

### TASK-EXPORT-SAFETY-WIRING-001 - Export Safety Report Wiring

Status: umgesetzt. Export Safety ist als CLI, Required-Reading-Profil, Agent-Entry-Link und Reading-Pack-Hinweis sichtbar; bleibt diagnostisch und beweist keine Secret-/PII-Abwesenheit.

Ziel: Der vorhandene Export-Safety-Report wird fuer Agenten und Bundle-Consumer sichtbar.

Aufgaben: Export Safety Report im Agent Entry Manifest referenzieren; Export-Profil und Redaction-Status im Agent Reading Pack sichtbar machen; `security_export_review` als Profil mit Export-Safety-Anforderung verdrahten; optionalen CLI-Check fuer Report/Profilstatus ergaenzen.

Nichtziele: kein globaler Dump-Fail nur wegen lokalem Privatprofil, kein externer Secretlint-Zwang, keine PII-Heuristik mit Scheinsicherheit.

### TASK-CARD-BUNDLE-EMISSION-001 - Card Bundle Emission

Ziel: Vorhandene Lens Cards, PR Delta Cards und imports-only Relation Cards werden optional im Bundle sichtbar.

Aufgaben: `lens_cards.jsonl` optional emittieren; `pr_delta_cards.jsonl` nur bei vorhandenem Delta-Kontext emittieren; `relation_cards.jsonl` nur bei frischer Graph-Quelle emittieren; Bundle Manifest Rollen ergaenzen; Surface Validation fuer Card-Artefakte additiv pruefen.

Nichtziele: keine neuen Relationstypen, keine Retrieval-Nutzung, keine Review-Findings, keine Impact-Sprache.

## P1 - Consumer-sichtbare Diagnose

### TASK-AGENT-CONSUMPTION-PREFLIGHT-001 - Agent Consumption Preflight

Status: umgesetzt. `agent-consumption preflight` loest Required Reading auf, kann Rollen aus einem Bundle Manifest ableiten, erzeugt eine Answer-Compliance-Vorlage und validiert optional vorhandene Answer Compliance.

Ziel: Required Reading, Consumption Trace und Export-/Card-Surfaces in einem praktischen Vorpruefbefehl zusammenziehen.

Umgesetzt: CLI `agent-consumption preflight --task-profile ...`; required/recommended-Artefakte gegen explizite Rollen oder Bundle Manifest pruefen; Answer-Compliance-Vorlage erzeugen; optional vorhandene Answer Compliance validieren; negative Semantik und Exit-Codes analog zu bestehenden Trace-Validierungen.

Nichtziel: Kein echter Lesebeweis. Ein Agent kann eine Trace falsch ausfuellen; der Contract macht die Abweichung nur maschinenlesbar.

### TASK-REVIEW-INTENT-CLI-001 - Review-Intent Router CLI

Ziel: Der vorhandene Review-Intent Router wird als opt-in CLI-Oberflaeche nutzbar, ohne Default-Promotion.

Aufgaben: CLI-Flag oder separater Command fuer Review-Intent Query; Ausgabe von Intent, Lane-Plan, Exclusions, Treffern, Fallbacks und Miss-Klassen; Default-Query bleibt unveraendert.

Promotion-Gate: keine zentrale Query-Klasse regressiert; expected-target recall besser oder gleich; Fehler-/Fallback-Zaehlung ehrlich; stale Graph Index beeinflusst Ranking nicht.

### TASK-QUERY-RANGE-REF-AUDIT-001 - Query Range-Ref Audit

Ziel: Vor einem neuen Proof-Carrying-Query-Contract pruefen, welche Query-Treffer bereits aufloesbare Range-Refs tragen.

Aufgaben: Query-Result-Schema und Runtime-Ausgabe gegen Range-Ref-Faehigkeit auditieren; Roundtrip gegen `canonical_md` pruefen; Citation-Map-Kompatibilitaet pruefen; nur bei belegter Luecke minimalen Adapter planen.

Nichtziele: kein grosser neuer Query-Contract ohne Gap-Beweis, kein Graph-/Symbol-Boost in diesem Slice.

## P2 - Graph und Relations kontrolliert weiterfuehren

### TASK-GRAPH-SOURCE-ROOTS-RECONCILE-001 - Graph Source Roots Consumer Reconciliation

Ziel: Nach G4c-2 wird verifiziert, dass der Source-Roots-Consumer sauber in Graph Producer, CLI, Bundle, Degradation und Tests verdrahtet ist.

Pruefen: Contract vorhanden; Producer konsumiert Source Roots; CLI konsumiert Source Roots; Bundlepfad konsumiert Source Roots; Pythonista/jsonschema-Degradation bleibt maschinenlesbar; Graph-Quality-Baseline stimmt mit neuer Messbedingung ueberein.

Nichtziele: kein Ranking-Default, keine Graph-Vollstaendigkeitsbehauptung, keine Runtime-Kausalitaet.

### TASK-GUARD-RELATION-GOLDSET-001 - Guard Relation Goldset before persistence

Ziel: Persistierte Guard Relation Cards werden nicht gebaut, bevor tests_by_name und validates_schema ueber ein Goldset gegen False Positives gemessen sind.

Aufgaben: Goldset fuer `tests_by_name` und `validates_schema`; Messung von Praezision, False Positives und unaufloesbaren Kandidaten; Entscheidung: persistierter Contract ja/nein; negative Semantik fuer Testsuffizienz und Runtime-Korrektheit erzwingen.

Nichtziele: keine sofortige Persistenz, kein Testvollstaendigkeitsclaim, kein Review-Impact.

## P3 - Retrieval v2 nur als Promotion-Frage

### TASK-RETRIEVAL-V2-PROMOTION-GATE-001 - Retrieval v2 Promotion Gate

Ziel: Retrieval v2 wird nicht als Wunschfeature gebaut, sondern als messbare Promotion-Frage behandelt.

Vergleichen: legacy FTS; Review-Intent opt-in; Review-Intent plus frischer Graph, falls vorhanden.

Metriken: Recall@5/10, MRR@10, expected-target recall, per-category regressions, fallback/error counts, miss taxonomy.

Default-Promotion nur wenn: besser als Baseline; keine zentrale Kategorie schlechter; Diagnose besser; kein stale Graph Einfluss; Range/Citation Health bleibt gruen.

## P4 - Backlog

Bewusst spaeter: Symbol Index v1, Token Budget Report, Compat Export Projection, Read-only Adapter ohne Mirror.

Diese Backlog-Punkte duerfen keine neuen Wahrheits-, Review-, Patch- oder Runtime-Claims einfuehren.

## Globale Negativsemantik

Jedes neue Artefakt aus dieser Roadmap muss maschinenlesbar sagen, was es nicht beweist:

```json
{
  "does_not_establish": [
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence"
  ]
}
```

Diagnostische Artefakte muessen zusaetzlich vermeiden, als Repo-Verstaendnis oder Forensikfreigabe gelesen zu werden:

```json
{
  "does_not_establish": [
    "repo_understood",
    "claims_true",
    "answer_safe_without_citations",
    "forensic_ready"
  ]
}
```

## Nichtziele

Nicht Teil dieser Roadmap: neue Primary Lens IDs, LLM-Integration, Embeddings, semantisches Reranking im Kern, automatische Review-Findings, Patch-Automation, automatische Commits oder PRs, Mirror-Betrieb, serverseitige Worktrees, freie Template-Engine.

## Risiko- und Nutzenabschaetzung

Nutzen: Agenten finden vorhandene Artefakte zuverlaessiger; Sidecars bleiben Navigation statt Wahrheitsersatz; Exportprofile werden weniger missverstaendlich; Retrieval-Verbesserungen werden messbar statt gefuehlt; Graph-Arbeit wird nicht zur Kausalitaetsbehauptung aufgeblasen.

Risiken: lokale Drift kann Planarbeit auf falschem Stand erzeugen; Cards koennen psychologisch als Review-Verstaendnis fehlgedeutet werden; zu viele Emissionen koennen fragile CI erzeugen; Export-Safety kann staerker klingen, als es ist; Contracts koennen existieren, ohne dass Agenten sie tatsaechlich nutzen.

Gegenmassnahme: Jeder Slice bleibt klein, deterministisch, messbar und negativsemantisch begrenzt.

## Essenz

Hebel: Vorhandene Artefakte emittieren, registrieren, auffindbar machen und erst nach Messung konsumieren.

Entscheidung: Nicht noch mehr Grundcontracts bauen; zuerst Agent Entry Manifest, Reading-Pack-v2-Index, Export-Safety-Wiring und Card-Bundle-Emission.

Naechste Aktion: `TASK-AGENT-ENTRY-MANIFEST-001` als ersten Umsetzungsslice starten, nachdem ein sauberer Worktree auf aktuellem `origin/main` bestaetigt ist.
