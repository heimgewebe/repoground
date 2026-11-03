# RepoGround S4 – vorregistrierter Agentennutzentest (Git-only vs. System-Evidenz)

**Stand:** 2. November 2026. **Ausgangsgenerator:** `7d299a7d1248a22263e176a7f7c5182a2ad57ba2` (unveränderlich produktiv). **Status dieses Arbeitsstands:** Code, Quellenorakel und Instrumentierung im isolierten Grabowski-Branch; *neue* Providerläufe sind nur nach tatsächlich erzeugten, validierten Receipts nachgewiesen. Keine S2-/S3-Produktivbehauptung.

## Bestehendes Instrumentarium, neue Kohorte

Der schon existierende [Agent-Study-v1-Vertrag](../usage/repoground-agent-study-v1.md) einschließlich `merger.repoground.cli.agent_study`, `tools/agent_study_codex_runner.py`, isolierten Codex-Sessions, SHA-gebundenen Traces/Receipts, echten Provider-Tokens, eindeutiger Modell-/Host-/Cacheidentität und geclustertem Langzeitvergleich bleibt die **einzige Messarchitektur**. Es wird kein neuer Scheduler, keine Benchmarkdatenbank und kein zweiter Runner eingeführt.

Das neue, explizit getrennte Aufgabenorakel: `docs/retrieval/repoground_system_evidence_agent_study_cases.v1.json`. Der native Validator meldete 12 gültige Fälle, exakt drei je `known_target`, `reverse_relations`, `impact_tests`, `boundary`, sechs Pilotfälle und zwei negative Abstinenzfälle. Taskset-SHA-256: `3927cf030fd997211c66d7e47f18947c8cbae506732b8fb305eaa75b59d7d360`. Alle 16 verwendeten konkreten Goldpfade wurden als existierende Gitobjekte an den jeweiligen vollständigen SHAs geprüft. Keine nachträgliche Frageumformulierung auf RepoGround-Bedürfnisse.

Gebundene Quellrevisionen (keine wechselnden `main`-Referenzen):

| Repository | Git-Commit |
|---|---|
| `heimgewebe/heim-pc` | `049efc0fcddee75d5d6ddee631be6e5b42784761` |
| `heimgewebe/nixer` | `c252b62b0fcd0bd5442681bb68d809a4b5984c61` |
| `heimgewebe/metarepo` | `c1ac04fec54de590eda209b916f81c4ce8eb363a` |
| `heimgewebe/repoground` | `7d299a7d1248a22263e176a7f7c5182a2ad57ba2` |

Die neue Kohorte enthält die zuvor festgelegten Aufgabenklassen: exakter Nixer-Pin, Flake-URL/Lock, äußere und innere Moduleinbindung, Dienstdeklaration, Cross-Repo-Rückverfolgung, Metarepo-Kopiervertrag, historischer inkonsistenter Pinwechsel, Entwickler-Testauswahl, plausible Runtime-Regression, erfundene Funktion, ausdrücklich nicht beweisbare Aktivierung und bekannte FTS-Nulltrefferfalle. Zwei Negativaufgaben verlangen `abstain` statt erfundener Bestätigung. Die FTS-Nulltrefferfalle wird nicht mit der strukturierten Flake-Evidenzabfrage gleichgesetzt.

## Instrumentierung von echten S4-Artefakten

Die explizite Tool-Allowlist des **bestehenden** instrumentierten Codex-Runners erhält genau den schon produktiv vorhandenen MCP-Leser `get_flake_relation_evidence`. Ein Toolname allein begründet keinen Erfolg. `_mcp_evidence_available` verlangt beim S4-Tool ein wirklich empfangenes strukturiertes Paket mit `evidence.status`, `relations`, `gaps`, vollem `pack_sha256` und `source_commit`; der Receipt-Konsument vergleicht `manifest_sha256` und `source_commit` mit den vorher eingefrorenen Manifest-Bindungen. Falsche Revision, geändertes Manifest, fehlende Paketbytes oder unbekannter Status werden als fehlgeschlagener Toolcall bewertet, nicht als Erfolg. Auch ein `partial`-Paket mit echten Lücken darf gelesen werden, ohne die fehlenden Beziehungen zu erfinden.

