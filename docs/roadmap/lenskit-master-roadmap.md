# Lenskit Master Roadmap

## Zweck
Diese Datei ersetzt keine Fachblueprints und keine Architekturdocs.
Sie ordnet vorhandene Roadmaps in eine Reihenfolge, klärt Rollenbegriffe und verhindert Drift.
Leitlinien:
- Diagnose-first.
- Keine Pfad-Erfindung.
- Keine Implementierung in diesem PR.
- Keine Blaupausen-Megafusion.

## Prüfgrundlage
Prüfung erfolgte im aktuellen Branch per `test -f` und `rg`.
Gefunden:
- `docs/lenskit-upgrade-blaupause.md`
- `docs/atlas-blaupause.md`
- `docs/architecture/inconsistencies.md`
- `docs/architecture/artifact-inventory.md`
- `docs/architecture/artifact-drift-matrix.md`
- `docs/architecture/runtime-matrix.md`
- `docs/architecture/two-layer-artifact-pattern.md`
- `docs/contracts/contracts-matrix.md`
Optional erwartet; Stand dieses Branches:
- `docs/blueprints/lenskit-output-optimierung-v1.md` ist vorhanden.
- `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md`
- `docs/blueprints/lenskit-evidence-address-architecture.md`
Einordnung:
- `docs/blueprints/lenskit-output-optimierung-v1.md` ist vorhanden (frühere Annahme über fehlenden File-Proof ist durch Branch-Stand überholt).
- `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md` und `docs/blueprints/lenskit-evidence-address-architecture.md` sind weiterhin optional erwartet, aber kein File-Proof unter `docs/blueprints/` vorhanden.
- Evidence-Address-Architektur kann als aktueller PR-Kontext oder geplanter Blueprint existieren.
Diagnosebefunde für Terminologie:
- Historische Begriffe (`chunk_index_sqlite`, `derived_index_json`) sind noch in älteren Blaupausen sichtbar.
- Kanonisch im Rollenmodell sind `sqlite_index` und `derived_manifest_json`.
- `output_health` ist in dieser Roadmap ein geplanter Health-/Diagnose-Track für spätere Citation-/Evidence-Prüfung, aber im aktuellen Branch nicht als vorhandene Bundle-Manifest-ArtifactRole zu behandeln.
- Federation ist nicht null, sondern partial/minimal vorhanden; Hardening offen.

## Namensdisziplin / Artifact Roles
| Alt / konzeptionell | Kanonisch |
| --- | --- |
| `merge_md` | `canonical_md` als ArtifactRole; `merge.md` als kanonisches Markdown |
| `chunk_index_sqlite` | `sqlite_index` |
| `derived_index_json` | `derived_manifest_json` |
| `*.derived_index.json` | Dateiname zur Role `derived_manifest_json` |
| `output_health_json` / `output_health` | `output_health` ist als Bundle-Manifest-ArtifactRole vorhanden und wird als Diagnoseartefakt emittiert; Citation-/Evidence-Health-Erweiterung bleibt geplant |
| `citation_map_jsonl` | Manifest-Role registriert; `derived`/`navigation_index`; CLI-Producer implementiert; Merger-Pipeline-Emission umgesetzt (Beleg: `docs/proofs/citation-map-pipeline-emission-proof.md`) |
Zusatz:
Rollenamen folgen `bundle-manifest.v1.schema.json`, nicht älteren Blueprint-Begriffen oder Dateinamen.

## Konfliktauflösung
1. Range-/Citation-Grundlagen vor Query-/Agent-/UI-Ausbau.
2. `citation_map_jsonl` ersetzt nicht `chunk_index_jsonl`.
3. `range-ref.v2` bleibt docs-first und v1-kompatibel.
4. `bundle_manifest` ist perspektivisch zentrale Registry; `dump_index_json` und `derived_manifest_json` bleiben Views bis zur Konsumentenmatrix.
5. Atlas bleibt Paralleltrack und blockiert Lenskit Evidence Addressing nicht.
6. Federation-Hardening erst nach lokaler Evidence-Address-Stabilisierung.
7. Semantic/Reranking erst nach Belegadressierung sowie Query-/Trace-Grundlagen.

## Gemeinsame Umsetzungsreihenfolge

### Phase 0 - Roadmap-Konsolidierung
Aktueller PR:
- [x] `docs/roadmap/lenskit-master-roadmap.md`
- [x] optionale kleine Korrektur in `docs/architecture/inconsistencies.md` bei belegtem Altbefund (Phase-6-Altbefund `agent_query_session` als resolved/closed dokumentiert)
- [x] Design-Blueprint für die offene `agent_query_session` v1/v2-Konsolidierungsentscheidung: `docs/blueprints/agent-query-session-v1-v2-consolidation-decision.md`
Gate:
- keine widersprüchlichen Rollennamen
- keine erfundenen Blueprint-Pfade
- Reihenfolge Range/Citation vor Query/Agent/Federation/UI festgelegt

### Phase 1 - Range- und Citation-Fundament
Spätere PRs:
- [x] `docs/architecture/range-semantics.md`
- [x] `docs/proofs/citation-map-artifact-fit.md`
- [x] `citation-map.v1.schema.json` plus minimale Beispiele plus Schema-Test
- [x] Bundle-Manifest-Role `citation_map_jsonl`
- [x] `chunk_index` dual range mit `content_range_ref`, `canonical_range`, `source_range`
- [x] Citation-Map-CLI-Producer plus Real-Dump-Proof
  - **Producer implementiert und gehärtet (2026-05-14):**
    - `merger/lenskit/core/citation_map.py` (pure Funktionen + IO-Adapter).
    - CLI: `lenskit citation produce <bundle_manifest>` mit `--json`- und `--output`-Option.
    - Normalisierung: bevorzugt `canonical_range`, fällt auf `content_range_ref` zurück (beide müssen `artifact_role == "canonical_md"` haben).
    - `make_citation_id(canonical_md_sha256, start_byte, end_byte, content_sha256)` pro Chunk.
    - `start_line`/`end_line` werden aus `canonical_md`-Bytes berechnet (`byte_range_to_line_range()`); Input-Werte werden ignoriert. Semantik: `canonical_range` ist Position in `canonical_md` laut Contract.
    - H1–H4/H6-Hardening: kein partieller Output, sicherer Default-Pfad, `run_id`-Gate, `repo_id`-Konfliktprüfung, Module-Level-Registry.
    - `ARTIFACT_CONTRACT_REGISTRY` und `ARTIFACT_AUTHORITY_REGISTRY` auf Modulebene in `merge.py`.
    - Tests: `test_citation_map_producer.py` (73 Tests, alle grün).
    - Real-Dump-Proof PASS gegen Dump `lenskit-max-260514-0409_merge` (541 Chunks, 0 Fehler, 0 Duplikate, Schema-Validierung PASS); Beleg: `docs/proofs/citation-map-producer-proof.md`.
