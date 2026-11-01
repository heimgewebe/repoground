# RepoGround – longitudinales Messregister

**Erstellt:** 1. November 2026
**Messprotokoll:** [RepoGround Agent Study v1](../usage/repoground-agent-study-v1.md)
**Neues eingefrorenes Taskset:** [12 Fälle, 3 Bedingungen, 2 Wiederholungen](../retrieval/repoground_agent_study_cases.v1.json)

Dieses Register trennt drei Evidenzniveaus, damit künftige Messungen nicht versehentlich eine Kausalwirkung suggerieren:

1. **Produktionsverfügbarkeit und technische Funktion:** Git-, Generator-, Health- und echte MCP-Abfragen.
2. **Historische echte Agentenläufe mit anderem Design:** relevant als Ausgangsvermutung; nicht in neue statistische Blöcke aufnehmen.
3. **Neue dreifach gepaarte Agentenstudien:** nur nach vollständiger Ausführung, Traceprüfung und unabhängiger Qualitätsbewertung.

## Historische externe/ältere Belege – keine Protokollgleichheit

| Datum / Serie | Design und Quelle | Ergebnis | Was gerade nicht belegt ist |
|---|---|---|---|
| 29.10.2026 – 20 echte Codex-Paare | Nur Git gegen verpflichtenden RepoGround-MCP, 20 Aufgaben, Commit bbaccb6a, Modell gpt-5.6-sol | Git Ø 25,107 s; RepoGround Ø 39,852 s; 16/20 mit RepoGround langsamer; +59 % mittlere Dauer, +32 % Input-Tokens | Kein geprüfter Gewinn an semantischer Korrektheit; Ziel-ID im Text ist kein vollständiges Quellenreview |
| 29.–30.10.2026 – 4 Nachmesspaare | Selektive Nachprobe mit optimiertem Core, vorangehendes anderes Release | Git gesamt 99,649 s, RepoGround 122,402 s; +22,8 % Gesamtdauer | Winzige Stichprobe; Provider-Streuung, Cache und Fallauswahl nicht kontrolliert |
| 29.10.2026 – 16 direkte Graphabfragen | Alt- gegen neuen Schema-Validator, identische Quelle, keine Coding-Agenten | Direkte Core-Abfrage 12,604 → 2,939 s (4,29×), identische Antworten | Kein Nachweis gleicher Agentenbeschleunigung |
| 01.11.2026 – technische Produktivabnahme | RepoGround-Generator und alle 13 offiziellen Snapshots auf neuem Commit 0fe8e5fd97, 13/13 fresh_exact + Health PASS | Neue Symbol-Fehlanzeige 0 Treffer statt erfundener Fuzzy-Pfade; echte Python-Shebang-Symbolstelle gefunden | Kein neuer A/B/C-Providerlauf, keine menschlich geprüfte Gesamtantwortqualität |

