# RepoGround – dauerhafte A/B/C-Agentenmessung v1

**Status:** Die CLI und die Vertragstests sind implementiert. Neue echte Providerläufe stehen noch aus. Keine automatische Beförderung.

## Zweck und Abgrenzung

Wie viel verbessert RepoGround tatsächlich die Arbeit von Grabowski – und hält diese Verbesserung über mehrere RepoGround-Releases, Git-Revisionen und Wiederholungen? Wir messen **die gesamte Agentenaufgabe**, nicht die Geschwindigkeit eines isolierten Graphendpunkts.

Das System verwendet den bereits vorhandenen RepoGround-Agent-Benchmark-Runner für externe JSON-stdin/stdout-Prozesse, kanonische Hashes und atomare Dateien. Der bestehende 24-Fälle-A/B-Vertrag bleibt unverändert; die neue CLI ergänzt die dritte, selektive Werkzeugwahl und wiederholbare Vergleiche. Kein weiterer Dienst, Index, Cache oder Agentenrouter.

Dateien:
- Engine: merger/repoground/core/agent_study.py
- CLI: merger/repoground/cli/agent_study.py
- Frozen Taskset: docs/retrieval/repoground_agent_study_cases.v1.json
- Schemas: merger/repoground/contracts/agent-study-{taskset,receipt,evaluation}.v1.schema.json
- Tests: merger/repoground/tests/test_agent_study.py
- Historisches Register: docs/diagnostics/repoground-agent-study-history.md

## Drei tatsächlich unterscheidbare Bedingungen

| Arm | Werkzeuge | Erfolgsbedingung |
|---|---|---|
| A: git_only | Git-/Dateisuche, Dateilesen | Kein RepoGround-Zugang, auch nicht über versteckte Plugins |
| B: repoground_mandatory | Gleiche direkten Werkzeuge plus RepoGround | Mindestens ein *erfolgreicher* echter RepoGround-Aufruf |
| C: repoground_selective | Exakt dieselben Werkzeuge wie B | Agent entscheidet selbst; auch null RepoGround-Aufrufe sind zulässig |

**C−A ist der Hauptvergleich**, B−A misst die Kosten verpflichtenden Einsatzes, C−B die selektive Einsparung. Kein Agent darf die Ergebnisse anderer Bedingungen sehen. Das an den Agenten gesendete Aufgabenprompt ist für A/B/C bytegleich. Der Unterschied liegt ausschließlich im Toolzugang beziehungsweise in der Verwendungspflicht.

Beim Provider müssen unregistrierte Apps, versteckte RepoGround-Verbindungen, Chat-Historie und geteilter Workspace wirklich ausgeschlossen sein. Eine im JSON-Auftrag behauptete Isolation ist kein Sicherheits- oder Betriebsnachweis; der externe Runner muss sie umsetzen. Pro Lauf werden gesonderte Sitzungs- und Workspace-IDs vergeben. Provider, Modellversion, Sampling, Agenteninstruktion, Hostklasse, Caching, Runner und Budgets sind im gesamten Vergleich konstant zu halten.

## Gefrorener Aufgabenmix und Stichprobe

Die Git-geprüfte Studienfassung vom 1. November 2026 verwendet zwölf Aufgaben auf RepoGround, Grabowski und Commonthing, genau drei je Klasse:

| Klasse | Frage |
|---|---|
| known_target | Findet RepoGround bekannte Ziele mit mehr als unnötigem Tool-Overhead? |
| reverse_relations | Helfen eingehende Beziehungen, Aufrufer und Modulgrenzen? |
| impact_tests | Findet der Agent Änderungen und betroffene Tests zuverlässiger? |
| boundary | Unterlässt er erfundene Definitionen und unbelegte Laufzeitaussagen? |

Mindestens zwei Aufgaben erfordern Abstinenz oder fachliche Begrenzung. Die zwölf Prompts und die unabhängig festgelegten erlaubten beziehungsweise notwendigen Quellpfade sind Bestandteil desselben eingefrorenen Taskset-Digests. Die Orakel bleiben **außerhalb** der Laufaufträge; nur der Evaluator sieht sie.

