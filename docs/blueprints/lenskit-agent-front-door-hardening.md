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

| Fläche | Aktuelle Rolle | Planungsrelevante Grenze |
| --- | --- | --- |
| `canonical_md` | kanonische Inhaltsquelle | bleibt einzige Inhaltswahrheit |
| Agent Reading Pack | `navigation_index` / `derived` | Einstieg und Navigation, keine Wahrheit |
| Bundle Manifest | Registry für Artifact Roles, Authority, Canonicality und Hashes | Artefaktwahrheit, keine Inhaltswahrheit |
| Citation Map | Belegnavigation | kein Wahrheits- oder Vollständigkeitsverdikt |
| Claim Evidence Map | Evidence-Index | keine Claim-Bewertung |
| Post-Emit-Health | finale Integritäts-/Oberflächendiagnose | `pass` bedeutet weder `repo_understood` noch `answer_safe_without_citations` |
| Bundle Surface Validation | Surface-/Link-Konsistenzdiagnose | `pass` bedeutet weder `claims_true` noch `forensic_ready` |
| Retrieval Eval / Miss Taxonomy | Retrieval-Diagnostik | beweist keine semantische Vollständigkeit |
| Primary Lenses | `entrypoints`, `core`, `interfaces`, `data_models`, `pipelines`, `ui`, `guards` | Focus-Overlay; keine neuen IDs in diesem Plan |

### 3.2 Noch nicht als stabile Repo-Fläche vorhanden

- hartes Required Reading je Task-Profil
- Answer Compliance Contract
- Agent Consumption Trace
- Agent Entry Manifest
- Review-Retrieval-Goldset
- Primary Lens Audit
- Facet Model
- Lens Cards
- PR Delta Cards
- Relation Cards
- Guard Relation Cards

### 3.3 Retrieval-Baseline: bewusst offene Evidence-Lücke

Die extern vorgeschlagenen Zahlen `recall@10 = 13.33`, `MRR = 0.0889` und zwei Hits bei
15 Queries sind im Repository nicht als committetes Eval belegt; der bestehende
Capability-Audit markiert diesen Befund als unklar. Dieser Blueprint verwendet die Zahlen
daher **nicht** als Architekturbeweis oder Promotion-Baseline.

Konsequenz: Slice 3 muss ein versioniertes Review-Goldset und eine reproduzierbare
Baseline im Repo schaffen, bevor Retrieval-v2-Arbeit priorisiert, bewertet oder promoted
werden darf.

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

**Ziel:** Review-relevante Auffindbarkeit messen, bevor Retrieval verändert wird.

**Geplante Deliverables, vor Umsetzung gegen bestehende Retrieval-Konventionen zu
prüfen:**

```text
docs/retrieval/review_queries.v1.json
merger/lenskit/contracts/review-retrieval-goldset.v1.schema.json
merger/lenskit/tests/test_review_retrieval_goldset.py
docs/diagnostics/review-retrieval-baseline.md
```

Der Schema-Pfad ist ein Planungskandidat, keine Vorentscheidung: Falls das vorhandene
Query-Format `docs/retrieval/queries.v1.json` ohne neue Contract-Familie erweitert werden
kann, ist Wiederverwendung vorzuziehen.

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

**Voraussetzung:** Slices 1 bis 5 sind stabil, und mindestens ein Maschinenconsumer
benötigt die Regeln außerhalb des Markdown-Packs.

**Planungskandidaten:**

```text
merger/lenskit/contracts/required-reading-protocol.v1.schema.json
merger/lenskit/core/required_reading.py
merger/lenskit/tests/test_required_reading_protocol.py
```

Optional, nur bei belegtem Operator-/Wrapper-Bedarf:

```text
merger/lenskit/cli/cmd_required_reading.py
merger/lenskit/tests/test_cli_required_reading.py
```

**Contract-Inhalt:** versionierte Task-Profile mit `required`, `recommended`, `optional`
und Negativsemantik. Ein Resolver darf Manifest-Verfügbarkeit gegen ein Task-Profil
prüfen und `pass|warn|fail|not_applicable` liefern.

**Statusgrenze:** `pass` bedeutet ausschließlich, dass deklarierte Required-Flächen
verfügbar sind; nicht, dass sie gelesen wurden oder eine Antwort korrekt ist.