Der Git-only-Arm erhält weiterhin keine RepoGround-MCP-Werkzeuge. Der Pflicht-Arm verlangt wirklich erfolgreichen RepoGround-Konsum; der optionale Arm darf RepoGround auslassen. Unterschiedliche Quellrevision, Modell, Runner-Code oder Toolvertrag erzeugen einen **neuen Protokollschlüssel**; frühere Serien werden nicht vermengt. Eine Änderung an `tools/agent_study_codex_runner.py` verändert dessen Runner-Fingerprint und Toolvertrag automatisch.

## Messablauf

1. Die vier gefrorenen Git-Quellen verfügbar halten; für Nixer ggf. einen *separaten, read-only isolierten Checkout* am Quellcommit verwenden, nie den kanonischen Checkout umstellen.
2. Die existierenden gesunden S4-Bundle-Manifeste für Heim-PC, Metarepo und RepoGround mit SHA-256 fixieren. Nixer ist bisher nicht offiziell fleet-publiziert; das Quellrepo nur für die Studie über die vorhandene `ground snapshot create`-Schnittstelle als eingefrorenes, unveränderliches **Studienbundle** abbilden. Nicht wegen der Studie den produktiven Publisher erweitern.
3. Mit `agent_study validate-taskset --roots` das echte Quellorakel sowie mit `agent_study plan` alle Manifest-/Runner-Bindungen prüfen. Neue, separate Run-ID und private Plan-/Trace-/Receiptverzeichnisse verwenden, niemals bestehende Rohdaten überschreiben.
4. Mit `agent_study run-batch` dieselben sechs Pilotfragen × drei Arme × zwei Wiederholungen durch das echte Codex-Modell bearbeiten. Wenn die Instrumentierung noch nicht bereit ist, keine Providerkosten, Tokens oder Erfolge erfinden. Die Aufgabenprompts bleiben armgleich.
5. Antworten gegen eingefrorene Gitbelege möglichst blind und mit gleicher Rubrik unabhängig prüfen; anschließend die native `agent_study evaluate`- und `trend`-Funktion verwenden. Nur bereinigte, SHA-gebundene Ergebnisreports versionieren.

## Ausgangsbefund und notwendige neue Evidenz

Die ältere, **nicht vergleichsgleiche** R5-Studie mit 36 echten Codex-Läufen und unabhängiger Modell-Source-Begutachtung lieferte Git-only 9/12, Pflicht-RepoGround 8/12 und optional 9/12 qualitätsgeprüfte Erfolge. B war im Mittel 9,720 Sekunden langsamer als A; der optionale Arm C benutzte RepoGround **kein einziges Mal**. Damit ist ein allgemeiner Agentengewinn bisher **nicht nachgewiesen**. Die S4-Vorberechnung (~410× schneller im isolierten p95-Datenzugriff) darf nicht zur gesamten Agentenlaufzeit hochgerechnet werden.

Für die neue Systemwissenskohorte zählen nur reale zusätzliche Erkenntnisse und vollständige Agentenzeit, Tool-Aufrufe, nachgewiesene Zitate, False Positives, Unsicherheitsausweisung und Provider-Tokens. Ohne einen source-reviewed neuen Paardatensatz bleibt das Urteil `not_established`, unabhängig von grünem PR/CI, gesundem Bundle oder neuem Tool in der Allowlist.
## Reale Agentenstudie R0, 2. November 2026

Alle 36 echten gpt-5.6-luna-Durchläufe sind mit SHA-gebundenen Providerreceipts abgeschlossen. In der nativen Auswertung: Git-only 9/12 gültig und 22.091 ms Median, RepoGround-Pflicht 10/12 und 29.309 ms, RepoGround-optional 10/12 und 25.714 ms. Eingabetokens: 1.750.957 / 2.971.982 / 2.535.420. Der Entscheid bleibt `not_established`: keine unabhängig geprüften Antworten und kein vollständiger Paarblock. Der Blindexport umfasst 29 reviewfähige und sieben ungültige Antworttexte.