- [x] Citation-Readiness-Validator plus Real-Dump-Proof
  - `merger/lenskit/core/citation_validate.py` implementiert (Konsument/Readiness-Gate, kein Producer).
  - CLI: `lenskit citation validate <bundle_manifest>` mit `--json`-Option.
  - Tests: `test_citation_validate.py`, `test_cli_citation.py` (synthetische Fixtures, kein Real-Dump erforderlich).
  - Real-Dump-Proof erbracht: aktueller echter Dump validiert (`594` Chunks, Status `ok`); Beleg: `docs/proofs/citation-readiness-validator-proof.md`.
- [x] Merger-Pipeline-Emission von `citation_map_jsonl` ins Bundle-Manifest
  - Beleg: `docs/proofs/citation-map-pipeline-emission-proof.md`
Gate:
- `citation_map_jsonl` nie `canonical_content` oder `content_source`
- `canonical_range` und `source_range` getrennt
- Backcompat: alte Bundles ohne Citation Map brechen nicht

### Phase 2 - Query / Context / Trace
Spätere PRs:
- Query-Ergebnisse referenzieren optional `citation_id`
- Context Bundle referenziert Citations, erfindet sie nicht
- Trace macht Provenance sichtbar
Gate:
- lokale Citation Map validiert
- Context/Trace E2E nachweisbar

### Phase 3 - Graph Runtime
Spätere PRs:
- Graph verbessert Retrieval optional
- Graph ersetzt kein Evidence Addressing
- Recovery-/Policy-Hardening separat abschließen
Gate:
- Graph-Einfluss erklärbar und rückverfolgbar

### Phase 4 - Federation / Cross-Repo
Spätere PRs:
- erst nach lokal stabiler Evidence Address
- Identity Engine und Conflict Handling härten
- `cross_repo_links` und `federation_conflicts` als partial/minimal weiterführen
Gate:
- lokale Citation-/Range-Semantik stabil
- Cross-Bundle-Konfliktstatus sichtbar

### Phase 5 - Agent Control Surface
Spätere PRs:
- Agent Profiles, Query Sessions, Evidence Packs, MCP nach Query/Trace/Citation-Grundlagen
- Agent nutzt Evidence, erzeugt aber keine Citation-Wahrheit
Gate:
- Evidence refs validierbar
- Unsicherheit und Provenance sichtbar

### Phase 6 - UI / Service / Produktisierung
Spätere PRs:
- UI zeigt Status und Provenance
- Service/API erzeugt keine neue Wahrheitsschicht
Gate:
- Artifact Lookup stabil
- Sicherheits- und Backcompat-Guards grün

### Phase 7 - Semantic / Reranking
Spätere PRs:
- Semantic Retrieval und Reranking nach Evidence Addressing
- Retrieval-Eval-Härtung fortführen
Gate:
- Ranking-Verbesserung ersetzt keine Belegqualität

## Governance-Track C — Authority / Canonicality / Risk-Class

Dieser Track ist unabhängig von den Milestones A–B und blockiert sie nicht.
Er normiert die epistemischen Grenzen des Systems als explizite Governance-Schicht.

### C1 — Authority / Risk-Class Matrix (Blueprint)

Status: Blueprint (`docs/blueprints/lenskit-authority-risk-matrix.md`).  
Scope: Governance- und Contracts-first; kein Runtime-Code, keine neuen Schemas.

- `docs/blueprints/lenskit-authority-risk-matrix.md` — normative Matrix für
  Authority-Klassen, Canonicality, Risk-Class, allowed/forbidden Inferences,
  Trust-Surface, Exportability pro Artefaktklasse.
  Enthält: Contract-Skizzen (`authority-matrix.v1`, `inference-boundary.v1`,
  `risk-class.v1`), Anti-Hallucination-Lint-Entwürfe, Agent-/RAG-Analyse,
  Übergangsplan Phase 1–6.

Gate:
- Blueprint kompatibel mit bestehenden Contracts und B1/B2-Invarianten (geprüft)
- Keine Runtime-Änderungen in C1

### C2a — Authority / Inference Boundary Contract Gap Audit (Proof)

Status: Audit/Proof (docs-only), `docs/proofs/authority-contract-gap-audit.md`.
Scope: prüft die C1-Kompatibilität bestehender Contracts unter `merger/lenskit/contracts/`
und bereitet die Contract-Normierung (C2) vor — **ohne** C2 zu implementieren.

- Kein Runtime-Code, keine Schemas, keine Lints, keine Contract-Änderung.
- Befund: Die geprüften Runtime-Lookups `artifact-lookup`, `trace-lookup` und `context-lookup`
  sowie `retrieval-eval.v1` und `context-quality.v1` sind bereits C1-kompatibel; größte Lücke ist
  ein systemweit fehlendes `risk_class`. `diagnostics-lookup.v1` bleibt separat im Audit
  eingeordnet (`missing_boundary`: Facade ohne `authority`/`claim_boundaries`). Sicherster
  nächster Schritt (C2.1) sind additive, optionale `authority`/`risk_class`-Felder für bereits
  disclaimer-tragende Diagnose-Contracts.

### C2.1 — Additive Authority/Risk-Class für Diagnose-Contracts (umgesetzt)

Status: **UMGESETZT** (Contract-only, additiv), Beleg
`docs/proofs/authority-risk-class-c2-1-proof.md`.
Scope: additive, optionale, **const** Felder `authority` (`diagnostic_signal`) und
`risk_class` (`diagnostic`) in genau drei bereits disclaimer-tragenden Diagnose-Contracts:
`post-emit-health.v1`, `agent-export-gate.v1` und top-level `retrieval-eval.v1`.

- **Keine** Pflichtfelder, **keine** Lockerung bestehender Constraints, `additionalProperties:
  false` bleibt erhalten.
- **Keine** Runtime-/CLI-/Producer-Änderung, **keine** Lints, **keine** Export-Gates.
- `miss_taxonomy` in `retrieval-eval.v1` bleibt unverändert; `output-health.v1`,
  `bundle-manifest.v1`, `agent-query-session.v2` und die Federation-Contracts wurden **nicht**
  angefasst.
- Validierung: 86 passed in den drei Zielsuiten (74 Baseline + 12 additive Tests),
  75 passed in der Consumer-Regression, ruff `F401,F811` sauber.

