# RepoGround Commonworld – semantische Studienbewertung v2

**Stand:** 2026-11-04 · **Status:** neue Protokoll-/Goldsetversion, keine damit durchgeführten Providerläufe.

## Auslöser (v1 bleibt unverändert)

Die originale Commonworld-only-Kohorte `repoground-commonworld-agent-utility-frozen-20261103-v1` wurde mit dem eingefrorenen Commonworld-Commit `2c6a790a8b76027d620cfc416918c9b6f08e34cc`, Generator `b9db1745335f12f5e32120cc0366cf4687585a00` und Manifest-SHA `e1f1d60fa35983a23b6f61eb70db0eaded2b90921831b174d5feed893a8bf688` durchgeführt.

**Diagnose, kein Nutzennachweis:** 17 von 36 geplanten echten Codex-Receipts wurden validiert; fünf der sechs Pilotfälle besitzen einen vollständigen A/B/C-Block mit nur einer Wiederholung. Beim ersten Fall wurde der dritte Arm während des Providerlaufs ausdrücklich abgebrochen und besitzt keinen Abschlussreceipt. Alle fünf vollständigen selektiven C-Läufe verwendeten **null** RepoGround-Aufrufe. Qualität wurde nicht unabhängig benotet, daher steht die Entscheidung weiter auf `not_established`.

Der ursprüngliche Evaluator wertete alle nicht vorab genannten Pfade als `unsupported_paths`, auch wenn Source-Dokumente konkrete relevante zusätzliche Abhängigkeiten belegen. Zudem wurde die Frage, ob erfolgreiche Tests aktuelle Live-Auslieferung *beweisen*, als `abstain` gewertet, obwohl ein fachlich belegtes **Nein** eine gültige inhaltliche Antwort ist. Diese beiden Kategorien dürfen nicht gleichgesetzt werden.

Original-Taskset, Protokoll, Originaltraces, Receipts und das armverblindete v1-Reviewpacket werden **nicht geändert oder in v2 nachträglich benotet**. Messungen verschiedener Taskset-SHAs sind nicht dieselbe Kohorte.

## Minimalinvasive Änderung

Die Agent-Studienschnittstelle für Plan, Requests, Runner und Providerreceipts bleibt auf Schema `1.0`. Ausschließlich das **Taskset und dessen deterministische Bewertungsregeln** haben jetzt die opt-in-Version `2.0`:

`docs/retrieval/repoground_commonworld_agent_study_cases.v2.json`

Jeder v2-Oracle besitzt:

- `path_policy: independent_review`: Aus dem Goldset nicht vorab bekannte Pfade werden als `unlisted_paths` ausgewiesen. Sie sind **nicht automatisch falsch**, dürfen aber ohne independenten `correct`-Verdikt und `citations_checked=true` auch keinen Qualitätserfolg erzeugen. Der Reviewer muss dabei **jede Behauptung, jede Zitierung und die Relevanz sämtlicher genannten Pfade** am eingefrorenen Commit prüfen.
- `review_criteria`: vor der Antwort feststehende fachliche Bewertungskriterien.
- `negative_conclusion`: trennt eine belegte Verneinung (`outcome: answer`) von echten Wissensgrenzen (`outcome: abstain`).

Die tatsächlichen numerischen `unsupported_paths` bleiben bei v1 exakt die strikte Allowlist-Differenz. Bei v2 ist diese Kennzahl **unbekannt (`null`)**, weil bloß unregistrierte Pfade keine geprüften Falschbehauptungen sind. Stattdessen werden separat `unlisted_paths` und `unlisted_paths_review_pending` berichtet. Die Summary zählt diese Werte, ohne sie als unbelegte Aussagen zu erfinden. Ein fehlendes oder negatives Qualitätsurteil kann dadurch keinen Nutzenkandidaten begründen.

### Negativkontrollen

- **G1 – aktuelle reale Browserladezeit:** `abstain`, denn ein Git-Stand liefert keinen aktuellen Nutzer-Millisekundenwert.
- **G2 – beweisen Tests aktuelle Live-Auslieferung?** `answer`, erwartete begründete Schlussfolgerung: **Nein**. `asserted_sufficient_evidence=true` kann sich auf den ausreichend bewiesenen *negativen Schluss* beziehen und ist nicht selbst eine Behauptung, dass der produktive Dienst getestet wurde. Entscheidend ist der unabhängig geprüfte Antworttext.
- **G3 – welche historische Version wird am 4. November 2026 aktuell ausgeliefert?** `abstain`, denn die tatsächliche Live-Version ist aus historischen Dateien nicht bestimmt.

Beide echten Abstentionen behalten ihre Pflicht zum Nichtwissen. Ein `answer` als Ersatz für unbewiesene Echtzeitwerte bleibt bei ihnen Fehlzuversicht. Das Schema verweigert v1-Aufgaben mit nachträglich eingeschleusten v2-Feldern.

### Bewusst nicht geändert

- Keine neuen Agenten, Retrieval-Regeln, Graphdienste oder Runner.
- Keine Ausführung vorhandener v1-Versuche nach veränderten Regeln.
- Keine Qualitätsbehauptung aus gefundenen Pfaden, grüner CI oder erfolgreichen MCP-Aufrufen.
- Keine Pflicht zur RepoGround-Nutzung im selektiven Arm.
- Keine Änderung an veröffentlichten Bundles oder Commonworld-Quellständen.

## Abnahme und weiterer Messweg

1. V2-Validator gegen den exakten Git-Commit, Regressionen für v1 und v2, Plan-Engine und Report-Pfade müssen PASS zeigen.
2. Vor dem ersten neuen Providerlauf sind genau dieser neue Taskset-SHA, vorhandene Hardlink-freie Runnerfassung, Codex-Modell, MCP-Implementierung, Source- und Manifestidentität sowie der neue `protocol_key` zu binden.
3. Eine neue getrennte A/B/C-Pilotkohorte darf **erst nach fachlicher Prüfung des Goldsets** beginnen. Der v1-Pilot liefert nur Gründe für diese Neubewertung, aber keine statistisch kombinierbare Stichprobe.
4. Aus v2-Receipts ein armverblindetes Reviewpacket exportieren und unabhängig, quellengebunden beurteilen. **Kein `correct` ohne Prüfung aller zusätzlich genannten relevanten Dateien.**
5. Falls auch der neue selektive Arm RepoGround nie nutzt, eine klar abgegrenzte Werkzeugwahl-Diagnose statt eines weiteren ungerichteten 72-Läufe-Programms durchführen.
6. Historische, repositoryübergreifende und laufzeitbezogene Aufgaben anschließend als eigene **separat vorregistrierte** Kohorte prüfen, denn die Commonworld-only-Kohorte testet diese theoretischen Alleinstellungsmerkmale nicht.

Die Nutzenentscheidung bleibt `not_established`, solange kein vollständiger, qualitätsgeprüfter und statistisch vertretbarer A/B/C-Vergleich vorliegt.
