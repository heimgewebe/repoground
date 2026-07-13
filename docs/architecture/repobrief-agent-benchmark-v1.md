# RepoBrief Agent Benchmark v1

Status: Harness- und Vertragsfläche für `RAB-V1-T001`  
Standardaktivierung: `false`

## Zweck

Der Benchmark misst später den zusätzlichen Nutzen eines RepoBrief-MCP-Zugangs
gegenüber einem gewöhnlichen Coding-Agent-Ablauf mit Dateisuche, Glob, `grep`
und gezieltem Lesen. V1 baut zunächst den geeichten Prüfstand. Es führt selbst
kein Sprachmodell aus und liefert deshalb noch kein Urteil über Agentennutzen.

## Vergleichsbedingungen

### Baseline

Die Baseline darf ausschließlich die im Taskset genannten normalen
read-only-Werkzeuge verwenden:

- Dateisuche und Glob;
- Textsuche beziehungsweise `grep`;
- gezieltes Lesen von Dateien und Bereichen.

### Behandlung

Die Behandlung behält alle Baseline-Werkzeuge und erhält zusätzlich:

- `ask_context`;
- RepoBrief-Ressourcen;
- `grounding_verify`;
- `live_freshness`.

Damit wird der realistische additive Nutzen geprüft. RepoBrief ersetzt nicht
das Lesen des Quellcodes.

## Gefrorenes Taskset

Das versionierte Taskset enthält genau 24 commitgebundene Fälle auf Lenskit,
Grabowski und Weltgewebe:

- acht Navigationsfälle;
- acht Struktur- und Auswirkungsfälle;
- acht Grounding- und Freshness-Fälle.

Mindestens sechs Fälle verlangen eine korrekte Abstinenz, eine Negativaussage,
`stale`, `not_comparable` oder `invalid_evidence`. Ein Agent kann daher nicht
allein dadurch gewinnen, dass er viele Pfade selbstbewusst nennt.

Goldziele, Budgets, Werkzeuglisten, Schwellen und Repository-Commits werden
über den kanonischen Taskset-SHA-256 gebunden. Eine Änderung erzeugt einen
anderen Benchmark und darf nicht still mit früheren Ergebnissen vermischt
werden.

## Paarplanung und Isolierung

Benchmark v1 verlangt exakt zwei vollständige Wiederholungen. Für jeden Fall
werden Baseline und Behandlung in getrennten Sitzungen und getrennten
Arbeitsräumen ausgeführt. Die Reihenfolge wird deterministisch balanciert:
pro Wiederholung startet die Hälfte der Fälle mit der Baseline, die andere
Hälfte mit der Behandlung.

Zwischen den Bedingungen dürfen keine Transkripte, Toolergebnisse, Caches,
Arbeitsräume oder Erinnerungen wiederverwendet werden. Fehlende, doppelte oder
nachträglich veränderte Laufaufträge bleiben als ungültige Evidenz sichtbar.

## Externer Runner

Der Harness startet genau einen expliziten Prozess aus einer Argumentliste.
Er verwendet keine Shell-Zeichenkette. Der Prozess erhält einen JSON-Auftrag
über Standard Input und muss genau ein JSON-Objekt zurückgeben.

Ein gültiger Lauf benötigt mindestens:

- exakte Provider- und Modellkennung;
- identische Sampling-Einstellungen innerhalb eines Paars;
- vom Provider gemeldete Input- und Output-Tokens;
- vollständige Toolaufrufe mit Dauer und Byteumfang;
- Start, Ende, Laufzeit, Exitstatus und Fehlerklasse;
- ein vollständiges Inline-Transcript oder ein hashgebundenes Artefakt;
- Bindung an den unveränderten Laufauftrag.

Geschätzte Tokens, fehlende Transkripte, unbekannte Tools, Budgetüberschreitungen
oder manipulierte Aufträge machen den Lauf ungültig. Sie werden nicht als null,
Erfolg oder stiller Retry behandelt.

## Auswertung

Der deterministische Evaluator misst pro Fall und Aufgabenklasse:

- Ziel- und Fehlertreffer;
- Citation- und Range-Korrektheit;
- richtige Abstinenz und falsches Vertrauen;
- Laufzeit;
- Toolaufrufe;
- Provider-Tokens;
- gelesene und ausgegebene Toolbytes;
- ungültige, fehlgeschlagene und abgebrochene Läufe.

Eine Aufgabenklasse kann nur dann als nützlich gelten, wenn die registrierte
Verbesserung in beiden Wiederholungen dieselbe Richtung zeigt und keine
Qualitäts-, Freshness- oder False-Confidence-Schwelle verletzt wird. Zeit- oder
Tokenersparnis darf eine fachliche Regression nicht überdecken.

## Synthetische Fixtures

Synthetische Quittungen testen ausschließlich Schema, Integrität und
Entscheidungslogik. Ihre Evaluation trägt zwingend
`measurement_scope=synthetic_contract_fixture` und
`decision.status=synthetic_only`.

Sie belegt ausdrücklich nicht:

- realen Agentennutzen;
- Antwortkorrektheit außerhalb der fixierten Erwartungen;
- vollständiges Repositoryverständnis;
- Testhinreichendheit;
- Review- oder Merge-Reife;
- eine Standardbeförderung.

## Aufgabenfolge

- `RAB-V1-T001`: Verträge, gefrorenes Taskset, Runnergrenze und Evaluator;
- `RAB-V1-T002`: echte gepaarte Agentenläufe mit einem gebundenen,
  instrumentierten Runner;
- `RAB-V1-T003`: evidenzgebundene Entscheidung über opt-in, bevorzugte
  Aufgabenklassen oder Verwerfung.

Ein inkrementeller Rebuild oder File-Watcher wird erst priorisiert, wenn reale
Agentenevidenz zeigt, dass RepoBrief nützlich ist und Freshness-Latenz diesen
Nutzen praktisch begrenzt.
