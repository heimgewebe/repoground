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
