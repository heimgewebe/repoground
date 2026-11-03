# RepoGround – longitudinales Messregister

**Erstellt:** 1. November 2026
**Messprotokoll:** [RepoGround Agent Study v1](../usage/repoground-agent-study-v1.md)
**Neues eingefrorenes Taskset:** [12 Fälle, 3 Bedingungen, 2 Wiederholungen](../retrieval/repoground_agent_study_cases.v1.json)

Dieses Register trennt drei Evidenzniveaus, damit künftige Messungen nicht versehentlich eine Kausalwirkung suggerieren:

1. **Produktionsverfügbarkeit und technische Funktion:** Git-, Generator-, Health- und echte MCP-Abfragen.
2. **Historische echte Agentenläufe mit anderem Design:** relevant als Ausgangsvermutung; nicht in neue statistische Blöcke aufnehmen.
3. **Neue dreifach gepaarte Agentenstudien:** echte Provider-/Tracebelege auch bei ausstehendem Review gesondert ausweisen; einen **qualitätsgeprüften Nutzen** erst nach unabhängiger Qualitätsbewertung behaupten.

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

## Commonworld – technische Zitierabnahme vom 03.11.2026 (kein A/B/C-Lauf)

**[Revisions- und Hashbeleg](../proofs/repoground-commonworld-citation-recovery-20261103.md)**. Nach Merge von PR #1400 läuft die RepoGround-CLI/Fleet-Publikation auf Generator `b9db1745335f12f5e32120cc0366cf4687585a00`; die frisch veröffentlichte Commonworld-Quelle ist `2c6a790a8b76027d620cfc416918c9b6f08e34cc`. Das Bundle ist `fresh_exact` und `range_strict`-PASS. **1.886 von 1.886** Such-Chunks haben einen kanonischen Range-Bezug; keiner stammt aus dem bewusst ausgeschlossenen `releases/`-Root. Drei vorher unzitierbare Implementierungs-/Testpfade bestanden den echten `query_existing_index → range_get`-Rücklesetest einschließlich SHA-256-Abgleich. Auch `context_pack → range_get` mit direkt zurückgegebenem Ref wurde bestanden.

Der alte Snapshot hatte **1.639 von 50.770** Chunks mit `canonical_range` (3,23 %) und einen 16-teiligen Markdown-Dump. Generator, Source-Revision und Scope unterschieden sich; daraus ist **keine isolierte Zeit- oder Qualitätswirkung** ableitbar. **Neue Agentenprovider-Receipts: 0; neue A/B/C-Qualitätsbewertungen: 0; Agentennutzenstatus: `not_established`.** R3/R5 bleiben unveränderte, methodisch getrennte historische Kohorten.

## Eingefrorener Ausgangspunkt für die neue Kohorte

- **Studienversion:** repoground-agent-study-frozen-20261101-v1
- **Git SHA RepoGround:** 0fe8e5fd972c69b0d816b6bf124e10e6f5a43112
- **Git SHA Grabowski:** 3fbe93d2f4c7a99c3c1aaf2c35952bac3541d98f
- **Git SHA Commonthing:** 8dbc8c53ea7f26e218d419ac401eef44b29f9333
- **Sichtbarer Umfang:** 12 Fälle (6 Pilot), vier Aufgabenklassen, mindestens zwei negative Grenzfälle; Goldpfade aus tatsächlichen Git-Blobs am fixierten Commit validiert.
- **Bedingungen:** A git_only, B repoground_mandatory, C repoground_selective.
- **Vergleich:** gleiches Quellmaterial und Agent-/Runner-/Host-/Sampling-/Cache-Profil; neuer Generator darf variieren; zwei vollständige Wiederholungen vor jeder stabileren Interpretation.
- **A/B/C-Run-Receipts zum Zeitpunkt T0:** **0**. Erst die unten beschriebene getrennte **R3-Kohorte** enthält später echte Providerläufe; T0 bleibt unverändert Planung.

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

**Forschungsstand vor R3:** RepoGround war als deterministischer Quellenindex über 13 Repositories technisch nachgewiesen. Der damals noch ausstehende sechs Fälle umfassende A/B/C-Pilot wurde später als **R3** tatsächlich durchgeführt; sein ungeprüfter Ergebnisscope steht unten. Die semantische Qualitätsbewertung bleibt offen.


## T0 – überprüfter Infrastruktur-Smoketest vom 01.11.2026

**Messart:** ausschließlich Plan-/Vertragsprüfung, keine neue
Provider-, Modell- oder Agentenausführung.

