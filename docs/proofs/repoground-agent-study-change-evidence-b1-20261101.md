# RepoGround – begrenzte Nutzwertinterventionen A1/B1 (02.11.2026)

**Status:** A1 und B1 jeweils mit **36/36** echten Agentensitzungen abgeschlossen. **Kein** Qualitäts- oder Produktivitätsgewinn durch RepoGround nachgewiesen; **keine** Default-Promotion. Die vorregistrierten Mindestbedingungen für eine Bestätigungsstudie wurden in beiden Runden verfehlt. Maßgebliche Entscheidungsregel: [zwei Versuchs­runden mit Stopkriterium](../roadmap/repoground-agent-tool-selection-plan.md). Vergleichsbasis: [R5 mit Quellenbewertung](repoground-agent-study-codex-v2-r5-20261101.md).

## A1: genau eine Toolwahl-/Kontextintervention, abgeschlossen

A1 behielt das eingefrorene R5-Aufgabenmaterial und die drei Bedingungen A Git-only, B verpflichtend, C freiwillig bei. **Eine** reversible Promptänderung leitete bei komplexeren Beziehungen zu gezielten RepoGround-Abfragen mit kleinem Kontextbudget, warnte vor nicht notwendigen Discovery-/Freshness-Zwischenaufrufen und vor anschließender redundanter breiter Git-Suche. Die A-Bedingung behielt ihr ursprüngliches Git-first-Promptverhalten. Codex-Modell, Host- und historische Source-Manifest-SHAs blieben identisch, Runner-/Prompt-Version und damit Protokollschlüssel wurden als neuer Eingriff registriert.

