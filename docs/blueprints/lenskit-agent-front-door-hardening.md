---
doc_type: blueprint
status: active
task: TASK-AGENT-FRONTDOOR-001
---

# Lenskit Agent Front-Door Hardening Blueprint

## Einordnung

Dieser Blueprint plant die nächste Härtungsstufe der agent-facing Lenskit-Oberfläche. Er
ersetzt weder die bestehende Output-Architektur noch deren bereits umgesetzte
Begriffshärtung:

- `lenskit-output-optimierung-v1.md` bleibt die Herkunft des Agent Reading Pack.
- `lenskit-anti-hallucination-output-architecture.md` bleibt die übergreifende
  Authority-/Inference-Grenze.
- `lenskit-authority-risk-matrix.md` bleibt die Governance-Grundlage für Authority und
  Risk-Class.

Der neue Scope ist enger: vorhandene Artefakte sollen über eine bessere Front Door
aufgabengerecht genutzt werden, bevor weitere Contracts, Sidecars oder Retrieval-
Optimierungen entstehen. Dieser PR registriert nur den Plan; er ändert keine Runtime,
Pipeline, Schemas, Health-Gates oder Producer.

## Problem

Lenskit erzeugt bereits eine kanonische Markdown-Sicht und abgeleitete Flächen wie Agent
Reading Pack, Bundle Manifest, Citation Map, Claim Evidence Map, Post-Emit-Health und
Bundle Surface Validation. Das Agent Reading Pack ist dabei Navigation, nicht
Inhaltswahrheit.

Lesende LLMs oder Coding Agents können diese Flächen trotzdem ignorieren und nur
`canonical_md` linear lesen. Dadurch bleiben vorhandene Evidence-Adressen,
Oberflächendiagnosen und aufgabenspezifische Grenzen praktisch ungenutzt. Das primäre
Problem ist daher nicht ein Mangel an neuen Artefakten, sondern eine zu schwache
Front-Door-Nutzungsdisziplin.

## Architekturentscheidung

1. `canonical_md` bleibt die einzige Inhaltswahrheit.
2. Das Agent Reading Pack bleibt ein abgeleiteter Navigationsindex, keine Wahrheit.
3. Sidecars bleiben je nach Rolle Navigation, Diagnose, Index oder Cache; sie erhalten
   keine stille Authority-Aufwertung.
4. Lenskit führt keine LLM- oder Embedding-Integration im Core ein.
5. Lenskit erzeugt keine autonomen Review-Findings und keine Patch-Automation.
6. Ein Health- oder Surface-Pass ist keine Antwortsicherheit, kein Repo-Verständnis und
   kein Wahrheitsverdikt.
7. Neue maschinenlesbare Consumption-Flächen folgen nur nach sichtbarer Markdown-
   Härtung und einem belegten Bedarf.

## Non-Goals

- kein LLM-Core
- keine Embeddings
- kein semantisches Reranking
- keine autonomen Review-Findings
- keine Patch-Automation
- keine neuen Primary Lens IDs
- keine sofortigen neuen Consumption-Contracts
- kein Agent Entry Manifest im ersten Slice
- kein Agent Consumption Trace im ersten Slice
- keine neuen Sidecars im ersten Slice
- keine Promotion bestehender Health-/Surface-Diagnosen zu Antwort-Gates
- keine Pipeline-, Service- oder Frontend-Mutation durch diesen Blueprint-PR

## Strategie und Reihenfolge

1. Agent Reading Pack v1.1 als Front-Door-Härtung umsetzen.
2. Die erwartete Pack-Struktur mit einem Agent-Pack-Usage Smoke absichern.
3. Ein Retrieval Review Goldset v1 definieren und die Baseline messen.
4. Das Required Reading Protocol zunächst als Markdown stabilisieren.
5. Fehlende Front-Door-Sektionen später höchstens als Warnungen in bestehenden
   Diagnoseflächen sichtbar machen.
6. Erst danach ein JSON-Contract für Required Reading erwägen.
7. Answer Compliance und Agent Consumption Trace nur bei praktisch belegtem Bedarf
   ergänzen.
