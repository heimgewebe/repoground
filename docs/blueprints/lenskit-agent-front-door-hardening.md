---
doc_type: blueprint
status: active
task: TASK-AGENT-FRONTDOOR-001
---

# Lenskit Agent Front-Door Hardening Blueprint

## 0. Dokumentrolle und Einordnung

Dieser Blueprint ordnet die vollständige Roadmap für Front-Door-Härtung,
Nutzungsdisziplin und spätere deterministische Linsen in die bestehende Lenskit-
Architektur ein. Er ist ein **Planungsartefakt**, keine Implementierungs- oder
Runtime-Evidence.

Er ersetzt keine bestehenden Fachblueprints:

- `lenskit-output-optimierung-v1.md` bleibt die Herkunft und bestehende Roadmap des
  Agent Reading Pack.
- `lenskit-anti-hallucination-output-architecture.md` bleibt die übergreifende
  Authority-/Inference-Grenze und dokumentiert die bereits umgesetzte A1-
  Begriffshärtung.
- `lenskit-authority-risk-matrix.md` bleibt die Governance-Grundlage für Authority,
  Canonicality, Risk-Class und verbotene stille Authority-Upgrades.
- `lenskit-evidence-address-architecture.md` und die Range-Ref-Planung bleiben für
  Belegadressen zuständig.
- `lenskit-artifact-output-control-plane.md` bleibt für Profile, Artifact Roles und
  Health-/Capability-Grenzen zuständig.

Der Blueprint ergänzt diese Dokumente um eine noch fehlende Frage: **Wie wird die
vorhandene agent-facing Oberfläche so benutzt, dass Agents nicht bei linearem Lesen von
`canonical_md` stehen bleiben, ohne dass Lenskit selbst zum Agenten, Reviewer oder
Wahrheitsbewerter wird?**

Dieser Blueprint-PR ändert keine Producer, Contracts, Pipelines, Health-Gates, Services,
Frontends oder Retrieval-Implementierung. Jede Umsetzung erfolgt in einem eigenen,
begrenzten Folge-PR.

## 1. These, Antithese und Entscheidung

### These

Lenskit braucht zuerst keine neue Sidecar-Familie. Der größte kurzfristige Hebel ist die
vorhandene Front Door: Das Agent Reading Pack muss task-spezifisch erklären, welche
bereits vorhandenen Artefakte zu lesen sind und welche Aussagen daraus nicht folgen.

### Antithese

Markdown-Anweisungen allein sind nicht für alle späteren Wrapper-, CI- oder
Agent-Workflows ausreichend. Bei belegtem Bedarf können maschinenlesbare Required-
Reading-, Answer-Compliance- oder Consumption-Contracts sinnvoll werden.

### Synthese / Architekturentscheidung

1. Vorhandene Front Door härten.
2. Struktur und Nutzungserwartung testen.
3. Retrieval-Nutzen mit einem repo-eigenen Goldset messen.
4. Regeln zunächst als Markdown stabilisieren.
5. Erst danach und nur bei belegtem Bedarf contractisieren.
6. Primary Lenses auditieren, bevor Facets, Cards und Relations hinzukommen.
7. Retrieval v2 nur deterministisch und erst nach einer reproduzierbaren Baseline
   entwickeln.

## 2. Zielbild

Lenskit soll normale LLMs und Coding Agents bei Repo-Fragen, belegorientierten
PR-Reviews und späteren Patch-Vorbereitungen unterstützen, ohne selbst Agent, Reviewer
oder Patch-Automat zu werden.

### 2.1 Lenskit bleibt

- deterministisch
- read-first
- evidence-first
- range-strict
- contract-aware
- sidecar-aware
- nicht-agentisch
- ohne LLM-Core
- ohne Embedding-Pflicht
- ohne automatische Review-Urteile

### 2.2 Lenskit erzeugt oder adressiert

- eine kanonische Repo-Sicht
- Navigation und Artifact-Role-Grenzen
- Evidence-Adressen und auflösbare Bereiche
- Health-/Surface-Diagnostik
- Retrieval-Diagnostik
- task-spezifische Leseregeln
- später, nach eigenen Gates: Facets, Lens Cards und Relation Cards

### 2.3 Lenskit erzeugt nicht

- Inhaltswahrheit außerhalb `canonical_md`
- automatische PR-Findings oder Review-Verdicts
- Patch-Pläne als Handlungsanweisung
- Testvollständigkeitsurteile
- Runtime-Kausalitätsurteile
- unbelegte Impact-Wahrheiten
- CI-Freigaben durch LLM-ähnliche Bewertung

## 3. Repo-belegte Ausgangslage

### 3.1 Bereits vorhanden

In diesem Abschnitt bedeutet „vorhanden“, dass eine belegte Repo-Fläche aus
Contract, Core/Validator/Producer, Dokumentation oder fokussierten Tests
existiert. Dies impliziert nicht automatisch Bundle-Emission, Consumer-
Integration oder Runtime-Nutzung.