| Merkmal | Nachweis |
| --- | --- |
| Eingefrorener Taskset-Digest | c09d2ed62456b1ad385f82e906be38ffc2a6ba02205b535d0ef4935ba9c59980 |
| Revisionsgebundene Quellpfade | RepoGround 9, Grabowski 2, Commonthing 2 |
| Gesunde Snapshot-/Generator-Identität | Alle drei auf Generator 0fe8e5fd972c69b0d816b6bf124e10e6f5a43112 |
| Erstellte Pilot-Requests | 36 (6 Fragen × 3 Arme × 2 Wiederholungen) |
| Real ausgeführte Agentenläufe | **0** |
| Fehlende Agenten-Receipts | **36**, vollständig sichtbar |
| Auswertung/Trend | not_established; eine Probe-Vergleichsgruppe |
| Vertragstest und Bestandstests | 178 PASS, Ruff PASS und CI-Komplexitätsratchet PASS; einzig vorhandener pytest-asyncio-Konfigurationshinweis |
| Technischer Prüfbeleg | Grabowski-Jobs c5bc062941bb (Tests samt CI-Ratchet) und 950743924ac4 (Plan/Leerauswertung) |

Die Planung erfolgte absichtlich mit einer als **planning-only**
gekennzeichneten Profilidentität ohne echten Provider. Ihr
Protokollschlüssel a2f926440a61edd7a94f44c6bb20fc5fb762f532ca17041e7ad5176b6e005739
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

## R3 – erster vollständiger echter Codex-A/B/C-Pilot vom 01.11.2026

**Originalnachweis:** [Ausführlicher Ergebnis- und Hashbeleg](../proofs/repoground-agent-study-codex-pilot-20261101.md)

| Merkmal | Gemessener Stand |
| --- | --- |
| Run-ID / Protokoll | `study-20261101-codex-r3` / `7bd39c8bbb7f5e5f60e8aee2005a6b856057e56182a2788ff7a5479d77e70ab7` |
| Taskset | `c09d2ed62456b1ad385f82e906be38ffc2a6ba02205b535d0ef4935ba9c59980` |
| Tatsächliche Agenten-Sitzungen | **36/36**, alle gültigen Provider-/Trace-Receipts |
| Ergebnisstatus | **33 erfolgreiche strukturierte Antworten, 3 fehlgeschlagene** im erfundenen Symbol-Grenzfall |
| Reale RepoGround-Aufrufe | A: **0**, B: **41**, C: **0** |
| Durchschnittliche Gesamtdauer einschließlich Fehler | A **22,982 s**, B **31,047 s**, C **24,276 s** |
| Gegenüber A, vollständig gepaarte Rohzeit | B **+8,065 s** (10/12 langsamer), C **+1,294 s** (8/12 langsamer) |
| Rein strukturelle Outcome-/Goldpfad-Korrespondenz | A **10/12**, B **10/12**, C **7/12** (kein semantischer Korrektheitsbeweis) |
| Mechanisch existierende Git-Zitatzeilen | **135/135** |
| Unabhängige qualitative Grades | **0**; keine qualitätsgeprüften Vergleichsblöcke |
| Messurteil | `not_established` (keine Default-Förderung) |

**Wichtige Interpretation:** Der optionale Agent hat RepoGround
tatsächlich **in keinem** der zwölf C-Läufe verwendet, obwohl es
zugelassen war. Eine messbare selektive Verbesserung ist somit
nicht gezeigt. Die B-Pflicht verschlechterte in dieser kleinen
Stichprobe die durchschnittliche Gesamtlaufzeit und erhöhte die
gemeldeten Input-Tokens. Kein Kausal- oder Qualitätsurteil aus
bloßen Zeitdifferenzen ohne unabhängige Source-Bewertung ableiten.

Die vorangegangenen R1/R2-Instrumentierungsfehler sind ausdrücklich
**andere Protokollkohorten** und gehen nicht in R3 ein. Die
36 Originalreceipts und Transkripte bleiben ausschließlich im
privaten Host-State; das Repository enthält bewusst nur
einen bereinigten, SHA-gebundenen Auszug. Jeder zukünftige
Runner-Refactor benötigt eine neue Fingerprint- und
`protocol_key`-Identität; ältere Zahlen werden nicht verändert.

## R5 – vollständige Codex-v2-A/B/C-Qualitätsstudie vom 01.11.2026

