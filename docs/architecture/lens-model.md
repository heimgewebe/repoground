# Deterministic Lens Model

## 1. Zweck und Scope

Dieses Dokument normiert die Begriffe und Schichtengrenzen der Lenskit-Linsenarchitektur.
Es ist Architekturdefinition, Begriffsschicht und Grundlage für spätere Contracts.

Das englische `lens` geht auf das lateinische `lens` zurück, das die
Linsenfrucht bezeichnet; die optische Linse wurde nach ihrer Form benannt.
Im Systemkontext bezeichnet eine Lens eine kontrollierte Sicht auf denselben
Gegenstand, nicht einen neuen Gegenstand und keine neue Wahrheit.

Normativer Kernsatz:

> Eine Lenskit-Linse ist eine deterministische, abgeleitete Sicht auf Repo- oder Bundle-Artefakte. Sie besitzt eine dokumentierte Herkunftsregel und eine explizite Geltungsgrenze. Sie dient der Navigation und erzeugt kein eigenes Wahrheits-, Review-, Sicherheits- oder Impact-Urteil.

Dieses Dokument ist nicht Runtime-Evidence, kein JSON-Schema, kein Implementierungsbeweis,
kein Bundle-Artefakt, kein Review-Bericht und kein Statusbeweis.

Das Two-Layer Artifact Pattern bestimmt, welche Lens-Flächen nur zeigen und
welche Quellen Inhalt beweisen.
Der Agent Consumption Contract bestimmt, welche Flächen für eine Aufgabe
konsumiert oder deklariert werden; er macht daraus keine Lens-Primitive.
Das Lens-Modell ordnet Navigation, ersetzt aber weder diese
Consumption-Regeln noch die bestehenden Authority- und
Canonicality-Grenzen.

Beziehungen:
- `docs/blueprints/lenskit-agent-front-door-hardening.md`
- `docs/blueprints/lenskit-authority-risk-matrix.md`
- `docs/blueprints/lenskit-anti-hallucination-output-architecture.md`
- `docs/architecture/two-layer-artifact-pattern.md`
- `docs/architecture/agent-consumption-contract.md`
- `docs/architecture/answer-compliance.md`
- `docs/architecture/artifact-inventory.md`

## 2. Invarianten

- Linsen sind abgeleitete Navigation, keine Inhaltsautorität.
- `canonical_md` bleibt innerhalb eines Dump-Bundles die einzige Inhaltswahrheit.
- Eine Primary Lens bleibt single-label.
- Additive Facets, States, Relations und Task Contexts ersetzen keine Primary Lens.
- Reihenfolgen in Listen dürfen keine semantische Priorität ausdrücken.
- Unbekannte Begriffe werden nicht still zu bekannten Primary Lenses, Facets, States oder Relationstypen umgedeutet.

## 3. Primary Lens

Eine Primary Lens beantwortet:

> Was ist dieser Pfad primär?

Für jeden vom Modell akzeptierten und an `infer_lens()` übergebenen Repo-Pfad
liefert die aktuelle Klassifikationsfunktion genau eine Primary Lens.
Diese Totalität der Klassifikationsfunktion beweist nicht, dass ein konkreter
Audit alle Repo-Pfade erhalten oder verarbeitet hat.

`infer_lens()` ist die aktuelle Implementierung der Primary-Lens-Zuordnung.
Das Lens-Modell normiert die Semantik der Primary Lens, nicht die dauerhafte
Unveränderlichkeit einer einzelnen Python-Funktion.
Änderungen an IDs, Prioritäten oder Zuordnungsregeln benötigen jedoch einen
eigenen, kompatibilitätsgeprüften Slice.

Die sieben kanonischen IDs bleiben unverändert:
- `entrypoints`
- `core`
- `interfaces`
- `data_models`
- `pipelines`
- `ui`
- `guards`

Der Primary Lens Audit erklärt die bestehende `infer_lens()`-Zuordnung über
`matched_rule`. Er ersetzt sie nicht, fügt keine neue Lens hinzu und bleibt ebenfalls
single-label.

Primary Lens beantwortet nicht:
- Warum ist der Pfad für diesen PR wichtig?
- Was bricht bei einer Änderung?
- Sind Tests ausreichend?
- Ist der Code sicher?
- Ist ein Review vollständig?
- Welche semantische Wichtigkeit hat der Pfad?

## 4. Facet

Ein Facet ist eine additive Sichtachse. Ein Ziel kann null, ein oder mehrere Facets
tragen. Facets verändern keine Primary Lens und bilden keine zweite konkurrierende
Primary-Lens-Ebene.