| Fläche | Aktuelle Rolle | Planungsrelevante Grenze |
| --- | --- | --- |
| `canonical_md` | kanonische Inhaltsquelle | bleibt einzige Inhaltswahrheit |
| Agent Reading Pack | `navigation_index` / `derived` | Einstieg und Navigation, keine Wahrheit |
| Bundle Manifest | Registry für Artifact Roles, Authority, Canonicality und Hashes | Artefaktwahrheit, keine Inhaltswahrheit |
| Citation Map | Belegnavigation | kein Wahrheits- oder Vollständigkeitsverdikt |
| Claim Evidence Map | Evidence-Index | keine Claim-Bewertung |
| Post-Emit-Health | finale Integritäts-/Oberflächendiagnose | `pass` bedeutet weder `repo_understood` noch `answer_safe_without_citations` |
| Bundle Surface Validation | Surface-/Link-Konsistenzdiagnose | `pass` bedeutet weder `claims_true` noch `forensic_ready` |
| Review Retrieval Goldset / Eval / Miss Taxonomy | versioniertes Review-Messset mit reproduzierbaren Metriken, Baseline und Miss-Diagnostik | diagnostische Oberfläche; beweist weder Review-Vollständigkeit noch ausreichende Retrieval-Qualität |
| Primary Lenses | `entrypoints`, `core`, `interfaces`, `data_models`, `pipelines`, `ui`, `guards` | Focus-Overlay; keine neuen IDs in diesem Plan |
| Primary Lens Audit | aufrufbare Contract-/Core-Fläche zur deterministischen Erklärung von `infer_lens()` | Contract/Core/Tests vorhanden; kein CLI, keine automatische Bundle-Emission, keine neue Primary Lens und keine Review-Priorität |
| Lens Cards v1 | optionale `navigation_index` / `derived` Cards, je genau ein akzeptierter Repo-Pfad | Contract/Core/Validation/Tests vorhanden; keine automatische Bundle-/Manifest-Emission, keine Artifact Role, keine Consumer-Integration, keine Review-/Safety-/Impact-Semantik |
| Required Reading Protocol | deterministische Auflösung der Pflichtartefakte je Task-Profil | definiert Leseanforderungen; beweist weder tatsächliches Lesen noch Antwortkorrektheit oder Repo-Verständnis |
| Answer Compliance Contract | maschinenlesbare Selbstdeklaration der für eine Antwort verwendeten Artefakte und Belege | beweist weder tatsächliches Lesen noch Antwortkorrektheit, Vollständigkeit oder Repo-Verständnis |
| Agent Consumption Trace | deterministische Prüfung deklarierter Nutzung gegen Required-Reading-Erwartungen | beweist kein tatsächliches Lesen, keine Antwortkorrektheit und kein Repo-Verständnis |
| Agent Entry Manifest Core | Contract, Producer und Tests für einen abgeleiteten Agent-Einstiegsindex | keine belegte automatische Bundle-Emission oder stabile Consumer-Integration; beweist kein Repo-Verständnis |

### 3.2 Noch nicht als stabile Repo-Fläche vorhanden

- harte Durchsetzung des Required Reading Protocol in Consumer- oder Export-Gates
- automatische Bundle-Emission und Consumer-Integration des Agent Entry Manifest
- automatische Bundle-Emission und Consumer-Integration des Facet Model (v1 Contract/Core/Tests vorhanden)
- automatische Bundle-/Manifest-Emission und Consumer-Integration von Lens Cards
- PR Delta Cards
- Relation Cards
- Guard Relation Cards

### 3.3 Review-Retrieval-Baseline
Das versionierte Review-Goldset, der Metrikadapter, die reproduzierbaren
Metriken und die Miss-Diagnostik sind implementiert.
Belege:
- `docs/retrieval/review_queries.v1.json`
- `merger/lenskit/retrieval/review_eval.py`
- `merger/lenskit/tests/test_review_retrieval_goldset.py`
- `merger/lenskit/tests/test_review_retrieval_metrics.py`
- `docs/diagnostics/review-retrieval-baseline.md`
Konkrete Metrikwerte werden gegen einen gewählten Index reproduziert und
nicht als zeitlose Leistungszahlen dieses Blueprints festgeschrieben.
Die Baseline ist eine diagnostische Messfläche. Sie beweist weder
ausreichende Retrieval-Qualität noch Review-Vollständigkeit oder
semantische Abdeckung.

## 4. Problem

Lenskit besitzt bereits nützliche Navigations-, Evidence- und Diagnoseflächen. Lesende
LLMs oder Coding Agents können diese Flächen trotzdem ignorieren und ausschließlich
`canonical_md` linear lesen. Dann bleiben vorhandene Belegadressen, Surface-Diagnosen,
Claim-Grenzen und Retrieval-Metriken praktisch ungenutzt.

Das primäre Problem lautet deshalb nicht „Lenskit hat zu wenig Artefakte“, sondern:

> Lenskit hat eine umfangreiche agent-facing Oberfläche, aber noch keine ausreichend
> sichtbare, task-spezifische Front Door für deren disziplinierte Nutzung.

## 5. Architekturprinzipien

### 5.1 Front-Door-Prinzip

Das Agent Reading Pack ist die zentrale menschlich und maschinell lesbare Einstiegsfläche.
Neue agent-facing Sidecars dürfen erst geplant werden, wenn ihre Rolle dort sichtbar,
task-spezifisch begründet und gegenüber `canonical_md` abgegrenzt werden kann.

### 5.2 Keine Sidecar-Inflation vor Nutzungsbeleg

Ein formal aussehendes Problem rechtfertigt nicht automatisch ein neues JSON-Artefakt.
Markdown-Härtung, Tests und Messung kommen vor neuen Consumption-Subsystemen.

### 5.3 Task-Profile statt Pauschalpflicht

Nicht jede Frage benötigt alle Artefakte. Die erste verbindliche Profilmenge ist:

- `basic_repo_question`
- `pr_review`
- `roadmap_status_claim`
- `artifact_surface_review`
- `retrieval_quality_review`

Spätere Kandidaten wie `patch_preflight`, `contract_change_review` oder
`security_review` werden nicht in Slice 1 aufgenommen. Sie benötigen eigene Use Cases
und Akzeptanzkriterien.

### 5.4 Negativsemantik überall

Jede neue oder geänderte agent-facing Navigations-, Diagnose- oder Consumption-Fläche
muss explizit sagen, was sie nicht etabliert. Mindestens zu berücksichtigen sind:

```text
truth
correctness
completeness
repo_understood
answer_safe_without_citations
test_sufficiency
runtime_behavior
regression_absence
```

Die konkrete Contract-Sprache darf je vorhandener Fläche `does_not_mean`,
`does_not_prove`, `claim_boundaries` oder später `does_not_establish` heißen. Dieser
Blueprint fordert semantische Konsistenz, aber keine unkoordinierte Umbenennung
bestehender Contracts.

### 5.5 Bestehende Lenses bleiben Primary Lenses

Die sieben vorhandenen IDs bleiben unverändert. Neue Sichtachsen werden später als
Facets, Relations, States, Task Contexts oder Cards modelliert, nicht als zusätzliche
Primary Lens IDs.

### 5.6 Messung vor Optimierung

- Retrieval v2 erst nach Review-Goldset und Baseline.
- Lens Cards erst nach Primary Lens Audit.
- Consumption Trace erst nach stabiler Answer Compliance und realem Consumer.
- Agent Entry Manifest nur bei nachweislich wachsender, schwer navigierbarer
  Sidecar-Fläche.

## 6. Architekturentscheidung und Non-Goals

### 6.1 Verbindliche Entscheidungen

