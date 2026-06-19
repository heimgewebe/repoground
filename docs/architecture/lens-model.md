---
doc_type: architecture
status: active
---

# Deterministic Lens Model

## 1. Zweck und Scope

Dieses Dokument normiert die Begriffe und Schichtengrenzen der Lenskit-Linsenarchitektur.
Es ist Architekturdefinition, Begriffsschicht und Grundlage fuer spaetere Contracts.

Eine Lens ist etymologisch eine Linse: eine kontrollierte Sicht auf denselben Gegenstand.
Im Systemkontext ist sie kein neuer Gegenstand und keine neue Wahrheit.

Normativer Kernsatz:

> Eine Lenskit-Linse ist eine deterministische, abgeleitete Sicht auf Repo- oder Bundle-Artefakte. Sie besitzt eine dokumentierte Herkunftsregel und eine explizite Geltungsgrenze. Sie dient der Navigation und erzeugt kein eigenes Wahrheits-, Review-, Sicherheits- oder Impact-Urteil.

Dieses Dokument ist nicht Runtime-Evidence, kein JSON-Schema, kein Implementierungsbeweis,
kein Bundle-Artefakt, kein Review-Bericht und kein Statusbeweis.

Beziehungen:
- `docs/blueprints/lenskit-agent-front-door-hardening.md`
- `docs/blueprints/lenskit-authority-risk-matrix.md`
- `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`
- `docs/architecture/two-layer-artifact-pattern.md`
- `docs/architecture/agent-consumption-contract.md`
- `docs/architecture/answer-compliance.md`
- `docs/architecture/artifact-inventory.md`

## 2. Invarianten

- Linsen sind abgeleitete Navigation, keine Inhaltsautoritaet.
- `canonical_md` bleibt innerhalb eines Dump-Bundles die einzige Inhaltswahrheit.
- Eine Primary Lens bleibt single-label.
- Additive Facets, States, Relations und Task Contexts ersetzen keine Primary Lens.
- Reihenfolgen in Listen duerfen keine semantische Prioritaet ausdruecken.
- Unbekannte Begriffe werden nicht still zu bekannten Linsen- oder Facet-Namen umgedeutet.

## 3. Primary Lens

Eine Primary Lens beantwortet:

> Was ist dieser Pfad primaer?

Jeder auditierbare Repo-Pfad hat genau eine Primary Lens. Sie beschreibt ausschliesslich
die primaere technische Rolle des Pfads. Die Primary Lens wird aktuell durch
`infer_lens()` in `merger/lenskit/core/lenses.py` bestimmt.

Die sieben kanonischen IDs bleiben unveraendert:
- `entrypoints`
- `core`
- `interfaces`
- `data_models`
- `pipelines`
- `ui`
- `guards`

Der Primary Lens Audit erklaert die bestehende `infer_lens()`-Zuordnung ueber
`matched_rule`. Er ersetzt sie nicht, fuegt keine neue Lens hinzu und bleibt ebenfalls
single-label.

Primary Lens beantwortet nicht:
- Warum ist der Pfad fuer diesen PR wichtig?
- Was bricht bei einer Aenderung?
- Sind Tests ausreichend?
- Ist der Code sicher?
- Ist ein Review vollstaendig?
- Welche semantische Wichtigkeit hat der Pfad?

## 4. Facet

Ein Facet ist eine additive Sichtachse. Ein Ziel kann null, ein oder mehrere Facets
tragen. Facets veraendern keine Primary Lens und bilden keine zweite konkurrierende
Primary-Lens-Ebene.

Jede spaetere Facet-Zuordnung muss deterministisch ableitbar sein und mindestens
folgende Ebenen trennen:
- `target`
- `name`
- `source_rule`
- `confidence_class`
- `does_not_establish`

Das bestehende Feld `possible_facets` im Primary Lens Audit ist derzeit nur ein leerer
Platzhalter. Der aktuelle Producer emittiert dort leere Listen. Dieses Feld beweist
nicht, dass Facet-Zuordnung oder ein Facet Model bereits implementiert ist.

Es existieren konkurrierende Kandidatenlisten:

Repo-naher Blueprint-Kandidatenstand:
- `contract`
- `artifact_surface`
- `diagnostic`
- `retrieval`
- `claim_boundary`
- `security`
- `test_guard`

Aeltere Minimalstart-Idee:
- `contract`
- `artifact_surface`
- `uncertainty`

Diese Listen sind nicht reconciled und werden hier nicht still zusammengefuehrt. Die
endgueltige Facet-Model-v1-Taxonomie ist noch offen.

`uncertainty` kann Facet- oder State-Semantik ueberlappen. `claim_boundary` kann Facet,
State oder Negativgrenze sein. Diese Entscheidung gehoert in den folgenden
Facet-Model-v1-Slice.

`impact`, `test_relevance` und `runtime_causality` sind keine Primary Lenses und keine
automatisch zugelassenen v1-Facets.

## 5. Confidence Class