Historische Quellzitate wurden im R0-Runner wegen einer zu engen Commit-Whitelist verworfen, obwohl die historischen Gitobjekte existieren. Die alte v1-Kohorte und ihre Rohbelege bleiben unverändert. Ein neues v2-Taskset bindet vier zulässige historische Revisionen und lässt diese durch Git-Ancestry und präzise Einzelfallprüfung verifizieren. Ein neuer Vergleich braucht einen neuen Protokollschlüssel, keine rückwirkende Schönrechnung.

## Nachbewertung der Original-Kohorten R0 und V2 (separate, unveränderte Evidenz)

**Messentscheidung: `not_established`**. Die ursprünglichen Modellläufe,
Providertraces, Receipts, Blindzuordnungen und Bewertungen bleiben in ihren
jeweiligen privaten Studienwurzeln; sie wurden nicht überschrieben. Nach dem
frühen R0-Bericht wurden die 29 reviewfähigen R0-Antworten unabhängig
armblind gegen eingefrorene Git-Quellen bewertet: 24 `correct`, vier
`partial`, eine `uncertain`. Dies ist eine unabhängige **Modellbewertung**,
keine menschliche Abnahme. Das Original-Protokoll behält seine sieben ungültigen
Versuche (darunter den historischen Zitatvalidatorfehler). R0 und V2 dürfen
wegen verschiedener Protokoll- und Taskset-Hashes nicht zusammengepoolt werden.

Für V2 wurde **keine neue Runner-Architektur** verwendet. Das neue Goldset
`docs/retrieval/repoground_system_evidence_agent_study_cases.v2.json`
(SHA-256 `e3785cc5d894271fe01a74293db6b183825038d22fbe80e07423ce986df3f730`)
bindet historische Zitat-Commits pro Aufgabe. Der neue Protokollschlüssel lautet
`7fb215e9aee64026bf806038d3b86e0b32ab88bc20fb3bdffa702c041f7d16cc`.
Alle 36 echten V2-Modellversuche wurden im ursprünglichen privaten Studienroot
abgeschlossen. 34 waren protokollgültig; die 34 eindeutigen Blindantworten
erhielten in fünf getrennten read-only Git-Quellenprüfungen 32 `correct`
und zwei `partial`. Die ursprünglichen Bewertungsdateien blieben erhalten;
der native `review-import` band die Bewertungen unverändert an die
Originalreceipts. Auch diese unabhängigen Urteile sind **Modell-**, keine
Menschenbewertungen.

Die nativen, strengeren `quality_correct`-Zahlen bewerten nicht bloß das
externe Urteil, sondern auch die Aufgabenerfüllung nach Goldpfaden. Deshalb
weichen sie von den 32 fachlich korrekten V2-Modellurteilen ab:

| V2 (12 Versuche je Arm) | Git-only | RepoGround-Pflicht | RepoGround-optional |
|---|---:|---:|---:|
| Protokollgültig | 11 | 11 | 12 |
| `quality_correct` | 3/11 | 4/11 | 2/12 |
| Median aller gemessenen Laufzeiten | 22.821 ms | 32.968 ms | 29.645,5 ms |
| Input-Tokens gesamt | 1.991.938 | 3.006.352 | 1.857.572 |
| Werkzeugaufrufe gesamt | 69 | 107 | 66 |
| RepoGround-Aufrufe / Fehlschläge | 0 / 0 | 48 / 6 | 0 / 0 |

Für R0 lauten die entsprechenden strengeren Erfolge 3/9, 3/10, 2/10;
Medianlaufzeiten 22.091 / 29.309 / 25.714 ms und Input-Tokens
1.750.957 / 2.971.982 / 2.535.420 (gleiche Armreihenfolge).
Die bewerteten R0-Ergebnisse enthalten acht vollständige
Task×Wiederholung-Blöcke, V2 enthält zehn; wegen ungültiger Antworten und
der vorregistrierten Mindestdeckung bleibt die Qualitätsprüfung im
automatischen Entscheidungsobjekt unvollständig. Eine stärkere
statistische Schlussfolgerung ist damit nicht zulässig.