**Pilot:** 6 Fälle × 3 Arme × 2 Wiederholungen = 36 reale Läufe.
**Vollstudie:** 12 Fälle × 3 Arme × 2 Wiederholungen = 72 reale Läufe.

Ein Durchgang mit nur einer Wiederholung ist eine Diagnose, keine belastbare Aussage. Die Reihenfolge wird in einer vorab festgelegten, balancierten Sechs-Permutationen-Folge zwischen A/B/C gedreht. Wiederholungen desselben Falls sind statistisch **keine zusätzlichen unabhängigen Aufgaben**.

Eine Änderung eines Prompts, einer Quell-SHA, des Goldsets oder der Bewertungslogik ist eine neue Studienversion. Für echte Zeitvergleiche weiterhin die identische **Frozen-Kohorte** an den ursprünglichen Git-Commits messen. Neue Aufgaben und produktive heutige HEADs gehören in eine separate, offen benannte rollierende Kohorte. Die beiden Kohorten dürfen nicht statistisch vermengt werden.

## Was protokolliert wird

**Qualität:** Erwartete und gefundene Pfade; Quellrevision der zitierten Zeilen; Abdeckung des Goldsets; außerhalb des Goldsets liegende Pfade; korrektes Nichtwissen; ungestützte Zuversicht; unabhängig begutachtete Korrektheit und Quellenprüfung.

**Zeit:** Gesamtdauer pro Aufgabe in Millisekunden einschließlich der Toolkosten; Median und P95 pro Arm; task-gepaarte mittlere und mediane Differenzen C−A, B−A und C−B. Die Bootstrap-95-%-Intervalle resampeln **Aufgaben** (3.000 deterministische Ziehungen), nicht einzelne Wiederholungen. Unter vier vollständig bewerteten Aufgaben ist das Intervall nicht verfügbar.

**Token und Toolkosten:** Tatsächlich vom Provider gemeldete Input-, Output- und Cache-Tokens; Anzahl, Status, Latenz und ein-/ausgegebene Bytes aller echten Toolcalls, einschließlich Fehlversuchen. Keine nachträglich geschätzten Tokens. Optional CPU-Zeit und Peak-RSS.

**Fehlgeschlagene Aufgaben verbrauchen ebenfalls Ressourcen:** Gültige Quittungen mit Status failed oder timeout und wirklich provider-gemeldeten Tokens/Tools/Abrechnungen zählen zu allen Arm-Gesamtkosten. Das Feld resource_accounted_trials nennt die tatsächliche Zahl solcher Quittungen. Nur gültige *erfolgreiche* Aufgaben gehen in Antwortqualität, Erfolgsdauer und vollständig bewertete Task-Paarvergleiche ein. Bei ganz fehlenden Quittungen bleiben die nicht beobachtbaren Verbrauchswerte unbekannt, keinesfalls 0.

**Geld:** Nur vom Provider tatsächlich abgerechnete Beträge; Rate-Card-Schätzungen sind keine Istkosten. Unbekannt bleibt null und wird niemals zu 0 Euro umgedeutet. Abrechnungswährungen nicht zusammenrechnen.

**Gültigkeit:** Git-/Prompt-/Modell-/Runner-/Manifest-SHA, Sitzungs-/Workspace-Isolation, Zeitstempel, Trace-Dateigröße und SHA-256 sowie echtes Review. Fehlende, manipulierte und fehlgeschlagene Läufe bleiben sichtbar. Ein unvollständiger dreifacher Block wird **nicht** als Erfolg oder Effizienzgewinn gewertet.

**Antwortprüfung:** Ein maschineller Pfadtreffer allein ist nur Navigation, nicht Korrektheit. Ein externer Reviewer muss die tatsächliche Antwort und jeden behaupteten Quellbeleg anhand des eingefrorenen Commits prüfen. Bewertungen lauten correct, partial, incorrect oder uncertain. Andere tatsächlich korrekte Pfade außerhalb des begrenzten Goldsets sind als Prüfhinweis zu behandeln, nicht automatisch als Halluzination.