`confidence_class` beschreibt die Herkunftsart der Zuordnung. Sie ist keine
Wahrscheinlichkeit, kein Korrektheitswert und kein numerischer Score.

`direct` bedeutet: Die Zuordnung ist direkt aus einer kontrollierten Eigenschaft
ableitbar, zum Beispiel aus explizitem Pfad, Dateisuffix, Contract-Datei, deklarierter
Artifact Role oder Manifestwert.

`derived` bedeutet: Die Zuordnung wird deterministisch aus vorhandenen strukturierten
Signalen abgeleitet.

`heuristic` bedeutet: Die Zuordnung folgt einer dokumentierten deterministischen Regel,
ohne semantischen Vollstaendigkeits- oder Wahrheitsbeweis.

## 6. Source Rule und Evidence Ref

`source_rule` beschreibt, durch welche Regel eine Zuordnung entstand.

`evidence_ref` adressiert eine konkrete Belegstelle oder ein strukturiertes Artefakt.

`confidence_class` beschreibt die Herkunftsart der Zuordnung.

Keine dieser Ebenen beweist fuer sich Wahrheit, Vollstaendigkeit, semantische Wichtigkeit,
Runtime-Wirkung oder Review-Relevanz. Ob `evidence_ref` in Facet Model v1 Pflicht wird,
bleibt offen.

## 7. Relation

Eine Relation ist eine Verbindung zwischen zwei adressierbaren Zielen. Sie benoetigt
Quelle, Ziel, Typ und Herkunft. Sie kann `direct`, `derived` oder `heuristic` sein.

Kernsatz:

> Relation beschreibt eine sichtbare Verbindung; sie beweist weder Kausalitaet noch Auswirkung einer Aenderung.

Dieser PR legt keine Relationstyp-Taxonomie fest.

## 8. State

Ein State beschreibt einen epistemischen oder Aufloesungszustand. Er ist keine technische
Dateirolle, keine Primary Lens und keine automatische Fehlerbewertung.

Beispielkandidaten, nicht finaler Contract:
- `missing_evidence`
- `heuristic_assignment`
- `unresolved_reference`

Ein `missing_evidence`-State bedeutet nicht automatisch:
- Aussage falsch
- Implementierung defekt
- Aenderung unsicher
- Test fehlgeschlagen

Ob `uncertainty` als eigenes Facet oder durch konkrete States modelliert wird, ist fuer
Facet Model v1 noch zu entscheiden.

## 9. Task Context

Task Context erklaert, warum ein Ziel fuer eine konkrete Aufgabe navigativ relevant ist.

Beispiele:
- `pr_review`
- `contract_change_review`
- `artifact_surface_review`
- `security_review`
- `roadmap_status_claim`

Task Context ist keine dauerhafte Eigenschaft der Datei, veraendert keine Primary Lens,
ist nicht dasselbe wie ein Required-Reading-Profil und beweist keinen Review-Befund oder
Change Impact.

Required Reading beantwortet:

> Welche Artefakte muessen gelesen werden?

Task Context beantwortet:

> Warum kann dieses Ziel fuer die konkrete Aufgabe relevant sein?

## 10. Lens Card

Eine Lens Card ist eine kleine abgeleitete Navigationseinheit. Sie kann spaeter Primary
Lens, Facets, States, Relations und Evidence-Adressen zusammenfuehren. Sie bleibt
regenerierbar und ersetzt keine kanonischen Inhalte.

Authority:
- `navigation_index`

Canonicality:
- `derived`

Verbotene unqualifizierte Card-Felder oder Claims:
- `verdict`
- `approved`
- `safe`
- `complete`
- `covered`
- `critical`
- `impact`
- `breaks`
- `requires_fix`

## 11. Relation Card und Guard Relation

Eine Relation Card ist eine spaetere Spezialisierung: die kompakte Darstellung einer
Relation mit Herkunft und Evidence-Grenze. Sie ist kein Kausalitaets- oder Impact-Beweis.

Eine Guard Relation ist eine spaetere Spezialisierung: eine Relation zwischen Ziel und
Test-, Validator-, Guard- oder CI-Flaeche. Sie dient Navigation.

Eine Guard Relation beweist nicht:
- `test_sufficiency`
- `coverage_completeness`
- `guard_effectiveness`
- `runtime_correctness`
- `regression_absence`

Diese Spezialisierungen werden hier nicht implementiert.

## 12. Abgrenzung zum Agent Consumption Trace

Agent Consumption Trace ist ausserhalb der Lens-Primitiven einzuordnen. Er ist eine
Consumer-/Compliance-Flaeche und kann spaeter Lens Cards konsumieren.

Agent Consumption Trace ist kein Facet, keine Relation, kein State und keine Primary Lens.
Er beweist kein tatsaechliches Lesen und kein Repo-Verstaendnis.

## 13. Schichtenmodell