Mögliche Folgearbeiten (separate PRs, nicht Teil von C1, C2a oder C2.1):
- C2.2: `bundle-manifest.v1`-Normierung (per-role `risk_class`, `output_health`-Authority-Zweig) — **UMGESETZT** (siehe C2.2-Abschnitt unten)
- C2.3: `allowed_inferences`/`forbidden_inferences` als optionale Schema-Felder — **UMGESETZT** (contract-only/test-only; siehe C2.3-Abschnitt unten)
- C3 / C2.4: Anti-Hallucination-Contract-Lint (kontraktstatischer L3+L5-Teil) — **UMGESETZT** (siehe C2.4-Abschnitt unten). Die AST-/codepfadbasierten Regeln L1/L2/L4 bleiben **offen**.
- C4: Runtime-Annotation — **offen**
- C2.5 / C5: Export-Gate-Integration für L6-Export-Risk-Inferenzen — **MINIMAL UMGESETZT** (siehe C2.5-Abschnitt unten). Das breitere C5-Governance-Framework bleibt **offen**.
- C2.6: Auflösung der C2.4-Deferral — required Root-Boundary (`does_not_prove`) für `retrieval-eval-diagnostics.v1` plus Producer-Emission — **UMGESETZT** (siehe C2.6-Abschnitt unten). Deferral-Registry jetzt leer.

### C2.2 — Additive per-role Risk-Class + output_health-Authority im Bundle-Manifest (umgesetzt)

Status: **UMGESETZT** (Contract-only, additiv), Beleg
`docs/proofs/authority-risk-class-c2-2-manifest-proof.md`.
Scope: ausschließlich `merger/lenskit/contracts/bundle-manifest.v1.schema.json`:
(1) additives, optionales, **per-Rolle const** `risk_class` (abgeleitet aus der bereits
vorhandenen per-Rolle-`authority`: `canonical_content→content`, `navigation_index→navigation`,
`runtime_cache→cache`, `diagnostic_signal→diagnostic`); (2) neuer `allOf`-Zweig für die
bisher unbeschränkte Rolle `output_health` (`authority: diagnostic_signal`,
`canonicality: diagnostic`, `risk_class: diagnostic`), deckungsgleich mit der bereits vom
Producer emittierten Annotation.

- **Keine** Pflichtfelder, **keine** Lockerung bestehender Constraints; `additionalProperties:
  false` bleibt auf Manifest- und Artefakt-Item-Ebene erhalten. const greift nur bei
  Anwesenheit → Legacy-Bundles ohne `risk_class` bleiben valide.
- **Keine** Producer-/Runtime-/CLI-Emission von `risk_class`, **kein** Lint, **kein**
  Export-Gate. **Kein** Eingriff in `output-health.v1.schema.json` (nur die Manifest-Rolle).
- **STOP (scoped, aktiv erzwungen):** `retrieval_index`-Rollen (`chunk_index_jsonl`,
  `graph_index_json`) erhalten **keinen** risk_class-Wert — und das Schema **verbietet**
  `risk_class` für sie aktiv (`not: {required: ["risk_class"]}`), weil C1 keinen
  eindeutigen risk_class für `retrieval_index` dokumentiert (kein §3-Abschnitt). Jeder
  Enum-Wert wird abgewiesen; ein blosses Weglassen des Constraints würde die Tür für
  semantische Aufwertungen öffnen (C1 §4 P4 / §3.9).
- Validierung: 30 passed in der Zielsuite (Manifest + Rollen-Completeness, inkl. 6 additiver
  C2.2-Tests), 188 passed in der Bundle-/Health-/Parity-Regression, ruff `F401,F811` sauber.

### C2.2 Follow-up — Producer-Emission für eindeutig klassifizierte Manifest-Rollen (umgesetzt)

Status: **UMGESETZT** (additive Producer-Emission), Beleg
`docs/proofs/authority-risk-class-c2-2-manifest-proof.md` §7a.
Scope: `ARTIFACT_AUTHORITY_REGISTRY` in `merger/lenskit/core/merge.py` emittiert
`risk_class` für Rollen mit eindeutig belegtem C1-risk_class:
`canonical_content → content`, `navigation_index → navigation`, `runtime_cache → cache`,
`diagnostic_signal → diagnostic`. Producer-Emission für eindeutig klassifizierte
Manifest-Rollen umgesetzt.

- **STOP für `retrieval_index` aktiv erhalten:** Für `chunk_index_jsonl` und
  `graph_index_json` wird **kein** `risk_class` emittiert; der Schema-Sperrriegel aus
  C2.2 (`not: {required: ["risk_class"]}`) bleibt unverletzt.
- **`must_resolve_to`:** Wird nicht emittiert, weil das Manifest-Schema das Feld nicht
  kennt und `additionalProperties: false` auf Artefakt-Item-Ebene greift.
- **Keine** Pflichtfeld-Migration, **keine** Anti-Hallucination-Lint, **kein**
  Export-Gate, **keine** Änderung an `canonical_md` oder am Retrieval-Verhalten,
  **keine** Schema-Änderung.
- Validierung: 32 passed in der Zielsuite (Manifest + Rollen-Completeness, inkl. 2
  additiver Producer-Emissionstests), 190 passed in der Bundle-/Health-/Parity-/
  Reading-Pack-Regression, ruff `F401,F811,F841,E711,E712` sauber.

### C2.3 — Additive optionale Inference-Boundary-Felder (umgesetzt)

Status: **UMGESETZT** (contract-only/test-only), Beleg
`docs/proofs/authority-risk-class-c2-3-inference-boundary-proof.md`.
Scope: additive, optionale, plural benannte `allowed_inferences` und
`forbidden_inferences` als `array[string]` in vier bereits boundary-nahen Diagnose-
Contracts: `post-emit-health.v1`, `agent-export-gate.v1`, `retrieval-eval.v1` und
`context-quality.v1`.

- **Keine** Pflichtfelder, **keine** Major-Version, **keine** Producer-/Runtime-/CLI-Emission.
- **Keine** claim-Bewertung (`supported`/`unsupported`/`proven`) und **kein** Wahrheitsurteil;
  `allowed_inferences` beschreibt erlaubte Nutzung, `forbidden_inferences` ergänzt
  bestehende Boundary-Disclaimer (z. B. `does_not_mean` oder
  `claim_boundaries.does_not_prove`) maschinenlesbar.
- **Freie Strings bewusst beibehalten:** kein Enum/const-Vokabular in C2.3, weil spätere
  C2.4/C2.5-Arbeit die Policy-/Lint-Vokabulare erst stabilisieren muss.
- **Nicht angefasst:** `output-health.v1`, Federation-Contracts, `agent-query-session.v2`,
  `bundle-manifest.v1`; keine neuen `authority-matrix.v1`- oder `inference-boundary.v1`-
  Contracts.
- C2.4/C3 (kontraktstatischer Lint) ist mit dem nächsten Abschnitt **UMGESETZT**;
  C2.5/C5 (Export-Gate, L6-Export-Risk-Inferenzen) ist **minimal umgesetzt**
  (siehe C2.5-Abschnitt). Die AST-Regeln (L1/L2/L4) und C4 (Runtime-Annotation)
  bleiben **offen**.

### C2.4 — Anti-Hallucination-Contract-Lint (kontraktstatischer L3+L5-Teil, umgesetzt)

