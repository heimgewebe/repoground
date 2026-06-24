# Deterministic Lens Model

## 1. Zweck und Scope

Dieses Dokument normiert die Begriffe und Schichtengrenzen der Lenskit-Linsenarchitektur.
Es ist Architekturdefinition, Begriffsschicht und Grundlage für spätere Contracts.

Das englische `lens` geht auf das lateinische `lens` zurück, das die
Linsenfrucht bezeichnet; die optische Linse wurde nach ihrer Form benannt.
Im Systemkontext bezeichnet eine Lens eine kontrollierte Sicht auf denselben
Gegenstand, nicht einen neuen Gegenstand und keine neue Wahrheit.

Normativer Kernsatz:

> Eine Lenskit-Linse ist eine deterministische, abgeleitete Sicht auf Repo- oder Bundle-Artefakte. Sie besitzt eine dokumentierte Ableitungsregel und eine explizite Geltungsgrenze. Sie dient der Navigation und erzeugt kein eigenes Wahrheits-, Review-, Sicherheits- oder Impact-Urteil.

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
Das Facet Model v1 ist ein eigener Report (`lenskit.lens_facet_report`,
`merger/lenskit/contracts/lens-facet.v1.schema.json`) und befüllt `possible_facets`
nicht; die Verknüpfung beider Flächen bleibt einem späteren Slice vorbehalten.

Der aktuelle Blueprint nennt als erste, nicht finale Kandidaten:
- `contract`
- `artifact_surface`
- `diagnostic`
- `retrieval`
- `claim_boundary`
- `security`
- `test_guard`

Facet Model v1 setzt aus diesen Kandidaten eine bewusst kleine, kontrollierte
Taxonomie um: `contract`, `test` und `retrieval`. `test` ist die engere,
additive Form des Kandidaten `test_guard` (der `guard`-Anteil würde die
`guards` Primary Lens nur wiederholen). Die übrigen Kandidaten
(`artifact_surface`, `diagnostic`, `claim_boundary`, `security`) sind begründet
zurückgestellt. Die v1-Taxonomie ist damit ausdrücklich nicht vollständig und
bleibt erweiterbar.

`uncertainty` und `claim_boundary` werden in v1 nicht als Facets aufgenommen.
Ob `uncertainty` ein Facet, ein Oberbegriff für konkrete States oder kein
eigener kontrollierter Bezeichner ist und welche Rolle `claim_boundary` (Facet,
State oder Negativgrenze) spielt, bleibt späteren Slices vorbehalten.

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
Facet Model v1 macht Evidence-Adressen nicht zur Pflicht; `path`, `source_rule`
und `derivation_type` bilden den nachvollziehbaren Herkunftsnachweis. Ob
spätere, abgeleitete Facets Evidence-Adressen verlangen, bleibt offen.

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

Eine Lens Card ist eine kleine abgeleitete Navigationseinheit. Lens Card v1 ist
als Contract/Core/Validation/Test-Slice umgesetzt und beschreibt genau eine Card
für genau einen akzeptierten Repo-Pfad. `path` ist die Lens-Card-v1-Identität
innerhalb eines expliziten einzelnen Repository-Kontexts; ein separater
Card-ID-Begriff wird nicht eingeführt.

Ein akzeptierter Repo-Pfad ist ein Pfad, den das kontrollierte lexikalische
Pfadmodell akzeptiert. Daraus folgen weder Dateiexistenz noch Git-Tracking,
Lesbarkeit oder erfolgreiche Auflösung gegen einen bestimmten Snapshot.

Eine Batch-Ausgabe ist nur eine deterministisch sortierte In-Memory-Liste einzelner
Cards, kein Reportcontainer und kein Persistenzformat.

Lens Card v1 komponiert bestehende Flächen:
- `primary_lens` und `matched_rule` stammen aus der öffentlichen Primary-Lens-
  Erklärfunktion.
- `facets` sind eine Projektion aus `infer_facets()` mit genau den Feldern
  `facet`, `source_rule` und `derivation_type`.
- facet-freie Pfade erzeugen gültige Cards mit `facets: []`.
- `navigation_refs` enthält genau einen typisierten `repo_path`-Verweis auf
  denselben `path`.

Cards bleiben regenerierbar und ersetzen keine kanonischen Inhalte.