1. `canonical_md` bleibt die einzige Inhaltswahrheit.
2. Das Agent Reading Pack bleibt `navigation_index` / `derived`.
3. Sidecars bleiben rollenabhängig Navigation, Diagnose, Index oder Cache.
4. Kein Health- oder Surface-Pass wird als Antwortsicherheit interpretiert.
5. Kein Slice führt freie Modellinterpretation in einen Lenskit-Producer ein.
6. Keine neue maschinenlesbare Fläche wird nur aus Zukunftsvermutung eingeführt.
7. Jeder Slice wird separat registriert und darf höchstens ein neues Subsystem bauen.

### 6.2 Globale Non-Goals

- kein LLM-Core
- keine Embeddings
- kein semantisches oder LLM-basiertes Reranking
- keine autonomen Review-Findings
- keine Patch-Automation
- keine neuen Primary Lens IDs
- keine sofortigen neuen Consumption-Contracts
- kein Agent Entry Manifest im ersten Slice
- kein Agent Consumption Trace im ersten Slice
- keine neuen Sidecars im ersten Slice
- keine sofortige CI-Promotion neuer Agent-Pack-Regeln
- keine Promotion bestehender Health-/Surface-Diagnosen zu Antwort-Gates
- kein Retrieval-Goldset in diesem Blueprint-PR
- keine Pipeline-, Schema-, Health-, Runtime-, Service- oder Frontend-Änderung in diesem
  Blueprint-PR

## 7. Phasen und Abhängigkeiten

### Phase 1 — Front Door und Messbarkeit

1. Agent Reading Pack v1.1
2. Agent-Pack-Usage Smoke
3. Retrieval Review Goldset v1

### Phase 2 — Regeln stabilisieren und optional contractisieren

4. Required Reading Protocol v0 als Markdown
5. Post-/Surface-Warns für Agent-Pack-Usage
6. Required Reading Protocol v1 als JSON
7. Answer Compliance Contract v1

### Phase 3 — Deklarierte Nutzung prüfen

8. Agent Consumption Trace v1
9. Agent Entry Manifest v1, nur falls die Sidecar-Fläche weiter wächst

### Phase 4 — Deterministische Linsen ausbauen

10. Primary Lens Audit v1
11. Facet Model v1
12. Lens Cards v1
13. PR Delta Cards v1
14. Relation Cards v1
15. Guard Relation Cards v1

### Phase 5 — Retrieval verbessern

16. Retrieval v2 deterministisch

### Abhängigkeitskette

```text
Slice 1 -> Slice 2
Slice 1 -> Slice 4 -> Slice 5 -> Slice 6 -> Slice 7 -> Slice 8
Slice 3 -------------------------------------------------------> Slice 16
Slice 10 -> Slice 11 -> Slice 12 -> Slice 13
                         Slice 12 -> Slice 14 -> Slice 15
Slice 6/7/8 or growing sidecar surface ------------------------> Slice 9
```

## 8. Roadmap-Slices

### Slice 1 — Agent Reading Pack v1.1

**Ziel:** Das vorhandene Pack wird zur klaren Front Door für task-spezifische
Pflichtlektüre und epistemische Grenzen.

**Voraussichtlich betroffene Dateien:**

```text
merger/lenskit/core/agent_reading_pack.py
merger/lenskit/tests/test_agent_reading_pack.py
merger/lenskit/tests/test_cli_agent_pack.py
docs/proofs/agent-reading-pack-producer-proof.md
```

Optional darf ein fokussierter Test hinzukommen:

```text
merger/lenskit/tests/test_agent_reading_pack_usage_rules.py
```

**Neue Pack-Abschnitte:**

- `REQUIRED_READING_BY_TASK`
- `WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT`
- `SIDECAR_USAGE_RULES`
- `ANSWER_COMPLIANCE_CHECKLIST`
- `DO_NOT_CLAIM`

**Geplante Required-Reading-Matrix:**

| Task-Profil | Required | Recommended | Nicht ausreichend |
| --- | --- | --- | --- |
| `basic_repo_question` | `agent_reading_pack`, `canonical_md` | `citation_map_jsonl` | Sidecar-Claims ohne kanonischen Check |
| `pr_review` | `agent_reading_pack`, `canonical_md`, `citation_map_jsonl`, `post_emit_health` | `claim_evidence_map_json`, `bundle_surface_validation` | nur lineares Lesen von `canonical_md` |
| `roadmap_status_claim` | `agent_reading_pack`, `canonical_md`, `claim_evidence_map_json` | `citation_map_jsonl` | Roadmapstatus ohne kanonischen Inhalt und Evidence-Navigation |
| `artifact_surface_review` | `bundle_manifest`, `post_emit_health`, `bundle_surface_validation`, `canonical_md` | `output_health` | `output_health` allein |
| `retrieval_quality_review` | `retrieval_eval_json`, `chunk_index_jsonl`, `sqlite_index`, `canonical_md` | `docs/retrieval/*` | Eindruck statt reproduzierbarer Metrik |

Die Matrix wird im Implementierungs-PR nochmals gegen die dann aktuellen Artifact Roles,
Producer und Manifest-Regeln geprüft. Ein Artefakt darf nur als `required` erscheinen,
wenn seine Abwesenheits- und Capability-Semantik für das Profil geklärt ist.

**`WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT`:** mindestens für:

- belegorientierten PR Review
- Roadmap-/Status-Claims
- Bundle-/Surface-Health-Bewertung
- Retrieval-Qualitätsbewertung
- Citation-Readiness-Aussagen
- Aussagen zur Claim Evidence Map
- Aussagen über vorhandene oder fehlende Sidecars

**`SIDECAR_USAGE_RULES`:**

- Sidecars nie als Inhaltswahrheit zitieren.
- Sidecars nutzen, um kanonische Bereiche, Belege oder Diagnostik zu finden.
- Claim Evidence Map nur als Evidence-Index lesen.
- Retrieval Eval nur als Diagnose lesen.
- Post-Emit-Health nicht als Repo-Verständnis lesen.
- Surface Validation nicht als Claim-Wahrheit lesen.

**Minimale `ANSWER_COMPLIANCE_CHECKLIST`:**

```text
Lenskit consumption:
- task_profile:
- required_artifacts_checked:
- sidecars_used:
- canonical_ranges_or_citations_used:
- sidecars_not_used_and_why:
- epistemic_gaps:
- does_not_establish:
```

Diese Checkliste ist eine deklarative Hilfestellung. Sie beweist weder tatsächliches Lesen
noch Antwortkorrektheit.

**`DO_NOT_CLAIM`:**