Status: **UMGESETZT** (lint-/test-/CI-only, keine Contract-Änderung), Beleg
`docs/proofs/authority-risk-class-c2-4-lint-proof.md`.
Scope: der **mechanisch aus Schemas allein entscheidbare** Teil der C1-Lint-Regeln
(`docs/blueprints/lenskit-authority-risk-matrix.md` §6), wie vom Gap-Audit
(`docs/proofs/authority-contract-gap-audit.md` §8) als „Vorbereitung der
Lint-Regeln als spätere CI-Stufe" vorgesehen. Der Lint ist auf dem aktuellen
Contract-Stand **grün** und fängt künftige Drift ab, ohne eine vorzeitige
Contract-Migration zu erzwingen.

- Geänderte/ergänzte Dateien:
  - `merger/lenskit/core/anti_hallucination_lint.py` (reine Funktionen + IO-Adapter)
  - `merger/lenskit/cli/cmd_governance.py` (`lenskit governance lint`, Dispatch in `cli/main.py`)
  - `merger/lenskit/tests/test_anti_hallucination_lint.py` (25 Tests)
  - `.github/workflows/anti-hallucination-lint.yml` (path-scoped blockierender Gate)
  - `docs/proofs/authority-risk-class-c2-4-lint-proof.md`
- Implementiert (blockierend):
  - **L3 — Missing Inference Boundary:** Contracts, deren **Wurzelobjekt** eine
    boundary-pflichtige Authority selbst deklariert (`authority`/`session_authority`
    const ∈ {`diagnostic_signal`, `runtime_observation`, `agent_context_projection`}),
    müssen ein maschinenlesbares Boundary-Array an der Wurzel tragen
    (`does_not_prove`/`does_not_mean`/`claim_boundaries`). `bundle-manifest.v1`
    (per-Rolle-Authority, nested) ist korrekt **nicht** governt.
  - **L5 — Unsupported Truth Language:** verbotene Wahrheits-/Sicherheits-Feldnamen
    (`understanding_score`, `agent_safe`, `proven`, `verified`, …) als Property-Keys
    und verbotene Verdict-Tokens (`proven`, `verified`, `safe`, `green/yellow/red`, …)
    als `enum`-/`const`-Werte von Verdict-Feldern (`verdict`/`status`/`*_verdict`). Nur
    **Exact-Match**, nie Substring; Disclaimer-Array-**Werte** (`does_not_*`,
    `*_inferences`, `agent_use_constraints`) werden **nie** gescannt.
- **STOP / Out of Scope (dokumentiert, nicht implementiert):**
  - **L1/L2/L4** erfordern Python-**AST-/Codepfad**-Analyse (hohe False-Positive-Fläche
    laut Blueprint §6) → spätere AST-Lint-Stufe.
  - **L6** (Export-Risk) = Export-Gate-Integration = **C5** (inzwischen minimal
    umgesetzt für die Export-Risk-Inferenzen: siehe C2.5-Abschnitt).
  - Die Out-of-Scope-Regeln werden maschinenlesbar im Report (`rules_out_of_scope`)
    geführt.
- **Deferral-Registry (getrackt, nicht-blockierend):** genau
  `retrieval-eval-diagnostics.v1.schema.json` deklarierte `authority:
  diagnostic_signal` ohne Boundary-Array und war **nicht** in der C2a-Audit-Tabelle
  erfasst. C2.4 machte diese Lücke ehrlich als `deferred` sichtbar, statt sie still zu
  ignorieren oder die Contract-Migration zu erzwingen (Gap-Audit §8/§5.D/§7). Das
  Hinzufügen der Boundary war als C2.x-Folgearbeit angekündigt und ist
  **inzwischen durch C2.6 umgesetzt** (Root-`does_not_prove` + Producer-Emission;
  Deferral-Registry jetzt leer). `audit_deferral_registry()` + Test verhindern
  weiterhin, dass die Deferral-Liste verrottet.
- **Keine** Contract-Änderung, **keine** Producer-/Runtime-Emission, **keine**
  Claim-Wahrheitsbewertung. Der Lint-Report ist selbst ein `diagnostic_signal`
  (`authority`/`risk_class`/`does_not_mean`).
- Validierung: `governance lint` → PASS (38 gescannt, 0 Fehler, 1 deferred), exit 0;
  `test_anti_hallucination_lint.py` 32 passed; Regression
  (contracts/health/quality/eval/cli) ohne Regression; ruff
  `F401,F811,F841,E711,E712` sauber.

### C2.5 — Export-Gate liest L6-Export-Risk-Inferenzen (minimal umgesetzt)

Status: **MINIMAL UMGESETZT** (additive Gate-Härtung, keine Contract-Änderung),
Beleg `docs/proofs/authority-risk-class-c2-5-export-gate-proof.md`.
Scope: der **Export-Gate-Teil** der C1-Regel **L6**, den C2.4 ausdrücklich nach
C5 verschoben hat. Das bestehende `agent_export_gate` (A5) wird **minimal
gehärtet**, nicht ersetzt: es liest jetzt das optionale C2.3-Feld
`forbidden_inferences` aus den Diagnoseartefakten des Bundles.

- Geänderte/ergänzte Dateien:
  - `merger/lenskit/core/agent_export_gate.py` (additives Lesen + Gate-Bedingung)
  - `merger/lenskit/tests/test_agent_export_gate.py` (C2.5-Tests)
  - `docs/proofs/authority-risk-class-c2-5-export-gate-proof.md`
- Regel (blockierend, **nur agent-facing**): Wenn ein Diagnoseartefakt im Bundle
  maschinenlesbar eine Inferenz aus dem geschlossenen Export-Risk-Vokabular
  verbietet, wird ein **agent-facing** Export auf `fail` herabgestuft (bzw. bleibt
  `blocked`) und ein Fehler benennt die Inferenz. Nicht-agent-facing Profile
  werden weiterhin getrennt geprüft und sind **nicht** export-risk-gegated.
- Export-Risk-Vokabular (klein, geschlossen, exakt; spiegelt
  `context_quality.DOES_NOT_MEAN`): `claims_true`, `repo_understood`,
  `answer_safe_without_citations`, `retrieval_complete`. Freie C2.3-Strings
  außerhalb dieses Vokabulars blockieren **nicht**.
- Lesefläche: Manifest-Artefakte mit `authority == diagnostic_signal` (sicher via
  `resolve_secure_path`, bundle-intern) plus das bereits geladene
  `post_emit_health`-Dokument. Kein Lesen außerhalb des Bundles.
- **STOP / bewusst nicht enthalten:** **kein** neuer Contract, **keine**
  Runtime-Annotation, **keine** Producer-Emission von `forbidden_inferences`,
  **keine** Wahrheitsermittlung, **keine** Manifest-Mutation, **keine** Änderung
  an `canonical_md` oder am Retrieval. Report-Form unverändert (Grund in
  bestehendem `errors`-Array → weiterhin schema-valide gegen
  `agent-export-gate.v1`). Die `evaluate_agent_export_gate`-Signatur bleibt
  gleich; die `bundle-health export-gate`-CLI ist unverändert. C4
  (Runtime-Annotation) und das breitere C5-Governance-Framework bleiben **offen**.