Authority: `navigation_index`
Canonicality: `derived`

Die Authority- und Canonicality-Achsen werden durch das Lens-Modell nicht neu
definiert. Maßgeblich bleiben die bestehenden Authority-Risk- und
Two-Layer-Regeln.

Lens Card v1 trägt die feste neunteilige Lens-Familien-Negativsemantik in
kanonischer Reihenfolge. Der semantische Validator prüft neben der
Contract-Shape, ob eine Card aus ihrem `path` durch die kontrollierten Producer
neu berechnet werden kann. Ein Validator-Pass beweist keine Wahrheit, kein
Repo-Verständnis, keine Reviewvollständigkeit, keine Runtime-Korrektheit, keine
Testausreichung und keinen Change Impact.

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

Nicht Teil von Lens Card v1:
- CLI
- automatische Emission
- Bundle-/Manifest-Sichtbarkeit
- Artifact Role
- Relations
- States
- Task Contexts
- Evidence-Adressen
- PR Delta Cards
- Retrieval-Nutzung

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

Soweit eine Schicht Repo-Pfade adressiert, gelten diese innerhalb eines
expliziten einzelnen Repository-Kontexts.

| Schicht | Kardinalität | Beschreibt höchstens | Geltungsgrenze |
| --- | --- | --- | --- |
| Primary Lens | genau 1 je akzeptiertem Pfad | primäre technische Rolle | keine Wichtigkeit, keine Audit-Vollständigkeit, kein Impact |
| Facet | 0..n | additive Sichtachse | keine Wahrheit, Priorität oder Risikobewertung |
| Relation | 0..n | sichtbare Verbindung | keine Kausalität oder Bruchbehauptung |
| State | 0..n | Evidenz-, Auflösungs- oder Adressierungszustand | kein automatisches Fehlerurteil |
| Task Context | 0..n je Aufgabe | aufgabenspezifische Navigationsrelevanz | kein Review-Befund |
| Lens Card | genau 1 je akzeptiertem Pfad | kompakte Primary-Lens-/Facet-Navigationsprojektion | keine Inhaltsautorität, keine Evidence, kein Review- oder Impact-Urteil, kein Dateiexistenzbeweis |

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
- fokussierte Tests für das Primary Lens Audit
- Facet Model v1: Contract (`lens-facet.v1.schema.json`), Core Producer
  (`lens_facets.py`) und fokussierte Tests, mit der bewusst kleinen Taxonomie
  `contract`/`test`/`retrieval`.
- Lens Card v1: Single-Card-Contract (`lens-card.v1.schema.json`),
  deterministischer Einzel-/Batch-Producer (`lens_cards.py`), semantischer
  Validator (`lens_card_validate.py`) und fokussierte Tests. Eine Card steht für
  genau einen akzeptierten Pfad. `path` ist die Identität innerhalb eines einzelnen
  Repository-Kontexts. Die Card projiziert Primary Lens plus Facets. Ein akzeptierter
  Repo-Pfad beweist weder Dateiexistenz noch Git-Tracking.
- PR Delta Cards v1 — umgesetzt. Der definierte Slice ist auf main gemergt und post-merge verifiziert.