Eine Full-Studie kann höchstens den vorsichtigen Status selective_benefit_candidate erreichen, wenn Qualität nicht schlechter wird, zwei Wiederholungen vollständig und geprüft sind und das obere task-geclusterte 95-%-Intervall der C−A-Laufzeitdifferenz unter null liegt. **Das führt zu keiner automatischen Änderung an Grabowski.** Kein synthetischer Test und kein Pilot kann Default-Beförderung begründen.

## Praktische Wiederholung

### 1. Frozen Git-Basis überprüfen

~~~bash
python -m merger.repoground.cli.agent_study validate-taskset \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --roots /abs/pfad/roots.json
~~~

roots.json verweist auf lokale Git-Wurzeln; der Planer liest Goldpfade über git cat-file -e SHA:path, **nicht** über den aktuellen HEAD:

~~~json
{
  "repoground": "/home/USER/repos/repoground",
  "grabowski": "/home/USER/repos/grabowski",
  "commonthing": "/home/USER/repos/commonthing"
}
~~~

Alte Source-SHAs bei Bedarf über den normalen Git-Weg verfügbar machen. Keine automatischen Resets oder Publikationsnebenwirkungen.

### 2. Runner und Toolinventar bindend beschreiben

Die extern gespeicherte profile.json enthält **tatsächlich registrierte** Toolnamen. Die Namen im Beispiel sind anzupassen, keine Verfügbarkeitsbehauptung:

~~~json
{
  "provider": "provider-id",
  "model": "exact-model-id",
  "sampling": {"temperature": 0},
  "agent_version": "pinned-instruction-revision",
  "runner_version": "instrumented-runner-revision",
  "host_class": "fixed-hardware-os-profile",
  "cache_policy": "controlled",
  "tool_contract": "readonly-three-arm-v1",
  "tool_names": {
    "git": ["git_search", "git_show"],
    "file": ["read_file"],
    "repoground": ["repoground_query", "repoground_find_symbol"]
  }
}
~~~

Ein providergebundener extern instrumentierter Runner muss die Policy für A/B/C tatsächlich erzwingen. Codex/Claude brauchen jeweils ihre echte exakte Modellkennung, Runner- und Isolationskonfiguration. Die bisherige A/B-Prüfstrecke dokumentiert bereits die Probleme versteckter Pluginzugänge.

### 3. Gesunde, eingefrorene Snapshot-Manifestdaten binden

Eine extern gespeicherte snapshots.json enthält **für alle drei Repository-IDs** jeweils:

~~~json
{
  "repoground": {
    "source_commit": "EXACT_40_HEX_COMMIT",
    "generator_commit": "EXACT_40_HEX_COMMIT",
    "manifest_path": "/absolute/path/to/healthy.bundle.manifest.json",
    "manifest_sha256": "EXACT_64_HEX_SHA256",
    "health": "pass"
  }
}
~~~

Dazu entsprechende echte Einträge für grabowski und commonthing. Der Planer vergleicht die eingetragenen Git-Commits mit der eingefrorenen Taskset-Revision, die Manifeste mit ihren tatsächlichen Datei-SHA-256 und den behaupteten Healthstatus. Der *tatsächliche* Freshness-/Health-Nachweis muss vor dem Lauf ebenfalls an der zuständigen Veröffentlichungsquelle geprüft werden. Die Bindung ist kein eigener Remote-HEAD-Check.

Wichtig für Wiederholungen über Monate: Alte, durch reguläre Snapshot-Retention entfernte Studienbundles mit dem **vorhandenen RepoGround-Generator** neu aus derselben eingefrorenen Quellrevision in einem isolierten Studienverzeichnis erstellen. Nicht still die aktuelle Source statt der eingefrorenen verwenden; nicht eine zweite Publisher-Architektur bauen. Der Generator-SHA darf sich mit neuem RepoGround ändern und ist absichtlich **nicht** Teil des Vergleichsschlüssels, der Git-Quell-SHA dagegen schon.

### 4. Plan erzeugen

~~~bash
python -m merger.repoground.cli.agent_study plan \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --profile /abs/pfad/profile.json --roots /abs/pfad/roots.json \
  --snapshots /abs/pfad/snapshots.json \
  --run-id study-20261101-01 --suite pilot --repetitions 2 \
  --out /abs/pfad/study-20261101-01
~~~