**Akzeptanz:** Schema, Resolver und Tests sind deterministisch; unbekannte Rollen oder
Profile werden konservativ behandelt.

**Komplexität:** mittel.

### Slice 7 — Answer Compliance Contract v1

**Ziel:** Eine Antwort kann verwendete Artefakte, Zitate, epistemische Lücken und bewusst
nicht gelesene Empfehlungen deklarieren.

**Planungskandidaten:**

```text
merger/lenskit/contracts/answer-compliance.v1.schema.json
docs/architecture/answer-compliance.md
merger/lenskit/tests/test_answer_compliance_schema.py
```

**Mindestfelder:** Task-Profil, deklarierte Artefakte, deklarierte Zitate, epistemische
Lücken, nicht gelesene Empfehlungen und `does_not_establish`.

**Grenze:** Der Contract normiert eine Selbstauskunft. Er beweist weder tatsächliche
Nutzung noch Antwortkorrektheit, vollständigen Kontext oder Repo-Verständnis.

**Akzeptanz:** Der Contract kann unabhängig von einem konkreten LLM-Provider validiert
werden und enthält keine Wahrheits- oder Review-Verdicts.

**Komplexität:** mittel.

### Slice 8 — Agent Consumption Trace v1

**Voraussetzung:** Ein realer Wrapper oder Workflow erzeugt Answer Compliance und
benötigt einen Vergleich mit Required Reading.

**Planungskandidaten:**

```text
merger/lenskit/contracts/agent-consumption-trace.v1.schema.json
merger/lenskit/core/agent_consumption_validate.py
merger/lenskit/tests/test_agent_consumption_trace.py
```

Optionaler CLI-Pfad nur bei konkretem Consumer:

```text
merger/lenskit/cli/cmd_agent_consumption.py
merger/lenskit/tests/test_cli_agent_consumption.py
```

**Validator-Grenzen:** fehlendes Required → `fail`; fehlendes Recommended → `warn`;
unbekannte Rolle → konservative Warnung; fehlende Negativsemantik oder Truth-Claim →
`fail`.

**Pflichtgrenze:** Der Trace erklärt deklarierte Nutzung, beweist aber kein tatsächliches
Lesen.

**Akzeptanz:** Required-Reading-Abweichungen sind maschinenlesbar, ohne
`actual_reading_proven`, `answer_correct` oder `repo_understood` zu behaupten.

**Komplexität:** mittel bis hoch.

### Slice 9 — Agent Entry Manifest v1

**Voraussetzung:** Required Reading, Answer Compliance oder Consumption Trace existieren,
oder die agent-facing Sidecar-Fläche ist nachweislich zu groß für einen stabilen Einstieg.

**Planungskandidaten:**

```text
merger/lenskit/contracts/agent-entry-manifest.v1.schema.json
merger/lenskit/core/agent_entry_manifest.py
merger/lenskit/tests/test_agent_entry_manifest.py
```

**Inhalt:** kanonische Quelle, `read_first`, Verweis auf Task-Protokoll, verfügbare
Flächen und Negativsemantik.

**Nicht-Ziel:** kein zweites Bundle Manifest, keine neue Truth-Registry, keine Einführung
nur zur Bequemlichkeit.

**Akzeptanz:** ultrakleiner, deterministischer Index; die Existenz beweist weder
Repo-Verständnis noch Antwortsicherheit.

**Komplexität:** mittel.

### Slice 10 — Primary Lens Audit v1

**Ziel:** Die bestehende heuristische Zuordnung zu den sieben Primary Lenses sichtbar und
prüfbar machen, ohne IDs oder Prioritäten zu ändern.

**Planungskandidaten:**

```text
merger/lenskit/contracts/primary-lens-audit.v1.schema.json
merger/lenskit/core/lens_audit.py
merger/lenskit/tests/test_primary_lens_audit.py
docs/architecture/lens-model.md
```

**Output-Grenze:** Pfad, Primary Lens, matched rule und Negativsemantik; keine Aussage zu
semantischer Wichtigkeit, Review-Priorität oder vollständigem Kontext.

**Nicht-Ziele:** keine Änderung an `LENS_IDS`, keine neue Primary Lens, keine
Priority-Änderung, kein Impact-Begriff.

**Akzeptanz:** Audit ist deterministisch und erklärt bestehende Heuristik statt sie still
zu verändern.