- Validierung: Zieltrio (`test_agent_export_gate.py`,
  `test_contract_inference_boundaries.py`, `test_anti_hallucination_lint.py`) →
  **107 passed** (`test_agent_export_gate.py` 47, davon 12 neue C2.5-pytest-Fälle);
  Regression (health/quality/eval/contract-guards/cli) 97 passed, keine
  Regression; ruff `F401,F811,F841,E711,E712` sauber; `git diff --check` sauber.

### C2.6 — Auflösung der C2.4-Deferral: retrieval-eval-diagnostics.v1 Root-Boundary (umgesetzt)

Status: **UMGESETZT** (boundary-normalizing Contract-Tightening + Producer-Emission),
Beleg `docs/proofs/authority-risk-class-c2-6-diagnostics-boundary-proof.md`.
Scope: löst die einzige von C2.4 getrackte Deferral. `retrieval-eval-diagnostics.v1`
deklarierte `authority: diagnostic_signal` (boundary-pflichtig unter C1/L3), trug
aber keine maschinenlesbare Inference-Boundary. C2.6 ergänzt eine required
Root-Boundary und emittiert sie aus dem bestehenden Producer.

- Geänderte/ergänzte Dateien:
  - `merger/lenskit/contracts/retrieval-eval-diagnostics.v1.schema.json`
    (Pflicht-Root-`does_not_prove` als `array[string]`, `minItems: 1`, `allOf`/`contains`)
  - `merger/lenskit/retrieval/eval_diagnostics.py` (`DOES_NOT_PROVE`-Konstante +
    Emission in `generate_report`)
  - `merger/lenskit/core/anti_hallucination_lint.py` (`DEFERRED_BOUNDARY_CONTRACTS`
    jetzt leer; Mechanismus erhalten)
  - `merger/lenskit/tests/test_anti_hallucination_lint.py`,
    `merger/lenskit/tests/test_retrieval_eval_diagnostics.py`
  - `docs/proofs/authority-risk-class-c2-6-diagnostics-boundary-proof.md`
- Boundary-Vokabular (Pflicht-`contains`, an `retrieval-eval.v1`
  `miss_taxonomy.does_not_prove` angelehnt, auf die per-Miss-*Diagnose* dieses
  Contracts adaptiert): `absence_of_retrieval_hit_does_not_prove_absence_in_repository`,
  `miss_diagnosis_does_not_prove_claim_truth_or_falsehood`,
  `primary_diagnosis_does_not_prove_root_cause_certainty`,
  `retrieval_eval_does_not_prove_retrieval_completeness`,
  `diagnosis_is_diagnostic_not_authoritative`.
- **Pflichtfeld bewusst gewählt** (anders als die rein optionalen C2.1–C2.3-Felder):
  Producer steht unter eigener Kontrolle und wird mitgeändert, keine persistierten
  Alt-Artefakte (keine Manifest-Rolle, keine Beispiel-Fixtures), und das Sibling
  `retrieval-eval.v1` führt `miss_taxonomy.does_not_prove` ebenfalls als Pflicht mit
  `contains`. Ein optionales Feld wäre Boundary-Theater.
- **STOP / bewusst nicht enthalten:** keine Wahrheits-/Claim-Bewertung, keine
  Repository-Abwesenheitsbehauptung, keine Ranking-/Retrieval-Verhaltensänderung,
  keine Manifest-Mutation, kein neuer Contract, keine Änderung an den L3/L5-Lint-Regeln
  oder am Export-Gate (C5). C4 (Runtime-Annotation) und das breitere C5-Framework
  bleiben **offen**.
- Validierung: `governance lint` → PASS (38 gescannt, 0 Fehler, **0 deferred**, exit 0);
  Zielsuiten (`test_anti_hallucination_lint.py`, `test_retrieval_eval_diagnostics.py`)
  59 passed; Regression (contracts/health/quality/eval/export-gate/cli) 173 passed,
  keine Regression; Schema-Meta-Validierung (`Draft7Validator.check_schema`) OK; ruff
  `F401,F811,F841,E711,E712` sauber.

## Paralleltrack Atlas
- Atlas = physische Wahrnehmung / Filesystem-Snapshot
- Lenskit = Knowledge Compiler / Evidence Runtime
- Details bleiben in `docs/atlas-blaupause.md`
- Atlas blockiert Range-/Citation-Fundament nicht
Optionale spätere Stichpunkte:
- Cross-root growth reports
- Content parser policy
- Remote collector / SSH model
- Watch-mode event schema
- Knowledge-map output

## Statusmodell
- `implementation`: `none` | `partial` | `done`
- `tests`: `missing` | `partial` | `present`
- `hardening`: `missing` | `partial` | `complete`
- `gate`: `open` | `passed`
Begründung:
- Historische `[x]`-Listen bleiben lesbar.
- Die Master-Roadmap trennt Implementation, Tests, Hardening explizit.

## Paritaetsgates (repolens vs rlens)

Zwei getrennte Gates sind verpflichtend, um Content-Paritaet nicht mit Diagnose-Paritaet zu verwechseln.

- `content_parity_pass`
  - Bedeutet: gleiche Repo-Dateien, gleiche Source-Hashes, gleiche source-basierte Chunk-Abdeckung, logisch gleiche FTS-Inhalte.
  - Content parity allows equal empty FTS for repos without indexable text; FTS non-emptiness is a diagnostic/profile health condition, not a content equality condition.
  - Beweist nicht: gleiche Pipeline-/Diagnose-/Runtime-Artefakte.
- `diagnostic_parity_pass`
  - Bedeutet zusaetzlich:
    - `output_health.verdict == pass`
    - `range_ref_resolution_status == ok`
    - keine Health-Warnings/-Errors
    - relevante Bundle-Artefakte mit konsistenten Hash-/Bytes-Werten
    - Profilabhaengige Diagnoseartefakte werden nur verlangt, wenn das jeweilige `*_expected`-Flag gesetzt ist. Dann gilt fail-closed:
      - `retrieval_eval_json` muss vorhanden **und** im Bundle-Manifest enthalten sein (`retrieval_eval_json_manifested=True`), wenn `retrieval_eval_json_expected=True`.
      - `citation_map_jsonl` muss validierbar sein, wenn `citation_map_jsonl_expected=True`.
      - `fts_non_empty` muss True sein, wenn `fts_non_empty_expected=True`.
    - Fehlt ein `*_expected`-Flag oder ist es `False`, wird das Artefakt nicht verlangt.
    - Ein nicht-bool `*_expected`-Wert ist ein Konfigurationsfehler und laesst `diagnostic_parity_pass` scheitern (fail-closed, keine stille Normalisierung).