| Beleg | A1 |
| --- | --- |
| Run-ID | `study-20261101-codex-v3-a1` |
| Protokollschlüssel | `971172c157e6f0595bc511759cc2e1c544e49199e8af3374e434d717603b5788` |
| Frozen-Taskset-SHA256 | `c09d2ed62456b1ad385f82e906be38ffc2a6ba02205b535d0ef4935ba9c59980` |
| Runner-Quell-SHA256 | `7ce70e6f314adb2d400e02a30c761d8fd13740e08861c48947278957d2ac7a50` |
| Experiment-Quellrevision | `13c9658f6b55a44a85408feb8a248aca5960e568` ([PR #1390, geschlossen/ungemergt](https://github.com/heimgewebe/repoground/pull/1390)) |
| Original-A1-Bericht SHA256 | `54e31f7e49581acfc49f64b196e16459e08175c63a44459462253ac498c1bd61` |
| Original-A1-Plan SHA256 | `da32024fe05895116946adf1f294abdcf6f4db4567e920a174e577df62f175fc` |

| Echt gemessene Runden-A1-Kennzahl | A Git-only | B Pflicht | C optional |
| --- | ---: | ---: | ---: |
| Strukturierte, tracevalidierte Codex-Läufe | 12/12 | 12/12 | 12/12 |
| Mittlere Gesamtdauer | 25,191 s | 31,045 s | 23,069 s |
| Erfolgreiche und fehlgeschlagene Git-Werkzeugaufrufe zusammen | 52 | 50 | 52 |
| Tatsächliche RepoGround-MCP-Aufrufe | 0 | 18 | **0** |
| Gemeldete Input-Tokens insgesamt | 1.801.457 | 2.353.625 | 1.237.255 |

Die A1-Promptänderung verringerte die RG-Aufrufe im Pflichtarm gegenüber R5 (39 auf 18), ersetzte aber nur **zwei** Git-Werkzeugaufrufe bei zwölf Aufgaben und ließ B durchschnittlich **5,854 Sekunden länger** dauern als A. Die selektive C-Bedingung verwendete RepoGround **in keinem einzigen Fall**. Weniger Tokenverbrauch und Laufzeit in C können nicht durch ein dort unbenutztes Werkzeug verursacht worden sein. 36/36 Originalreceipts wurden gegen ihre echten JSONL-Traces geprüft. Für A1 wurden **keine** neuen armverblindeten semantischen Source-Grades erzeugt; folglich bleibt der native Bericht korrekt auf `graded_trials=0`, `complete_blocks=0` und `not_established`. Keine statistischen Qualitäts- oder Kausalerfolge daraus konstruieren.

**A1-Entscheidung:** Vorregistriertes Signal „C nutzt RepoGround bei mindestens zwei geeigneten Aufgaben und spart wenigstens 20 % Git-Suchaufwand bei gleicher Qualität“ klar verfehlt. **Nicht mergen und nicht als Agentenoptimierung bewerben.** Die experimentelle Git-Quellrevision bleibt als nachvollziehbarer Nachweis erhalten, ohne produktiven Runner zu ersetzen.

## B1: echte Git-Änderungsevidenz über vorhandenes `change_evidence_pack`

B1 benutzt als **zweiten und letzten** geplanten Eingriff ausschließlich das bereits vorhandene, ursprünglich nicht auf der Codex-Whitelist stehende read-only-Tool `change_evidence_pack` für bekannte, echte SHA40-Paare `base..target`. Die Taskset-/Goldfragen werden als eigenes Protokoll bei den historisch fixierten RepoGround- und Grabowski-Commits geprüft, ohne R5/A1 mit anderen Tasksets statistisch zu poolen.

| Vorregistrierter technischer Vertrag | B1 |
| --- | --- |
| Pilot-Run-ID | `study-20261101-codex-v4-b1` |
| Protokollschlüssel | `6c1ff7838ecab975f9d2b6700a9ff29d0288892d4bcf27800606174d624aa9ed` |
| Taskset-Original-JSON | [12 feste Aufgaben, davon sechs Pilotfälle](../retrieval/repoground_agent_study_change_evidence_cases.b1.json) |
| Validierter Taskset-Digest | `f3f2e86c5ede63e22f564fe8dd30b94bc72ef4265eb7187ba4ecafd0570795aa` |
| B1-Runner-Quell-SHA256 | `1df4f5edf2ac4f62d31ede922befc01cb4d9ee906968e52770277b5e7a8fa5da` |
| Reales Toolset | A Git/Datei; B/C plus 13 read-only RepoGround-Werkzeuge |
| Pilotumfang | sechs Fälle × drei Arme × zwei Wiederholungen = 36 echte Codex-Sitzungen |

Die echten MCP-Smokeproben bestätigten `change_evidence_pack` in der registrierten Toolliste, gesunde Hash-/Quellbindung und bei passendem historischem, sauberem Checkout `live_freshness=fresh`. Das Ergebnis ist wegen begrenzter Strukturprojektion und unbewiesener vollständiger Testabdeckung ausdrücklich `status=warn`. Ein erfolgreiches **lesen** dieses begrenzten Pakets ist nicht gleichbedeutend mit korrekt gefundener vollständiger Testabdeckung. Bei `stale`, `invalid` oder `unavailable` bleibt Git der Fallback. Kein ungewollter Snapshot-Build, keine Runtime-/Mergewirkung.


## B1 – vollständige tatsächliche Auswertung

**Originale Daten:** Der vorregistrierte B1-Codex-Runner verarbeitete 36/36 eindeutige Requests und erzeugte 36 gegen den jeweiligen Originaltrace erfolgreich validierte native Receipts. Der Job endete erfolgreich; er hat kein einziges Experiment heimlich erneut ausgeführt. **13** Provider-Antworten genügten dem bisherigen target-only-Zitiervertrag, **23** wurden als `invalid_agent_answer` gespeichert. Diese 23 sind `failed` gemäß unverändertem Messvertrag, **nicht** als 23 sachliche Falschantworten zu lesen.

| Native B1-Quittungen einschließlich fehlgeschlagener Versuche | A: nur Git | B: RepoGround Pflicht | C: optional |
| --- | ---: | ---: | ---: |
| Tatsächlich erfasste Sitzungen | 12 | 12 | 12 |
| Ursprünglich formatgültige Antworten | 5 | 4 | 4 |
| `invalid_agent_answer` | 7 | 8 | 8 |
| Mittlere Gesamtdauer **aller** Sitzungen | **28,716 s** | **64,749 s** | **31,414 s** |
| Git-Werkzeugaufrufe | 47 | 47 | 51 |
| RepoGround `change_evidence_pack` | **0** | **12** | **0** |
| Sonstige RepoGround-MCP-Aufrufe | 0 | 3 (`bundle_discover`) | 0 |
| Tatsächlich gemeldete Input-Tokens, gesamt | 1.173.354 | 1.701.069 | 1.251.962 |
| Vom Provider abgerechnete Geldbeträge | unbekannt | unbekannt | unbekannt |

Die 12 echten `change_evidence_pack`-Reads waren im MCP-Vertrag erfolgreich, lieferten aber keinen belegten Agentennutzen: B benötigte ebenso **47 Git-Aufrufe** wie A, im Mittel jedoch **36,033 Sekunden** mehr pro Sitzung und etwa **45 % mehr gemeldete Input-Tokens**. Für das Pack selbst wurden eine mediane Werkzeugdauer von **21,026 Sekunden**, ein Mittel von **31,091 Sekunden** und ein Maximum von **54,128 Sekunden** aus echten Provider-Ereignissen erfasst. Die derzeitige Implementierung kompiliert bei jeder geeigneten einzelnen Anfrage erneut den Git-gebundenen strukturellen Änderungseinfluss; eine bestehende temporäre Reuse-Option gilt nur innerhalb autorisierter Eventbatches, nicht als genereller MCP-Cache. Das erklärt einen plausiblen direkten Overhead, ist aber kein eigener Kausalversuch.

**Wissenschaftlich zentral: Zitiervertrag passt nicht zu Commitpaarfragen.** Die B1-Aufgaben verlangten ausdrücklich einen Vergleich von `base..target`; der unveränderte Runner aus den ursprünglichen R5-Einzelrevision-Aufgaben akzeptiert im Ergebnis-JSON jedoch ausschließlich Zitate auf `target`. Die von Codex tatsächlich erzeugten Antworten der 23 formal abgewiesenen Läufe sind parsebares JSON mit inhaltlicher Erklärung. Eine **separat deklarierte nachträgliche Quellprüfung** zeigte für alle **23/23**, dass die Ablehnung ausschließlich auf Zitaten des im Prompt genannten **Basiscommits** beruhte und die betreffenden Git-Blob-Dateien und Quellzeilen dort existierten. Betroffen sind A **7**, B **8**, C **8**. Das ist weder ein Beweis für inhaltliche Korrektheit noch eine Erlaubnis, die unveränderlichen Originalreceipts umzuschreiben. Die Korrektur des Zitiervertrags wäre eine **neue Studienmethodik** und wird hier nicht nachträglich als positiver Effekt verbucht.

| Abschließende B1-Bindung | Wert |
| --- | --- |
| Privater Originalplan SHA256 | `0990cee9a4baeb48c497d22578798510687491ecc7bbff02a4f23b0650f7306d` |
| Native `report-b1.json` SHA256 | `6d9e2c3a7d4e7d24c11854f5c385bf4b1db6520c269eaa8f2ec1d3ee674733fd` |
| Nachträgliche, ausschließlich strukturelle Quellenprüfung SHA256 | `cb14498e754090dcda14381877bcc235839627cac7213591c047044404bb822f` |
| Alt-Reviewer-Rubrik, B1 vorab separat eingefroren | SHA256 `235e17ae3d17f548b3b862959d16bc003c3485417e2b68774a70f09128d07835` |
| Native B1-Beurteilung | `not_established`, `graded_trials=0`, `complete_blocks=0` |
| Verblindeter Reviewexport | 13 formalgültige Antworten, private Armzuordnung separat, **noch keine** unabhängigen semantischen Grades |

Die vollständig erhaltenen 36 Original-Modelltraces und alle Providerverbrauchswerte ermöglichen eine spätere **eigens deklarierte explorative** Paarrevisions-Nachprüfung, jedoch keine rückwirkend vorregistrierte Bestätigung. Die native Laufbewertung zählt ausdrücklich auch Formatfehler als verbrauchte Zeit und Tokens. Solange keine fachlichen Originalbewertungen durchgeführt wurden, dürfen `graded_trials=0` und `complete_blocks=0` nicht als 0 korrekt beantwortete Fälle gedeutet werden.

**Verbindliche Stopentscheidung nach A1 und B1:** Im optionalen Arm C wurde RepoGround in **keiner einzigen** der jeweils 12 Sitzungen verwendet, also in **0 von 24** echten Versuchen über beide Runden. Die mindestens zwei unterschiedlichen geeigneten, tatsächlich RG-nutzenden Aufgaben aus der vorregistrierten Pilot-Regel fehlen. B zeigte in beiden Runden zusätzlichen Tool- und Zeitaufwand ohne Git-Arbeit zu ersetzen. Deshalb **keine 72er-Bestätigungsstudie, keine weitere allgemeine Agentenbeschleunigungsrunde und keine Übernahme der A1-/B1-Runner-Änderungen in den produktiven Standard**. Git-first beibehalten; RepoGround gezielt als deterministische, revisions- und quellengebundene Navigation verwenden, soweit eine konkrete Aufgabe das benötigt. Ein künftiger neuer Auftrag braucht einen eigenen echten Nutzungsfall – nicht nur weitere Rankings oder mehr MCP-Aufrufe.

**Integritätsgrenze:** Die originalen JSONL-Transkripte, privaten Reviewer-Zuordnungen und historisch gebundenen Snapshots bleiben im privaten Originalstudien-State; dieses Dokument gibt nur reproduzierbare SHA- und Ergebnisbelege wieder. Historische R5-/A1-Resultate und B1 sind getrennte Protokollgruppen.