**Komplexität:** mittel.

### Slice 11 — Facet Model v1

**Ziel:** Additive Sichtachsen einführen, ohne das genau-eine-Primary-Lens-Modell zu
ersetzen.

**Erste Kandidaten:** `contract`, `artifact_surface`, `diagnostic`, `retrieval`,
`claim_boundary`, `security`, `test_guard`.

**Planungskandidaten:**

```text
merger/lenskit/contracts/lens-facet.v1.schema.json
merger/lenskit/core/lens_facets.py
merger/lenskit/tests/test_lens_facets.py
```

**Regeln:** mehrere Facets pro Datei; genau eine Primary Lens; Facets sind Navigation;
jedes Facet nennt `source_rule`, Confidence-Klasse und Negativsemantik.

**Akzeptanz:** Facets sind deterministisch aus repo-belegten Regeln ableitbar und werden
nicht als semantische Wahrheit oder Review-Priorität behandelt.

**Komplexität:** mittel.

### Slice 12 — Lens Cards v1

**Ziel:** Kleine agentenlesbare Navigationseinheiten aus Primary Lens und Facets erzeugen.

**Planungskandidaten:**

```text
merger/lenskit/contracts/lens-card.v1.schema.json
merger/lenskit/core/lens_cards.py
merger/lenskit/core/lens_card_validate.py
merger/lenskit/tests/test_lens_cards.py
```

**Mindestinhalt:** Pfad, Primary Lens, Facets, Navigation-Refs und Negativsemantik.

**Verbotene Verdict-Semantik:** `verdict`, `fix`, `safe`, `covered`, `complete`,
`impact`, `breaks` dürfen nicht als unqualifizierte Card-Felder eingeführt werden.

**Front-Door-Anschluss:** Sobald Lens Cards existieren, muss das Agent Reading Pack ihre
Rolle und Authority-Grenze erklären.

**Akzeptanz:** Cards navigieren zu kanonischen Quellen; sie behaupten weder Bug-Präsenz
noch Review-Priorität.

**Komplexität:** mittel bis hoch.

### Slice 13 — PR Delta Cards v1

**Ziel:** Bereits vorhandene PR-Schau-/Delta-Daten in Lens-Card-Navigation übersetzen.

**Planungskandidaten:**

```text
merger/lenskit/core/pr_delta_cards.py
merger/lenskit/tests/test_pr_delta_cards.py
docs/proofs/pr-delta-cards-gap-report.md
```

**Möglicher Inhalt:** geänderte Datei, Primary Lens, Facets, Contract-/Test-Guard-
Relationen sowie fehlende Hunk-/Symbol-Unterstützung.

**Nicht-Ziele:** kein Review-Verdict, kein Patch-Vorschlag, keine Risk-Wertung ohne
eigenen Contract und keine Impact-Wahrheit.

**Akzeptanz:** PR-Deltas werden navigierbar, ohne automatische Findings zu erzeugen.

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

1. Reicht Markdown-Front-Door-Härtung oder ist ein JSON-Contract nötig?
2. Welcher reale Consumer rechtfertigt Agent Consumption Trace?
3. Wie wird Sidecar-Nutzung gemessen, ohne tatsächliches Lesen vorzutäuschen?
4. Welche Retrieval-Goldset-Kategorien sind für PR Review zuerst erforderlich?
5. Lässt sich das bestehende Query-Format für das Goldset wiederverwenden?
6. Wann ist die Sidecar-Fläche groß genug für ein Agent Entry Manifest?
7. Wann dürfen Lens Cards eingeführt werden, ohne Primary-Lens- und Authority-Grenzen zu
   verwischen?
8. Welche Negativsemantik bleibt Markdown, welche wird später Contract-Pflicht?
9. Wie werden capability-degradierte Hosts in Required Reading abgebildet?
10. Welche konkrete Nichtregressionsschwelle promoted Retrieval v2?

## 14. Next Implementation Slice

**TASK-AGENT-FRONTDOOR-001 — Agent Reading Pack v1.1: Required Reading and Compliance
Front Door**

### Erlaubter Scope

```text
merger/lenskit/core/agent_reading_pack.py
merger/lenskit/tests/test_agent_reading_pack.py
merger/lenskit/tests/test_cli_agent_pack.py
docs/proofs/agent-reading-pack-producer-proof.md
```

Optional:

```text
merger/lenskit/tests/test_agent_reading_pack_usage_rules.py
```

### Nicht ändern

```text
merger/lenskit/core/post_emit_health.py
merger/lenskit/core/bundle_surface_validate.py
merger/lenskit/core/agent_export_gate.py
merger/lenskit/core/merge.py
merger/lenskit/contracts/*.schema.json
```

### Erfolgskriterium

Ein lesender Agent sieht nach dem Pack explizit, dass für PR Review, Status-Claims,
Surface Review und Retrieval-Qualitätsbewertung zusätzliche rollenadäquate Flächen nötig
sind. Gleichzeitig bleibt klar, dass weder Pack noch Sidecars Wahrheit, Vollständigkeit,
Review-Suffizienz oder Antwortkorrektheit beweisen.

## 15. Nicht-normative Contract- und Output-Skizzen

Die folgenden Skizzen bewahren die beabsichtigte Form späterer Slices, sind aber **keine
Schemas** und dürfen nicht vor den jeweiligen Eintrittsgates als Contract implementiert
werden.

### 15.1 Review-Goldset-Query

```json
{
  "id": "find-agent-reading-pack-producer",
  "query": "agent reading pack producer",
  "task_profile": "pr_review",
  "expected_paths": [
    "merger/lenskit/core/agent_reading_pack.py",
    "merger/lenskit/tests/test_agent_reading_pack.py"
  ],
  "required_in_top_k": 10,
  "does_not_establish": [
    "semantic_completeness",
    "review_sufficiency"
  ]
}
```

### 15.2 Required Reading Protocol

```json
{
  "kind": "lenskit.required_reading_protocol",
  "version": "1.0",
  "task_profiles": {
    "pr_review": {
      "required": [
        "agent_reading_pack",
        "canonical_md",
        "citation_map_jsonl",
        "post_emit_health"
      ],
      "recommended": [
        "claim_evidence_map_json",
        "bundle_surface_validation"
      ],
      "optional": [
        "retrieval_eval_json",
        "sqlite_index"
      ],
      "does_not_establish": [
        "answer_correct",
        "repo_understood",
        "review_complete",
        "test_sufficiency"
      ]
    }
  }
}
```

### 15.3 Required Reading Resolver

```json
{
  "task_profile": "pr_review",
  "available_required": [],
  "missing_required": [],
  "available_recommended": [],
  "missing_recommended": [],
  "status": "pass|warn|fail|not_applicable",
  "does_not_establish": []
}
```

### 15.4 Answer Compliance

```json
{
  "kind": "lenskit.answer_compliance",
  "version": "1.0",
  "task_profile": "pr_review",
  "declared_used_artifacts": [],
  "declared_citations": [],
  "declared_epistemic_gaps": [],
  "declared_unread_recommended": [],
  "does_not_establish": [
    "answer_correct",
    "repo_understood",
    "all_relevant_context_used"
  ]
}
```

### 15.5 Agent Consumption Trace

```json
{
  "kind": "lenskit.agent_consumption_trace",
  "version": "1.0",
  "task_profile": "pr_review",
  "used_artifacts": [
    {"role": "agent_reading_pack", "usage": "read"},
    {"role": "canonical_md", "usage": "cited"}
  ],
  "used_citation_ids": [],
  "unread_required_artifacts": [],
  "unread_recommended_artifacts": [],
  "epistemic_gaps": [],
  "does_not_establish": [
    "actual_reading_proven",
    "answer_correct",
    "repo_understood"
  ]
}
```

### 15.6 Agent Entry Manifest

```json
{
  "kind": "lenskit.agent_entry_manifest",
  "version": "1.0",
  "canonical_source": "canonical_md",
  "read_first": ["agent_reading_pack"],
  "task_protocol": "required_reading_protocol",
  "available_surfaces": [],
  "does_not_establish": [
    "repo_understood",
    "answer_safe_without_citations",
    "claims_true"
  ]
}
```

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

```json
{
  "kind": "lenskit.lens_card",
  "version": "1.0",
  "path": "merger/lenskit/core/agent_reading_pack.py",
  "primary_lens": "core",
  "facets": ["artifact_surface", "claim_boundary"],
  "navigation_refs": [],
  "does_not_establish": [
    "semantic_importance",
    "bug_presence",
    "review_priority"
  ]
}
```

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