Arbeitsregel:
- Erst diagnostizieren, dann aendern.
- Keine Heuristik-Patches ohne Target-Proof.

## Nicht jetzt
- keine UI vor Citation-/Query-Grundlagen
- keine Federation-Härtung vor lokaler Evidence Address
- kein Evidence Use in Citation Map v1
- keine SQLite-Wahrheit
- keine Löschung von `dump_index_json` oder `derived_manifest_json` ohne Konsumentenmatrix
- keine semantische Reranking-Priorisierung vor Belegadressierung
- keine Einführung von `output_health` als ArtifactRole ohne eigenen Contract-/Manifest-PR
- keine Implementierung in diesem PR

## Nächste konkrete PRs
PR 0:
- [x] `docs/roadmap/lenskit-master-roadmap.md`
- [x] optionale kleine Korrektur in `docs/architecture/inconsistencies.md`, nur bei belegtem Altbefund (belegter Altbefund vorhanden und minimal eingeordnet)
PR 1:
- [x] `docs/architecture/range-semantics.md`
- [x] `docs/proofs/citation-map-artifact-fit.md`
PR 2:
- [x] `citation-map.v1.schema.json` (`merger/lenskit/contracts/citation-map.v1.schema.json`)
- [x] minimale Beispiele (`merger/lenskit/contracts/examples/citation_map_minimal.jsonl`)
- [x] Schema-Test (`merger/lenskit/tests/test_citation_map_schema.py`)
PR 3 (teilweise erledigt):
- [x] Bundle-Manifest-Role `citation_map_jsonl`
- [x] Chunk-Index dual range (`canonical_range`, `source_range` zusätzlich zu `content_range_ref`)
- [x] Citation-Map-Producer plus eigener Producer-Real-Dump-Proof
- [x] Citation-Readiness-Validator (`merger/lenskit/core/citation_validate.py`, CLI `lenskit citation validate`, Testabdeckung in `merger/lenskit/tests/test_citation_validate.py` und `merger/lenskit/tests/test_cli_citation.py`; Real-Dump-Proof erbracht mit aktuellem Dump, 594 Chunks, Status `ok`)
PR 4 (erledigt):

- [x] `merger/lenskit/core/parity_gates.py` — Produktionsmodul mit `evaluate_parity_gates` und `ParityGateResult`. Gate-Semantik ist jetzt kanonisch und wiederverwendbar (nicht mehr nur Test-Helper).
- [x] PR 4b Basis: Real-Dump-Parser + CLI-Compare-Pfad
  - `merger/lenskit/core/parity_state.py` erzeugt ein kanonisches State-Dict aus zwei realen Bundle-Manifests fuer `evaluate_parity_gates`.
  - CLI: `lenskit parity compare LEFT_MANIFEST RIGHT_MANIFEST --json` mit standardisierten Exit-Codes (0/1/2).
  - Bundle-Manifest bleibt Registry-Wahrheit; Diagnoseartefakte werden nicht als stray files akzeptiert.
- [x] repolens diagnostic parity hardening
  - Ziel erreicht: repolens und rlens teilen dieselbe Pipeline und erreichen auf vollwertigen Hosts nicht nur Content-, sondern Diagnostic-Paritaet.
  - E2E-Beleg gegen echte Bundle-Manifests via `build_parity_state`+`evaluate_parity_gates`: `merger/lenskit/tests/test_parity.py::test_e2e_repolens_rlens_reach_diagnostic_parity` (alle 15 State-Flags True, 10 Artefakte verglichen, kein left/right-only). Beleg: `docs/proofs/repolens-rlens-diagnostic-parity-proof.md`.
  - Profilgrenze explizit dokumentiert: capability-degradierte iOS/Pythonista-Hosts (kein `jsonschema`/`fts5`) fordern nur Content-Paritaet; siehe `docs/architecture/artifact-capability-matrix.md` (Abschnitt "Diagnostic-Paritaet als Profilgrenze").
- [x] CLI-Erzwingung und parity-relevantes CI-Gate
  - CLI-Erzwingung: `lenskit parity enforce LEFT RIGHT --require {content,diagnostic}` (Default `diagnostic`) in `merger/lenskit/cli/cmd_parity.py`, Exit-Codes 0/1/2, `--json`/`--include-state`. Policy ist profilabhaengig (content fuer degradierte Profile, diagnostic fuer vollwertige Hosts).
  - CI-Gate: path-scoped blockierender Workflow `.github/workflows/parity-gate.yml` ("Parity Gate") faehrt die Gate-Suite (`test_parity.py`, `test_parity_state.py`, `test_cli_parity_compare.py`) bei Aenderungen an parity-relevantem Code/Tests/Contracts; inkl. `jsonschema`-Runtime-Dependency. Abgegrenzt vom Frontend-Feature-Guard (`parity_check.yml`).
  - Tests: `merger/lenskit/tests/test_cli_parity_compare.py` (enforce Policy-/Exit-Code-Faelle), `test_parity.py::test_e2e_parity_enforce_cli_on_real_bundles`.
Diagnosehinweis für Priorisierung:
- `merge.md` bleibt kanonische Vollquelle; JSON-Artefakte sind Einstieg/Index/Metadaten.
- Ein schwacher Retrieval-Eval-Stand priorisiert Evidence-/Retrieval-Grundlagen vor Semantic/Reranking.

PR 5 (docs-only): rLens CLI Client Blueprint und Umsetzungspfad

- [x] Blueprint anlegen: `docs/blueprints/rlens-cli-client-blueprint.md`
- [x] Read-only rLens CLI Client Basis implementiert (PR B)
  - [x] `health` — `GET /api/health`
  - [x] `artifacts` — `GET /api/artifacts`
  - [x] `latest --repo REPO` — `GET /api/artifacts/latest`
- [x] Read-only Jobs/Logs (PR C)
  - [x] `jobs` — `GET /api/jobs` (optional `--status`, `--limit`)
  - [x] `job JOB_ID` — `GET /api/jobs/{job_id}`
  - [x] `logs JOB_ID` — `GET /api/jobs/{job_id}/logs` (SSE bis `event: end`, optional `--last-id`, `--timeout`)
  - [ ] `run`, `cancel` (PR E) — nach API-/Sicherheitsreview
