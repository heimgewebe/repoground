# RepoGround – Agentenwerkzeugwahl nach tatsächlichem Nutzwert

**Aktueller Entscheidungsstand (01.11.2026):** Der ursprüngliche R1–R4-Abschnitt ist eine datierte Planung vom 30.10.; inzwischen sind echte R3- und R5-Läufe ausgewertet. Der maßgebliche, begrenzte Fortsetzungsauftrag steht unter [R5 – zwei Nutzwertversuche und Stopentscheidung](#r5--zwei-nutzwertversuche-und-stopentscheidung-01112026). Er ergänzt die historische Planung, ohne bereits durchgeführte Schritte rückwirkend umzubenennen.

**Stand:** 30. Oktober 2026 · **Priorität:** P1, gezielter Anschluss an die produktive Graph-Integration · **Status:** R1-Quellintegration in Grabowski gemergt; R1-Clientabnahme und R2–R4 noch offen.

**Ziel:** Coding-Agenten sollen RepoGround **dann** verwenden, wenn seine revisionsgebundenen Beziehungen gegenüber direkter Git-/Dateisuche zusätzliche, überprüfbare Information liefern. Bei einfachen Fragen bleibt der direkte Weg Standard. Wir optimieren die **gesamte Aufgabe**, nicht die Anzahl der Graphabfragen.

**Einordnung:** Ergänzt [Vision und Agentenadoption](repoground-vision-and-agent-adoption.md), [Ausbau-Thread 3 – Consumers](repoground-expansion-thread-3-consumers.md) und die [Master-Roadmap](repoground-master-roadmap.md). Der bereits beschlossene Struktur-/Föderations-/Zeitgeschichtsausbau wird **nicht** rückwirkend durch eine neue Benchmark-Start- oder Merge-Sperre blockiert. Dieser Plan betrifft nur Auswahl, Verbrauch und Messung vorhandener Werkzeuge; er erstellt keine zusätzliche Agentenplattform.

## 1. Diagnose: Was ist schon belegt?

- **Technische Leseleistung:** Nach PR [#1363](https://github.com/heimgewebe/repoground/pull/1363) benötigte die direkte vollständige Graphabfrage auf demselben früheren 119.169-Kanten-Bundle durchschnittlich **2,939 statt 12,604 Sekunden** (4,29× schneller, gleicher Antwort-Hash). Siehe [technischer und ursprünglicher Agentennachweis](../proofs/repoground-agent-utility-20pairs-20261029.md).
- **Ende-zu-Ende-Agenten vor dieser Optimierung:** 20 gepaarte reale Codex-Aufgaben am identischen Quellcommit: direkte Git-Navigation durchschnittlich **25,107 s**, mit RepoGround-MCP **39,852 s**; **16/20** RepoGround-Aufgaben langsamer, **+59 %** Zeit und **+32 %** gemeldete Input-Tokens. Beide Bedingungen nannten bei allen 20 Aufgaben das erwartete Ziel, was allein noch keine vollständig geprüfte Antwortqualität beweist.
- **Nach produktiver Aktivierung:** Vier weitere ausgewählte, prompt-/modell-/quellgleiche Agentenpaare: Git insgesamt **99,649 s**, mit optimiertem RepoGround **122,402 s** (**+22,8 %**, in **3/4** Fällen langsamer). Das neue RepoGround-Treatment war gegenüber dem ursprünglichen Treatment derselben vier Fälle schneller (122,402 statt 209,672 s); Modellstreuung, Cache und andere Toolaufrufzahlen verhindern eine eindeutige Kausalzuordnung. Die Nachmessung ist als [Kommentar zu #1363](https://github.com/heimgewebe/repoground/pull/1363#issuecomment-6500234053) und mit lokalen hashgebundenen Laufquittungen belegt.
- **Tatsächlicher Produktionszustand vom 29.10.2026:** Generator/Source `88584eee78a68c717bd9dc61bedbc865eed27fea`, gesundes Bundle mit **119.202 Beziehungen**, echte CLI-/MCP-Abfragen von **4,704 / 4,581 s** inklusive Prozessstart; authentifizierter Codex-Agent hat RepoGround wirklich aufgerufen. Der Zustand ist **datiert**, kein Ersatz für frischen Live-Readback.

**Schluss:** Graphlesen funktioniert und ist schneller geworden. Ein *allgemeiner* Zeit-, Qualitäts- oder Kostenvorteil für Coding-Agenten ist **nicht** belegt. Die untersuchten 20 Aufgaben waren zudem aus vorhandenen S1-Kanten ausgewählt und bestanden überwiegend aus einfachen bekannten Beziehungen – also gerade nicht aus den schwierigsten Anwendungsfällen.

## 2. Begriffe und Routingregel

- **Git-/Dateisuche:** direkt nach einer bekannten Datei, Zeile oder Zeichenfolge im tatsächlichen Quellcode suchen (`git show`, `rg`, gezieltes Lesen). Wenig Zusatzaufwand.
- **RepoGround:** aus einem veröffentlichten, revisionsgebundenen *Graphen* gerichtete Beziehungen und ihre Quellen lesen. `incoming` bezeichnet eingehende Verweise auf ein Ziel; `outgoing` Verweise vom Ziel weg. Ein statischer Verweis ist kein Beweis für Laufzeitverhalten oder vollständige Testabdeckung.
- **MCP:** Schnittstelle, über die ein Agent RepoGround-Werkzeuge wirklich aufrufen kann. „Verbunden“ ist noch keine erfolgreiche Nutzung.
- **Fallback:** bei ungeeignetem oder nicht verfügbarem Graphen regulär mit Git/Dateilesen fortfahren, nicht künstlich stoppen.

Die Auswahl geschieht **beim aufrufenden Agenten**, nicht durch einen neuen autonomen RepoGround-Entscheider. RepoGround bleibt deterministisch und read-only. Der interne `retrieval/task_profile_routing.py`-Code betrifft Retrieval **innerhalb** von RepoGround und ist nicht automatisch bereits ein Git-vs.-MCP-Router.

| Aufgabensignal | Anfangsroute | Warum / erforderlicher Beleg |
| --- | --- | --- |
| Datei, Funktion, Zeile oder Import **bekannt**; einfache Inhaltsfrage | **Git zuerst** | Direktes Lesen reicht meist; 20er- und 4er-Messungen zeigen erhebliche MCP-Mehrkosten |
| Einzelner eindeutig lokalisierter Aufruf oder Markdown-Link | **Git zuerst** | Quellzeile und Definition gezielt überprüfen |
| **Unbekannte eingehende** Aufrufer, Verbraucher oder Referenzen | **RepoGround-Kandidat** | Gerichtete Rückwärtsbeziehungen könnten viel manuelle Suche ersetzen; Treffer an Git prüfen |
| Mehrere zusammenhängende Abhängigkeiten, Teststellen, Änderungsauswirkungen | **RepoGround-Kandidat** | Strukturierte Evidenz kann bekannte Verknüpfungen liefern; Unaufgelöstes und Lücken benennen |
| Repositoryübergreifende Verträge oder Historie zwischen Revisionen | **RepoGround-Kandidat**, *nur wenn passende Föderations-/History-Artefakte existieren* | Commit-/Bundle-Bindung, Abdeckung und Grenzen ausdrücklich prüfen |
| Bundle fehlt, ist veraltet, widersprüchlich oder ohne passende Daten | **Git-Fallback** | Nie aus fehlender Kante auf „keine Abhängigkeit“ schließen; kein stiller Snapshot-Build |
| Tatsächliches Review-, Test-, Merge- oder Produktionsurteil | **Autoritative Primärquellen** | Git, CI, Tests und Laufzeit belegen den Zustand; RepoGround darf nur Hinweise liefern |

**Einfacher Ablauf pro Aufgabe:**

1. Frage klassifizieren: Ist Ziel und Quelle schon bekannt? **Dann direkt lesen.** Kein pflichtmäßiger RepoGround-Preflight.
2. Bei echtem Relations-/Impact-Bedarf zuerst tatsächlichen `repo`-, `commit`- und Bundlezustand feststellen; nur einen eindeutigen, relevanten, gesunden, ausreichend frischen Graphen verwenden.
3. **Klein anfangen:** zunächst eine gezielte RepoGround-Abfrage auf die nötige Symbol-/Beziehungsfamilie und mit kleinem Ergebnisbudget. Eine zweite Abfrage nur bei einer konkret offenen Teilfrage. Weitere Aufrufe begründen, statt dieselbe Umgebung wiederholt abzufragen. **Das ist eine Pilotheuristik, keine harte globale Limitsperre.**
4. Gefundene relevante Stellen an Git/`canonical_md` und der gebundenen Revision überprüfen; nicht unterstützte Aussagen und unbekannte Abdeckung offenlassen.
5. Bei fehlendem Mehrwert, Latenz-/Toolschleife oder veralteter Quelle auf den direkten Weg zurückfallen. Die Aufgabe geht weiter.

## 3. Umsetzung in vier kleinen, getrennten Schritten

### R1 – Entscheidungstabelle in einen realen Consumer übernehmen (P1, zuerst)

**Umsetzung:** In der bestehenden Grabowski-Aufgaben-/Agentenführung die obige Git-vs.-RepoGround-Auswahl als **kleine optionale Anweisung** integrieren; vorher die tatsächlich verwendete Konfigurations-/Prompt-Quelle prüfen. Keine zweite Routerbibliothek, kein neuer Dienst, keine verpflichtende MCP-Discovery für jede kleine Frage. Bestehende RepoGround-Frontdoor und Taskprofile wiederverwenden. Änderungen an `heimgewebe/grabowski` benötigen eine **eigene**, dort autorisierte Writer-Lane und einen eigenen PR.

**Fertig, wenn:** Ein bekannter Datei-/Zeilenfall ohne RepoGround-Toolaufruf gelöst wird; bei einer unbekannten Rückwärtsbeziehung ein echter passender MCP-Aufruf mit korrekter Revision erfolgt; fehlendes oder altes Bundle einen funktionierenden Git-Fallback auslöst. Nachweis: tatsächliche Tool-Transcripts, keine Agenten-Selbstauskunft.

**Implementierungsabgleich (30.10.2026):** [Grabowski PR #1678](https://github.com/heimgewebe/grabowski/pull/1678) wurde auf `main` gemergt (`4b322857c628af439b4d780da97a44f6d8fe9e57`). Die optionale Git-first-/RepoGround-Kandidat-Regel `selective-repoground-retrieval` liegt im tatsächlich verwendeten `src/grabowski_mcp.py:AGENT_INSTRUCTION_RULES`-Quellvertrag. Das belegt die **Quellintegration**, nicht automatisch die produktive Clientinstruktionsübernahme oder die drei oben beschriebenen echten Tool-/Fallback-Proben. R1 bleibt bis zum revisionsgebundenen Consumer-Ende-zu-Ende-Nachweis **teilweise abgenommen**; R2–R4 sind dadurch nicht erledigt.

### R2 – Unnötige Agenten-Toolschleifen beseitigen (P1, erst nach R1-Trace)

**Diagnose vor Patch:** In echten Aufgaben getrennt messen: (a) wiederholte `discover`-/`preflight`-Aufrufe, (b) übergroße Antwortpakete, (c) erneute Abfragen desselben unveränderten Ziels und (d) Validierungs-/Prozessstartzeit. Nicht jede Mehrzeit ist ein Graph-Performanceproblem.

**Umsetzung:** Nur den **nachgewiesenen** größten Verursacher klein beheben: etwa bessere konkrete Werkzeugbeschreibung, knapperes Ergebnisbudget oder gezieltere Toolwahl im Consumer. Existierende `get_structure_neighborhood`, `find_symbol`, `get_callers`, `live_freshness` und Aufgabenprofile verwenden, sofern die reale Toolinventur sie bestätigt; Namen nicht aus diesem Plan als heute überall verfügbar unterstellen. Kein neuer Cache, keine parallele Indexdatenbank, kein neuer Scheduler.

**Fertig, wenn:** Dasselbe reale Quellziel bei unveränderter Quellen-/Antwortqualität mit weniger überflüssigen MCP-Aufrufen oder belegbar kürzerer Gesamtzeit erreichbar ist. Auch „kein Patch nötig“ ist ein zulässiger Abschluss bei fehlendem Ursachenbeleg.

### R3 – Passenden Aufgabenmix statt Graph-Selbsttest messen (P1, nach R1)

**Messinfrastruktur ab 01.11.2026:** Für Wiederholungen über Releases liegt jetzt ein
[versioniertes A/B/C-Instrument mit fixer Git-Quelle, zwölf vorregistrierten
Aufgaben, sechs Pilotfällen, zwei Wiederholungen, exakten Trace-/Token-/Manifest-
Nachweisen, externem Quellreview und Protokoll-getrenntem Zeitvergleich]
(../usage/repoground-agent-study-v1.md) vor.
Der tatsächliche Vergleich ist **A = Git-only**, **B = verpflichtender
RepoGround-Einsatz**, **C = selektive Werkzeugwahl**. Bestehende
[24-Fälle-A/B-Verträge](../architecture/repobrief-agent-benchmark-v1.md)
werden weiter genutzt und nicht umgedeutet. Das
[historische Messregister](../diagnostics/repoground-agent-study-history.md)
trennt echte alte 20-Paar-Läufe von künftigen A/B/C-Ergebnissen.
Der Teststand belegt die Messwerkzeuge und einen quellengebundenen
36-Lauf-Plan, **keinen** neuen realen Agentennutzen. R3 bleibt bis zu
authentischen Läufen und unabhängiger Qualitätsbewertung offen.


**Pilot:** Vor Messbeginn **12 reale Aufgaben** aus wenigstens zwei Heimgewebe-Repositories fixieren: 3 einfache bekannte Ziele (Negativkontrolle), 3 unbekannte eingehende Bezüge, 3 Change-Impact-/Testauswahlfragen und 3 repoübergreifende oder revisionshistorische Fragen. Wo Artefakte für Letzteres fehlen, dies offen als `unavailable`/Abstinenzfall registrieren und nicht künstlich Erfolg erzwingen. Mindestens zwei negative/unsichere Fälle aufnehmen. Goldziele und Quellbelege vorher unabhängig vom Treatment festlegen.

**Vergleich:** Gleiche Aufgabe, Git-Revision, Modell, Prompt, erlaubte Werkzeuge und Laufbudget; isolierte Codex-/Consumer-Läufe mit **(A) normaler Git-Navigation** und **(B) optionalem selektivem Routing**. Reihenfolge abwechseln. Zuerst sechs Paare als günstige Diagnose, die restlichen sechs nur bei brauchbaren Ergebnissen. Für aussichtsreiche Aufgabenklassen eine zweite balancierte Wiederholung, bevor von stabiler Verbesserung gesprochen wird. Das bestehende [Agent-Benchmark-Modell](../architecture/repobrief-agent-benchmark-v1.md) für Traces, echte Provider-Tokens und Bewertung wiederverwenden; vorhandene 20 alten Paare nur als **separaten historischen Vergleich**, nicht in dieselbe Stichprobe mischen.

**Pro Aufgabe protokollieren:** Task-/Prompt-/Commit-/Manifest-SHA, tatsächliche Toolcalls mit Resultat/Fehlern, Quellbeleg- und Zielkorrektheit (durch überprüfenden Menschen oder deterministische Goldbewertung), richtige Abstinenz, End-to-End-Zeit, Input-/Output-/Cache-Tokens, gegebenenfalls **tatsächlich** abgerechnete Kosten, Fehlversuche, Nacharbeit und korrekte Git-Fallbacks. Rohbelege hashbinden; Geheimnisse und personenbezogene Daten aus Veröffentlichung ausschließen.

**Entscheidung pro Aufgabenklasse, nicht als globaler Mittelwert:**

- **Bevorzugen:** In zwei Wiederholungen korrekte, revisionsbelegte Antworten mindestens so zuverlässig wie Git und entweder (a) nachweisbar bessere Ziel-/Folgenabdeckung **ohne** unvertretbare Zeitmehrkosten oder (b) bei gleicher Qualität grob **≥ 15 % kürzere** mediane End-to-End-Zeit. Token-/Kostenentwicklung gesondert ausweisen. Das ist ein **Pilot-Entscheidungskriterium**, kein Sicherheits- oder CI-Merge-Gate.
- **Git behalten:** Keine stabile Qualitätsverbesserung, bei gleicher Qualität weiterhin spürbar langsamer oder unnötige Toolkosten. Keine breite RepoGround-Default-Aktivierung.
- **Nicht entscheidbar:** Kleine oder schwankende Stichprobe, fehlende Goldbelege, uneinheitliche Toolverwendung oder unvollständige Telemetrie. Ergebnisscope offen angeben, nicht schönrechnen.

**Ablage bei Umsetzung:** Ein datierter neuer Proof unter `docs/proofs/` mit Aufgabenmatrix, Hash-/Tool-Belegen, Klassenentscheidung und expliziter Beleggrenze; keine ausgedachte Erfolgsquote und keine bloße „MCP connected“-Behauptung.

### R4 – Bewährte Route gezielt ausrollen oder abbrechen (P2, optional)

**Bei belegtem Nutzen:** Nach Grabowski ein einzelner weiterer echter Consumer (Codex oder Claude) über einen **separaten** autorisierten Konfigurations-PR, mit echter Source-/MCP-/Fallback-Probe. Standard bleibt optional; keine systemweite Toolpflicht. Prüfen, dass die bisherige stabile Ausgabe und die publizierte Runtime unverändert nutzbar bleiben.

**Ohne belegten Nutzen:** R2/R4 nicht erzwingen. Git-first als praktikablen Default dokumentieren; Graph als gezieltes Werkzeug verfügbar lassen und den nächsten Ausbau nur aus einem konkret fehlgeschlagenen realen Anwendungsfall ableiten.

## 4. Abhängigkeiten, Risiken und Ende

- **Owner:** Grabowski allein für Code-/Git-/Deployment-Mutationen, Großer Adler für unabhängige lesende Abnahme. RepoGround selbst erhält keinerlei Merge-/Patch-/Deploy-Befugnis.
- **Keine Doppelarbeit:** Bestehende Consumer- und Graph-/History-/Federation-Slices nutzen; vor Umsetzung PRs, aktive Leases und vorhandene Routen erneut prüfen. Die hier genannten R1–R4 sind **Arbeitspaketlabels dieses Plans**, keine vorgetäuschten Bureau-Task-IDs oder abgeschlossenen Implementierungen.
- **Wichtigste Gefahr:** Ein Graph kann nützliche *bekannte* Abhängigkeiten zeigen, ohne vollständig zu sein. Falsch positive und falsch negative Beziehungen müssen in der Bewertung sichtbar bleiben; statische Beziehungen niemals mit ausgeführten Tests oder realen Wirkungen gleichsetzen.
- **Ausfallpfad:** Bei unsicherem Manifest oder Toolfehler Git verwenden. Keine neuen künstlichen Sperren vor normalen PRs oder anderen unabhängigen Featurearbeiten.
- **Änderungsgrenze dieses Plan-PRs:** Nur diese Roadmap und ihr Eintrag im vorhandenen Planungsindex. **Keine Runtime-, MCP-, Schema-, Prompt- oder Hoständerung.** Eine spätere Ausführung braucht je Slice echte Code-/CI-/Runtimebelege.

**Abschlussdefinition:** Das Git-first/RepoGround-kandidat-Routing ist bei einem realen Agenten nachgewiesen, die kleine aufgabenklassenspezifische Gegenprobe bewertet fachliche Richtigkeit und Gesamtaufwand, und die Entscheidung lautet transparent entweder **selektiv fördern**, **Git beibehalten** oder **mit Begründung unentschieden**. Keine Architekturvermehrung ist dafür notwendig.


## R3-Messinstrumentarium – Implementierungsbeleg vom 01.11.2026

Die für R3 geforderte reproduzierbare Messstrecke liegt als eigenständige,
kleine CLI-Schicht **auf dem vorhandenen JSON-stdio-Agentenbenchmark**, nicht
als neuer Agentenrouter oder Publisher vor:

- [Vertrags- und Messhandbuch](../usage/repoground-agent-study-v1.md),
  [eingefrorener 12-Fälle-Goldsatz](../retrieval/repoground_agent_study_cases.v1.json)
  und [langfristiges Messregister](../diagnostics/repoground-agent-study-history.md).
- Drei Arme: **A Git-only**, **B RepoGround verpflichtend**, **C RepoGround
  selektiv** (auch null MCP-Aufrufe); pro Klasse drei Aufgaben, zwei
  Negativfälle, sechs Pilotaufgaben. Pilot 36, Vollstudie 72 isolierte Läufe
  bei je zwei Wiederholungen.
- Maschinenlesbare, versionsgebundene Quittungen mit echtem Transcript,
  Git-/Generator-/Manifest-Fingerprints, Provider-Tokens, Tool-Bytes und
  Latenzen. Der Vergleichsschlüssel bindet konstante Messbedingungen; die
  Generatorrevision bleibt als bewusst veränderlicher Eingriff erhalten.
- Reale Git-Quellpfade überprüft, **178 Regressions-/Bestandstests bestanden**
  und Ruff erfolgreich (Prüflauf am 01.11.2026). Ein tatsächlicher
  CLI-Plan-Durchlauf mit gesunden veröffentlichten Manifests für alle drei
  Repositories erzeugte 36 Pilot-Requests. Die Leerauswertung weist
  **36 fehlende Receipts und 0 gültige Läufe** korrekt als
  **not_established** aus; keine künstlichen Agentenerfolge.
- Die früheren 20 Git-vs.-MCP-Livepaare bleiben historische Evidenz
  **anderer Methodik**. Ihr negatives Zeit-/Token-Ergebnis darf nicht
  mit der neuen selektiven Dreiarmstudie statistisch vermischt werden.

**Offen, und ausdrücklich nicht durch Werkzeugtests erledigt:** einen
instrumentierten echten Provider-/Agenten-Runner anbinden, die eingefrorenen
A/B/C-Aufgaben unter tatsächlich isolierten Sitzungen durchführen, unabhängige
Antwort-/Quellenreviews erstellen und die daraus gewonnenen
vergleichbaren Laufberichte versionieren. Bis dahin gibt es keine neue
Aussage über Agentennutzen, Kostenersparnis oder eine automatische
Standardumstellung.

## R5 – zwei Nutzwertversuche und Stopentscheidung (01.11.2026)

**Entscheidung:** RepoGround bleibt als revisionsgebundene, deterministische Quellen-/Nachweisschicht erhalten. Die Behauptung „macht Coding-Agenten allgemein schneller oder richtiger“ ist **nicht** belegt. Vor weiterem Ausbau **höchstens zwei kleine, fachlich verschiedene Interventionen** mit echten Agenten und danach **höchstens eine** gezielte Bestätigungsstudie. Keine neue Architektur, kein Standardzwang, kein dritter Optimierungszyklus ohne neuen realen Nutzungsfall und einen neuen gesonderten Auftrag.

### 0. Belegter Ausgangspunkt und zu prüfende Hypothesen

Originalquellen: [R5-Quellreview und Reproduktion](../proofs/repoground-agent-study-codex-v2-r5-20261101.md), [native R5-Evaluation](../diagnostics/agent-study-reports/codex-v2-r5-20261101.json), [R3-Originaldaten und Protokolltrennung](../diagnostics/repoground-agent-study-history.md).

| Reale R5-Pilotkohorte, 6 Aufgaben × 2 Wiederholungen | A Git-only | B RepoGround-Pflicht | C optional |
| --- | ---: | ---: | ---: |
| Streng qualitätskorrekte Antworten | 9/12 | 8/12 | 9/12 |
| Mittlere Gesamtzeit | 24,633 s | 34,353 s | 27,252 s |
| Gemeldete Input-Tokens, gesamt | 1.582.935 | 2.522.860 | 1.947.112 |
| Erfolgreiche Git-Werkzeugaufrufe | 47 | 47 | 51 |
| RepoGround-MCP-Aufrufe | 0 | 39 | **0** |

B benötigte gegenüber A gemittelt **9,720 s mehr** pro Aufgabe (task-geclustertes 95-%-Intervall: **+6,148 bis +12,809 s**), rund **59 % mehr Input-Tokens** und ebenfalls 47 erfolgreiche Git-Aufrufe. In B entfielen **12** RepoGround-Aufrufe auf `bundle_discover` und **13** auf `query_existing_index`. Die Zahl zeigt zusätzlichen Aufwand, **nicht** schon, dass jede einzelne Abfrage unnütz war; dafür sind die originalen Traces je Fall zu prüfen. C hat RepoGround **nie verwendet**. R5 hatte 36 tatsächliche Providerreceipts und 36 blinde Quellbewertungen, aber nur einen GPT-6-Reviewer im selben Operator-Thread, kein unabhängiges menschliches Panel. Beurteilung: `not_established`.

**H1 – Substitution statt Zusatzsuche:** Bei unbekannten eingehenden Beziehungen und konkreten Test-/Impact-Fragen kann die Kombination vorhandener RepoGround-Reads die Zahl der für die Antwort tatsächlich benötigten Git-/Datei-Suchschritte reduzieren, ohne inhaltliche oder zeitliche Nachteile.

**H2 – Änderungsevidenz statt allgemeiner Suche:** Bei **echten** Commitpaaren `base..target` kann das bereits vorhandene `change_evidence_pack` einen kompakten, revisionsgebundenen Beleg für Änderungen, betroffene Tests und Vertragsfolgen liefern, den Git allein nur mit mehr Agentenarbeit zusammensetzt.

**Wichtige technische Abgrenzung:** `change_evidence_pack` ist in der derzeitigen realen R5-Codex-Whitelist von zwölf RepoGround-Tools **nicht** enthalten. Es verlangt `base_revision`, `target_revision`, einen MCP-Server mit `--repo-root` und ein dazu passendes Git-Checkout; für strukturelle Evidenz braucht es eine saubere, zum Zielcommit passende Quelle. Es ist **kein** sinnvoller Ersatz für eine normale Suche nach einer bekannten Datei oder für einen Symbolfund ohne Commitpaar. Ebenso beweist ein statischer Graph keine Laufzeit- oder Testwirkung.

### 1. Runde A – existierende Symbol-/Beziehungswerkzeuge effektiv verwenden

**Voraussetzung, ohne neue Providerläufe:** Die bereits privaten R5-Traces nach Aufgabentyp auswerten: die 12 Discovery- und 13 Indexaufrufe, tatsächliche Reihenfolge und Bytes, weiterführende Git-Suchen, gültige/falsche Quellen, Toolstatus und Laufzeiten. Konkrete Dopplung oder fehlende Werkzeugwahl **erst nach Sichtung** als Ursache bezeichnen. Bei nachweislich notwendiger Git-Gegenprüfung zählt diese nicht als vermeidbare Arbeit.

**Kleinste Änderung:** Genau **eine** nachgewiesene Ursache beseitigen: etwa bei bereits eindeutig revisionsgebundenen Quellen einen überflüssigen Discovery-Schritt vermeiden, das richtige vorhandene `find_symbol`/`get_structure_neighborhood`/`get_callers`-Werkzeug sichtbar machen oder die Ergebnisgröße begrenzen. Die Auswahl erfolgt beim bestehenden Consumer/Runner, nicht durch einen zweiten Agentenrouter. Für bekannte Ziele und Negativkontrollen weiterhin Git-first. Kein globales „RepoGround mindestens einmal“ außer im ausdrücklich diagnostischen B-Arm; C bleibt freiwillig. Reversibel, mit gezielten Positiv-/Negativtests und echten MCP-Readbacks, insbesondere für `stale`, `unavailable`, S0/S1 und unerfundene Quellen.

**Messung A1:** Mit derselben gefrorenen 6-Fälle-Pilotbasis, **6 × 3 × 2 = 36 echten Sitzungen** (Git A, Pflicht B, selektiv C). B und C bekommen dieselbe tatsächlich installierte Toolauswahl; die fachliche Frage bleibt A/B/C-bytegleich, der experimentelle Werkzeugvertrag ist explizit unterschiedlich. Neue Runner-/Prompt-/Tool-/Generator-Fingerprints, neue Run-ID und neuer `protocol_key`; **R5 darf kein stillschweigend mitgemischter Kontrollarm sein.** Das Original-R5-Taskset und die privaten Receipts bleiben unverändert. Wenn bereits ein solcher Lauf nachweislich vorliegt, ihn zuerst verifizieren, nicht wiederholen.

**Pilot-Signal für einen Fortsetzungskandidaten:** C nutzt RepoGround in **mindestens zwei unterschiedlichen, vorregistriert geeigneten Aufgaben**, und bei diesen Aufgaben sinken die benötigten Git-/Datei-Suchaufrufe um **mindestens 20 %** gegenüber A **bei gleicher oder besserer quellengeprüfter Qualität**. Die gesamte End-to-End-Dauer darf im Mittel nicht mehr als **10 %** über A liegen; Input-Tokens dürfen nicht verdeckt steigen. Ein einzelner gelungener Toolaufruf, eine direkte Graph-Mikrobenchmark-Verbesserung oder bloß reduzierte MCP-Aufrufzahl genügt nicht. Fehlt dieses Signal, die Relationsabkürzung **nicht** als Default oder „fertige Agentenoptimierung“ ausgeben.

### 2. Runde B – `change_evidence_pack` ausschließlich bei echten Änderungen

**Neue, vorher fixierte Aufgabenklasse:** Aus **tatsächlich vorhandenen Git-Commitpaaren** die sechs Pilotfragen für `base..target` und sechs weitere, zunächst zurückgehaltene Bestätigungsfälle bilden: mindestens zwei Repositories; echte mehrteilige Änderungsauswirkungen, betroffene Tests, Vertragsänderungen sowie einfache und bewusst negative/abdeckungsarme Fälle. Vor **jedem** Agentenlauf Fragen, Orakel, zulässige Quellen, beide SHA40, Git-Diff-SHA256, Modell, Toolinventar, Reihenfolge und Messschema archivieren. Kein nachträgliches Umetikettieren von Fällen aufgrund der Antworten.

**Vorheriger technischer Smoke:** Mit sauberem, korrekt revisionsgebundenem Checkout und `--repo-root` genau einen echten `change_evidence_pack`-MCP-Roundtrip samt begrenztem Antwortbudget (Startwert höchstens **1.200 Kontexttokens**) und identischer Git-Gegenprobe. Für fehlende Bundles, Dirty-/historische Checkoutstände und nicht abgedeckte Änderungen den dokumentierten S0-/Git-Fallback erhalten. Nur soweit nötig die vorhandene R5-Agenten-Whitelist/Promptoberfläche **minimal** für B/C erweitern; der bisherige Runner-Code ist kein Beweis tatsächlicher Werkzeugfreigabe beim Client. A erhält dasselbe Commitpaar und denselben Fragetext, aber keinen RepoGround-Zugang.

**Messung B1:** **6 × 3 × 2 = 36 echte Sitzungen** nach dem bestehenden JSONL-/Receipt-/Blindreview-Protokoll. Erzwungenes B dient nur zur Overhead-Diagnose; die Nutzwertfrage ist selektives C gegen A. B1 ist eine **andere Taskset-/Toolvertrag-Kohorte** als A1 und R5 und darf nicht gepoolt werden. Stop bei unzureichender Quellbindung, erkennbaren sicherheits-/integritätsrelevanten Regressionen oder fehlender tatsächlicher Nutzung.

**Pilot-Signal:** Mindestens zwei verschiedene echte Impact-/Testfälle profitieren nach unabhängiger Source-Begutachtung durch weniger notwendige Git-Sucharbeit (Richtwert **≥ 20 %**) bei mindestens gleicher korrekter Folgen-/Testabdeckung, ohne neue ungestützte Sicherheit. Die mittlere Aufgabenzeit soll nicht über A liegen oder – falls die Genauigkeit wirklich steigt – höchstens **10 %** teurer sein. Antwortpaketbytes und echte Provider-Tokens zusätzlich protokollieren; Geldkosten ohne Abrechnung bleiben unbekannt.

### 3. Eine Bestätigung statt eines endlosen Optimierungsprojekts

**Hartes Ausführungslimit:** Höchstens **36 + 36 + 72 = 144** neue Provider-Sitzungen für beide Runden zusammen. Die letzte Gruppe von **12 × 3 × 2 = 72** ist **nur dann** zulässig, wenn mindestens ein Pilot das vorregistrierte Signal erfüllt. Bei zwei Kandidaten zuerst die fachlich stärkere Substitution wählen; die andere nicht stillschweigend ebenfalls voll testen. Pro Versuch immer neue create-only-Receipts und eindeutige Run-ID, niemals ungültige oder bereits gestartete Versuche automatisch wiederholen. Vor dem Lauf tatsächlich verfügbare Provider-/Budgetgrenzen prüfen; keine fixe Kostenersparnis behaupten.

**Einheitliches Protokoll:** Gleiche echten Agentenmodelle, Sampling, Hostklasse, Cachepolitik, Toolgrenzen, Quellen und Quoten **innerhalb** jedes Vergleichs; balancierte Armreihenfolge, isolierte Sessions/Workspaces, vollständige JSONL-Traces und genau dieselbe Aufgabe für A/B/C. Originalberichte samt Source-/Manifest-/Runner-/Trace-SHA256 versionieren, Rohtraces und private Reviewer-Mappings nicht. Der existierende Evaluator berechnet task-geclusterte Intervalle; zwei Wiederholungen **zählen nicht als zwölf unabhängige Aufgaben**. Pilotfälle von nicht vorab gezeigten Bestätigungsfällen getrennt ausweisen.

**Qualitätsprüfung:** Vor Entblindung jede tatsächliche Erklärung, Quellstelle und wichtige Gegenbehauptung am fixierten Commit kontrollieren. Ein vom Agenten getrenntes Modell reicht für eine erste Bewertung, ist aber nicht dasselbe wie ein externes Gutachten; bei entscheidenden oder strittigen Fällen einen unabhängigen Second-Source-Reviewer einsetzen. `quality_correct`, falsche Zuversicht, fehlende Gold-/relevante Pfade, ungestützte Zusatzbehauptungen und Fallback-Verhalten getrennt berichten.

**Kriterien für eine **eng begrenzte** Förderung:** Im Bestätigungslauf C gegen A **nicht schlechtere** quellengeprüfte Korrektheit und **keine** erhöhte falsche Sicherheit. Dazu entweder (a) obere 95-%-Grenze der task-gepaarten C−A-Gesamtzeitdifferenz unter null bei identischem Qualitätsniveau **oder** (b) belegter zusätzlicher fachlich korrekter Folgen-/Testnutzen auf mindestens zwei bislang zurückgehaltenen Fällen bei insgesamt **höchstens 10 %** Zeitmehrkosten. Auch bei (b) als **aufgabenklassenspezifischer Kandidat**, nicht als allgemeiner Geschwindigkeitsbeweis oder automatischer Default. Die vorhandene native `decision`-Formel wird nicht heimlich geändert, damit der gewählte Kandidat besser aussieht.

### 4. Verbindliche Stop-/Fortsetzungsentscheidung

| Nachweise nach den zwei Piloten und ggf. einer Bestätigung | Entscheidung |
| --- | --- |
| Echte Substitution **und** robuste Qualität-/Zeitwirkung in einer begrenzten Klasse | **Nur für diese Klasse optional anbieten**; Git-Fallback, keine Pflicht und ein einziger echter Consumer-Ende-zu-Ende-Test vor Rollout |
| C nutzt RepoGround weiterhin nicht, B bleibt bloß zusätzlicher Aufwand oder Effekte sind negativ | **Allgemeines Agentenbeschleunigungs-Versprechen einstellen**; Git-first beibehalten, RepoGround für deterministische Navigation, Quellenprüfung und historische Revisionsbelege pflegen |
| Echte Rohdaten oder unabhängige Qualitätsprüfung unvollständig | **Unentschieden, kein Rollout**; vorhandene Daten korrigiert bewerten, aber keinen automatischen dritten Optimierungsversuch starten |

**Nicht in diesem Auftrag:** neue Graphdatenbank, Cache-/Routerplattform, Index-Neubau, großflächiger Refactor, weitere Suchfeatures ohne konkrete Fehlerursache, automatischer Defaultwechsel, neue Sicherheits-/Reviewbürokratie oder unabhängige Feature-PRs pauschal blockieren.

**Umsetzungshoheit:** Grabowski alleiniger Writer/Operator je einmaligem gebundenem Worktree/PR; Captain für Merges. Großer Adler bei konkretem Unabhängigkeitsbedarf lesend. R5 und R3 bleiben historische Primärbelege, keine künstliche Regression und kein Grund, Änderungen ohne neuen tatsächlichen Agentenmesswert als „Wirkung bestätigt“ zu verkaufen.

**Abschlussartefakte:** Je wirklich ausgeführter Runde ein datierter SHA-gebundener Proof im bestehenden `docs/proofs/`, ein neuer nativer Auswertungsreport im vorhandenen Berichtspfad und ein kurzer Eintrag im [Langzeit-Messregister](../diagnostics/repoground-agent-study-history.md). **Keinen** gesonderten Steuerungsdienst, Backlog oder zweiten Studien-Recorder anlegen.