Jede spätere Facet-Zuordnung muss mindestens folgende Konzepte ausdrücken:
- eine adressierbare Zielidentität,
- einen kontrollierten Facet-Bezeichner,
- eine dokumentierte Ableitungsregel,
- eine Ableitungsart,
- explizite Negativsemantik.
Die konkreten JSON-Feldnamen, die Zieladressierung und die genaue Shape werden
im Facet-Model-v1-Contract festgelegt.

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

Ältere Minimalstart-Idee:
- `contract`
- `artifact_surface`
- `uncertainty`

Diese Listen sind nicht reconciled und werden in diesem Dokument weder
zusammengeführt noch als finale Facet-Model-v1-Taxonomie festgelegt.

`uncertainty` kann Facet- oder State-Semantik überlappen. `claim_boundary` kann Facet,
State oder Negativgrenze sein. Diese Entscheidung gehört in den folgenden
Facet-Model-v1-Slice.

`impact`, `test_relevance` und `runtime_causality` sind keine Primary Lenses und keine
automatisch zugelassenen v1-Facets.

Ein Facet-Name autorisiert keine weitergehende Aussage.

Beispiele:

- `security` würde nur eine kontrollierte Zuordnung zu einer
  sicherheitsbezogenen Oberfläche ausdrücken, nicht das Vorliegen eines
  Risikos und nicht die Sicherheit des Ziels.
- `test_guard` würde nur eine navigative Zuordnung zu Test- oder
  Guard-Flächen ausdrücken, nicht Testabdeckung, Wirksamkeit oder
  Test-Suffizienz.
- `claim_boundary` würde nur eine deklarierte Claim-Grenze sichtbar machen,
  nicht Wahrheit oder Falschheit eines Claims.

## 5. Ableitungsart

Die Ableitungsart beschreibt, wie eine Zuordnung erzeugt wurde.
Sie ist unabhängig von den bestehenden Achsen `authority` und
`canonicality`.
Sie ist keine Wahrscheinlichkeit, kein Korrektheitswert und kein numerischer
Confidence Score.

- `direct`: Die Zuordnung wird unmittelbar aus einer expliziten und
  kontrollierten Eigenschaft abgelesen, beispielsweise aus einem Pfad,
  einem Dateisuffix, einem Contract-Typ, einem Manifestwert oder einer
  deklarierten Artifact Role.
- `derived`: Die Zuordnung wird deterministisch aus vorhandenen
  strukturierten Signalen abgeleitet.
- `heuristic`: Die Zuordnung folgt einer dokumentierten deterministischen
  Regel ohne semantischen Wahrheits-, Vollständigkeits- oder
  Wichtigkeitsbeweis.

Der Wert `derived` auf der Achse der Ableitungsart ist nicht identisch mit
`canonicality = derived`.
- Die Ableitungsart beschreibt, wie eine einzelne Zuordnung entstand.
- Canonicality beschreibt den Quellenstatus eines Artefakts.

## 6. Ableitungsregel und Evidence-Adresse

Eine Ableitungsregel beschreibt, durch welche kontrollierte Regel eine
Zuordnung entstand.
Eine Evidence-Adresse verweist auf eine konkrete Belegstelle oder ein
strukturiertes Artefakt.
Die Ableitungsart beschreibt dagegen, auf welche Weise aus den verfügbaren
Signalen eine Zuordnung erzeugt wurde.

Keine dieser Ebenen beweist für sich Wahrheit, Vollständigkeit, semantische
Wichtigkeit, Runtime-Wirkung oder Review-Relevanz.
Ob Evidence-Adressen im Facet Model v1 Pflicht werden, bleibt offen.

## 7. Relation

Eine Relation ist eine Verbindung zwischen zwei adressierbaren Zielen.
Eine Relation muss konzeptionell eine Quelle, ein Ziel, einen Relationstyp
und die Ableitungsart der Relation ausdrücken.
Die konkreten Feldnamen, Adressformen und Relationstypen bleiben dem späteren
Contract vorbehalten. Die Ableitungsart kann `direct`, `derived` oder `heuristic` sein.

Kernsatz:

> Relation beschreibt eine sichtbare Verbindung; sie beweist weder Kausalität noch Auswirkung einer Änderung.

Dieser PR legt keine Relationstyp-Taxonomie fest.

## 8. State

Ein State beschreibt einen epistemischen oder Auflösungszustand. Er ist keine technische
Dateirolle, keine Primary Lens und keine automatische Fehlerbewertung.

Beispielkandidaten, nicht finaler Contract:
- `missing_evidence`
- `unresolved_reference`
- `ambiguous_target`