| Schicht | Kardinalitaet | Zweck | Beweist nicht |
| --- | --- | --- | --- |
| Primary Lens | genau 1 pro Pfad | primaere technische Rolle | Wichtigkeit, Impact |
| Facet | 0..n | additive Sichtachsen | Wahrheit, Prioritaet |
| Relation | 0..n | sichtbare Verbindung | Kausalitaet, Bruch |
| State | 0..n | epistemischer/Aufloesungszustand | Fehler oder Unsicherheit der Implementierung |
| Task Context | 0..n pro Aufgabe | aufgabenspezifische Navigation | Review-Befund |
| Lens Card | abgeleitet | kompakte Navigationsprojektion | Inhaltsautoritaet |

## 14. Authority und Canonicality

`canonical_md` bleibt innerhalb eines Dump-Bundles die einzige Inhaltswahrheit.

Folgende Flaechen bleiben abgeleitete Navigation oder Diagnose:
- Primary Lens Audit
- Facets
- Relations
- States
- Lens Cards
- Health Reports
- Surface Validation

Ein Health- oder Surface-Pass beweist nicht:
- `repo_understood`
- `claims_true`
- `review_complete`
- `test_sufficiency`
- `runtime_correctness`
- `forensic_ready`

Das Lens-Modell erzeugt keine neue Evidence. Es kann Evidence nur adressieren,
projizieren oder navigativ ordnen.

## 15. Negativsemantik

Als gemeinsame Mindestgrenze zukuenftiger Lens-/Facet-/Relation-/Card-Artefakte gilt:

```json
{
  "does_not_establish": [
    "truth",
    "correctness",
    "completeness",
    "runtime_behavior",
    "test_sufficiency",
    "regression_absence",
    "semantic_importance",
    "review_priority",
    "change_impact"
  ]
}
```

Bestehende Contracts verwenden teils andere Feldnamen wie `does_not_mean`,
`does_not_prove` oder `claim_boundaries`. Dieser PR migriert keine bestehenden
Contracts. Semantische Grenzen sollen konsistent sein. Feldnamenvereinheitlichung ist
ein separater Task.

## 16. Determinismus-Invarianten

1. Gleicher Repo-Zustand und gleiche Regeln erzeugen dieselbe Zuordnung.
2. Ausgaben werden stabil sortiert.
3. Deduplizierung ist deterministisch.
4. Reihenfolge erzeugt keine semantische Prioritaet.
5. Keine Netzwerkabfrage ist fuer die Klassifikation erforderlich.
6. Keine LLM-Auswertung ist erforderlich.
7. Keine Embeddings sind erforderlich.
8. Keine Systemzeit veraendert die Zuordnung.
9. Heuristische Regeln werden explizit benannt.
10. Unbekannte Begriffe werden nicht still umgedeutet.
11. Neue Facets aendern keine Primary Lens.
12. Abgeleitete Karten bleiben regenerierbar.

## 17. Aktueller Implementierungsstand

Implementiert:
- sieben Primary Lenses
- `infer_lens()`
- Primary Lens Audit Contract
- Primary Lens Audit Core Producer
- fokussierte Primary-Lens-Audit-Tests

Nicht implementiert:
- Facet Model
- Lens Cards
- Relation Cards
- Guard Relation Cards
- automatische Primary-Lens-Audit-Bundle-Emission
- verpflichtendes CLI-Wiring fuer den Audit

Es wird nicht behauptet, dass jeder Dump bereits ein Primary-Lens-Audit-Sidecar enthaelt.

## 18. Sequenzierung

Sequenz:

Primary Lens Audit v1 -- Contract/Core/Tests umgesetzt
-> Lens Model -- dieser PR
-> Facet Model v1 -- naechster Code-Slice
-> Lens Cards v1
-> PR Delta Cards
-> Relation Cards
-> Guard Relation Cards

Das Lens-Modell ist Voraussetzung fuer das Facet Model, aber kein Implementierungsbeweis.

## 19. Open Decisions for Facet Model v1

Diese Punkte werden in diesem PR nicht entschieden, sofern kein bestehendes Repo-Dokument
sie bereits eindeutig normiert:

1. endgueltige Facet-v1-Taxonomie
2. `uncertainty` als Facet oder State-Modell
3. Rolle von `claim_boundary`
4. genaue JSON-Struktur
5. Bericht versus einzelne Zuordnungen
6. Identitaet und Deduplizierung
7. Sortierregeln
8. erlaubte `source_rule`-Taxonomie
9. Evidence-Refs Pflicht oder optional
10. Target-ID-Modell
11. Verhalten bei unbekannten Facet-Namen
12. Bundle-/Manifest-Sichtbarkeit
13. CLI
14. automatische Emission
15. Feldnamen fuer Negativsemantik

## 20. Non-goals

- keine neuen Primary Lenses
- keine Aenderung an `infer_lens()`
- keine gemeinsame Rule Engine
- kein Facet-Contract
- kein Facet-Code
- keine Lens Cards
- keine Relationsimplementierung
- kein CLI
- keine Bundle-Emission
- kein Retrieval-Ranking
- keine Embeddings
- keine LLM-Integration
- keine Review-Urteile
- keine Impact-Sprache