- [x] Host-Profile (PR D)
  - [x] `--profile NAME` an allen Subkommandos
  - [x] `RLENS_PROFILE`-Env-Variable
  - [x] Config-Pfad: `$LENSKIT_RLENS_PROFILES` > `$XDG_CONFIG_HOME/lenskit/rlens-profiles.json` > `~/.config/lenskit/rlens-profiles.json`
  - [x] Schema: `default_profile`, `profiles[NAME].base_url`, `profiles[NAME].token_env`
  - [x] Priorität Base-URL: `--base-url` > `RLENS_BASE_URL` > Profil-`base_url` > Default
  - [x] Priorität Token: `--token` > `RLENS_TOKEN` > Profil-`token_env` (Env-Lookup)
  - [x] `lenskit rlens-client profiles [--json]` listet Profile (redigiert; nur `base_url` und `token_env`-Name) und validiert Config strikt
  - [x] Sicherheits-Hardening: `token`/`secret`-Felder im Profil verboten (`config_error`, Exit 2); unbekannte Schlüssel abgelehnt
  - [x] Sobald Profil-Config vorhanden ist, wird sie auch ohne Profilselektion strikt validiert
  - [x] Explizit angeforderte Profile werden nie still ignoriert (auch nicht bei Base-URL-Override)
- [ ] Heim-PC/Heimserver-Betriebsmodell entscheiden
  - lokaler Service je Host
  - Remote-Client via LAN/Tailscale/SSH-Tunnel
- [x] CLI-Client-Sicherheitsinvarianten durch Tests abgesichert
  - Bearer Token (`--token` / `RLENS_TOKEN`)
  - Token-Redaction in Fehlerausgaben
  - Token nie als Query-Parameter
  - Default loopback `http://127.0.0.1:8787`
  - Profile-Config trägt keine Secrets (nur Env-Var-Namen via `token_env`)

Status:
- Blueprint: docs-only (PR A, abgeschlossen).
- Read-only Client-Basis: umgesetzt (PR B) — `health`, `artifacts`, `latest --repo`.
- Jobs/Job/Logs (SSE): umgesetzt (PR C) — `jobs`, `job JOB_ID`, `logs JOB_ID`.
- Host-Profile: umgesetzt (PR D) — `--profile`, `RLENS_PROFILE`, `profiles`-Subkommando.
- Run/Cancel: offen (nach API-/Sicherheitsreview).
- `merger/lenskit/cli/rlens.py` bleibt Service-Launcher und wird nicht umgedeutet.


PR 6 (Artifact Output Control Plane, docs-first):
- [x] `docs/blueprints/lenskit-artifact-output-control-plane.md`
- [x] `docs/architecture/artifact-consumer-matrix.md`
- [x] `docs/architecture/artifact-capability-matrix.md`
- [x] `docs/architecture/artifact-evidence-levels.md`
- Ziel: Profile als Presets dokumentieren, Evidence-Level von Profilnamen trennen und Pre-/Post-Health als zweistufiges Modell festlegen.
- Hinweis: `content_parity_pass`/`diagnostic_parity_pass` bleiben dokumentierte Testsemantik und werden hier nicht als bereits erzwungenes Runtime-Gate umdefiniert.

PR 7 (Anti-Hallucination Output Architecture, docs-first):
- [x] `docs/proofs/anti-hallucination-capability-audit.md` (Befund/Falsifikation Plan vs. Repo)
- [x] `docs/blueprints/lenskit-anti-hallucination-output-architecture.md` (reconciled Roadmap)
- Ziel: Output-/Beleg-Härtung risiko-getaktet vor neue Agentenintegrationen stellen; bestehende Arbeitspakete A–H härten statt duplizieren.
- Epistemische Korrektur: keine Auto-Claim-Bewertung (`supported/unsupported`); Lenskit adressiert Belege, bewertet sie nicht (`docs/blueprints/lenskit-output-optimierung-v1.md` AP F angepasst).
- Gate: keine neuen gated Integrationen (MCP/Task Pack/Dashboard) vor Anti-Hallucination-Lint + agent-safe Gate + `context_risk`-Pflicht.
- Umsetzungsstand Milestones A/B (Beleg: git log + Blueprint-Markierungen + Proofs):
  A1 (Agent Reading Pack Begriffshärtung), A3 (Range-Ref v2), A4 (Post-emit Bundle Health),
  A5 (Agent Export Gate / Redaction Enforcement) sind **UMGESETZT**. B1 (Context Quality
  Signals) ist mit dieser PR **UMGESETZT** (Details unter PR 8). Nächster offener
  Umsetzungs-PR: **B2 (Retrieval Miss Taxonomy)** — separat, nicht in B1 enthalten.

PR 8 (Milestone B1 — Context Quality Signals): **UMGESETZT**
- Scope: minimale, additive **diagnostische Projektion** vorhandener Signale; **kein** neuer
  Wahrheitslayer. Beleg: `docs/proofs/context-quality-signals-proof.md`,
  Blueprint `lenskit-anti-hallucination-output-architecture.md` §3 (B1).
- Geänderte/ergänzte Dateien:
  - `merger/lenskit/core/context_quality.py`
  - `merger/lenskit/contracts/context-quality.v1.schema.json`
  - `merger/lenskit/cli/cmd_context_quality.py` (Dispatch in `merger/lenskit/cli/main.py`)
  - `merger/lenskit/tests/test_context_quality.py`
  - `merger/lenskit/tests/test_cli_context_quality.py`
  - `docs/proofs/context-quality-signals-proof.md`
- Artefakt: `<stem>.context_quality.json` (`authority: diagnostic_signal`, `risk_class:
  diagnostic`); Kopf-Feld `projection_status` (`complete|degraded|blocked`) = nur
  Projektions-Vollständigkeit, **kein** globaler Verdict.
- CLI: `lenskit context-quality inspect <manifest> [--json] [--emit-artifact] [--output PATH]`.
- Nicht-Ziele (weiterhin aufrecht, bewusst aufgeschoben):
  - **kein** globaler Verstehens-Verdict (kein `understanding_health`),
  - **kein** aggregierter Score,
  - **keine** Claim-Wahrheitsbewertung,
  - **kein** Retrieval-Vollständigkeitsbeweis,
  - **kein** Antwort-Sicherheits-Gate,
  - **keine** Manifest-Mutation/-Registrierung (Artefakt bleibt unregistriert),
  - **keine** B2 Retrieval Miss Taxonomy in dieser PR.
- Validierung:
  - `ruff check --select=F401,F811 --exclude='**/fixtures/**' .` (passed)
  - `python3.11 -m pytest merger/lenskit/tests/test_context_quality.py merger/lenskit/tests/test_cli_context_quality.py` (24 passed)
  - `python3.11 -m pytest merger/lenskit/tests/test_output_health.py merger/lenskit/tests/test_post_emit_health.py merger/lenskit/tests/test_cli_bundle_health.py merger/lenskit/tests/test_bundle_manifest_integration.py` (93 passed, keine Regression)
- B2 wurde mit PR 9 als **separates Arbeitspaket** umgesetzt; spätere Ranking-/Reranking-
  und Retrieval-Verbesserungsarbeit bleibt als eigenes Folgepaket offen.

PR 9 (Milestone B2 — Retrieval Miss Taxonomy, separat): **UMGESETZT**
- Scope: additive **diagnostische Klassifizierungsschicht** für Retrieval-Eval-Misses;
  **keine** Wahrheitsbehauptungen, **keine** Repo-Abwesenheitsansprüche, **keine** Ranking-Änderungen.
  Beleg: `docs/proofs/retrieval-miss-taxonomy-proof.md`.