- Relation Cards v1 — bewusst begrenzter imports-only Slice:
  deterministische Projektion lokaler `file → file`-`import`-Kanten mit
  `evidence_level=S1` aus einem bereits geladenen
  `architecture.graph.v1`-Mapping. Contract, Core, source-aware Validation
  und fokussierte Tests sind gemergt und auf main post-merge verifiziert
  (`TASK-RELATION-CARD-001`, `done`, PR #796, `f12d9e6d`).
  Relation Cards erkennen keine Beziehungen selbst; externe `module:`-Nodes
  sind ausgeschlossen; Guard Relations, Bundle-, CLI- und
  Retrieval-Integration bleiben offen.

Nicht implementiert:
- vollständige Facet-Taxonomie (v1 deckt nur drei kontrollierte Facets ab)
- Befüllung von `possible_facets`
- automatische Lens-Card-Emission
- Bundle-/Manifest-Sichtbarkeit von Lens Cards
- weitere Relation-Typen über `imports` hinaus (`mentions`/`validates`/`tests`/`documents`/`produces`/`consumes`/`same_surface`)
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
→ Lens Model — umgesetzt
→ Facet Model v1 — Contract/Core/Tests umgesetzt (Taxonomie bewusst klein)
→ Lens Cards v1 — Contract/Core/Validation/Tests umgesetzt
→ PR Delta Cards v1 — Contract/Core/Validation/Tests umgesetzt
→ Relation Cards v1 — imports-only Contract/Core/Validation/Test-Slice gemergt und post-merge verifiziert
→ Guard Relation Cards
```

Das Lens-Modell ist Voraussetzung für das Facet Model, aber kein Implementierungsbeweis.

## 19. Open Decisions for Subsequent Slices

Die folgenden Fragen werden in diesem Dokument nicht entschieden. Sie sind
dem jeweils genannten Folgeslice oder einer ausdrücklich übergreifenden
Modellentscheidung zugeordnet.

### Facet Model v1 — entschieden

Facet Model v1 ist als Contract/Core/Test-Slice entschieden und umgesetzt
(siehe Abschnitt 17 und `merger/lenskit/contracts/lens-facet.v1.schema.json`):

- Taxonomie: kontrollierte v1-Facets `contract`, `test`, `retrieval`
  (bewusst unvollständig);
- Zielidentität: hostunabhängige kanonische repo-relative POSIX-Pfadidentität.
  Stringeingaben werden lexikalisch streng geprüft und nicht still normalisiert
  (ungültig sind z.B. `./a`, `a/./b`, `a//b`, Backslashes, Windows-Drive-Präfixe).
  Bei `PurePosixPath` ist nur die bereits von `pathlib` interpretierte
  POSIX-Repräsentation sichtbar; ursprüngliche redundante Schreibweisen sind
  nicht rekonstruierbar. Natives `Path` wird auf POSIX nur durch seine
  Typverwandtschaft zu `PurePosixPath` akzeptiert (keine portable
  Cross-Platform-Garantie). `PureWindowsPath` wird weiterhin mit `TypeError`
  abgelehnt. Core und Schema setzen EINE Facet-v1-Unicode-Skalar-Pfadpolicy
  durch: Steuer- und C1-Zeichen (U+0000–U+001F, U+007F–U+009F, inkl. NEL U+0085),
  Zeilen-/Absatztrenner (U+2028/U+2029), die BOM (U+FEFF) und reine
  Whitespace-Pfade sind ausgeschlossen. Beim Surrogat-Zeichenmodell unterscheiden
  Core und Schema bewusst: der Python-Core lehnt jeden Surrogat-Codepunkt in
  Runtime-Strings ab; die ECMAScript-Unicode-Regex-Validierung (u-Flag, wie Ajvs
  Default `unicodeRegExp`) lehnt ungepaarte UTF-16-Surrogat-Einheiten ab. Gültige
  internationale Unicode- und astrale Skalare (z. B. Emoji, ZWJ-Sequenzen)
  bleiben zulässig. Diese Entscheidung gilt nur für die Facet-v1-Artefaktfläche,
  nicht als globale Lenskit-Dateinamenpolitik; Begründung und Belege stehen im
  Proof. Das Schema prüft nur die emittierte Stringrepräsentation;
- Aufrufgrenze: `produce_facet_report()` erwartet ein Iterable mehrerer
  Pfadwerte; ein einzelner pfadartiger Wert (`str`, `bytes`, `bytearray`,
  `os.PathLike`) wird mit `TypeError` abgelehnt statt zeichenweise iteriert
  (für einen Einzelpfad: `infer_facets()`); Generatoren werden unterstützt;
- Report-Art: Zuordnungsreport, kein Evaluations-/Coverage-Report; facet-freie
  Pfade erscheinen nicht als Items; `target_count` zählt nur Pfade mit
  mindestens einem Facet;
- Zuordnungsidentität: `(path, facet)`, deterministisch dedupliziert
  (Producer-Invariante; das Schema setzt zusätzlich `uniqueItems` zur
  Verhinderung JSON-wertgleicher Duplikate);
- Ableitungsfeld: der v1-Contract erlaubt ausschließlich `direct` (`const`);
  das allgemeine Modellvokabular `direct`/`derived`/`heuristic` (Abschnitt 5)
  bleibt späteren, strukturell abgeleiteten Regeln vorbehalten; kein Confidence
  Score;
- Ableitungsregel: kontrolliertes `source_rule` je Zuordnung, genau eine Regel
  je Facet (keine Regelkollision in v1);
- Evidence-Policy: keine Pflicht-Evidence in v1;
- Negativsemantik: die Baseline aus Abschnitt 15 in fester kanonischer
  Reihenfolge auf Report- und Item-Ebene; diese feste Reihenfolge ist eine
  kanonische Serialisierungsreihenfolge für deterministische Ausgabe und trägt
  keine Rang-, Prioritäts- oder Wichtigkeitssemantik (vgl. Abschnitt 2);
- Summary-Kohärenz ist Producer-Invariante; das Schema prüft Typ und Shape,
  nicht die rechnerische Übereinstimmung mit `items`;
- Mehrfachzuordnung (mehrere Facets je Pfad) ist Producer-Capability und nicht
  mit dem aktuellen realen Bestand gleichzusetzen (derzeit keine realen
  Mehrfachzuordnungen);
- unbekannte Facet-Namen werden abgelehnt; ein Pfad darf null Facets tragen.

Weiterhin offen (nicht in v1 entschieden):
- die vollständige Facet-Taxonomie über die drei v1-Facets hinaus;
- `uncertainty` als Facet, State-Oberbegriff oder kein eigener Bezeichner;
- Rolle von `claim_boundary` (Facet, State oder Negativgrenze);
- ob Evidence-Adressen für spätere, abgeleitete Facets Pflicht werden.

### Lens Cards v1 — entschieden

Lens Card v1 ist als Contract/Core/Validation/Test-Slice entschieden und
umgesetzt:

- Contract-Einheit: genau eine Lens Card.
- Kardinalität: genau eine Card pro akzeptiertem Repo-Pfad.
- Identität: `path` (Identität innerhalb eines expliziten einzelnen Repository-Kontexts. Kein Dateiexistenzbeweis).
- zusätzliche Card-ID: keine.
- Primary Lens: Projektion aus der bestehenden öffentlichen Erklärfunktion,
  inklusive `matched_rule`.
- Facets: Projektion aus `infer_facets()` mit `facet`, `source_rule` und
  `derivation_type`; v1 ausschließlich `direct`.
- facet-freier Pfad: gültige Card mit `facets: []`.
- Navigation: genau ein `repo_path`-Verweis auf denselben `path`.
- Authority/Canonicality: `navigation_index` / `derived`.
- Persistenz, CLI und Bundle-Emission: keine.

Weiterhin offen:
- automatische Emission
- Bundle-/Manifest-Sichtbarkeit
- mögliche Artifact Role
- Relations
- States
- Task Contexts
- Retrieval-Nutzung

### PR Delta Cards v1 — umgesetzt

Der definierte Slice ist auf main gemergt und post-merge verifiziert.

- Identität: `path` innerhalb eines expliziten Delta-Kontexts.
- Keine GitHub-PR-Identität oder Commitidentität wird als Wahrheit behauptet.
- PR Delta Cards v1 enthalten keine Hashfelder und behaupten keine
  Hashprovenienz. Eine mögliche spätere Bundle-/Manifest-Integration ist
  nicht Teil dieses Slices und wird durch diesen PR weder implementiert
  noch zugesichert.
- Flache Projektion der `produce_lens_card(path)`-Werte.
- Change-Status ist strikt kontrolliert (`added`, `changed`, `removed`).
- keine automatische Emission.
- keine Datei-/Bundle-Ladeintegration.
- keine CLI.
- kein Consumer.
- keine Relations.
- keine Impact-/Risiko-/Reviewaussagen.

Die weiterhin offenen Punkte bleiben weiterhin offen:
- Relations
- States
- Task Contexts
- Retrieval-Nutzung

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
- keine vollständige Facet-Taxonomie über die v1-Facets `contract`, `test` und `retrieval` hinaus
- keine Befüllung von `possible_facets` und keine Consumer-Integration des Facet Reports
- keine automatische Lens-Card-Emission und keine Lens-Card-Consumer-Integration
- keine Relationsimplementierung
- kein CLI
- keine Bundle-Emission
- kein Retrieval-Ranking
- keine Embeddings
- keine LLM-Integration
- keine Review-Urteile
- keine unqualifizierten oder kausalen Change-Impact-Behauptungen