- kein „Repo verstanden“ aus einem Health-Pass
- keine Claim-Wahrheit aus der Existenz einer Claim Evidence Map
- keine „Antwort sicher ohne Zitate“-Aussage
- keine Test-Suffizienz aus gefundenen Testdateien
- kein Change-Impact aus Relation oder Pfadnähe allein

**Tests:**

- alle fünf Abschnitte vorhanden
- alle fünf Task-Profile vorhanden
- `canonical_md` bleibt einzige Inhaltswahrheit
- Agent Reading Pack bleibt `navigation_index` / `derived`
- Claim Evidence Map wird als Navigation/Evidence-Index beschrieben
- Post-Emit-Health wird als Diagnose, nicht als Antwortsicherheit beschrieben
- keine verbotene Authority- oder Truth-Sprache
- deterministische Ausgabe bleibt erhalten

**Nicht-Ziele:**

- kein neues JSON-Schema
- kein neues Sidecar oder Evidence Level
- kein Export-Gate-Fail
- keine Health-/Surface-Gate-Promotion
- kein Retrieval-Ranking
- keine Pipeline-Mutation
- keine Lens Cards

**Akzeptanz:** Ein Agent erkennt Task-Profil, Required-/Recommended-Artefakte,
Canonical-only-Grenzen und die gewünschte Nutzungsdeklaration. Die Pack-Struktur beweist
nicht, dass ein Agent sie befolgt hat.

**Komplexität:** mittel.

### Slice 2 — Agent-Pack-Usage Smoke

**Ziel:** Die Front-Door-Struktur wird als statische, deterministische Erwartung testbar.

**Geplanter Hauptpfad:**

```text
merger/lenskit/tests/test_agent_reading_pack_usage_rules.py
```

**Checks:**

- alle Task-Profile vorhanden
- jedes Profil unterscheidet `required`, `recommended` und Negativsemantik
- `pr_review` verlangt `citation_map_jsonl`
- `roadmap_status_claim` verlangt `claim_evidence_map_json`
- `artifact_surface_review` verlangt `post_emit_health` und
  `bundle_surface_validation`
- `retrieval_quality_review` verlangt `retrieval_eval_json`
- `basic_repo_question` bleibt leichtgewichtig
- kein Sidecar wird als Wahrheit markiert

**Optionaler späterer CLI-Check:**

```text
python -m merger.lenskit.cli.main agent-pack inspect --pack <path> --json
```

Ein CLI-Subcommand ist nur zulässig, wenn er eine echte Consumer-Lücke schließt. Er ist
kein Muss für Slice 2 und darf keine neue Contract-Familie implizieren.

**Nicht-Ziele:** kein Schema, keine CI-Promotion, keine Validierung externer Antworten.

**Akzeptanz:** Fehlende oder widersprüchliche Front-Door-Sektionen werden durch gezielte
Tests erkannt.

**Komplexität:** niedrig bis mittel.

### Slice 3 — Retrieval Review Goldset v1

**Status:** Structural Goldset sowie Metric Baseline und Miss Diagnostics
sind implementiert.
**Belege:**
- `docs/retrieval/review_queries.v1.json`
- `merger/lenskit/retrieval/review_eval.py`
- `merger/lenskit/tests/test_review_retrieval_goldset.py`
- `merger/lenskit/tests/test_review_retrieval_metrics.py`
- `docs/diagnostics/review-retrieval-baseline.md`
**Bewusst nicht Teil des abgeschlossenen Slices:**
- kein neuer Goldset-Contract
- kein neuer CLI-Befehl
- kein Bundle-Sidecar
- keine Ranking- oder Runtime-Änderung
- keine Promotion der gemessenen Retrieval-Qualität

**Mindestumfang:** mindestens 20 Queries aus den Kategorien:

1. `agent_pack`
2. `claim_evidence`
3. `citation_map`
4. `post_emit_health`
5. `bundle_surface`
6. `bundle_manifest`
7. `retrieval`
8. `router`
9. `cli`
10. `contracts`
11. `security`
12. `source_acquisition`
13. `pr_schau`
14. `range_ref`
15. `lenses`

**Metriken:**

- recall@10
- MRR
- category recall
- zero-hit-rate
- expected-path hit
- expected-test hit
- Miss Taxonomy

**Miss-Kategorien zur Kalibrierung:**

- `path_miss`
- `symbol_miss`
- `category_miss`
- `ranking_miss`
- `noise_match`
- `doc_over_code`
- `test_over_source`
- `source_over_contract`
- `query_too_generic`

Die Namen müssen vor Contractisierung mit der bestehenden Retrieval Miss Taxonomy
reconciled werden; keine parallele Taxonomie ohne Migrationsentscheidung.

**Nicht-Ziele:** kein Retrieval v2, kein Ranking-Fix, keine Embeddings, kein semantisches
Reranking.

**Akzeptanz:** Eine versionierte Query-Menge erzeugt reproduzierbare Baseline-Metriken und
macht Misses unterscheidbar, ohne semantische Vollständigkeit zu behaupten.

**Komplexität:** mittel.

### Slice 4 — Required Reading Protocol v0 als Markdown

**Ziel:** Die erprobten Task-Profile normativ dokumentieren, ohne bereits einen neuen
JSON-Contract einzuführen.

**Geplanter Pfad:**

```text
docs/architecture/required-reading-protocol.md
```

**Inhalt:** Definitionen für `required`, `recommended`, `optional`, Task-Profile,
Capability-/Abwesenheitssemantik, Sidecar Authority, Compliance Checklist und Beispiele.

**Tests, falls das Repo-Muster einen Doc-Guard rechtfertigt:**

```text
merger/lenskit/tests/test_required_reading_protocol_doc.py
```

**Akzeptanz:** Alle stabilisierten Profile und ihre Negativsemantik sind dokumentiert;
das Agent Reading Pack verweist auf die Architekturregel, ohne sie zu duplizieren.

**Nicht-Ziele:** kein JSON-Schema, kein Resolver, kein Runtime-Gate.

**Komplexität:** niedrig bis mittel.

### Slice 5 — Post-/Surface-Warns für Agent-Pack-Usage

**Ziel:** Bestehende Diagnoseflächen dürfen fehlende Front-Door-Regeln sichtbar machen,
ohne daraus Antwort- oder Truth-Gates zu machen.

**Voraussichtlich betroffene Dateien:**

```text
merger/lenskit/core/post_emit_health.py
merger/lenskit/core/bundle_surface_validate.py
merger/lenskit/tests/test_post_emit_health.py
merger/lenskit/tests/test_bundle_surface_validate.py
```