**Funktionaler Befund:** Der V2-Pflichtarm verbrauchte ungefähr 1,5-mal so
viele Input-Tokens wie Git-only und hatte einen um 10,147 Sekunden
höheren Laufzeitmedian. Sein gepaarter taskgeclusterter Mehrzeit-Mittelwert
beträgt 8,317 Sekunden, das Bootstrap-95%-Intervall schließt null ein
(−5,853 bis +20,040 Sekunden). Der optionale V2-Arm nutzte RepoGround
tatsächlich **kein einziges Mal**. Die V2-Klasse `impact_tests` hatte
zwar vollständig gültige Receipts und einen kürzeren gepaarten Pflicht-Arm,
aber unter der strengen `quality_correct`-Rubrik **keinen
Qualitätserfolg in irgendeinem Arm**; daraus folgt noch kein Nachweis
historischer Nutzungsüberlegenheit. Ebenso war `reverse_relations` in V2
bei der Pflichtverwendung länger, ohne strengeren Qualitätserfolg.
Das native Urteil bleibt deshalb `not_established` und
`default_promoted=false`. Ein isoliert schneller S4-Paketleser ist nicht
gleich einem schnelleren oder besseren End-to-End-Agenten.

Private, SHA-gebundene Nachrechenreferenzen (nur Hashes, keine Rohdaten):

| Abgeleitetes Artefakt | SHA-256 |
|---|---|
| R0 `evaluation-luna-graded.json` | `839d1f74b7e17f5636fa9cc44ac414996cee484926725be9aa40a9ca752cd5f3` |
| R0 `owner-only/grades-luna.json` | `080c05b58e4e5cefc4153c81e4097f609a932a9eb84f253df23fb4c809149dc7` |
| V2 `evaluation-luna-graded.json` | `717d40ee87f7c1a2ce0c4b944f591c23f1e6b34f9a6cc9107129a2e3c1df145b` |
| V2 `owner-only/grades-luna.json` | `2e2974f6015c0a30da51c8a63d0430292c538983ef8bdb5dbc3f24bc04264df3` |

**Wiederholungsvertrag:** `agent_study validate-taskset`, `plan`,
`run-batch`, `validate-receipt`, `review-export`, `review-import`,
`evaluate --grades` und `trend` bleiben die maßgeblichen Werkzeuge.
Bei neuen Kohorten Taskset-/Modell-/Runner-/Tool-/Quell-SHAs, Reihenfolge,
Providertraces, Cache-/Hostbedingungen und Bewertungsart separat binden.
Abweichende Protokollschlüssel nur **nebeneinander** vergleichen,
nie zusammenrechnen. Bei weiterem Ausbau zuerst die Qualität historischer
`impact_tests` und präzise Anwendung der vorab berechneten Flake-Evidenz
gezielt verbessern; kein verpflichtender globaler RepoGround-Zugriff ohne
nachgewiesenen zusätzlichen Endnutzen.


## Native Langzeit-Trendprojektion (getrennte Protokollgruppen)

Die vorhandene agent_study trend-CLI wurde mit exakt zwei unabhängig
validierten, qualitätsgebundenen Originalauswertungen ausgeführt. Der
bereinigte, maschinenlesbare Output ist in
[repoground-system-agent-study-r0-v2-trend-20261102.json](repoground-system-agent-study-r0-v2-trend-20261102.json)
versioniert. Er enthält nur Protokollschlüssel, Auswertungsidentitäten,
Generatorrevisionen und statistische Aggregate; weder private
Armzuordnungen noch Providertraces, Geheimnisse oder lokale Runtimepfade.

Der Native-Output (SHA-256
ee22d700ec287de3647fe3825d23e132eab54840fe924e3677d23b79ba7fe14d)
weist total_runs=2, comparison_groups=2 und in **beiden**
Gruppen cross_run_causal_claim=false aus. Die voneinander abweichenden
Protokollschlüssel verhindern damit bereits in der vorhandenen Trendfunktion
eine unzulässige gemeinsame R0/V2-Wirkungsschätzung. Für spätere Wiederholungen
sind neue kohortengebundene Evaluationsberichte in eine eigene private
Trend-Eingabemappe aufzunehmen und nur geprüfte, sensible-freie Aggregate
zu veröffentlichen.
