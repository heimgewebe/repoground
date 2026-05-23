# Lenskit Anti-Hallucination Output Architecture (Reconciled)

Status: Blueprint (docs-first, diagnose-first).
Beziehung zu bestehenden Docs: **Diese Datei ersetzt nichts.** Sie reconciled einen
extern vorgeschlagenen Anti-Hallucination-Plan mit dem realen Repo-Stand und ordnet
ihn in die bestehende Reihenfolge ein:
- Befund/Falsifikation: `docs/proofs/anti-hallucination-capability-audit.md`
- Bestehende Arbeitspakete A–H: `docs/blueprints/lenskit-output-optimierung-v1.md`
- Globale Reihenfolge/Gates: `docs/roadmap/lenskit-master-roadmap.md`
- Profile/Evidence/Health: `docs/blueprints/lenskit-artifact-output-control-plane.md`

Wenn ein Punkt hier einem bestehenden Arbeitspaket entspricht, wird **das bestehende
Paket gehärtet**, kein Parallelartefakt gebaut. Neue Begriffe stehen nie neben alten
ohne Migrationsnotiz.

---

## 0. Kernthese

Lenskit soll **nicht** zum Erklär-LLM werden. Lenskit erzeugt **belegbare Bedingungen**,
unter denen ein LLM Bedeutung sicherer erschließt. Der perfekte Plan sortiert nicht nach
konzeptioneller Eleganz, sondern nach **dump-/repo-belegtem Risiko**: erst reale
Output-Schäden schließen, dann Authority/Risk normieren, dann repo-eigene Lesart, dann
strukturierte Navigation, dann kuratierte Semantik, zuletzt gated Integrationen.

## 1. Invarianten (Leitplanken)

1. Keine freie Lenskit-Interpretation; keine automatische Architektur-Erzählung.
2. **Keine automatische Claim-Bewertung** (`supported/unsupported/true/false/proven`).
3. Keine unqualifizierten Purpose-/Meaning-/Important-Claims in generierten Feldern.
4. Jede Navigation hat Resolve-Pflicht (`must_resolve_to: role_specific_authority`).
5. Runtime-/Retrieval-Kontext ist Beobachtung, nicht Repo-Wahrheit.
6. Repo-declared context (`.lenskit/`) ist deklarierte Navigation, nicht Inhaltswahrheit.
7. Safe Export (Profil/Redaction) ist nicht dasselbe wie Output Health.
8. Caches/Tooling-Artefakte erscheinen nie als Repo-Kontext (nur als Diagnose).
9. Range-Refs trennen Source- und Artifact-Achsen.
10. `canonical_md` bleibt einzige Inhaltswahrheit; `bundle_manifest` Artefaktwahrheit;
    Schemas Vertragswahrheit; `query_trace`/Sessions Runtime-Beobachtung.

## 2. Zielzustand (Rollen)

```
Repo            -> deklariert Lesart und Grenzen (.lenskit/, optional)
Lenskit         -> sammelt, validiert, adressiert, klassifiziert, warnt
LLM             -> interpretiert, erklärt, synthetisiert
canonical_md    -> Inhaltswahrheit
bundle_manifest -> Artefakt-/Metadatenwahrheit
schemas         -> Vertragswahrheit
query_trace     -> Runtime-Beobachtung
repo_declared_* -> kuratierte Navigation, nicht Wahrheit
```

---

## 3. Optimierte Roadmap (reconciled)

Reihenfolge bleibt risiko-getaktet (A vor B vor … vor G). Jeder PR nennt das bestehende
Arbeitspaket (AP), das er härtet, oder markiert sich als **neu**.

### Milestone A — Akute Output- und Beleg-Härtung

#### PR A0 — Capability + Output Risk Audit  (Status: erledigt durch diese Doku-PR)
- **Ziel:** Vor jedem neuen Artefakt belegen, was existiert/leckt/geplant ist.
- **Repo-Befund:** `docs/proofs/anti-hallucination-capability-audit.md`.
- **Änderung:** Audit + diese reconciled Roadmap; surgische Doku-Korrekturen
  (README, output-optimierung-v1, inconsistencies, master-roadmap).