**Bestehende harte Grenzen bleiben:** fehlendes erforderliches Pack, falsche
`navigation_index`-/`derived`-Selbstdeklaration oder eine Relativierung der kanonischen
Authority bleiben schwerwiegender als fehlende neue Sektionen.

**Neue Regeln starten als Warnungen:** fehlendes `REQUIRED_READING_BY_TASK`,
`ANSWER_COMPLIANCE_CHECKLIST`, `WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT` oder
`SIDECAR_USAGE_RULES`.

**Stop-Bedingung:** Wenn die Änderung breite Anpassungen bestehender Health-/Surface-
Tests oder eine semantische Promotion von Diagnose zu Antwortsicherheit erfordert, wird
der Slice gestoppt und neu geplant.

**Akzeptanz:** additive Warnungen sind deterministisch und erhalten alle bestehenden
`does_not_mean`-Grenzen.

**Komplexität:** mittel.

### Slice 6 — Required Reading Protocol v1 als JSON

**Status:** Required Reading Protocol, Resolver, fokussierte Tests und der
CLI-Lesepfad sind implementiert.
**Belege:**
- `merger/lenskit/contracts/required-reading-protocol.v1.schema.json`
- `merger/lenskit/core/required_reading.py`
- `merger/lenskit/tests/test_required_reading_protocol.py`
- `merger/lenskit/cli/cmd_agent_consumption.py`
- `merger/lenskit/cli/main.py`
**Weiterhin offen:**
- harte Durchsetzung in Consumer- oder Export-Gates
- automatische Bundle-Integration
- tatsächliche Adoption durch externe Agent-Wrapper

**Contract-Inhalt:** versionierte Task-Profile mit `required`, `recommended`, `optional`
und Negativsemantik. Ein Resolver darf Manifest-Verfügbarkeit gegen ein Task-Profil
prüfen und `pass|warn|fail|not_applicable` liefern.

**Statusgrenze:** `pass` bedeutet ausschließlich, dass deklarierte Required-Flächen
verfügbar sind; nicht, dass sie gelesen wurden oder eine Antwort korrekt ist.

**Akzeptanz:** Schema, Resolver und Tests sind deterministisch; unbekannte Rollen oder
Profile werden konservativ behandelt.

**Komplexität:** mittel.

### Slice 7 — Answer Compliance Contract v1

**Status:** Answer Compliance Contract, Architekturgrenzen und fokussierte
Tests sind implementiert.
**Belege:**
- `merger/lenskit/contracts/answer-compliance.v1.schema.json`
- `docs/architecture/answer-compliance.md`
- `merger/lenskit/tests/test_answer_compliance_schema.py`
**Geltungsgrenze:**
Answer Compliance ist eine deklarative Selbstauskunft über verwendete
Artefakte, Citations, Ranges und epistemische Lücken.
Sie beweist weder tatsächliches Lesen noch korrekte Nutzung, Vollständigkeit,
Antwortkorrektheit oder Repo-Verständnis.
**Bewusst nicht Teil:**
- eigener Answer-Compliance-Producer
- automatische Bundle-Emission
- eigenständige Wahrheitsbewertung

**Komplexität:** mittel.

### Slice 8 — Agent Consumption Trace v1

**Status:** Agent Consumption Trace Contract, Validator, Strict-Mode,
Exit-Code-Policy, fokussierte Tests und CLI sind implementiert.
**Belege:**
- `merger/lenskit/contracts/agent-consumption-trace.v1.schema.json`
- `merger/lenskit/core/agent_consumption_validate.py`
- `merger/lenskit/tests/test_agent_consumption_trace.py`
- `merger/lenskit/cli/cmd_agent_consumption.py`
- `merger/lenskit/cli/main.py`
- `merger/lenskit/tests/test_cli_agent_consumption.py`
**Weiterhin offen:**
- automatische Bundle-Emission
- Einbindung in Output Health oder Post-Emit Health
- Export-Safety-Wiring
- verbindliche Adoption durch externe Agent-Wrapper
**Geltungsgrenze:**
Der Trace vergleicht deklarierte Nutzung mit Required-Reading-Erwartungen.
Er beweist kein tatsächliches Lesen, keine Antwortkorrektheit und kein
Repo-Verständnis.

**Komplexität:** mittel bis hoch.

### Slice 9 — Agent Entry Manifest v1

**Status:** Agent Entry Manifest Contract, Core-Producer und fokussierte
Tests sind implementiert.
**Belege:**
- `merger/lenskit/contracts/agent-entry-manifest.v1.schema.json`
- `merger/lenskit/core/agent_entry_manifest.py`
- `merger/lenskit/tests/test_agent_entry_manifest.py`
**Weiterhin offen:**
- eigener CLI-Befehl
- automatische Bundle-Emission
- Bundle-Manifest-Rolle
- stabile Consumer-Integration
**Geltungsgrenze:**
Der Core erzeugt einen abgeleiteten Agent-Einstiegsindex. Das beweist weder
automatische Bereitstellung noch tatsächlichen Konsum oder Repo-Verständnis.

**Komplexität:** mittel.

### Slice 10 — Primary Lens Audit v1

**Ziel:** Die bestehende heuristische Zuordnung zu den sieben Primary Lenses sichtbar und
prüfbar machen, ohne IDs oder Prioritäten zu ändern.

**Status:** Contract, Core Producer und fokussierte Tests sind implementiert.

**Belege (Evidence):**
- `merger/lenskit/contracts/primary-lens-audit.v1.schema.json`
- `merger/lenskit/core/lens_audit.py`
- `merger/lenskit/tests/test_primary_lens_audit.py`

**Bewusst nicht Teil des abgeschlossenen Slices:**

- automatische Bundle-Emission
- CLI-Anschluss

Diese Anschlüsse werden durch den Status nicht als notwendige Folgearbeiten
festgelegt.

**Im abgeschlossenen Slice unverändert:**

- `LENS_IDS`
- `infer_lens()` und seine bestehende Prioritätslogik

**Output-Grenze:** Pfad, Primary Lens, matched rule und Negativsemantik; keine Aussage zu
semantischer Wichtigkeit, Review-Priorität oder vollständigem Kontext.

**Nicht-Ziele:** keine Änderung an `LENS_IDS`, keine neue Primary Lens, keine
Priority-Änderung, kein Impact-Begriff.