8. Primary Lenses auditieren, bevor Facets, Lens Cards oder Relation Cards entstehen.
9. Retrieval v2 ausschließlich deterministisch und erst nach einem stabilen Goldset
   angehen.

## Roadmap-Slices

| Slice | Ergebnis | Eintrittsbedingung / Grenze |
| --- | --- | --- |
| 1 | Agent Reading Pack v1.1 | Front Door im vorhandenen Markdown härten; keine neuen Artefakte |
| 2 | Agent-Pack-Usage Smoke | Slice 1 strukturell testen; keine externe Antwort validieren |
| 3 | Retrieval Review Goldset v1 | Messgrundlage schaffen; noch kein Ranking-Fix |
| 4 | Required Reading Protocol v0 als Markdown | Task-Profile nach praktischer Erprobung normativ dokumentieren |
| 5 | Post-/Surface-Warns | Nur additive Warnungen; keine Antwortsicherheits- oder Truth-Promotion |
| 6 | Required Reading Protocol v1 als JSON | Erst nach stabilen Markdown-Regeln und nachgewiesenem Maschinenbedarf |
| 7 | Answer Compliance Contract | Nutzungserklärung normieren, ohne Korrektheit zu behaupten |
| 8 | Agent Consumption Trace | Nur wenn ein realer Wrapper/Workflow den Contract konsumiert |
| 9 | Agent Entry Manifest | Nur falls die Sidecar-Fläche tatsächlich unübersichtlich wächst |
| 10 | Primary Lens Audit | Bestehende Primary-Lens-Zuordnung sichtbar machen, nicht ändern |
| 11 | Facet Model | Additive Sichtachsen; genau eine Primary Lens bleibt bestehen |
| 12 | Lens Cards | Kleine Navigationskarten ohne Verdict-, Fix- oder Impact-Semantik |
| 13 | PR Delta Cards | Bestehende Deltas navigierbar machen, keine Review-Urteile erzeugen |
| 14 | Relation Cards | Deterministische Beziehungen ohne Kausalitätsbehauptung |
| 15 | Guard Relation Cards | Tests/Guards zuordnen, ohne Test-Suffizienz zu behaupten |
| 16 | Retrieval v2 deterministisch | Nur nach Goldset und messbarer Nichtregression |

Jeder Slice ist ein eigener Implementierungs- oder Planungs-PR. Ein Slice darf nicht
mehrere neue Subsysteme implizit zusammenziehen.

## Slice 1 — Agent Reading Pack v1.1

### Ziel

Das vorhandene Agent Reading Pack soll vor jeder späteren Contractisierung sichtbar
machen, welche Artefakte ein Task-Profil benötigt, welche Authority-Grenzen gelten und
welche Aussagen nicht zulässig sind.

### Geplante Abschnitte

- `REQUIRED_READING_BY_TASK`
- `WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT`
- `SIDECAR_USAGE_RULES`
- `ANSWER_COMPLIANCE_CHECKLIST`
- `DO_NOT_CLAIM`

### Erste Task-Profile

| Profil | Zweck | Minimale Leitplanke |
| --- | --- | --- |
| `basic_repo_question` | leichte Repo-Frage | Pack und `canonical_md`; Sidecar-Aussagen am Kanon prüfen |
| `pr_review` | belegorientierter Review | Citation-/Health-Flächen zusätzlich prüfen; kein Review-Verdict aus Diagnose ableiten |
| `roadmap_status_claim` | Roadmap-/Statusaussage | Claim-Evidence-Navigation nutzen; Status weiterhin am kanonischen Inhalt prüfen |
| `artifact_surface_review` | Bundle-/Surface-Prüfung | Manifest, Post-Emit-Health und Surface Validation als Diagnose lesen |
| `retrieval_quality_review` | Retrieval-Bewertung | Retrieval-Eval und Indexflächen metrisch prüfen; Eindruck ersetzt keine Baseline |

Die konkrete Required-/Recommended-Matrix wird im Slice-1-PR gegen die dann aktuellen
Artifact Roles und Producer-Contracts verifiziert. Dieser Blueprint friert keine noch
ungeprüfte Runtime-Payload ein.

### Slice-1-Nicht-Ziele