- **Nicht-Ziele:** Keine Code-/Schema-Änderung.
- **Akzeptanz:** Jede Folge-PR referenziert eine Audit-Zeile.

#### PR A1 — Agent Reading Pack Begriffshärtung  (härtet AP D) — **UMGESETZT**
- **Ziel:** Navigationsbegriffe entschärfen; Importance-Implikation entfernen.
- **Ergebnis (PR A1 umgesetzt: Producer/Tests/Doku migriert `TOP_FILES → TOP_CHUNK_SPANS`):**
  - Heading `## TOP_FILES` → `## TOP_CHUNK_SPANS` in Producer + Tests + Proof-Doku.
  - Maschinenlesbarer Governance-JSON-Block im Pack:
    `applies_to: TOP_CHUNK_SPANS`, `risk_class: navigation`, `may_cite: false`,
    `must_resolve_to: role_specific_authority`,
    `does_not_prove: [semantic_importance, architecture_truth, complete_context]`.
  - README-Beschreibung auf `TOP_CHUNK_SPANS` ohne Wichtigkeitsanspruch.
  - Neue Negativtests: `test_agent_pack_no_top_files_heading`,
    `test_agent_pack_no_important_language`, `test_agent_pack_declares_does_not_prove`,
    `test_agent_pack_governance_block_fields`, `test_agent_pack_has_no_top_level_architecture`,
    `test_agent_pack_governance_block_is_valid_json` (JSON parsen, nicht nur strings).

#### PR A2 — Output Noise Hygiene härten  (härtet #681–#683)
- **Ziel:** Hard-Exclusion absichern + sichtbar machen; Listendrift beseitigen.
- **Repo-Befund:** `merger/lenskit/core/merge.py:297-314` (`SKIP_DIRS` deckt Caches), `:2277` (Walk-Filter);
  `merger/lenskit/core/merge.py:1772-1780` (`is_noise_file.noisy_dirs` ohne `.ruff_cache/.pytest_cache/
  .mypy_cache`); `merger/lenskit/core/lenses.py:87` (Fallback `core`).
- **Änderung:**
  - `is_noise_file` aus `SKIP_DIRS` ableiten statt Parallelliste pflegen.
  - Regressions-Guard: Cache-Dirs nie in canonical/chunk/sqlite/agent-navigation.
  - Optionales Diagnose-Artefakt/Block `excluded_noise[]` mit `{path, reason,
    not_repo_context:true}` (nur in Diagnose, nie in Inhalt/Navigation).
- **Nicht-Ziele:** Keine neue Hard-Exclusion-Semantik; kein Hard-Fail vor Diagnose.
- **Akzeptanz:** Guard-Test grün; `include_hidden` behält `.github`/`.wgx`, exkludiert
  Caches; `excluded_noise` nur in Diagnose.
- **Tests:** `test_cache_dirs_not_in_canonical_md`, `…_chunk_index`, `…_sqlite_index`,
  `test_cache_dirs_may_appear_only_in_excluded_noise`,
  `test_include_hidden_keeps_github_and_wgx_but_excludes_caches`,
  `test_is_noise_file_consistent_with_skip_dirs`.
- **Risiko:** niedrig; ggf. Snapshot-Diffs durch `excluded_noise`.

#### PR A3 — Range-Ref v2  (= AP B; reuse Blueprint)
- **Ziel:** Source- und Artifact-Achsen schema-seitig trennen.
- **Repo-Befund:** `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md`; `docs/architecture/range-semantics.md`; nur
  `merger/lenskit/contracts/range-ref.v1.schema.json`; AP B `[ ]`.