- Geänderte/ergänzte Dateien:
  - `merger/lenskit/retrieval/eval_core.py` erweitert: `classify_miss()`, `build_miss_taxonomy()`
  - `merger/lenskit/contracts/retrieval-eval.v1.schema.json` erweitert um `miss_taxonomy` (optional, backward-compatible)
  - `merger/lenskit/tests/test_retrieval_eval.py` erweitert: B2-Tests inkl. `query_execution_error` und Contract-Shape-Guards
  - `docs/proofs/retrieval-miss-taxonomy-proof.md` (diese Proof-Datei)
- Artefakt: `miss_taxonomy` Feld in `retrieval_eval.json` (`authority: diagnostic_signal`,
  `risk_class: diagnostic`); Klassifizierungen sind **mechanisch**, nicht semantisch.
- Miss-Typen (konservativ, additive zu Retrieval-Eval):
  - `zero_results` — Query returned no results
  - `expected_not_in_top_k` — Eval-declared expected pattern was not observed in returned top-k paths
  - `path_or_symbol_metadata_missing` — Insufficient metadata for classification
  - `stale_eval_input` — Eval run/artifacts were marked stale; diagnostic annotation only
  - `query_execution_error` — Query execution failed; technical failure, not a retrieval miss hit-signal
  - `unknown` — Fallback when no classification possible
- Compare-Mode-Scope (B2 v1): klassifiziert wird die top-level aktive Eval-Sicht (`details[]`).
  Eingebettete `baseline`-Blöcke dienen als Evidenz, werden aber nicht separat als eigene B2-Taxonomie ausgewertet.
- Erforderliche `does_not_prove` Einträge (hardcoded):
  - `absence_of_retrieval_hit_does_not_prove_absence_in_repository`
  - `miss_type_does_not_prove_claim_truth_or_falsehood`
  - `ranking_position_does_not_prove_semantic_importance`
  - `retrieval_eval_does_not_prove_retrieval_completeness`
  - `taxonomy_is_diagnostic_not_authoritative`
- Nicht-Ziele (weiterhin aufrecht, bewusst aufgeschoben):
  - **keine** Repository-Abwesenheitsbehauptung,
  - **keine** Claim-Wahrheitsbewertung,
  - **keine** Ranking-/Reranking-Änderungen,
  - **keine** Manifest-Registrierung,
  - **keine** globalen Scores oder Verdicts,
  - **keine** Modifikation von B1 (Context Quality Signals),
  - **keine** Agentenintegration-Gates (später, mit Anti-Hallucination-Lint).
- Validierung:
  - `ruff check --select=F401,F811 --exclude='**/fixtures/**' .` — PASSED
  - `python3 -m pytest merger/lenskit/tests/test_retrieval_eval.py -v` — 35 PASSED
  - `python3 -m pytest merger/lenskit/tests/test_retrieval_eval.py -k "miss_taxonomy or classify_miss" -v` — selected tests PASSED
  - Schema validation: `jsonschema.validate(retrieval_eval_output, schema)` — PASSED
- Backward-Kompatibilität:
  - Old retrieval_eval ohne `miss_taxonomy` validiert noch (Feld ist optional)
  - Existierende Retrieval-Metriken (recall@K, MRR, hits, zero_hit_ratio, stale_flag) unverändert
  - Keine Mutation bestehender Artefakte oder CLIs
- Python-Version: 3.10.12 (lokal getestet; `python3.11` lokal nicht vorhanden)
- B2 bleibt **separates Arbeitspaket** von B1; keine Vermischung diagnostischer Schichten.

PR 10 (Suboptimalitäten-Audit, 2026-05-25): **TEILWEISE UMGESETZT**
- Scope: Repo-weiter Sweep auf Drift/Inkonsistenzen/Tech-Debt; sichere, eng abgegrenzte
  Fixes sofort, größere Punkte getrackt. Vollbefund: `docs/architecture/inconsistencies.md` §7.
- Behoben (verifiziert: Python-/Repo-Testlauf 1456 passed / 1 skipped; zusätzlich wurden
  7 vorbestehende Browser-/Playwright-Errors beobachtet, ohne Bezug zu diesem Audit-Patch):
  - MD5-Härtungs-Konsistenz: `usedforsecurity=False` + `# nosec B303` an `merge.py:2674`
    und `adapters/sources.py:318` (Angleichung an kanonisches Muster, verhindert bandit-B303-Drift).
  - Debug-`print`-Ausgaben von stdout auf `sys.stderr` umgestellt (`merge.py:3330,3401-3404,3654,4975`),
    damit aktiver `debug` den maschinenlesbaren Daten-Kanal nicht verschmutzt.
  - `lenskit verify` von Platzhalter-No-op auf echten contract-Verifier verdrahtet
    (`pr_schau_verify.run_verify()`, `pr-schau.v1`); Standalone-`main()`-Verhalten erhalten;
    Verifier-Tests erweitert.
  - Irreführender `DEPRECATED`-Hinweis an `build_agent_query_session` (v1) korrigiert: v1 (Datei-Artefakt
    mit Integrity/Environment, CLI `--trace`) und v2 (Runtime-Inline, Service) sind parallele Formen,
    keine Migration ohne Datenverlust.
  - Test-Lint-Debt (18× F841/E712 in 13 Test-Dateien) bereinigt; `ruff` mit `F401,F811,F841,E711,E712` sauber.
- Offen (getrackt, bewusst nicht blind geändert):
  - ~~Atlas-CLI-Subparser-Duplikation `cli/main.py` ↔ `cli/rlens.py` zentralisieren.~~ **UMGESETZT** (2026-05-27): `register_atlas_commands` + `handle_atlas_command` in `merger/lenskit/cli/cmd_atlas.py` als Single Source of Truth; beide Entry-Points konsumieren den Registrar. Beleg: `inconsistencies.md` §7 (Status "behoben").
  - Audit breiter `except Exception: pass`-Blöcke in Kern/Service (defensive Pfade nicht pauschal ändern). **Teilweise umgesetzt (2026-05-27):** dokumentierter Kern/Service-Slice in `core/merge.py`, `service/app.py` und `service/jobstore.py` auf gezielte `logger.debug`-/`logger.warning`-Pfadklassifikation umgestellt; kein Logging-Rundumschlag, weitere stille Defensivpfade bleiben als separater Sweep offen.
  - Konsolidierungs-Entscheidung `agent_query_session` v1/v2 (Design-Blueprint: `docs/blueprints/agent-query-session-v1-v2-consolidation-decision.md`).
- Nicht-Ziele: keine Massen-Stilkorrektur (E701/E402/E741 sind bewusst nicht im CI-Gate),
  keine Schema-/Verhaltensänderung an emittierten Artefakten.