**Originalnachweis:** [R5 – Agentenantworten, Quellreviews, Frozen-Artefakte und Hashbindung](../proofs/repoground-agent-study-codex-v2-r5-20261101.md). Die **originalen nativen JSON-Auswertungen** sind für maschinelle Trendvergleiche nun gemeinsam versioniert, aber ausdrücklich getrennt nach Protokoll:

- [R3: Originalbericht ohne semantische Grades](agent-study-reports/codex-r3-20261101.json), SHA256 `313829977906a6ddc15a22c88938ced29b362f359c9b37fd9c5e1873bd1224c6`;
- [R5: Originalbericht mit 36 verblindeten Quellgrades](agent-study-reports/codex-v2-r5-20261101.json), SHA256 `aa1a31ac7503738a0173dac52a92042be10435cd530c106376f69b7fc7eecce6`.

| Dimension | Tatsächlich geprüfter R5-Stand |
| --- | --- |
| Run-ID | `study-20261101-codex-v2-r5` |
| Neuer `protocol_key` | `8d33c6baaad6464fc62b42a0a5bfb88b7352ad67e1900f136b64b37b7238778c` |
| Unverändertes Taskset | `c09d2ed62456b1ad385f82e906be38ffc2a6ba02205b535d0ef4935ba9c59980` |
| Echte v2-Codex-Läufe | **36/36** erfolgreich strukturiert, mit überprüftem Original-JSONL und Erklärungstext |
| Frozen Git-Quellen | RepoGround `0fe8e5fd`; Grabowski `3fbe93d2`; Commonthing `8dbc8c53`, jeweils mit unabhängig archiviertem SHA-gebundenem Snapshot |
| Gesonderter Generator-Commit | `040ab8b7bddc8e19a1459fe16374ae1934f72e77` |
| Verblindete Source-Reviews | **36/36** nach tatsächlichen Modellantworten und Frozen-Git-Quellen: 31 `correct`, 5 `partial` |
| Strengere native Qualitäts-Erfolge | **A 9/12, B 8/12, C 9/12** |
| RepoGround-MCP | A **0**, B **39**, C **0** erfolgreiche Aufrufe |
| Durchschnittliche End-to-End-Dauer | A **24,633 s**, B **34,353 s**, C **27,252 s** |
| Gepaarte B−A-Dauer | **+9,720 s**; task-geclustertes 95-%-Bootstrap-Intervall **[+6,148; +12,809] s** |
| Gepaarte C−A-Dauer | **+2,619 s**; Intervall **[−1,019; +8,611] s** |
| Beurteilbare Aufgabenblöcke | **12/12** (sechs Aufgaben × zwei Wiederholungen) |
| Native Wiederberechnung | Originaler SHA-gebundener Bericht in allen Feldern außer neuer `created_at`-Erzeugungszeit reproduziert |
| Urteil | **`not_established`**; kein verpflichtender RepoGround-Einsatz begründbar |

**Wichtige Einordnung:** Das R5-Quellenreview erfolgte unabhängig vom gemessenen Codex-Modell durch GPT-6, **aber im selben Operator-Thread**, nicht als unabhängiges menschliches Panel. Der Reviewer kann echte Belege anhand der alten Git-Blobs prüfen; aus einer `citations_checked=true`-Kennzeichnung allein folgt trotzdem keine automatisch beweisbare Aussagewahrheit. Im optionalen Arm **C wurde RepoGround in keinem einzigen Lauf eingesetzt**. Die R5-Verbesserung gegenüber R3 betrifft die **Bewertbarkeit**, nicht einen durch R3/R5 identisch nachgewiesenen Agentennutzen. **R3 und R5 niemals statistisch poolen.**

Zur reproduzierbaren Trendprobe genügt die bestehende Studien-CLI mit den zwei versionierten Originalberichten:

~~~bash
python3 -B -m merger.repoground.cli.agent_study trend \
  --reports docs/diagnostics/agent-study-reports \
  --out /PRIVAT/NEUER-TREND-R3-R5.json
~~~

Erwarteter Readback: `total_runs=2`, `comparison_groups=2`, kein `cross_run_causal_claim`. Das Ergebnis wurde mit der nativen `history`-Funktion anhand beider echten JSON-Dateien gegengeprüft. Neue Repositorystände, Runner, Prompt, Modell, Cache- oder Toolverträge verlangen eigene Berichtseinträge und gegebenenfalls eigene `protocol_key`-Gruppen. Rohtraces, Blindkarten, Mapping, Gutachten, Tokeninhalte und persönliche Pfade bleiben **privat**; das Git-Register enthält nur bereinigte Ergebnisse und die dazugehörigen SHA256-Belegidentitäten.