- **Änderung:** `merger/lenskit/contracts/range-ref.v2.schema.json` mit `artifact_role`,
  `artifact_path`, `artifact_line_start/end`, `source_file_path`,
  `source_line_start/end`, `content_sha256`, `range_content_sha256`,
  `range_ref_version:"2"`. v1 bleibt lesbar; Resolver akzeptiert v1+v2; neue
  Agent-/Context-/Citation-Outputs bevorzugen v2.
- **Nicht-Ziele:** Kein Resolver-Caching; keine Manifest-Schema-Brüche; v1 nicht löschen.
- **Akzeptanz:** v2-Schema validiert; Roundtrip trennt Achsen; v1→Resolver unverändert.
- **Tests:** `test_range_ref_v2_schema`, `test_range_roundtrip_artifact_and_source_lines`,
  `test_range_ref_v1_backwards_compatible`, `test_citation_resolve_prefers_v2`.
- **Risiko:** Feldnamen-Verwechslung — durch klare Achsenpräfixe (`artifact_`/`source_`)
  mitigiert.

#### PR A4 — Post-hoc Bundle Validator  (= AP H; reuse `post_emit_health`)
- **Ziel:** Vollständiges Bundle nach Emission prüfen (Health kennt den Pack in-pipeline
  noch nicht).
- **Repo-Befund:** `merger/lenskit/core/output_health.py:424-466`; `docs/blueprints/lenskit-artifact-output-control-plane.md` §2.4
  (`post_emit_health`); `docs/architecture/artifact-evidence-levels.md` (`post_emit_validation_available`).
- **Änderung:** `post_emit_health` (Datei `<stem>.bundle_health.post.json`) bzw. CLI
  `lenskit bundle-health post <manifest> --json`: prüft Manifest-/Artefakt-Hashes,
  `agent_reading_pack` presence/hash, Self-Role nicht gelistet, Range-Ref-Resolution,
  Redaction-Status, Noise-Hygiene, erreichten Evidence-Level. Statusmodell
  `pass|warn|fail|blocked` plus `does_not_mean: [repo_understood,
  answer_safe_without_citations]`.
- **Nicht-Ziele:** `output_health`/`pre_emit_health` **nicht** auf Redaction umbiegen;
  kein paralleles "agent-ready"-Vokabular neben `post_emit_health`.
- **Akzeptanz:** `output_health.verdict=pass` impliziert nie automatisch
  `post_emit_health=pass`.
- **Tests:** `test_post_emit_health_requires_agent_pack`,
  `test_post_emit_health_independent_of_pre_health`,
  `test_post_emit_health_reports_evidence_level`.
- **Risiko:** mittel; additiv eingeführt, Consumer lesen weiter `output_health`.

#### PR A5 — Safe Output Profiles / agent-safe Gate  (= AP E; reuse control-plane-Namen)
- **Ziel:** Export-Sicherheit profilbasiert erzwingen; Redaction an agent-safe koppeln.
- **Repo-Befund:** **Namens-Drift** AP E (`max-private/agent-safe/…`) vs
  `docs/blueprints/lenskit-artifact-output-control-plane.md` §7
  (`agent-portable/local-search/…`); `merger/lenskit/core/redactor.py`; `capabilities.redaction`.
- **Änderung:** control-plane-Namen sind kanonisch. Mapping der Plan-Intents:
  `agent-safe → agent-portable + redact_secrets=true + require post_emit_health`;
  `max-private → debug-full/local intern, agent_export=false`. Profil-Gate validiert vor
  Export (missing dependency, unsupported capability, impossible evidence level,
  redaction off bei agent_export).
- **Nicht-Ziele:** Kein zweites Profilschema; kein Export ohne Redaction bei agent_export.
- **Akzeptanz:** agent_export mit `redact_secrets=false` → `fail`; `max-private` nicht
  agent-exportierbar.
- **Tests:** `test_agent_safe_requires_redaction`,
  `test_max_private_not_agent_exportable`, `test_agent_safe_requires_post_emit_health`.
- **Risiko:** mittel; Profil-Engine ist control-plane Phase C.

