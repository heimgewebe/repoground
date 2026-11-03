# RepoGround – Commonworld-only A/B/C preregistration (2026-11-03)

**Status:** Taskset-Vorregistrierung und minimaler Validator-Fix; **keine Provider-Receipts und keine Qualitätsgrades für diese Kohorte**. Die bestehende gemischte R1-Kohorte bleibt unabhängig und wird nicht überschrieben oder gepoolt.

## Fragestellung und Grenzen

Löst ein echter Coding-Agent anspruchsvolle Commonworld-Fragen mit freiwilligem RepoGround-Einsatz besser oder effizienter als mit Git und normaler Dateisuche? Das primäre Vergleichspaar ist **C (selective) − A (git_only)**. B (mandatory) dient zur Ermittlung der Kosten erzwungener Nutzung. Ein erfolgreicher MCP-Call allein ist kein Agentennutzen.

## Revisionsbindung

- **Commonworld-Quellcommit:** `2c6a790a8b76027d620cfc416918c9b6f08e34cc` (reine Commonworld-Aufgaben).
- **Generator:** `b9db1745335f12f5e32120cc0366cf4687585a00`.
- **Produktivbundle-Manifest:** SHA-256 `e1f1d60fa35983a23b6f61eb70db0eaded2b90921831b174d5feed893a8bf688`; Publish-Run `20261103T182131Z-83f90c21d844`; `fresh_exact`, Range-Strict PASS bei technischer Ausgangsprüfung.
- **Taskset:** `docs/retrieval/repoground_commonworld_agent_study_cases.v1.json` – zwölf Fälle, je drei aus `known_target`, `reverse_relations`, `impact_tests`, `boundary`; genau sechs Pilotfälle; drei korrekte Nichtwissens-/Abgrenzungsfälle.
- Die bereits gemessene gemischte R1-Kohorte mit RepoGround- und Commonworld-Aufgaben ist **nicht** diese Kohorte. Sie bleibt samt ihrer Plan-, Runner- und Trace-Hashes separat.

Ein eingefrorener Git-Commit bedeutet nicht, dass das öffentliche Deployment auf genau diesem Commit läuft. Für Behauptungen zu realer Runtime müssen separate Live-Evidenzen vorliegen. Das Goldset wird vor Agentenstart durch eine unabhängige, quellengebundene Gegenprüfung bestätigt; davon dürfen keine Antworten in die Agenten-Workspaces gelangen.

## Durchführungsplan mit bestehendem Studienrunner

1. `agent_study validate-taskset --taskset … --roots …` – Git-Blobs der notwendigen und erlaubten Pfade am fixierten Commit prüfen. Der Validator akzeptiert jetzt **ein oder mehrere** Repositories; Null-Repo-Fälle bleiben ungültig. Die ursprüngliche 12-Fall-Multi-Repo-Kohorte bleibt unverändert gültig.
2. Den installierten Codex-CLI-Adapter `tools/agent_study_codex_runner.py` und die tatsächlich installierte MCP-Implementierung **vor jedem Providerstart** fingerprinten. `model`, Prompt-/Runner-/Toolversion, Cachemodus, Hardwareklasse, Source-SHA, Snapshot-Manifest und `protocol_key` sind bindend; keine Annahme aus alten Receipts.
3. Technischer Smoke mit einem gesonderten, nicht gewerteten A/B/C-Aufgabenblock (3 reale Providerläufe): frische Sessions/Workspaces, A ohne RepoGround-Registrierung, B mit erfolgreichem RepoGround-Read, C mit freier Wahl. Nur bei tatsächlichen gültigen JSONL-Traces und Receipts fortsetzen.
4. Pilot: **36 neue echte Agentenläufe** (sechs Aufgaben × A/B/C × zwei Wiederholungen), vorab balancierte Armausführungsreihenfolge. Keine Wiederverwendung von R1-/R5-Receipts. Fehler, unbekannte Versuche und Timeouts bleiben sichtbar, niemals synthetisch als Erfolg ersetzen.
5. Antworten ohne Armkennung verblindet prüfen. Für jede wesentliche Aussage Belege im eingefrorenen Git-Stand nachlesen; prüfen: vollständige Schlussfolgerung, fehlende/falsche Quellen, korrektes Nichtwissen, Halluzination, Dauer, Token, Toolaufrufe und reale RepoGround-Nutzung. Die Originaltraces bleiben privat, in Git gelangen nur bereinigte, hashgebundene Belege.
6. **Nur bei brauchbarem Pilotsignal** eine getrennte bestätigende 72-Lauf-Kohorte (alle zwölf Aufgaben × drei Arme × zwei Wiederholungen) durchführen. Pilot und Bestätigung nicht zu unabhängigen Aufgaben zusammenrechnen; Änderungen an Aufgabe/Toolvertrag/Modell erzeugen neue Studien- und Protokollidentitäten.

### Entscheidungsregeln vor dem Lauf

- Hauptindikator: qualitätsgeprüfte aufgabengepaarte C−A-Differenz. Die Zeitvergleiche verwenden task-geclusterte Bootstrap-95-%-Intervalle, nicht einzelne Wiederholungen als unabhängige Stichprobe.
- Ein positiver Effizienzkandidat verlangt mindestens erhaltene Qualität, tatsächlich verwendetes RepoGround in C und das vorhandene strenge `selective_benefit_candidate`-Kriterium (oberes 95-%-Intervall von C−A-Laufzeit < 0); zusätzlich wird ein praktischer Effekt von mindestens 10 % medianer Zeitersparnis berichtet, ohne diese Einzelzahl allein zum Beweis zu erklären.
- Ein isolierter Qualitätsgewinn bei größeren Kosten rechtfertigt höchstens einen spezifischen Folgeversuch in betroffenen Aufgabenklassen, keine allgemeine RepoGround-Pflicht.
- Nutzt C erneut nie RepoGround, ist das ein **Negativergebnis der selektiven Werkzeugwahl**, keine stumme Erfolgsgeschichte. Ursache prüfen, aber nicht die bewertete Kohorte nachträglich verändern.
- B langsamer bei unveränderter Qualität: Pflichtnutzung nicht empfehlen. Kein Nutzen oder zu breite Konfidenzintervalle: `not_established`.
- Aus dem Codex-JSONL stammen echte Zeiten und Tokenmengen, nicht geschätzte Kosten. Abrechnungskosten bleiben unbekannt, solange sie nicht einzeln belegt sind.

### Ergebnis und Zuständigkeit

Ein echter Abschluss enthält gültige Provider-/Trace-Receipts, verblindete unabhängige Qualitätsgrades, native Evaluation und einen kurzen Entscheidungsbericht: wo RepoGround hilft, welche Funktion dabei tatsächlich beiträgt und wann Git allein genügt. Grabowski ist einziger Writer/Operator. Großer Adler kann ein unabhängiger Read-only-Quellenprüfer sein. Keine neue Agentenarchitektur, kein zweiter Studienrunner und kein automatisches Umschalten von Grabowski.