**Akzeptanz:** Audit ist deterministisch und erklärt bestehende Heuristik statt sie still
zu verändern.

**Komplexität:** mittel.

### Slice 11 — Facet Model v1

**Status:** Contract/Core/Tests umgesetzt
(`merger/lenskit/contracts/lens-facet.v1.schema.json`,
`merger/lenskit/core/lens_facets.py`,
`merger/lenskit/tests/test_lens_facets.py`; Proof
`docs/proofs/facet-model-v1-proof.md`, Task `TASK-LENS-FACET-001`).
Umgesetzte v1-Taxonomie: `contract`, `test`, `retrieval` — bewusst klein;
`test` ist die engere additive Form von `test_guard`, die übrigen Kandidaten
sind begründet zurückgestellt. Nicht umgesetzt: CLI, Bundle-Emission, Lens
Cards, Befüllung von `possible_facets`. Keine Änderung an `LENS_IDS` oder
`infer_lens()`.

**Ziel:** Additive Sichtachsen einführen, ohne das genau-eine-Primary-Lens-Modell zu
ersetzen.

**Regelwerk:** Der Facet-Contract muss die in `docs/architecture/lens-model.md`
festgelegten Schichtengrenzen, Ableitungsarten und Negativsemantiken
einhalten.

**Erste Kandidaten, nicht finale Taxonomie:** `contract`, `artifact_surface`,
`diagnostic`, `retrieval`, `claim_boundary`, `security`, `test_guard`.

**Planungskandidaten:**

```text
merger/lenskit/contracts/lens-facet.v1.schema.json
merger/lenskit/core/lens_facets.py
merger/lenskit/tests/test_lens_facets.py
```

**Regeln:** mehrere Facets pro Datei; genau eine Primary Lens; Facets sind Navigation;
jedes Facet nennt `source_rule`, eine Ableitungsart und Negativsemantik.
- jede Facet-Zuordnung drückt eine Ableitungsart aus: `direct`, `derived` oder `heuristic`.
Die Ableitungsart beschreibt die Entstehungsweise der Zuordnung und keinen
Confidence Score. Der konkrete JSON-Feldname bleibt dem
Facet-Model-v1-Contract vorbehalten.

**Akzeptanz:** Facets sind deterministisch aus repo-belegten Regeln ableitbar und werden
nicht als semantische Wahrheit oder Review-Priorität behandelt.

**Komplexität:** mittel.

### Slice 12 — Lens Cards v1

**Status:** Contract/Core/Validation/Tests umgesetzt
(`merger/lenskit/contracts/lens-card.v1.schema.json`,
`merger/lenskit/core/lens_cards.py`,
`merger/lenskit/core/lens_card_validate.py`,
`merger/lenskit/tests/test_lens_cards.py`,
`merger/lenskit/tests/test_lens_card_validate.py`; Proof
`docs/proofs/lens-card-v1-proof.md`, Task `TASK-LENS-CARD-001`).

**Ziel:** Kleine agentenlesbare Navigationseinheiten aus Primary Lens und Facets erzeugen.
Lens Card v1 beschreibt genau eine Card pro akzeptiertem Repo-Pfad; `path` ist
die Lens-Card-v1-Identität innerhalb eines expliziten einzelnen Repository-Kontexts.

Ein akzeptierter Repo-Pfad ist ein Pfad, den das kontrollierte lexikalische
Pfadmodell akzeptiert. Daraus folgen weder Dateiexistenz noch Git-Tracking,
Lesbarkeit oder erfolgreiche Auflösung gegen einen bestimmten Snapshot.

Die Card ist `authority=navigation_index` und
`canonicality=derived`.

**Planungskandidaten:**

```text
merger/lenskit/contracts/lens-card.v1.schema.json
merger/lenskit/core/lens_cards.py
merger/lenskit/core/lens_card_validate.py
merger/lenskit/tests/test_lens_cards.py
```

**Umgesetzter Mindestinhalt:** Pfad, Primary Lens, `matched_rule`, Facets als
Projektion aus `infer_facets()` (`facet`, `source_rule`, `derivation_type`),
genau ein `repo_path`-`navigation_ref` auf denselben Pfad und feste
neunteilige Negativsemantik.

**Validator-Grenze:** Der Validator prüft Contract-Shape und
Producer-Kohärenz durch Neuberechnung aus `path`. Er beweist keine Wahrheit,
kein Repo-Verständnis, keine Reviewvollständigkeit, keine Runtime-Korrektheit,
keine Testausreichung, keine Sicherheit und keinen Change Impact. Fehlendes
`jsonschema` wird maschinenlesbar als degradierte Validierung ausgewiesen und
führt nie zu `pass`.

**Verbotene Verdict-Semantik:** `verdict`, `fix`, `safe`, `covered`, `complete`,
`impact`, `breaks` dürfen nicht als unqualifizierte Card-Felder eingeführt werden.

**Front-Door-Anschluss:** Das Agent Reading Pack erklärt statisch Rolle,
Authority und Grenzen von Lens Cards. Es liest keine Card-Pfade aus einem
Manifest, behauptet keine Card-Emission und macht Lens Cards nicht zu Required
Reading.

**Weiterhin offen:** automatische Emission, CLI, Bundle-/Manifest-Sichtbarkeit,
Artifact Role, Consumer-Integration, Relations, States, Task Contexts, PR Delta
Cards und Retrieval-Nutzung.

**Akzeptanz:** Cards navigieren zu kanonischen Quellen; sie behaupten weder Bug-Präsenz
noch Review-Priorität.

**Komplexität:** mittel bis hoch.

### Slice 13 — PR Delta Cards v1

**Status:** umgesetzt, gemergt und post-merge verifiziert
(`merger/lenskit/contracts/pr-delta-card.v1.schema.json`,
`merger/lenskit/core/pr_delta_cards.py`,
`merger/lenskit/core/pr_delta_card_validate.py`,
`merger/lenskit/tests/test_pr_delta_cards.py`,
`merger/lenskit/tests/test_pr_delta_card_validate.py`; Proof
`docs/proofs/pr-delta-cards-gap-report.md`, `docs/proofs/pr-delta-cards-v1-post-merge-proof.md`, Task `TASK-PR-DELTA-CARD-001`).

**Ziel:** Bereits vorhandene PR-Schau-/Delta-Daten kontrolliert auf die Lens-Card-Produktion projizieren.

