# C2a — Authority / Inference Boundary Contract Gap Audit

**Status:** Audit / Proof (docs-only). Kein Runtime-PR, kein Contract-PR.
**Datum:** 2026-05-24
**Beziehung zu C1:** baut auf `docs/blueprints/lenskit-authority-risk-matrix.md` auf.

Pflichtlektüre (vor dieser Datei gelesen):
- `docs/blueprints/lenskit-authority-risk-matrix.md` (C1)
- `docs/roadmap/lenskit-master-roadmap.md`
- `docs/architecture/artifact-inventory.md`
- `docs/architecture/artifact-evidence-levels.md`
- `docs/proofs/retrieval-miss-taxonomy-proof.md`
- `docs/proofs/context-quality-signals-proof.md`
- `docs/proofs/post-emit-health-implementation-proof.md`
- `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`
- alle JSON-Schemas unter `merger/lenskit/contracts/`

---

## 1. Scope

Dieses Dokument ist ein **docs-only Audit**. Es prüft, welche bestehenden Contracts
unter `merger/lenskit/contracts/` bereits zur C1-Matrix passen, welche teilweise passen
und wo eine spätere C2-Migration (Contract-Normierung) riskant wäre.

Ausdrücklich gilt:
- **Keine Contract-Änderung** in dieser PR.
- **Keine Runtime-Änderung**, keine CLI-, Test- oder Dependency-Änderung.
- **Keine neuen Schemas**, keine Manifest-Verhaltensänderung.
- **Keine Lint-Implementierung**, keine Export-Gate-Implementierung.
- `allowed_inference` / `forbidden_inference` werden hier **nicht** in echte Contracts
  eingebaut. Sie werden nur als spätere Möglichkeit bewertet.
- C2a prüft ausschließlich die **C1-Kompatibilität** bestehender Contracts und bereitet
  C2 vor, ohne C2 zu implementieren.