Schreibt einen unveränderlichen Plan und genau einen Auftrag pro Lauf. Die Ausgabe enthält protocol_key und taskset_sha256. Eine bestehende Zielausgabe wird nicht überschrieben.

### 5. Echte Läufe mit einem externen Agentenadapter durchführen

runner-command.json enthält ein JSON-Array von Argumenten (exaktes argv, **keine Shell-Zeichenkette**). Der externe Runner liest einen JSON-Request von stdin, führt die Agentenaufgabe in der isolierten Umgebung durch, speichert den vollständigen echten Trace außerhalb des Repos und gibt ein JSON-Receipt gemäß Schema zurück. Das Receipt muss `execution_context` (Agentenrevision, Hostklasse, Cachemodus, Toolvertrag) an den Auftrag binden. Jeder erfolgreiche RepoGround-Toolcall muss die tatsächlich beobachtete Quellrevision, Generatorrevision, Manifest-SHA und Freshness als `repoground_evidence` tragen. Ein bloßer Toolname ist kein revisionsgenauer Beleg.

~~~bash
python -m merger.repoground.cli.agent_study run \
  --request /abs/pfad/study-20261101-01/requests/REQUEST.json \
  --runner-command /abs/pfad/runner-command.json \
  --trace-root /abs/pfad/traces \
  --out /abs/pfad/receipts/REQUEST.json
~~~

Alternativ kann der Plan seriell mit `run-batch` ausgeführt werden; vorhandene Receipts werden nur nach erneuter vollständiger Prüfung übersprungen. Bei dem ersten ungültigen Receipt bricht die Ausführung ab, ohne Dateien zu überschreiben:

~~~bash
python -m merger.repoground.cli.agent_study run-batch \
  --plan /abs/pfad/study-20261101-01/plan.json \
  --runner-command /abs/pfad/runner-command.json \
  --trace-root /abs/pfad/traces --receipts /abs/pfad/receipts
~~~

**Wiederanlauf ohne Erfolgsverzerrung:** Vor dem Start eines einzelnen
externen Agentenlaufs wird atomar unter receipts/.attempts/REQUEST.json
eine quell-/requestgebundene Startquittung angelegt. Bei Timeout,
Runner-Absturz, fehlerhaftem JSON oder anderen Ausführungsfehlern bleibt
sie mit Fehlerklasse und ohne erfundene Provider-Tokens erhalten.
Fehlt später das eigentliche Receipt, wird derselbe Versuch **nicht**
automatisch noch einmal gestartet, auch wenn run-batch erneut aufgerufen
wird. Ein abgebrochener/unklarer Versuch erfordert eine dokumentierte
Operatorentscheidung; eine neue Messung nutzt eine **neue Run-ID**.
Erfolgreiche bestehende Receipts werden nur nach vollständiger Prüfung
übersprungen. Die versteckte .attempts-Struktur wird nicht als gültiges
Provider-Receipt oder Messergebnis eingelesen.

Den Aufruf entsprechend der im Plan vorgegebenen Reihenfolge wiederholen. Fehlgeschlagene Läufe mit derselben Identität nicht heimlich durch neue ersetzen. RepoGround mandatory benötigt mindestens einen dokumentierten erfolgreichen RepoGround-Toolcall. Bei git_only darf kein RepoGround-Tool im zugelassenen Werkzeugvertrag vorkommen. Bei selective sind null RepoGround-Aufrufe erlaubt.

Echte Provider-Tokens und die Tooltranskripte stammen vom Adapter; die Studien-CLI kann weder eine Provider-Sitzung herbeizaubern noch aus Antworten nachträglich deren realen Tool- oder Tokenverbrauch rekonstruieren.

### 6. Unabhängige Bewertung und Aggregation

grades.json ist eine JSON-Liste, deren Einträge **echte** Bewertungen gebundener Request-IDs enthalten, beispielsweise:

~~~json
[
  {
    "request_id": "study-20261101-01--known-fleet-entrypoint--r1--git_only",
    "receipt_sha256": "EXACT_64_HEX_CANONICAL_RECEIPT",
    "reviewer": "external-source-auditor",
    "verdict": "correct",
    "citations_checked": true,
    "reviewed_at": "2026-11-01T08:00:00Z",
    "evidence_ref": "audit:hashgebundene-quellenpruefung"
  }
]
~~~