**Inhalt:** Pfad, Change-Status, Primary Lens, Facets, expliziter Delta-Kontext. PR Delta Cards v1 enthalten keine Hashfelder und behaupten keine
Hashprovenienz. Eine mögliche spätere Bundle-/Manifest-Integration ist
nicht Teil dieses Slices und wird durch diesen PR weder implementiert
noch zugesichert.
Unterstützt wird ein bereits geladenes,
pr-schau-delta.v1-konformes Mapping.
Dieser Slice enthält keinen Delta-Dateiloader und keinen Bundleadapter.

**Nicht-Ziele:** Kein Review-Verdict, kein Patch-Vorschlag, keine Impact-Wahrheit. Keine Behauptung über GitHub-PR-Identität, Commitidentität, Hunks oder Relationen. Keine CLI- oder Bundle-Integration.

**Akzeptanz:** Bereits geladene, pr-schau-delta.v1-konforme Mappings können deterministisch in PR Delta Cards projiziert werden, ohne automatische Findings zu erzeugen.

**Komplexität:** mittel.

### Slice 14 — Relation Cards v1

**Ziel:** Deterministisch beobachtbare Beziehungen sichtbar machen, ohne Kausalität zu
behaupten.

**Relation-Kandidaten:** `imports`, `mentions`, `validates`, `tests`, `documents`,
`produces`, `consumes`, `same_surface`.

**Planungskandidaten:**

```text
merger/lenskit/contracts/relation-card.v1.schema.json
merger/lenskit/core/relation_cards.py
merger/lenskit/tests/test_relation_cards.py
```

**Pflichtgrenzen:** Relations etablieren keine Kausalität, Runtime-Abhängigkeit,
Test-Suffizienz oder Change-Impact.

**Akzeptanz:** Jede Relation nennt ihre deterministische Quelle und löst auf vorhandene
Pfade/IDs auf.

**Komplexität:** hoch.

### Slice 15 — Guard Relation Cards

**Ziel:** Tests und Guards formal mit Code, Contracts und Surfaces verbinden.

**Relation-Kandidaten:** `tests_by_name`, `tests_by_path`, `validates_schema`,
`checks_surface`, `checks_cli`, `checks_security`.

**Nicht behaupten:** Ein zugeordneter Test reicht aus, schließt Regression aus oder
beweist Runtime-Korrektheit.

**Akzeptanz:** Guard-Relationen sind reproduzierbar, erklären ihre Match-Regel und tragen
Negativsemantik.

**Komplexität:** mittel.

### Slice 16 — Retrieval v2 deterministisch

**Voraussetzung:** Review Retrieval Goldset v1 ist stabil und liefert eine committete
Baseline.

**Kandidaten:** Review-Intent-Router, path-aware Ranking, Contract-ID-, Symbol-/Function-
und Testname-Boosting, Facet-/Relation-aware Ranking sowie verbesserte Miss-Diagnostik.

**Nicht erlaubt:** Embeddings, LLM-Reranking, freie semantische Zusammenfassung oder
ungemessene Default-Promotion.

**Promotion-Gate:** Retrieval v2 wird nur Default, wenn Goldset-Metriken besser sind,
keine zentrale Query-Klasse regressiert, Miss-Diagnostik aussagekräftiger wird und
Query-Kompatibilität erhalten bleibt.

**Akzeptanz:** gleiche Inputs erzeugen gleiche Rankings; Verbesserungen sind gegen die
versionierte Baseline nachgewiesen.

**Komplexität:** hoch.

## 9. Querschnittsgates

### Gate A — Canonical Authority

`canonical_md` bleibt die einzige Inhaltswahrheit. Das Agent Reading Pack und alle
späteren Cards/Protocols führen auf kanonische Bereiche oder rollenadäquate Belege zurück.

### Gate B — No Silent Authority Upgrade

Kein Artefakt darf still von Navigation, Diagnose, Index oder Cache zu Wahrheit werden.
Jede Authority-Änderung benötigt eine eigene Governance-Entscheidung.

### Gate C — Required Reading Visible Before JSON Contract

Task-spezifische Pflichtlektüre muss im Pack sichtbar, verständlich und getestet sein,
bevor ein JSON-Contract sie abbildet.

### Gate D — Negativsemantik

Jede neue agent-facing Fläche enthält eine repo-konforme Form von
`does_not_establish`/`does_not_mean`/`does_not_prove` und vermeidet Claim-Verdicts.

### Gate E — Determinism

Gleicher Bundle-Zustand und gleiche Inputs erzeugen gleiche Lenskit-Ausgaben. Freie
Modellinterpretation ist kein Producer-Schritt.

### Gate F — No LLM / No Embedding

Keine Modell-, Provider- oder Embedding-Abhängigkeit im Core-Pfad.

### Gate G — Retrieval Only After Goldset

Keine Retrieval-v2-Optimierung oder Promotion ohne versioniertes Goldset und Baseline.

### Gate H — Capability- und Abwesenheitssemantik

`required` darf nicht bedeuten, dass ein capability-degradierter Host unmögliche
Artefakte erzeugen muss. Jeder spätere Protocol-/Resolver-Slice muss zwischen fehlend,
nicht anwendbar und capability-bedingt nicht verfügbar unterscheiden.

### Gate I — Planning Registration

Jeder neue aktive Blueprint, Plan oder Slice wird regulär über Roadmap und Task-Control
registriert. Exemptions sind kein Ersatz für normale Registrierung.

## 10. Stop-Regeln

Sofort stoppen und den Slice neu bewerten, wenn:

- `canonical_md` relativiert wird;
- das Agent Reading Pack als Wahrheit behandelt wird;
- Health-/Surface-Pass als Antwortsicherheit formuliert wird;
- Claim Evidence Map als Claim-Wahrheit formuliert wird;
- neue Sidecars vor der Front-Door-Härtung eingeführt werden;
- Retrieval v2 ohne committetes Goldset begonnen wird;
- bestehende Tests durch Abschwächung statt Korrektur grün gemacht werden;
- ein Slice mehr als ein neues Subsystem gleichzeitig baut;
- neue Primary Lens IDs ohne Audit und eigene Architekturentscheidung eingeführt werden;
- ein Consumption Trace tatsächliches Lesen zu beweisen vorgibt;
- Planning Registration oder Evidence-Status unklar bleibt.

## 11. Risiko- und Nutzenabschätzung

### Nutzen