Quellen:
- [Die 20 Paare mit tatsächlichen Laufprovenienzen](../proofs/repoground-agent-utility-20pairs-20261029.md)
- [Werkzeugwahl und 4-Paar-Nachmessung](../roadmap/repoground-agent-tool-selection-plan.md)
- GitHub: [RepoGround #1383](https://github.com/heimgewebe/repoground/pull/1383) und [#1384](https://github.com/heimgewebe/repoground/pull/1384)
- Aktuelle zu diesem Datum belegte immutable Generator- und Source-Revision: 0fe8e5fd972c69b0d816b6bf124e10e6f5a43112

Die alten Laufdaten liegen teilweise in einem *hostlokalen* Grabowski-State-Verzeichnis und sind nicht dadurch automatisch zu einem öffentlichen, archivierten Datensatz geworden, dass ein Bericht im Repository liegt. Bei späterem Import Originaldateien, Run-/Trace-SHA-256, Provenienz und Datenschutz erneut prüfen. Nie gerundete Berichtszahlen als exakte ursprüngliche Trial-Receipts rekonstruieren.

## Eingefrorener Ausgangspunkt für die neue Kohorte

- **Studienversion:** repoground-agent-study-frozen-20261101-v1
- **Git SHA RepoGround:** 0fe8e5fd972c69b0d816b6bf124e10e6f5a43112
- **Git SHA Grabowski:** 3fbe93d2f4c7a99c3c1aaf2c35952bac3541d98f
- **Git SHA Commonthing:** 8dbc8c53ea7f26e218d419ac401eef44b29f9333
- **Sichtbarer Umfang:** 12 Fälle (6 Pilot), vier Aufgabenklassen, mindestens zwei negative Grenzfälle; Goldpfade aus tatsächlichen Git-Blobs am fixierten Commit validiert.
- **Bedingungen:** A git_only, B repoground_mandatory, C repoground_selective.
- **Vergleich:** gleiches Quellmaterial und Agent-/Runner-/Host-/Sampling-/Cache-Profil; neuer Generator darf variieren; zwei vollständige Wiederholungen vor jeder stabileren Interpretation.
- **Bisherige A/B/C-Run-Receipts:** **keine**. Das Register dokumentiert keine erfundenen Messwerte.

Das maschinelle Protokoll berechnet eine taskset_sha256 für jede Taskset-Datei und je Wiederholung einen protocol_key, der die konstant zu haltenden Vergleichsgrößen umfasst. Künftige Reportergebnisse bekommen eine eindeutige Run-ID (beispielsweise study-20261101-01), und jede spätere Run-ID muss bei **gleichen** Modell-/Datenbedingungen zu demselben Vergleichsschlüssel führen. Andernfalls trennt die Trendfunktion automatisch die Serie.

## Konvention für künftige Einträge

Pro durchgeführter Studie im Register **ein kurzer Abschnitt** mit:
- Run-ID, Datum/Uhrzeit, Taskset-SHA und protocol_key; Frozen- oder rollierende Kohorte;
- Git-/Generator-/Bundle-/Manifest-SHAs je Repository und exakte Runner-/Modell-/Host-/Cachekennung;
- Zahl der geplanten, gültigen, fehlgeschlagenen und vollständigen dreifachen Blöcke; Anzahl tatsächlich beurteilbarer Antworten und negative Fälle;
- primäre C−A-Werte und task-geclusterte 95-%-Intervalle, B−A und C−B als Diagnosen, plus Kosten nur bei belastbarer Abrechnung;
- Link zu **bereinigtem** versioniertem Report, Prüfer-/Trace-Evidenzverweisen und beobachteten Ausfällen;
- Status **not_established**, **selective_benefit_candidate** oder **no_selective_benefit_established**, ohne automatische Standardumstellung;
- sachliche Ursachenhypothese für den nächsten Patch, falls ein neuer Effekt wirklich nachgewiesen wurde.

Jeder rohe Run-Trace gehört zunächst in einen privaten, kontrollierten State-Bereich und nicht in Git. Keine Secrets, persönlichen Chatlogs, Tokeninhalte oder Provider-Anmeldedaten in ein öffentliches Ergebnisartefakt kopieren.

**Aktueller Forschungsstand:** RepoGround ist als aktueller deterministischer Quellenindex über 13 Repositories technisch nachgewiesen. Ein Vorteil bei den gesamten Aufgaben des Coding-Agenten **bleibt eine zu messende Hypothese**. Der nächste echte Schritt ist der 6-Fälle-A/B/C-Pilot an dem unveränderlichen Ausgangstaskset, nicht ein weiterer synthetischer „Erfolgsbenchmark“.


## T0 – überprüfter Infrastruktur-Smoketest vom 01.11.2026

**Messart:** ausschließlich Plan-/Vertragsprüfung, keine neue
Provider-, Modell- oder Agentenausführung.

| Merkmal | Nachweis |
| --- | --- |
| Eingefrorener Taskset-Digest | 103dfb9be83aec59b010141d064f62b59228ba7f47626f3844410b43ae89917b |
| Revisionsgebundene Quellpfade | RepoGround 9, Grabowski 2, Commonthing 2 |
| Gesunde Snapshot-/Generator-Identität | Alle drei auf Generator 0fe8e5fd972c69b0d816b6bf124e10e6f5a43112 |
| Erstellte Pilot-Requests | 36 (6 Fragen × 3 Arme × 2 Wiederholungen) |
| Real ausgeführte Agentenläufe | **0** |
| Fehlende Agenten-Receipts | **36**, vollständig sichtbar |
| Auswertung/Trend | not_established; eine Probe-Vergleichsgruppe |
| Vertragstest und Bestandstests | 166 PASS, Ruff PASS; einzig vorhandener pytest-asyncio-Konfigurationshinweis |
| Technischer Prüfbeleg | Grabowski-Jobs 8579e3309cc0 (Tests) und 593b826b5962 (Plan/Leerauswertung) |

Die Planung erfolgte absichtlich mit einer als **planning-only**
gekennzeichneten Profilidentität ohne echten Provider. Ihr
Protokollschlüssel 56fcecbc004e04dd9435821492de1b079ba3ed462ed5fbde1db1622610a9c041
ist **kein** Langzeitprotokoll realer Agentenläufe und wird nicht
mit späteren Providerdaten zusammengeführt. Die vertraulichen
Laufplan- und Rohdateien verblieben außerhalb des Repositories im
operativen State-Verzeichnis. Für den ersten echten Piloten
müssen Runner, Provider, Modell und Toolinventar neu und wirklich
quellengebunden eingetragen werden.

**Messurteil:** Die Infrastruktur unterscheidet echte fehlende Evidenz
von gültigen Daten und lässt sich mit aktuellen Snapshot-Manifesten
ausführen. Damit ist der Prüfstand technisch brauchbar, aber eine
qualitätsgeprüfte Verbesserung des Coding-Agenten noch **nicht belegt**.
