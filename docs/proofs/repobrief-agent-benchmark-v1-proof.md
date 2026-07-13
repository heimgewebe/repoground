# RepoBrief Agent Benchmark v1 — T001 Proof

Status: merged and validated
Bureau task: `RAB-V1-T001`
Pull request: `#1000`
Merge commit: `7b729b52b6bf0302029626878ee444e664a0dc08`
Validated product head before this proof: `9d1e4aaffe2946c741a21807143b6c6d7c18e9fd`
Default promotion: `false`

## Ergebnis

Der providerneutrale Benchmark-Harness ist implementiert. Er kann ein
gefrorenes Taskset prüfen, 96 isolierte Laufaufträge planen, externe
Agent-Runner ohne Shell starten, Laufquittungen gegen Auftrag, Budgets,
Werkzeugvertrag und Transcript prüfen sowie vollständige gepaarte Ergebnisse
deterministisch auswerten.

Der Abschluss belegt ausschließlich die Funktionsfähigkeit dieses Prüfstands.
Er enthält keine realen Agentenläufe und begründet keinen Vorteil von
RepoBrief gegenüber `grep`, Glob, Suche oder gezieltem Lesen.

## Implementierte Verträge

- `agent-benchmark-taskset.v1.schema.json`
- `agent-benchmark-run-request.v1.schema.json`
- `agent-benchmark-run-receipt.v1.schema.json`
- `agent-benchmark-evaluation.v1.schema.json`

Das Taskset enthält genau:

- 24 Fälle;
- acht Navigationsfälle;
- acht Struktur- und Auswirkungsfälle;
- acht Grounding- und Freshness-Fälle;
- zwei verpflichtende Wiederholungen;
- 96 geplante Laufaufträge.

## Integritätsgrenzen

Der Harness verwirft oder invalidiert unter anderem:

- vom gefrorenen Taskset abweichende Prompts, Commits, Budgets oder Tools;
- abweichende Provider-, Modell- oder Sampling-Konfigurationen innerhalb eines
  Paars;
- fehlende oder doppelte Aufträge und Quittungen;
- wiederverwendete Sitzungen oder Arbeitsräume;
- nicht erlaubte Toolaufrufe;
- geschätzte statt Provider-gemeldete Tokens;
- manipulierte, fehlende, leere, übergroße oder aus dem erlaubten Verzeichnis
  ausbrechende Transkripte;
- unbekannte Laufstatus, unstrukturierte Fehlerbelege sowie ungültige,
  zeitzonenlose oder rückwärts laufende Zeitstempel;
- unbeschränktes Einlesen externer Transcript-Artefakte;
- Budgetüberschreitungen;
- eine andere Wiederholungszahl als zwei.

Ein vollständig fehlendes Fallpaar bleibt in der erwarteten 48-Paar-Matrix als
ungültige Evidenz sichtbar. Es verschwindet nicht aus dem Nenner.

## Auswertungsgrenzen

Eine Effizienzverbesserung kann nur gelten, wenn sie in beiden Wiederholungen
dieselbe Richtung zeigt. Eine registrierte Qualitäts-, Freshness- oder
False-Confidence-Regression blockiert das Nutzenurteil auch bei geringerer
Laufzeit oder weniger Tokens.

Synthetische Fixtures tragen zwingend:

- `measurement_scope=synthetic_contract_fixture`;
- `decision.status=synthetic_only`;
- `default_promoted=false`.

Sie prüfen nur den Harness und dürfen nicht als Agentennutzen interpretiert
werden.

## CI-Evidenz

Auf Head `9d1e4aaffe2946c741a21807143b6c6d7c18e9fd` bestanden:

- vollständige Pytest-Suite: Workflow `29243937249`, Job `86796273777`;
- deterministischer Release-Kandidat: Workflow `29243937249`, Job
  `86796273762`;
- Browsertests: Workflow `29243937249`, Job `86796273791`;
- JavaScript-Tests: Workflow `29243937249`, Job `86796273787`;
- Lint und Maintainability: Workflow `29243937260`;
- CodeQL-Richtlinie: Workflow `29243937196`;
- CodeQL-Analysen: Workflow `29243933919`;
- Vertragsprüfung: Workflow `29243937734`;
- Anti-Hallucination-Vertrag: Workflow `29243937202`;
- Parity Gate: Workflow `29243937329`;
- Forensic Preflight: Workflow `29243937252`;
- AI-Context Guard: Workflow `29243937261`.

Der Proof-Commit selbst muss die Dokument- und Repository-Gates erneut
bestehen. Die oben genannten Produkt-, Test- und Sicherheitsgates sind an den
unveränderten Produktcode des geprüften Heads gebunden.

## Nicht belegt

Dieser Abschluss belegt nicht:

- realen Agentennutzen;
- geringere Kosten oder schnellere Bearbeitung bei echten Modellen;
- bessere Antwortkorrektheit außerhalb des fixierten Tasksets;
- vollständiges Repositoryverständnis;
- Testhinreichendheit;
- Review- oder Merge-Reife künftiger Änderungen;
- eine Standardbeförderung von RepoBrief.

## Nächste Aufgabe

`RAB-V1-T002` darf erst beginnen, wenn ein realer instrumentierter Agent-Runner
gebunden ist, der exakte Modellkennung, Provider-Tokens, Toolaufrufe und ein
vollständiges oder kryptografisch gebundenes Transcript liefert. Fehlt diese
Fläche, bleibt T002 blockiert. Werte werden nicht simuliert.