- schnellster Nutzen für lesende LLMs bei minimalem Runtime-Risiko
- Wiederverwendung der vorhandenen Agent Front Door
- weniger Sidecar-Inflation
- klare Sequenz vor späteren Contracts
- Retrieval-Probleme werden vor Optimierung messbar
- bestehende Primary Lenses bleiben stabil

### Risiken

- Markdown-Regeln können ignoriert werden.
- Das Agent Reading Pack kann zu lang werden.
- Required Reading kann einfache Fragen überfrachten.
- Neue Contracts könnten deklarierte Nutzung mit tatsächlicher Nutzung verwechseln.
- Facets und Cards könnten unbemerkt Review-/Impact-Semantik annehmen.
- Eine ungesicherte Retrieval-Baseline könnte falsche Prioritäten setzen.

### Gegenmaßnahmen

- Task-Profile staffeln und `basic_repo_question` leicht halten.
- Pack-Sektionen knapp, tabellarisch und testbar halten.
- JSON erst nach stabiler Markdown-Semantik.
- Consumption-Flächen immer mit Negativsemantik versehen.
- Primary Lens Audit vor Facets/Cards.
- Goldset und Baseline vor Retrieval v2.

## 12. Alternativpfad

Falls die Front-Door-Härtung trotz Slice 1 und 2 nachweislich ignoriert wird:

1. Required Reading Protocol früher als JSON contractisieren.
2. Answer Compliance Contract einführen.
3. Agent Consumption Trace nur in einem realen Wrapper erzwingen.
4. Agent Entry Manifest als Minimalindex ergänzen.
5. Bestehende Export-/Health-Flächen höchstens im Warn-Modus anbinden.

Dieser strengere Pfad ist eine Eskalation nach Messung, nicht der Default. Er darf keine
Authority-Promotion oder Antwortkorrektheitsbehauptung enthalten.

## 13. Open Questions

### Resolved

- Required Reading benötigt eine maschinenlesbare Contract-Fläche: ja
- Answer Compliance benötigt JSON: ja
- vorhandenes Review-Query-Format wird wiederverwendet: ja
- neuer Goldset-Contract: nein
- Review-Goldset-Kategorien: festgelegt
- Agent Consumption Trace besitzt einen Validator und CLI: ja
- Agent Entry Manifest Core: implementiert
- Review-Goldset und Baseline: implementiert

### Still open

- harte Required-Reading-Durchsetzung
- Adoption durch externe Consumer-/Agent-Wrapper
- automatische Entry-Manifest-Emission
- Bundle-/Manifest-Integration des Entry Manifest
- Consumption-Trace-Integration in Health-/Export-Gates
- konkrete Promotion-Schwelle für Retrieval v2
- Bundle-/Consumer-Integration des Facet Model v1 (Contract/Core/Tests umgesetzt)

## 14. Next Unimplemented Architecture Slice

Facet Model v1 und Lens Cards v1 sind als Contract/Core/Test- bzw.
Contract/Core/Validation/Test-Slices umgesetzt (siehe Slice 11 und Slice 12),
auf der akzeptierten normativen Grundlage des Deterministic Lens Model.
Der nächste noch nicht implementierte Architektur-Slice ist damit PR Delta Cards
v1 (Slice 13): Übersetzung vorhandener PR-Schau-/Delta-Daten in
Lens-Card-Navigation.
Dieser Blueprint erzeugt dafür keine neue Task-ID.

## 15. Nicht-normative Contract- und Output-Skizzen

Die folgenden Skizzen bewahren die beabsichtigte Form späterer Slices, sind aber **keine
Schemas** und dürfen nicht vor den jeweiligen Eintrittsgates als Contract implementiert
werden.

### 15.1 Review-Goldset-Query

Exact shape: see `docs/retrieval/review_queries.v1.json`.

### 15.2 Required Reading Protocol

Exact shape: see the canonical contract at
`merger/lenskit/contracts/required-reading-protocol.v1.schema.json`.

### 15.3 Required Reading Resolver

Für das Resolver-Ergebnis existiert derzeit kein eigener JSON-Contract.
Die deterministische Output-Shape wird durch
`merger/lenskit/core/required_reading.py::resolve_required_reading`
erzeugt und durch
`merger/lenskit/tests/test_required_reading_protocol.py`
abgesichert.

### 15.4 Answer Compliance

Exact shape: see the canonical contract at
`merger/lenskit/contracts/answer-compliance.v1.schema.json`.

### 15.5 Agent Consumption Trace

Exact shape: see the canonical contract at
`merger/lenskit/contracts/agent-consumption-trace.v1.schema.json`.

### 15.6 Agent Entry Manifest

Exact shape: see the canonical contract at
`merger/lenskit/contracts/agent-entry-manifest.v1.schema.json`.

### 15.7 Primary Lens Audit

```json
{
  "path": "merger/lenskit/core/agent_reading_pack.py",
  "primary_lens": "core",
  "matched_rule": "core path",
  "does_not_establish": [
    "semantic_importance",
    "review_priority",
    "complete_context"
  ]
}
```

### 15.8 Lens Card

Exact shape: see the canonical single-card contract at
`merger/lenskit/contracts/lens-card.v1.schema.json`.

### 15.9 Relation Card Negativsemantik

```json
{
  "does_not_establish": [
    "causality",
    "runtime_dependency",
    "test_sufficiency",
    "change_impact"
  ]
}
```

## 16. Slice-1-Optimierungsbewertung

- **Was wird optimiert:** Auffindbarkeit und Nutzungsdisziplin bestehender Flächen.
- **Wie:** durch kurze, task-spezifische Pflichtlektüre und sichtbare Negativsemantik im
  vorhandenen Pack.
- **Wodurch:** weniger implizite Regeln und weniger rein lineares Lesen von
  `canonical_md` bei Aufgaben mit Evidence-/Surface-Anforderungen.
- **Erwartete Wirkung:** hoch für Agent-Führung, zunächst niedrig bis mittel für
  maschinelle Erzwingung.
- **Nebenwirkung:** Das Pack wird länger; Gegenmittel sind kompakte Tabellen, klare
  Profile und keine Vorwegnahme späterer Contracts.

## 17. Essenz

**Hebel:** vorhandene Front Door härten, dann Nutzungserwartung testen, Retrieval messen
und erst danach contractisieren.

**Entscheidung:** kein sofortiges Consumption-Subsystem und keine neue Sidecar-Familie.

**Nächste Aktion:** ausschließlich Slice 1 unter `TASK-AGENT-FRONTDOOR-001` umsetzen.