**Begriffsnotiz zur Track-Nummerierung.** „C2" bezeichnet in diesem Dokument den
Governance-Track-Schritt aus `docs/roadmap/lenskit-master-roadmap.md` („C2: Contract-Normierung
— allowed/forbidden inferences als Schema-Felder"). Das ist nicht zu verwechseln mit dem
gleichlautenden „PR C2 — Anti-Hallucination Lint" aus
`docs/blueprints/lenskit-anti-hallucination-output-architecture.md` §3 (Milestone C). C2a ist
das Vor-Audit für die Contract-Normierung, nicht für die Lint-Stufe.

C2a definiert **keine** C1-Begriffe um und verändert **keine** der bestehenden
B1/B2/A4/A5-Invarianten. Bestehende rollenspezifische Disclaimer-Sets bleiben unangetastet.

---

## 2. Methodik

### Geprüfte Dateien

Alle `*.schema.json` unter `merger/lenskit/contracts/` wurden erfasst. Der Schwerpunkt liegt
auf den manifest-, diagnose- und runtime-tragenden Contracts; reine Atlas-/PR-Schau-/
Repolens-Report-Schemas werden gesammelt als „außerhalb des C1-Kerngeltungsbereichs"
behandelt (eigene Bundles / eigene Tracks), aber in §5 nicht ignoriert.

### Gesuchte Felder

Pro Contract wurde geprüft, ob folgende Konzepte als **maschinenlesbares Feld** vorhanden sind:

- `authority` (oder rollen-spezifisches Äquivalent wie `session_authority`)
- `canonicality`
- `risk_class`
- `does_not_prove`
- `does_not_mean`
- `claim_boundaries`
- implizite allowed/forbidden-inference-Semantik (z.B. `context_risk`,
  `claims_resolve_to`, `confidence: inferred`, `resolution: unresolved`, `must_resolve_to`)

Belegbasis der Feldbefunde: lexikalische Erfassung über alle Contracts plus Volltext-Lesung der
in §3 gelisteten Kern-Contracts.

### Bewertungskategorien

| Kategorie | Bedeutung |
| :--- | :--- |
| `aligned` | Contract trägt bereits maschinenlesbare Authority-/Boundary-Felder, die C1 entsprechen. |
| `partially_aligned` | Einige C1-Konzepte vorhanden, andere fehlen oder sind nur als Prosa deklariert. |
| `missing_boundary` | Kein maschinenlesbares Inferenzgrenzen-Feld; höchstens Description-Prosa. |
| `migration_candidate` | Geeignet für spätere additive C2-Ergänzung mit geringem Risiko. |
| `unsafe_to_migrate_without_consumer_changes` | Neue Pflichtfelder/Felder würden bestehende Consumer oder Altbundles brechen. |
| `should_remain_unchanged` | Soll vorerst nicht angefasst werden (instabile Semantik, unklare Consumer, oder Boundary-Feld würde falsche Authority vortäuschen). |

Mehrfachzuordnung ist erlaubt (z.B. `partially_aligned` + `migration_candidate`).

---

## 3. Contract Inventory Table

`bd-man` = manifest-deklarierte Authority/Canonicality (in `bundle-manifest.v1` per Rolle
gesetzt); `self` = im Contract selbst deklariert; `–` = nicht vorhanden.

| contract file | artifact / payload role | current authority | current canonicality | current risk_class | boundary fields present | C1 alignment | migration risk | notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bundle-manifest.v1.schema.json` | Bundle registry (root of navigation) | `self` per-role const (6-Werte-Enum, optional) | `self` per-role const (6-Werte-Enum, optional) | – | per-role `authority`/`canonicality`; keine `does_not_prove` | partially_aligned | medium | Zentrale Registry. Authority/Canonicality optional (Backcompat). Enum deckt **nicht** C1-Neuklassen (`external_unverified`, `derived_projection`, `agent_generated`) — laut C1 korrekt, da diese neu/konzeptionell sind. Rolle `output_health` hat **keinen** per-role authority-`allOf`-Zweig. |
| `retrieval-eval.v1.schema.json` | `retrieval_eval_json` (diagnostic) | bd-man `diagnostic_signal`; `self` const in `miss_taxonomy` | bd-man `diagnostic` | `self` const `diagnostic` in `miss_taxonomy` | top-level `claim_boundaries` (required: proves/does_not_prove/evidence_basis/requires_live_check); `miss_taxonomy.does_not_prove` (5 Pflichteinträge) | aligned | low | Stärkster Diagnose-Contract. Top-level-Objekt selbst trägt kein `authority`-Feld (nur im `miss_taxonomy`-Block). |
| `context-quality.v1.schema.json` | `context_quality` (diagnostic projection, unregistriert) | `self` const `diagnostic_signal` | – (kein Feld) | `self` const `diagnostic` | `does_not_mean` (4 Pflicht), `agent_use_constraints` (5 Pflicht) | aligned | low | Projektion; `does_not_mean`+`agent_use_constraints` sind funktional die forbidden-inference-Schicht. Kein `canonicality`-Feld (für diagnostic projection angemessen). |
| `post-emit-health.v1.schema.json` | `post_emit_health` (diagnostic, unregistriert) | – (kein Feld) | – | – | `does_not_mean` (2 Pflicht), `independence_note` | partially_aligned | low | Trägt Disclaimer, deklariert aber seine Authority/Risk-Class nicht selbst. Wird von `context_quality` nur als Beobachtung projiziert. |
| `agent-query-session.v2.schema.json` | `agent_query_session` (runtime observation) | `self` `session_authority` const `agent_context_projection` | – | – | `claim_boundaries` (required: proves/does_not_prove) | partially_aligned | medium | Spezialisierte Authority via `session_authority`. C1-Mapping: `authority: runtime_observation` + `agent_context_projection`. Generisches `authority`-Feld würde mit `session_authority` konkurrieren. |
| `query-context-bundle.v1.schema.json` | `context_bundle` (runtime payload) | – (bd-man Phase 4 offen) | – | – | `context_risk` (optional, in allen neuen Bundles): `does_not_prove`, `claims_resolve_to`, `may_answer_from_this_directly:false`, `retrieval_based_subset` | partially_aligned | medium | `context_risk` (B3) ist die starke Boundary-Schicht. Optional für Backcompat. Top-level Authority/Canonicality fehlen (Inventory: Phase 4 offen). |
| `agent-query-session.v1.schema.json` | legacy session | – | – | – | – | missing_boundary | – | Legacy; v2 ist kanonisch. should_remain_unchanged. |
| `artifact-lookup.v1.schema.json` | runtime artifact lookup facade | `self` const `runtime_observation` | `self` const `observation` | – | `claim_boundaries.does_not_prove` (required), `artifact_shape`, lifecycle-Felder | aligned | low | Voll C1-konform für Runtime-Beobachtung. Nur `risk_class`-Feld fehlt (C1-Mapping: `observation`). |
| `trace-lookup.v1.schema.json` | `query_trace` lookup facade | `self` const `runtime_observation` | `self` const `observation` | – | `claim_boundaries.does_not_prove` (required bei status ok) | aligned | low | Wie artifact-lookup; `risk_class` als einziges optionales Add. |
| `context-lookup.v1.schema.json` | `context_bundle` lookup facade | `self` const `runtime_observation` | `self` const `observation` | – | `claim_boundaries.does_not_prove` (required bei status ok) | aligned | low | Wie trace-lookup. |
| `query-result.v1.schema.json` | query result envelope | – (top-level) | – | – | `claim_boundaries.does_not_prove` | partially_aligned | low | Wrapper für `query-context-bundle`; trägt eigene `claim_boundaries`. |
| `output-health.v1.schema.json` | `output_health` / pre_emit_health (diagnostic) | bd-man-Rolle gelistet, aber **kein** per-role-const-Zweig; kein `self`-Feld | – | – | `verdict` (pass/warn/fail); keine `does_not_*` | partially_aligned + unsafe_to_migrate_without_consumer_changes | high | Ältester Diagnose-Contract. `verdict==pass` wird von Parity-Gates und Projektoren konsumiert; Naming-Migration `output_health → pre_emit_health` läuft noch (siehe artifact-evidence-levels.md). |
| `agent-export-gate.v1.schema.json` | `agent_export_gate` (gate result, unregistriert) | – (kein Feld) | – | – | `does_not_mean` (3 Pflicht: repo_understood, answer_safe_without_citations, claims_true) | partially_aligned | low | Gate-Ergebnis; trägt Disclaimer, deklariert keine eigene Authority/Risk-Class. |
| `cross-repo-links.v1.schema.json` | `cross_repo_links` (federation, heuristisch) | – | – | – | `confidence` const `inferred`, `link_type` const `co_occurrence`; starke Description-Prosa | missing_boundary | medium | C1-Mapping: `external_unverified` (`confidence: inferred`). Boundary nur als Prosa. Producer heuristisch/minimal. |
| `federation-conflicts.v1.schema.json` | `federation_conflicts` (federation, heuristisch) | – | – | – | `resolution` const `unresolved` | missing_boundary | medium | „Conflicts surfaced but never resolved automatically" ist boundary-artig. Producer heuristisch/minimal. |
| `federation-trace.v1.schema.json` | `federation_trace` (runtime/diagnostic) | – | – | – | – (Description: „Diagnostic execution trace") | missing_boundary | medium | Runtime-Beobachtung ohne maschinenlesbare Boundary. |
| `federation-index.v1.schema.json` | `federation_index` (navigation) | – | – | – | – | missing_boundary | medium | Navigations-/Index-Artefakt; keine Boundary-Felder. |
| `citation-map.v1.schema.json` | `citation_map_jsonl` (navigation_index) | bd-man `navigation_index` / `derived` (im Manifest erzwungen) | bd-man `derived` | – | keine im Contract selbst | partially_aligned | low | Authority/Canonicality werden im **Manifest** erzwungen (`citation_map_jsonl`-Zweig). Navigation hat noch kein `must_resolve`-Feld im Contract. |
| atlas-*, pr-schau*, repolens-*, sync.report, embedding-policy, entrypoints, range-ref.v1/v2, architecture.graph* | diverse (eigene Tracks / Hilfsartefakte) | – | – | – | – | missing_boundary / out_of_scope | n/a | Eigene Bundles (Atlas, PR-Schau) bzw. Zwischenartefakte. Nicht primärer C1-Kerngeltungsbereich; nur als Vollständigkeitsnotiz erfasst. |

---

## 4. Boundary Field Audit

C1 fordert ausdrücklich **kein** identisches Disclaimer-Set für alle Artefakte (siehe C1 §3.2
„C1 fordert nicht ein identisches Disclaimer-Set"). Bestehende spezialisierte B1/B2/A4/A5-Grenzen
dürfen **nicht** umgedeutet werden. Die folgende Bewertung respektiert das.

### `does_not_prove`
- **Vorkommen:** `retrieval-eval.v1` (top-level `claim_boundaries` + `miss_taxonomy`),
  `agent-query-session.v2`, `query-context-bundle.v1` (`context_risk`),
  `artifact-lookup.v1`, `trace-lookup.v1`, `context-lookup.v1`, `query-result.v1`.
- **Required vs. optional:** in `retrieval-eval` (claim_boundaries) und den Runtime-Lookups
  **required**; in `miss_taxonomy` mit 5 erzwungenen Konstanten; in `query-context-bundle`
  innerhalb des optionalen `context_risk`-Blocks (dort aber required).
- **Rollenspezifisch oder global:** durchgängig **rollenspezifisch** — jede Rolle deklariert
  ihre eigenen Sätze. Das ist C1-konform (kein erzwungenes globales Set).
- **Maschinenlesbarkeit:** hoch (Arrays, teils mit `contains`-Konstanten erzwungen).
- **C1-Passung:** stark. `does_not_prove` ist genau das von C1 als „Artefakt-lokales
  Disclaimer-Instrument" beschriebene Konzept.
- **C2-Empfehlung:** unangetastet lassen; später optional gegen eine Klassen-Norm
  (`forbidden_inference` pro Rolle) **validieren**, nicht ersetzen.

### `does_not_mean`
- **Vorkommen:** `context-quality.v1` (4 Pflicht), `post-emit-health.v1` (2 Pflicht),
  `agent-export-gate.v1` (3 Pflicht).
- **Required:** ja, jeweils mit `contains`-Konstanten erzwungen.
- **Rollenspezifisch:** ja. C1-konform.
- **Maschinenlesbar:** hoch.
- **C1-Passung:** stark; entspricht der Diagnostik-Klasse („warnt, beweist nicht").
- **C2-Empfehlung:** unangetastet lassen.

### `claim_boundaries`
- **Vorkommen:** `agent-query-session.v2` (proves/does_not_prove),
  `retrieval-eval.v1` (proves/does_not_prove/evidence_basis/requires_live_check),
  `query-result.v1`, Runtime-Lookups (`does_not_prove`-Teilmenge).
- **Required:** ja (in den genannten Contracts).
- **Rollenspezifisch:** ja, mit unterschiedlicher Tiefe (eval hat zusätzlich `evidence_basis`).
- **C1-Passung:** stark; `requires_live_check` ist sogar reicher als C1 fordert.
- **C2-Empfehlung:** unangetastet lassen; ggf. als Referenzform für andere Runtime-Contracts.

### `authority`
- **Vorkommen als generisches Feld:** `bundle-manifest.v1` (per-role), `artifact-lookup.v1`,
  `trace-lookup.v1`, `context-lookup.v1` (const `runtime_observation`); `context-quality.v1`,
  `retrieval-eval.v1`/`miss_taxonomy` (const `diagnostic_signal`).
- **Spezialform:** `agent-query-session.v2.session_authority` (const `agent_context_projection`).
- **Fehlt bei:** `post-emit-health.v1`, `agent-export-gate.v1`, `output-health.v1`,
  `query-context-bundle.v1` (top-level), den Federation-Contracts.
- **C1-Passung:** die vorhandenen Werte sind mit dem C1-Inventory-Vokabular deckungsgleich.
  Die C1-**Neuklassen** (`external_unverified`, `derived_projection`, `agent_generated`)
  kommen in **keinem** bestehenden Contract vor — laut C1 korrekt, da neu/konzeptionell.
- **C2-Empfehlung:** dort, wo es fehlt und die Rolle stabil ist, später **optional, const**
  ergänzen (z.B. `post_emit_health` → `diagnostic_signal`). Bei `agent-query-session.v2`
  **kein** generisches `authority` neben `session_authority` einführen (Ambiguität).

### `canonicality`
- **Vorkommen:** `bundle-manifest.v1` (per-role), Runtime-Lookups (const `observation`).
- **Fehlt bei:** allen Diagnose-Contracts als Selbstdeklaration (dort über Manifest/Inventory
  abgebildet).
- **C1-Passung:** ausreichend. C1 verlangt Canonicality nicht für jede Diagnose-Selbstdeklaration.
- **C2-Empfehlung:** nur dort ergänzen, wo eine Rolle ihre Canonicality nicht bereits über das
  Manifest erbt. Niedrige Priorität.

### `risk_class`
- **Vorkommen:** **nur** `context-quality.v1` (const `diagnostic`) und
  `retrieval-eval.v1.miss_taxonomy` (const `diagnostic`).
- **Fehlt bei:** allen anderen Contracts.
- **C1-Passung:** C1 normiert ein systemweites Risk-Class-Vokabular (`content`, `navigation`,
  `diagnostic`, `cache`, `observation`, `derived`, `external`). Bisher ist nur `diagnostic`
  punktuell belegt.
- **C2-Empfehlung:** `risk_class` ist der **größte einheitliche Lückenkandidat**. Später
  additiv-optional pro Rolle ableitbar (vgl. anti-hallucination-Blueprint PR C1-Skizze:
  „risk_class aus Authority ableiten"). Nicht in dieser PR.

**Zwischenfazit §4:** Die Disclaimer-Schicht (`does_not_prove`/`does_not_mean`/`claim_boundaries`)
ist bereits breit, rollenspezifisch und maschinenlesbar vorhanden und **soll unangetastet bleiben**.
Die Authority-Schicht ist teilweise vorhanden. Die einzige systemweit fehlende, aber sauber
ableitbare Schicht ist `risk_class`.

---

## 5. Gap Analysis

### A. Missing authority
Contracts ohne explizites Authority-Feld (weder generisch noch spezialisiert):
- `post-emit-health.v1`, `agent-export-gate.v1`, `output-health.v1`
- `query-context-bundle.v1` (top-level; Inventory führt Phase 4 als offen)
- `cross-repo-links.v1`, `federation-conflicts.v1`, `federation-trace.v1`, `federation-index.v1`
- `citation-map.v1` (Authority nur im Manifest erzwungen, nicht im Contract selbst)

### B. Missing canonicality
Contracts ohne Canonicality-Bezug im Contract selbst:
- alle Diagnose-Contracts (`context-quality`, `post-emit-health`, `agent-export-gate`,
  `output-health`, `retrieval-eval`)
- `query-context-bundle.v1`, alle Federation-Contracts
- (Anmerkung: für reine Diagnose-Selbstdeklarationen ist das C1-konform und kein Defekt.)

### C. Missing risk_class
Contracts ohne `risk_class` (= fast alle, außer `context-quality.v1` und `miss_taxonomy`):
- `bundle-manifest.v1`, `post-emit-health.v1`, `agent-export-gate.v1`, `output-health.v1`,
  `agent-query-session.v2`, `query-context-bundle.v1`, alle Runtime-Lookups, alle
  Federation-Contracts, `citation-map.v1`.

### D. Missing inference boundaries
Contracts ohne `does_not_prove`/`does_not_mean`/`claim_boundaries` oder äquivalente
maschinenlesbare Grenze:
- `output-health.v1` (nur `verdict`)
- `federation-trace.v1`, `federation-index.v1`
- `cross-repo-links.v1` / `federation-conflicts.v1` haben nur Const-Felder
  (`confidence: inferred`, `resolution: unresolved`) plus Description-Prosa — partielle,
  aber keine `does_not_*`-Grenze.

### E. Ambiguous terms
Begriffe, die später Truth-/Safety-/Completeness-Inflation erzeugen könnten:
- `output-health.v1.verdict` mit Werten `pass/warn/fail`: `pass` ist der von C1 §1.3
  ausdrücklich genannte Drift-Kandidat („Diagnostik → Wahrheit"). Heute durch Roadmap-Prosa
  und Parity-Gate-Semantik eingegrenzt, aber **nicht** im Contract durch ein `does_not_mean`
  abgesichert.
- `post-emit-health.v1.status` / `agent-export-gate.v1.status` mit `pass`: durch begleitende
  `does_not_mean`-Arrays bereits abgesichert (geringeres Risiko).
- `evidence_level`-Vokabular (`citable`, `forensic_strict` …): wird korrekt aus
  `artifact-evidence-levels.md` wiederverwendet; **kein** neuer Truth-Begriff. Keine Aktion.
- Keine verbotenen Begriffe (`understanding_health`, `agent_safe`, `supported`, `proven`,
  `complete` als Verdict) in den geprüften Contracts gefunden. C1-L5-Verbotsliste ist
  derzeit eingehalten.

### F. Migration hazards
Contracts, bei denen neue **Pflichtfelder** bestehende Consumer/Altbundles brechen würden:
- **`bundle-manifest.v1`:** `authority`/`canonicality` sind bewusst **optional** (Backcompat,
  „alte Bundles brechen nicht"). Ein erzwungenes `risk_class`-Pflichtfeld würde jedes
  Altbundle invalidieren. → nur additiv-optional.
- **`output-health.v1`:** Konsumiert durch `parity_gates.py` (`output_health.verdict==pass`),
  `post_emit_health` (als Beobachtung), `context_quality` (Projektion), `diagnostic_parity_pass`.
  Neue Pflichtfelder würden diese Pfade brechen. Zusätzlich läuft die Naming-Migration
  `output_health → pre_emit_health`. → unsafe ohne Consumer-Koordination.
- **`query-context-bundle.v1`:** `context_risk` ist absichtlich optional (B3 Backcompat).
  Eine Pflicht-Anhebung würde Altbundles und bestehende Consumer (CLI, WebUI, `context_lookup`)
  brechen. → additiv/optional halten.
- **`agent-query-session.v2`:** ein zweites generisches `authority` neben `session_authority`
  erzeugt Doppeldeutigkeit für Consumer (Service-API, `artifact_lookup`, Agents). → nicht
  additiv ergänzen; docs-only Mapping bevorzugen.

---

## 6. C2 Migration Candidates

Keine konkreten Schema-Patches — nur Bewertung. Empfohlene Migrationsart pro Kandidat:
`additive optional field first` | `required after deprecation window` | `docs-only clarification` |
`no migration recommended`.

### 6.1 `post-emit-health.v1`
- **Vorgeschlagene spätere Ergänzung:** optionales `authority` (const `diagnostic_signal`),
  optionales `risk_class` (const `diagnostic`).
- **Warum sinnvoll:** Contract trägt bereits `does_not_mean`, deklariert seine Klasse aber nicht
  selbst; macht spätere Lint-Validierung (C3) trivial.
- **Risiko:** niedrig (unregistriertes Artefakt, wenige Consumer).
- **Betroffene Consumer:** `cli/cmd_bundle_health.py`, `context_quality`-Projektor (liest
  `status_observed`), `agent_export_gate` (liest `post_emit_health_status`).
- **Empfohlene Migrationsart:** additive optional field first.

### 6.2 `agent-export-gate.v1`
- **Ergänzung:** optionales `authority`/`risk_class` (`diagnostic_signal`/`diagnostic`).
- **Warum:** Konsistenz mit den anderen Diagnose-Contracts.
- **Risiko:** niedrig.
- **Consumer:** Export-CLI, `context_quality` (liest `status_observed`).
- **Migrationsart:** additive optional field first.

### 6.3 `retrieval-eval.v1` (top-level)
- **Ergänzung:** optionales top-level `authority`/`risk_class` (zusätzlich zu dem bereits
  vorhandenen `miss_taxonomy`-Block).
- **Warum:** das Wurzelobjekt selbst deklariert seine Klasse noch nicht; Inventory tut es bereits.
- **Risiko:** niedrig (additiv, optional).
- **Consumer:** CI, `context_quality`, Entwickler.
- **Migrationsart:** additive optional field first (oder docs-only, da Manifest die Authority
  bereits trägt).

### 6.4 Runtime-Lookups (`artifact-lookup`, `trace-lookup`, `context-lookup`)
- **Ergänzung:** optionales `risk_class` (const `observation`).
- **Warum:** vervollständigt das C1-Tripel (authority+canonicality+risk_class) für Runtime.
- **Risiko:** niedrig; diese Contracts sind bereits am stärksten C1-konform.
- **Consumer:** Service-API, Agents.
- **Migrationsart:** additive optional field first — oder no migration (geringer Mehrwert,
  da authority+canonicality bereits eindeutig sind).

### 6.5 `bundle-manifest.v1`
- **Ergänzung:** optionales per-role `risk_class`; zusätzlich ein per-role-`authority`-Zweig
  für die Rolle `output_health` (heute ohne `allOf`-Constraint).
- **Warum:** macht die manifest-tragenden Rollen vollständig C1-normiert; schließt die
  `output_health`-Lücke im Manifest.
- **Risiko:** mittel — zentrale Registry, sehr breite Consumer-Basis.
- **Consumer:** praktisch alle (Producer `merge.py`/`AUTHORITY_REGISTRY`, alle Bundle-Leser,
  Parity-Gates, Health, Projektoren).
- **Migrationsart:** additive optional field first; **niemals** als Pflichtfeld in v1
  (würde Altbundles brechen). Pflicht erst in einer **neuen Manifest-Major-Version**.

### 6.6 `cross-repo-links.v1` / `federation-conflicts.v1` / `federation-trace.v1` / `federation-index.v1`
- **Ergänzung (konzeptionell):** `authority` (`external_unverified` bzw. `runtime_observation`),
  `does_not_prove`-Array.
- **Warum:** würde die Prosa-Disclaimer maschinenlesbar machen.
- **Risiko:** mittel bis hoch — die Producer sind ausdrücklich **heuristisch/minimal**
  (`artifact-inventory.md` §4); die Semantik ist noch nicht stabil.
- **Consumer:** Federation-Query-Pfad, CLI-Trace-Persistenz.
- **Migrationsart:** **no migration recommended** bis Federation-Hardening (Roadmap Phase 4)
  abgeschlossen ist. Bis dahin höchstens docs-only clarification.

### 6.7 `query-context-bundle.v1`
- **Ergänzung:** optionales top-level `authority`/`risk_class`.
- **Warum:** `context_risk` deckt Inferenzgrenzen bereits ab; ein Authority-Feld würde die
  Phase-4-Lücke schließen.
- **Risiko:** mittel — Altbundles ohne `context_risk` existieren; Consumer (CLI/WebUI/lookups).
- **Migrationsart:** additive optional field first; `context_risk`-Pflicht erst nach
  Consumer-Audit (`artifact-consumer-matrix.md`).

---

## 7. Contracts That Should Remain Unchanged For Now

Explizit **nicht** anfassen, mit Begründung:

- **`output-health.v1`** — Runtime-Consumer-Kopplung hoch (Parity-Gates, `diagnostic_parity_pass`,
  `context_quality`); zusätzlich offene Naming-Migration `output_health → pre_emit_health`.
  Ein Boundary-/Authority-Eingriff vor Abschluss dieser Migration schadet mehr als er nützt.
- **`agent-query-session.v2`** — Authority ist bereits über `session_authority` (const) und
  `claim_boundaries` korrekt deklariert. Ein zweites generisches `authority`-Feld würde
  Authority **vortäuschen/duplizieren**. Nur docs-only Mapping.
- **`cross-repo-links.v1`, `federation-conflicts.v1`, `federation-trace.v1`,
  `federation-index.v1`** — Semantik nicht stabil (heuristisch/minimal); Federation-Hardening
  ist Roadmap-Phase 4 und steht hinter lokaler Evidence-Address-Stabilisierung. Boundary-Felder
  jetzt würden Reife vortäuschen.
- **`citation-map.v1`** — Authority/Canonicality werden bereits korrekt im Manifest erzwungen.
  Ein zusätzliches `must_resolve`-Feld im Contract gehört in die Navigation-Normierung
  (C1 §3.3 / anti-hallucination Milestone E), nicht in C2a.
- **`agent-query-session.v1`, atlas-*, pr-schau*, repolens-*** — Legacy bzw. eigene Tracks;
  außerhalb des C1-Kerngeltungsbereichs.

---

## 8. Recommended C2 Sequence

Vorschlag für spätere, **separate** PRs. **Keine** dieser Arbeiten ist erledigt; alle bleiben
Folgearbeit.

- **C2.1** — Additive, optionale `authority`+`risk_class` (const) für die **niedrigst-riskanten,
  bereits disclaimer-tragenden Diagnose-Contracts**: `post-emit-health.v1`,
  `agent-export-gate.v1`, top-level `retrieval-eval.v1`. (Migration: additive optional.)
- **C2.2** — `risk_class`/Authority-Normierung für die **manifest-tragenden Rollen** in
  `bundle-manifest.v1` (optional pro Rolle, plus `output_health`-Authority-Zweig). (Migration:
  additive optional; Pflicht nur in neuer Major-Version.)
- **C2.3** — Vorbereitung von `allowed_inference`/`forbidden_inference` als optionale
  Schema-Felder, basierend auf bestehenden `does_not_prove`/`does_not_mean`-Grenzen; keine
  Pflichtfelder ohne Deprecation-Fenster. Schema-Level-Boundary-Validierung: bestehende
  `does_not_prove`/`does_not_mean` gegen eine Klassen-Norm prüfen (Konsistenz-Check,
  **keine** Ersetzung der rollenspezifischen Sätze).
- **C2.4** — Vorbereitung der Lint-Regeln (C1 §6 L1–L6) als spätere CI-Stufe — **erst** nachdem
  die Contracts stabil normiert sind.
- **C2.5** — Export-Gate-Integration von Risk-Class/Exportability — **erst** nach stabilen
  Contracts und aktivem Lint.

Federation-Contracts werden bewusst **nicht** in C2.1–C2.5 eingeplant; sie folgen erst nach
Federation-Hardening (Roadmap Phase 4).

---

## 9. Roadmap Impact

Vorgeschlagene, minimale Roadmap-Ergänzung (in `docs/roadmap/lenskit-master-roadmap.md`,
Governance-Track C):

- C2a wird als **Audit-/Proof-Schritt** zwischen C1 und der Contract-Normierung eingetragen,
  mit Verweis auf diese Datei.
- C2 (Contract-Normierung), C3 (Lint), C4 (Runtime-Annotation), C5 (Export-Gate) bleiben
  **weiterhin als Folgearbeit** markiert.
- Es wird **keine** Runtime-, Schema- oder Lint-Implementierung als erledigt markiert.

(Die tatsächliche Roadmap-Ergänzung ist Teil dieser PR; sie ändert nur den Governance-Track-C-
Abschnitt additiv.)

---

## 10. Audit Conclusion

**Bereits C1-kompatibel (aligned):** die Runtime-Lookups (`artifact-lookup`, `trace-lookup`,
`context-lookup`), `retrieval-eval.v1` (inkl. `miss_taxonomy`) und `context-quality.v1`. Sie
tragen Authority und/oder vollständige `claim_boundaries`/`does_not_prove`/`does_not_mean` und
respektieren die C1-Drift-Verbote.

**Größte Lücken:** (1) `risk_class` fehlt systemweit außer in zwei Diagnose-Contracts;
(2) mehrere Diagnose-/Gate-Contracts (`post-emit-health`, `agent-export-gate`, `output-health`)
deklarieren ihre Authority nicht selbst; (3) die Federation-Contracts haben nur Prosa-Disclaimer;
(4) `output-health.verdict=pass` ist der schärfste unabgesicherte Drift-Begriff.

**Sicherster nächster Contract-PR (C2.1):** additive, optionale, **const** `authority`+`risk_class`
für `post-emit-health.v1` und `agent-export-gate.v1` (und optional top-level `retrieval-eval.v1`).
Diese Contracts tragen bereits Disclaimer, sind unregistriert und haben eine kleine Consumer-Basis
— additive Felder brechen nichts.

**Was auf keinen Fall direkt implementiert werden darf:**
- Keine Pflichtfelder in `bundle-manifest.v1` v1 (Altbundle-Bruch).
- Kein Eingriff in `output-health.v1` vor Abschluss der `pre_emit_health`-Naming-Migration und
  ohne Parity-Gate-Koordination.
- Kein generisches `authority` neben `session_authority` in `agent-query-session.v2`.
- Keine Boundary-/Authority-Felder in den Federation-Contracts vor Federation-Hardening.
- Keine Lint-Regeln oder Export-Gates in C2.1.
- Keine `allowed_inference`/`forbidden_inference`-Pflichtfelder ohne vorherige Consumer- und
  Backcompat-Prüfung. `allowed_inference`/`forbidden_inference` bleiben Ziel der späteren
  Contract-Normierung, sollen aber erst nach additiver Authority-/Risk-Class-Normierung und
  Boundary-Validierung eingeführt werden.

---

## Validierung dieses Audits

| Prüfung | Ergebnis |
| :--- | :--- |
| Docs-only, keine Contract-/Schema-Änderung | erfüllt (nur dieses Dokument + Roadmap-Notiz) |
| Keine Behauptung, dass C2 implementiert ist | erfüllt (§8/§9 markieren alles als Folgearbeit) |
| Keine neuen Contract-Dateien | erfüllt |
| C1-Begriffe nicht umdefiniert | erfüllt (Vokabular aus C1 §2.1 übernommen) |
| B1/B2/A4/A5-Invarianten respektiert | erfüllt (rollenspezifische Disclaimer unangetastet) |
| Roadmap bleibt konsistent | erfüllt (Governance-Track C additiv ergänzt) |