### Milestone B — Kontextqualität und Retrieval-Realismus

#### PR B1 — Context Quality Signals  (scope: Projektion, kein neuer Wahrheitslayer) — **UMGESETZT**
- **Ziel:** Kontextbedingungen transparent machen — **keine** globale Verstehensampel.
- **Repo-Befund (Stand nach B1):** `context_quality` ist umgesetzt; `<stem>.context_quality.json`
  überlappt bewusst nicht `docs/architecture/artifact-evidence-levels.md`, sondern **projiziert**
  den dort definierten erreichten Evidence-Level (aus `post_emit_health`) zusammen mit weiteren
  vorhandenen Signalen. (Frühere Annahme „kein `context_quality.json`" ist überholt.)
- **Ergebnis (PR B1 umgesetzt: Schema/Core/CLI/Tests/Proof additiv):**
  - `merger/lenskit/contracts/context-quality.v1.schema.json` (neuer lokaler Contract).
  - `merger/lenskit/core/context_quality.py` — `compute_context_quality` (rein) +
    `write_context_quality` (optional persistierend, **keine** Manifest-Mutation/-Registrierung).
  - `<stem>.context_quality.json` als **Projektion** vorhandener Signale (Manifest-Rollen +
    `output_health`-Checks + `post_emit_health`-Status/Evidence-Level + `retrieval_eval`-Metriken
    + optional `agent_export_gate`), `authority: diagnostic_signal`, `risk_class: diagnostic`, mit
    `agent_use_constraints` und `does_not_mean: [repo_understood, retrieval_complete,
    answer_safe_without_citations, claims_true]`. **Kein** `understanding_health`, **kein**
    Gesamt-Score. Kopf-Feld ist `projection_status` (`complete|degraded|blocked`), **kein**
    globaler Verdict.
  - CLI `lenskit context-quality inspect <manifest> [--json] [--emit-artifact] [--output PATH]`.
  - Tests: `merger/lenskit/tests/test_context_quality.py`,
    `merger/lenskit/tests/test_cli_context_quality.py` (inkl. der benannten Invarianten
    „has_no_global_understanding_verdict" und „is_projection_of_existing_signals" in
    `test_named_blueprint_invariants`, plus Forbidden-Vocabulary-Walk).
  - Beleg: `docs/proofs/context-quality-signals-proof.md`.
- **Nicht-Ziele (eingehalten):** Keine neue Bewertung; keine Aggregation zu einer Ampel; keine
  Claim-Wahrheit; **keine** B2 Miss-Klassifikation (bleibt separat).
- **Akzeptanz:** Kein globaler Verstehens-Verdict im Artefakt (Negativtest grün); C2-Lint kann
  später dieselbe Invariante erzwingen.
- **Risiko:** Doppelung mit Evidence-Level — daher strikt als Projektion definiert.

#### PR B2 — Retrieval Miss Taxonomy  (neu, über AP-Eval)
- **Ziel:** Retrieval-Schwächen mechanisch klassifizieren (vor Task-Packs/MCP).
- **Repo-Befund:** `merger/lenskit/retrieval/eval_core.py`, `merger/lenskit/contracts/retrieval-eval.v1.schema.json`.
- **Änderung:** `<stem>.retrieval_miss_taxonomy.json` über vorhandenem Eval; erlaubte
  `miss_class`: `zero_results`, `expected_path_not_in_top10`,
  `expected_symbol_not_in_top10`, `filter_excluded_expected`,
  `expected_target_missing_from_bundle`, `stale_expected_target`,
  `ambiguous_query_many_domains`; je Miss `mechanical_hints` + `does_not_prove:
  [target_absent, semantic_irrelevance]`.
- **Nicht-Ziele:** Keine Klassen `semantic_confusion/probably_unimportant/user_meant_x`.
- **Akzeptanz:** Jeder Miss eines Eval-Laufs ist klassifiziert; keine semantische Deutung.
- **Tests:** `test_retrieval_miss_only_mechanical_classes`,
  `test_retrieval_miss_does_not_prove_absence`.
- **Risiko:** niedrig (diagnostisch).

#### PR B3 — Context Bundle Resolve Discipline  (härtet `query-context-bundle.v1`)
- **Ziel:** Context Bundles sind Auswahlspuren, keine Wahrheitsbündel.
- **Repo-Befund:** `merger/lenskit/contracts/agent-query-session.v2.schema.json` hat
  `session_authority`+`claim_boundaries`;
  `merger/lenskit/contracts/query-context-bundle.v1.schema.json` hat nur `resolver_status`.
- **Änderung:** additiver `context_risk`-Block (`retrieval_based_subset`,
  `missing_relevant_context_possible`, `may_answer_from_this_directly:false`,
  `*_claims_resolve_to: {content:canonical_md, metadata:bundle_manifest,
  schema:schema, runtime:query_trace}`).
- **Nicht-Ziele:** Keine Pflichtfeld-Brüche für bestehende Consumer (additiv/optional
  bis Consumer-Test).
- **Akzeptanz:** Bundle deklariert Resolve-Pflicht; Consumer-Test grün.
- **Tests:** `test_context_bundle_declares_context_risk`,
  `test_context_bundle_v1_backwards_compatible`.
- **Risiko:** mittel — additiv halten, Consumer in `artifact-consumer-matrix.md` prüfen.

### Milestone C — Authority/Risk operationalisieren

#### PR C1 — Authority Matrix + Risk Classes normieren  (härtet vorhandene Authority)
- **Ziel:** Vorhandene Authority/Canonicality normieren, `risk_class` **additiv** ableiten.
- **Repo-Befund:** `docs/architecture/artifact-inventory.md` Authority/Canonicality; `AUTHORITY_REGISTRY`
  in `merger/lenskit/core/merge.py`.
- **Änderung:** `risk_class` aus Authority ableiten (`canonical_content→canonical`,
  `navigation_index→navigation+must_resolve`, `diagnostic_signal→diagnostic`,
  `runtime_*→runtime_observation`, heuristisch→`heuristic`), in der Matrix dokumentiert.
- **Nicht-Ziele:** Authority nicht ersetzen/duplizieren.
- **Akzeptanz:** Jede Rolle hat abgeleitete `risk_class`; Navigation hat `must_resolve`.
- **Tests:** `test_every_role_has_risk_class`, `test_navigation_roles_must_resolve`.

#### PR C2 — Anti-Hallucination Lint  (neu, Kernhebel)
- **Ziel:** Invarianten als erzwungenes Gate, statt als Prosa.
- **Repo-Befund:** existiert nicht.
- **Änderung:** `lenskit anti-hallucination lint <bundle-or-repo>` prüft:
  100% neue Artefakte mit `authority`+`risk_class`; Navigation mit `must_resolve`;
  Runtime-Outputs mit `context_risk`; 0 unqualifizierte Purpose/Architecture-Summaries;
  0 `supported/unsupported`-Verdikte; 0 Cache-Dirs in canonical/agent-navigation; 0
  globale Verstehens-Verdicts. Forbidden-language nur in **generierten** Feldern ohne
  `evidence_mode`/`not_evidence`.
- **Nicht-Ziele:** Kein Lint über Inhaltswahrheit (`canonical_md` darf alles enthalten).
- **Akzeptanz:** Lint blockiert in CI bei Verstoß; läuft grün auf aktuellem Output.
- **Tests:** `test_lint_flags_supported_unsupported`,
  `test_lint_flags_unqualified_importance`, `test_lint_passes_clean_bundle`.
- **Risiko:** mittel — Forbidden-language-Heuristik muss canonical-Inhalt verschonen.

### Milestone D — repo-owned Kontext  (defer hinter A–C-Gates)

- **PR D1** `.lenskit/` Blueprint + Schema (`repo-profile.yml`, `authority-map.yml`,
  `do-not-assume.md`), Rolle `repo_declared_context`, `authority: declared_navigation`,
  `may_cite_as_content_truth:false`, `must_resolve_to: role_specific_authority`.
- **PR D2** `lenskit repo-context validate/inspect`: schema-valid, `evidence_refs`
  existieren, keine Felder `true/proven/supported`, `declared_purpose` braucht
  `source_kind`+`evidence_refs`+`does_not_establish`.
- **PR D3** Ingest in Agent Pack als `## REPO_DECLARED_CONTEXT` mit Warnung
  "declared navigation, not content truth".
- **Gate:** erst nach C2 (Lint) — sonst entsteht ein neuer Deutungslayer ohne Schutz.

### Milestone E — strukturierte Navigation  (defer)

- **PR E1** Structural `repo_map.v1` (mechanische Karte: `path/category/layer/
  layer_source/not_evidence`; `unknowns`), `risk_class: navigation`, `may_cite:false`.
  Verboten: `purpose/meaning/architecture_role/importance`.
- **PR E2** Context Profiles (Suchraumgrenzen; `include_paths/exclude_paths/
  truth_sources/navigation_sources`); `include_features` nur bei `.lenskit/`-Definition.
- **PR E3** Structural Architecture Signals — **in AP G falten**, kein Parallelartefakt;
  Flows/Producer nur mit `evidence_mode` (`human_curated/doc_seed/static_callgraph/
  contract_reference`), `confidence`, `not_evidence:true`.

### Milestone F — kuratierte Semantik  (ersetzt AP F-Verdikt-Logik)

- **PR F1** Declared Flows (nur repo-owned, `status: human_curated`, `does_not_prove`).
- **PR F2** Declared Claims (nur explizit, `source_kind: doc_declared`, `evidence[]`,
  `does_not_establish`).
- **PR F3** Claim Evidence References: `claim → evidence_refs` + `relation:
  citation_attached` + `does_not_establish: [truth, sufficiency, causality,
  completeness]`. **Verboten:** `auto_extracted/supported/unsupported/true/false/proven`.
  → **Löst den Widerspruch zu AP F** (siehe Audit §2.6): kein Verdikt, nur Referenz.

### Milestone G — gated Integrationen  (= master-roadmap Phase 5+)

MCP read-only, Task Pack, Search Jobs, Monitors, Dashboard, LLM-generated summaries —
**erst** wenn: Lint grün, agent-safe Gate aktiv, `context_risk` Pflicht, Range-Ref v2
aktiv, 0 Cache-Dirs in canonical/agent-navigation, `.lenskit/` validierbar, Navigation
mit `must_resolve`. MCP read-only erlaubt nur:
`lenskit.query/citation.resolve/artifact.read/context_quality.inspect/
repo_context.inspect`. Verboten: `shell_exec/direct_write/secret_read/auto_patch`.

---

## 4. Harte Stop-Regeln

- Vor A4 kein `post_emit_health=pass`/agent-ready-Aussage.
- Vor A5 kein Agentenexport ohne Redaction.
- Vor A3 keine neuen Kontextartefakte, die Range-Refs als endgültig zitierfähig zeigen.
- Vor B2 kein Task Pack auf Retrieval-Basis.
- Vor C2 keine neuen semantischen Output-Artefakte und keine `.lenskit/`-Ingestion.
- Generell: keine Auto-Claim-Bewertung, keine Auto-Architektur-Prosa.

## 5. Messbare Zielgrößen

```
cache_dirs_in_canonical_content: 0
cache_dirs_in_agent_navigation: 0
agent_pack_top_files_label: 0
unqualified_important_language: 0
range_ref_v2_for_new_agent_outputs: 100%
output_health_pass_implies_post_emit_pass: false
agent_safe_with_redaction_false: fail
retrieval_misses_classified: 100%
navigation_artifacts_with_must_resolve: 100%
runtime_outputs_with_context_risk: 100%
claim_assessments_supported_unsupported: 0
```

## 6. Was bewusst nicht gebaut wird (siehe Audit §3)

`output_health` nicht auf Redaction umbiegen; kein paralleles agent-ready-Artefakt;
kein zweites Profilschema; kein `supported/unsupported`; keine globale Verstehensampel;
kein Parallelartefakt zu `architecture_summary`; keine Agentenintegration vor C2/A4/A5.

### Agent-facing Output Safety: Vibe-Lab Transfer Boundary

Reconciliation-Notiz (docs-only). Belegbasis:
`docs/proofs/vibe-lab-transfer-falsification.md`,
`docs/proofs/anti-hallucination-capability-audit.md`. Diese Notiz baut nichts; sie
grenzt ab und verweist auf bereits vorhandene Schutzflächen.

#### These / Antithese / Synthese
- **These:** Vibe-Lab liefert nützliche Fehlerklassen für Agentenarbeit.
- **Antithese:** Vibe-Lab-Strukturen dürfen nicht als Module nach Lenskit wandern.
- **Synthese:** Lenskit übernimmt nur epistemische Disziplin und Fehlerklassen, keine
  Vibe-Lab-Governance. Vibe-Lab bleibt Kontrastfolie, nicht Modulquelle.

#### Verbindliche Abgrenzung
Nicht übernommen (kein neues Agent-Operability-Subsystem):
1. kein `write_change`,
2. kein `validate_change`,
3. keine Agent-Command-Chain,
4. kein generisches Handoff-System,
5. kein neues Generated-Artifacts-Register,
6. keine Promotion-Readiness-Control-Plane,
7. keine automatische Claim-Bewertung (`supported/unsupported`).

#### Bestehende Lenskit-Schutzflächen (referenziert, nicht dupliziert)
- Agent Reading Pack — Navigation, nicht Wahrheit (u. a. Begriffshärtung um
  `TOP_CHUNK_SPANS`; Claim-Grenzen bleiben contract-bound).
- Bundle Manifest — Rollen, Authority, Hashes.
- Citation Map — Belegadressen.
- Query Result — Claim-/Evidence-Kontext, soweit durch bestehende Contracts abgebildet
  (`merger/lenskit/contracts/query-result.v1.schema.json` `claim_boundaries`).
- Agent Query Session — `session_authority = agent_context_projection`
  (`merger/lenskit/contracts/agent-query-session.v2.schema.json`).
- Runtime Lookup Artefakte — Beobachtung/Projektion, nicht kanonischer Content.
- Output Health — Integritätsdiagnostik, **kein** automatisches `agent-safe`.

#### Offene Härtung (spätere, nicht-blockierende Themen)
- Context Bundle kann später `context_risk`/stärkere Claim-Boundaries bekommen, sofern
  die bestehende Roadmap dies trägt.
- `claim_evidence_map` darf, falls nötig, nur `claim → evidence_refs` modellieren —
  **kein** Wahrheitsverdikt; nur Evidence-Referenzmodell.
- Runtime Boundary Fields bleiben außerhalb dieser Notiz
  (`docs/proofs/runtime-artifact-metadata-gap-audit.md`).

#### Falsifikationskriterien
Dieser Abschnitt ist falsch, sobald er: neue Artefakte/Schemas/Roadmaps fordert,
Vibe-Lab-Strukturen kopiert, `claim_evidence_map` als Sofortimplementierung empfiehlt,
`output_health=pass` als `agent-safe` deutet, oder bestehende Contracts dupliziert statt
referenziert.

## 7. Nächster PR

**PR A1 (Agent Reading Pack Begriffshärtung).** Kleinste sinnvolle Code-Einheit mit
direktem Risiko-Bezug: `TOP_FILES → TOP_CHUNK_SPANS` + `does_not_prove`-Block, Tests
angepasst, README/Proof-Doku nachgezogen. Voraussetzung erfüllt: A0 (Audit) liegt vor.
A2 (Noise-Hygiene-Härtung) kann parallel laufen, da unabhängiger Code-Pfad.