Ob eine Zuordnung heuristisch entstand, gehört zur Ableitungsart und wird
nicht zusätzlich als State dupliziert.
States beschreiben davon unabhängige Evidenz-, Auflösungs- oder
Adressierungszustände.

Ein `missing_evidence`-State bedeutet nicht automatisch:
- Aussage falsch
- Implementierung defekt
- Änderung unsicher
- Test fehlgeschlagen

Ob `uncertainty` als Facet, als Oberbegriff für konkrete States oder gar nicht
als eigener kontrollierter Bezeichner modelliert wird, bleibt eine
Entscheidung des Facet-Model-v1-Slices.

## 9. Task Context

Task Context erklärt, warum ein Ziel für eine konkrete Aufgabe navigativ relevant ist.

Beispiele:
- `pr_review`
- `contract_change_review`
- `artifact_surface_review`
- `security_review`
- `roadmap_status_claim`

Task Context ist keine dauerhafte Eigenschaft der Datei, verändert keine Primary Lens,
ist nicht dasselbe wie ein Required-Reading-Profil und beweist keinen Review-Befund oder
Change Impact.
Task Context ist ein expliziter Input einer aufgabenspezifischen
Navigationssicht und kein versteckter globaler Zustand.

Required Reading beantwortet:

> Welche Artefakte müssen gelesen werden?

Task Context beantwortet:

> Warum kann dieses Ziel für die konkrete Aufgabe relevant sein?

## 10. Lens Card

Eine Lens Card ist eine kleine abgeleitete Navigationseinheit. Sie kann später Primary
Lens, Facets, States, Relations und Evidence-Adressen zusammenführen. Sie bleibt
regenerierbar und ersetzt keine kanonischen Inhalte.

Authority: `navigation_index`
Canonicality: `derived`

Die Authority- und Canonicality-Achsen werden durch das Lens-Modell nicht neu
definiert. Maßgeblich bleiben die bestehenden Authority-Risk- und
Two-Layer-Regeln.

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

Eine Relation Card ist eine spätere Spezialisierung: die kompakte Darstellung
einer Relation einschließlich ihrer Ableitungs- und Evidence-Grenzen. Sie ist
kein Kausalitäts- oder Impact-Beweis.

Eine Guard Relation ist eine spätere Spezialisierung: eine Relation zwischen Ziel und
Test-, Validator-, Guard- oder CI-Fläche. Sie dient Navigation.

Eine Guard Relation beweist nicht:
- `test_sufficiency`
- `coverage_completeness`
- `guard_effectiveness`
- `runtime_correctness`
- `regression_absence`

Diese Spezialisierungen werden hier nicht implementiert.

## 12. Abgrenzung zum Agent Consumption Trace

Agent Consumption Trace ist außerhalb der Lens-Primitiven einzuordnen. Er ist eine
Consumer-/Compliance-Fläche und kann später Lens Cards konsumieren.

Agent Consumption Trace ist kein Facet, keine Relation, kein State und keine Primary Lens.
Er beweist kein tatsächliches Lesen und kein Repo-Verständnis.

## 13. Schichtenmodell

| Schicht | Kardinalität | Beschreibt höchstens | Geltungsgrenze |
| --- | --- | --- | --- |
| Primary Lens | genau 1 je akzeptiertem Pfad | primäre technische Rolle | keine Wichtigkeit, keine Audit-Vollständigkeit, kein Impact |
| Facet | 0..n | additive Sichtachse | keine Wahrheit, Priorität oder Risikobewertung |
| Relation | 0..n | sichtbare Verbindung | keine Kausalität oder Bruchbehauptung |
| State | 0..n | Evidenz-, Auflösungs- oder Adressierungszustand | kein automatisches Fehlerurteil |
| Task Context | 0..n je Aufgabe | aufgabenspezifische Navigationsrelevanz | kein Review-Befund |
| Lens Card | noch nicht festgelegt | kompakte Navigationsprojektion | keine Inhaltsautorität |

## 14. Authority und Canonicality

`canonical_md` bleibt innerhalb eines Dump-Bundles die einzige Inhaltswahrheit.

Folgende Flächen bleiben abgeleitete Navigation oder Diagnose:
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

Die folgende Liste definiert eine gemeinsame semantische Baseline für spätere
Lens-, Facet-, Relation- und Card-Artefakte.
Konkrete Contracts müssen äquivalente oder stärkere Negativsemantik
ausdrücken und dürfen artefaktspezifische Grenzen ergänzen.
Das Lens-Modell normiert damit die Bedeutung der Grenzen, aber nicht
zwingend einen identischen JSON-Feldnamen oder eine identische Shape für
jeden Contract.