Dies ist eine **Formatvorlage, keine durchgeführte Bewertung**. Der `receipt_sha256` ist SHA-256 über die kanonische JSON-Serialisierung des **exakt bewerteten** Receipts. Wird die Agentenantwort später geändert, ist auch das Urteil nicht mehr gültig. Auswertung der Antwort möglichst vor Kenntnis des Arms, gleiche Rubrik und möglichst gleiche Reviewer über Zeit. Fehlendes Review = unbekannte Qualität.

~~~bash
python -m merger.repoground.cli.agent_study evaluate \
  --taskset docs/retrieval/repoground_agent_study_cases.v1.json \
  --plan /abs/pfad/study-20261101-01/plan.json \
  --receipts /abs/pfad/receipts --trace-root /abs/pfad/traces \
  --grades /abs/pfad/grades.json \
  --measurement-scope real_runner_reported \
  --out /abs/pfad/reports/study-20261101-01.json \
  --markdown /abs/pfad/reports/study-20261101-01.md
~~~

Ist der Lauf nur synthetisch, muss stattdessen synthetic_contract_fixture verwendet werden. Diese Daten dürfen nie als echte Agentenqualität oder Produktivitätsgewinn gelten.

### 7. Langzeitvergleich

~~~bash
python -m merger.repoground.cli.agent_study trend \
  --reports /abs/pfad/reports \
  --out /abs/pfad/auswertung-ueber-zeit.json
~~~

Die Trendfunktion erstellt **separate Gruppen je protocol_key**. Der Schlüssel bindet Goldset und Prompts, feste Git-Commits, Suite, Wiederholungsanzahl, Modell, Sampling, Agenten-/Runnerversion, Hostklasse, Cachemodus und Toolvertrag. Ein anderer Generatorstand ist die beabsichtigte Intervention und darf sich unterscheiden. Auch bei gleichem Schlüssel bleiben zeitliche Drift und Providerstreuung mögliche Störgrößen; keine unbewiesene Kausalbehauptung.

Nur bereinigte, von Reviewer und Original-Trace nachvollziehbare Report-JSONs mit Methodik und Git-Commit-Identitäten unter docs/diagnostics/ versionieren. Rohtraces, personenbezogene Inhalte, Secrets und lokale Checkoutpfade nicht automatisch committen.

## Wiederholungskadenz

1. **Nach jedem wesentlichen RepoGround-Release:** zunächst sechs Pilotfälle, zwei Wiederholungen mit gleicher Frozen-Quelle/Modell/Host.
2. **Nach mehreren aussagekräftigen Piloten:** zwölf Fälle, zwei Wiederholungen; volle unabhängige Quellenprüfung.
3. **Monatlich oder nach einer geänderten Agentenwerkzeugwahl:** kohärente Referenzmessung mit dokumentierten Fehlern, Kosten und negativen Fällen.
4. **Bei Quell-, Modell- oder Hardwarewechsel:** neue Vergleichsgruppe, alte Daten archivieren; keine verdeckte Zusammenführung.
5. **Bei Änderung der Bewertungsformel:** Rubrikversion erhöhen oder sämtliche alten Roh-Receipts mit exakt derselben neuen Auswerterversion erneut auswerten.

Historische 20-Paar-Runs vom 29.10.2026 bleiben im separaten [Messregister](../diagnostics/repoground-agent-study-history.md); sie sind ein wichtiger negativer Ausgangsbefund, aber nicht direkt in die neuen dreiarmigen Effektstichproben einzurechnen.

## Aktuell belegte Grenze

Die 12 Git-belegten Aufgaben, JSON-Schemas, isolierte Vertrags-Tests und CLI sind **Messinfrastruktur**. Ohne echten providerseitigen Adapter samt unabhängiger Qualitätsbewertung wird absichtlich weder eine neue Latenz- noch eine neue Korrektheits- oder Kostenverbesserung behauptet. Der frühere produktive 13/13-Snapshot-Nachweis ist ein technischer Verfügbarkeitsbefund, kein Ersatz für diesen Agentenversuch.