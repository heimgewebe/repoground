# RepoGround – Agentenwerkzeugwahl nach tatsächlichem Nutzwert

**Stand:** 29. Oktober 2026 · **Priorität:** P1, gezielter Anschluss an die produktive Graph-Integration · **Status:** Umsetzungsplan, nicht implementiert.

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

### R2 – Unnötige Agenten-Toolschleifen beseitigen (P1, erst nach R1-Trace)

**Diagnose vor Patch:** In echten Aufgaben getrennt messen: (a) wiederholte `discover`-/`preflight`-Aufrufe, (b) übergroße Antwortpakete, (c) erneute Abfragen desselben unveränderten Ziels und (d) Validierungs-/Prozessstartzeit. Nicht jede Mehrzeit ist ein Graph-Performanceproblem.

**Umsetzung:** Nur den **nachgewiesenen** größten Verursacher klein beheben: etwa bessere konkrete Werkzeugbeschreibung, knapperes Ergebnisbudget oder gezieltere Toolwahl im Consumer. Existierende `get_structure_neighborhood`, `find_symbol`, `get_callers`, `live_freshness` und Aufgabenprofile verwenden, sofern die reale Toolinventur sie bestätigt; Namen nicht aus diesem Plan als heute überall verfügbar unterstellen. Kein neuer Cache, keine parallele Indexdatenbank, kein neuer Scheduler.

**Fertig, wenn:** Dasselbe reale Quellziel bei unveränderter Quellen-/Antwortqualität mit weniger überflüssigen MCP-Aufrufen oder belegbar kürzerer Gesamtzeit erreichbar ist. Auch „kein Patch nötig“ ist ein zulässiger Abschluss bei fehlendem Ursachenbeleg.

### R3 – Passenden Aufgabenmix statt Graph-Selbsttest messen (P1, nach R1)

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