- `truth`
- `correctness`
- `completeness`
- `runtime_behavior`
- `test_sufficiency`
- `regression_absence`
- `semantic_importance`
- `review_priority`
- `change_impact`

Artefaktspezifische Grenzen dürfen diese Baseline ergänzen, beispielsweise
`causality`, `coverage_completeness` oder `guard_effectiveness`.

Bestehende Contracts verwenden dafür je nach Artefakt unter anderem
`does_not_establish`, `does_not_mean`, `does_not_prove` oder
`claim_boundaries`.
Dieser PR deprecatet, migriert oder vereinheitlicht diese bestehenden
Contract-Shapes nicht.

## 16. Determinismus-Invarianten

1. Gleiche normalisierte Eingaben, gleicher Repo- oder Bundle-Inhalt,
   gleiche Regelversion, gleiche Toolversion, gleiche Konfiguration und –
   wo relevant – gleicher Task Context erzeugen dieselbe fachliche
   Zuordnung.
2. Fachliche Ausgaben werden stabil sortiert. Die Reihenfolge erzeugt
   keine semantische Priorität.
3. Deduplizierung ist deterministisch.
4. Task Context ist ein expliziter Input und kein versteckter globaler
   Zustand.
5. Zeitstempel dürfen Metadaten verändern, nicht jedoch fachliche
   Zuordnungen.
6. Repo-Pfade werden vor einer pfadbasierten Zuordnung nach einer
   contractuell festgelegten, plattformunabhängigen Semantik normalisiert.
   Die konkrete Normalisierungsregel bleibt dem jeweiligen Contract
   vorbehalten.
7. Netzwerkabfragen, LLM-Auswertungen und Embeddings sind keine
   fachlichen Inputs der deterministischen Klassifikation und dürfen die
   Zuordnung nicht beeinflussen.
8. Heuristische Regeln werden explizit benannt.
9. Unbekannte Begriffe werden nicht still zu bekannten Primary Lenses,
   Facets, States oder Relationstypen umgedeutet.
10. Neue Facets verändern keine Primary Lens.
11. Abgeleitete Karten bleiben regenerierbar.

## 17. Aktueller Implementierungsstand

Implementiert:
- sieben Primary Lenses
- `infer_lens()`
- Primary Lens Audit Contract
- Primary Lens Audit Core Producer
- fokussierte Tests für das Primary Lens Audit.

Nicht implementiert:
- Facet Model
- Lens Cards
- Relation Cards
- Guard Relation Cards
- automatische Bundle-Emission
- CLI-Anschluss

Der implementierte Core-Slice ist unabhängig von CLI- oder Bundle-Emission
nutzbar.
Diese Anschlüsse werden durch den aktuellen Status weder verlangt noch als
notwendige technische Schuld behauptet.

## 18. Sequenzierung

Sequenz:

```text
Primary Lens Audit v1 — Contract/Core/Tests umgesetzt
→ Lens Model — dieser PR
→ Facet Model v1 — nächster Code-Slice
→ Lens Cards v1
→ PR Delta Cards
→ Relation Cards
→ Guard Relation Cards
```

Das Lens-Modell ist Voraussetzung für das Facet Model, aber kein Implementierungsbeweis.

## 19. Open Decisions for Subsequent Slices

Die folgenden Fragen werden in diesem Dokument nicht entschieden. Sie sind
dem jeweils genannten Folgeslice oder einer ausdrücklich übergreifenden
Modellentscheidung zugeordnet.

### Facet Model v1

**Taxonomie und Semantik**
- endgültige Facet-v1-Taxonomie
- `uncertainty` als Facet, State-Oberbegriff oder kein eigener Bezeichner
- Rolle von `claim_boundary`

**Contract und Datenmodell**
- JSON-Struktur des Facet Model v1
- konkrete Feldnamen
- Target-ID-Modell
- Bericht versus einzelne Zuordnungen
- Identität und Deduplizierung von Facet-Zuordnungen
- Sortierregeln
- Taxonomie der Ableitungsregeln
- Evidence-Adressen Pflicht oder optional
- Verhalten bei unbekannten Facet-Namen
- konkrete Shape der Negativsemantik

### Lens Cards v1
- Kardinalität und Identität von Lens Cards

### Relation Cards und Guard Relation Cards
- kontrollierte Relationstypen

### Übergreifende Modellentscheidungen
- kontrollierte State-Bezeichner

### Operationalisierung
- CLI
- automatische Emission
- Bundle-/Manifest-Sichtbarkeit
- mögliche Artifact Role

## 20. Non-goals

- keine neuen Primary Lenses
- keine Änderung an `infer_lens()`
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
- keine unqualifizierten oder kausalen Change-Impact-Behauptungen