- keine neuen Schemas
- keine neuen Sidecars
- keine Health-/Surface-Gate-Promotion
- kein Retrieval-Ranking
- keine Pipeline-Mutation
- keine Änderung an Primary Lens IDs
- kein Proof-Zwang vor der tatsächlichen Implementierung

### Slice-1-Akzeptanz

Ein Agent, der das Pack liest, kann Task-Profil, Pflichtlektüre, Authority-Grenzen und
eine knappe Offenlegung der verwendeten Flächen erkennen. Das Pack bleibt dabei
`navigation_index`/`derived`; seine Existenz oder Vollständigkeit beweist weder korrekte
Nutzung noch eine korrekte Antwort.

## Gates

### Canonical Authority Gate

`canonical_md` bleibt die einzige Inhaltswahrheit. Navigation muss auf kanonische
Bereiche oder rollenadäquate Belege zurückführen.

### No Silent Authority Upgrade

Kein Agent-, Evidence-, Health-, Retrieval-, Card- oder Relation-Artefakt darf ohne
explizite Governance-Entscheidung von Navigation/Diagnose zu Wahrheit aufgewertet
werden.

### Required Reading Visible Before JSON Contract

Task-spezifische Required-Reading-Regeln müssen zuerst im Agent Reading Pack sichtbar,
verständlich und getestet sein. Ein JSON-Contract darf die Regeln später abbilden, aber
nicht vorab erfinden.

### Negativsemantik / `does_not_establish`

Jede neue agent-facing Fläche muss explizit begrenzen, was sie nicht etabliert. Mindestens
zu prüfen sind Wahrheit, Korrektheit, Vollständigkeit, `repo_understood`,
`answer_safe_without_citations`, Test-Suffizienz, Runtime-Verhalten und
Regressionsfreiheit.

### Determinism

Gleicher Bundle-Zustand und gleiche Task-Profil-Eingabe müssen dieselbe Lenskit-Ausgabe
erzeugen. Freie Modellinterpretation ist kein Producer-Schritt.

### No LLM / No Embedding

Kein Slice darf eine Modell-, Provider- oder Embedding-Abhängigkeit in den Core-Pfad
einführen.

### Retrieval v2 Only After Goldset

Kein Retrieval-v2-Ranking wird begonnen oder promoted, bevor ein Review-Goldset eine
Baseline, Kategorien und Nichtregressionskriterien festlegt.

## Stop-Regeln

Sofort stoppen und den Slice neu bewerten, wenn:

- `canonical_md` relativiert würde;
- das Agent Reading Pack als Wahrheit behandelt würde;
- neue Sidecars vor der Front-Door-Härtung eingeführt würden;
- Retrieval v2 ohne Goldset begonnen würde;
- Health-/Surface-Pass als Antwortsicherheit formuliert würde;
- Claim Evidence Map als Claim-Wahrheit formuliert würde;
- bestehende Tests durch Abschwächung statt Korrektur grün gemacht würden;
- Planning Registration unklar bleibt;
- ein einzelner Slice mehrere neue Subsysteme gleichzeitig einführt.

## Open Questions

1. Reicht die Markdown-Front-Door-Härtung aus, oder ist später ein JSON-Contract nötig?
2. Wann rechtfertigt ein realer Workflow einen Agent Consumption Trace?
3. Wie lässt sich Sidecar-Nutzung praktisch messen, ohne tatsächliches Lesen oder
   Antwortkorrektheit vorzutäuschen?
4. Welche Retrieval-Goldset-Kategorien sind für PR Review zuerst erforderlich?
5. Wann dürfen Lens Cards eingeführt werden, ohne die Primary-Lens- und
   Authority-Grenzen zu verwischen?
6. Welche Regeln gehören langfristig in das Pack und welche in eine eigenständige
   Required-Reading-Dokumentation?

## Next Implementation Slice

**TASK-AGENT-FRONTDOOR-001 — Agent Reading Pack v1.1**

Der nächste PR darf ausschließlich Slice 1 umsetzen. Insbesondere bleiben
Post-Emit-Health, Bundle Surface Validation, Export Gate, Merge-Pipeline, Contracts und
Retrieval-Ranking außerhalb dieses ersten Implementierungsslices.
