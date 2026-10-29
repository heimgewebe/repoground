# RepoGround: 20 gepaarte Live-Agentenaufgaben – Wirksamkeit (29.10.2026)

## Messaufbau und identifizierbare Belege

- Tatsächlich **20 Aufgaben × 2 Bedingungen = 40 Codex-CLI-Läufe**, nicht Simulationen; Modell `gpt-5.6-sol`, Git-Quellcommit `bbaccb6ac561d218095f29c584b652293161330a`.
- Jeweils identische Prompts (`prompt_sha256`), Task-Quellen (`source_task_sha256`), Revisionen und Modelle für Baseline/Treatment in **allen 20 Paaren** frisch aus den Lauf-JSONs abgeglichen.
- Baseline: Git/Dateilesen ohne RepoGround. Treatment: dieselben Aufgaben mit explizit aktiviertem RepoGround-MCP. Beide isoliert mit `--ignore-user-config --disable apps --disable plugins`, damit der Baseline-Agent **keinen verdeckten RepoGround-Zugang** über angebundene ChatGPT-Apps hat.
- Taskset: `/home/alex/.local/state/grabowski/repoground-pr1362-staging/utility-paired-taskset-20261029.json`, SHA256 `b635d7ad9ecfbd2d6d2a9b10ae1961bfaab634edeaeae00acb1d1e30a31cae1e`.
- Maßgebliche 40 Laufdaten: `/home/alex/.local/state/grabowski/repoground-utility-clean-baseline-after-1362-20261029/trials/{task-id}-{baseline,treatment}.json`. Jeweils `trace_sha256` und `trace_bytes` verweisen auf tatsächliche `transcripts/`-JSONLs. Prüfjob `e8c16a68fa1c` erfolgreich laut ursprünglicher Übergabe.
- Frühere fehlerhaft isolierte Versuchsserien sind **ausgeschlossen**. Diese Auswertung verwendet nur den abschließend validierten Satz.

## Ergebnis: gemessene Zahlen (keine Qualitätsbehauptung)

| Kennzahl | Nur Git/Dateien | Mit RepoGround-MCP |
|---|---:|---:|
| Terminal erfolgreich | 20/20 | 20/20 |
| Ziel-ID im Antworttext | 20/20 | 20/20 |
| Laufzeiten gesamt | 502,144 s | 797,043 s |
| Laufzeit durchschnittlich | 25,107 s | 39,852 s |
| Laufzeit Median | 22,198 s | 38,712 s |
| Gemeldete Input-Tokens | 1.990.782 | 2.637.605 |
| Gemeldete Output-Tokens | 20.613 | 21.441 |
| Gemeldete Cached-Input-Tokens (enthalten) | 1.745.920 | 2.156.032 |
| RepoGround-MCP-Aufrufe | 0 | 78 |
| Davon gemeldete erfolglose MCP-Versuche | 0 | 2 |

**Treatment ist bei 16/20 Aufgaben langsamer**, im Mittel +14,745 s beziehungsweise rund **+59 %**, während gemeldete Input-Tokens um rund **+32 %** steigen. Alle vier Fälle mit verkürzter Laufzeit liegen in der Tabelle. Bei `call-metarepo-process` wurden 2 MCP-Versuche ohne erfolgreiches Ergebnis protokolliert; spätere Aufrufe gelangen. Die 78 Toolaufrufe sind tatsächliche an RepoGround gerichtete MCP-Aufrufe, nicht interne ressourcenleere MCP-Discovery.

### Paarergebnisse (Laufzeit in Sekunden)

| Aufgabe | Git | RepoGround | Differenz | MCP-Aufrufe | fehlgeschlagen |
|---|---:|---:|---:|---:|---:|
| `call-atlas-inventory` | 12.88 | 28.97 | +16.09 | 3 | 0 |
| `call-callgraph-cache` | 34.09 | 62.46 | +28.37 | 4 | 0 |
| `call-chunk-digest` | 14.69 | 24.13 | +9.44 | 5 | 0 |
| `call-main-argv` | 27.32 | 39.06 | +11.74 | 5 | 0 |
| `call-metarepo-process` | 10.74 | 44.48 | +33.74 | 9 | 2 |
| `import-adapter-merge` | 29.89 | 48.69 | +18.80 | 4 | 0 |
| `import-adapter-security` | 37.45 | 35.02 | -2.43 | 3 | 0 |
| `import-bundle-entrypoints` | 16.75 | 40.40 | +23.65 | 4 | 0 |
| `import-metarepo-path` | 20.09 | 31.74 | +11.65 | 3 | 0 |
| `import-pythonista` | 19.94 | 35.97 | +16.03 | 3 | 0 |
| `md-agents-roadmap` | 13.69 | 31.53 | +17.84 | 3 | 0 |
| `md-changelog-roadmap` | 11.45 | 33.83 | +22.38 | 3 | 0 |
| `md-contrib-agents` | 24.30 | 35.36 | +11.06 | 4 | 0 |
| `md-faq-getting-started` | 29.91 | 38.37 | +8.46 | 3 | 0 |
| `md-readme-product` | 34.16 | 32.80 | -1.36 | 4 | 0 |
| `test-agent-entry` | 17.12 | 53.59 | +36.47 | 4 | 0 |
| `test-consumption-wrapper` | 53.15 | 40.77 | -12.38 | 3 | 0 |
| `test-export-gate` | 26.30 | 42.81 | +16.51 | 3 | 0 |
| `test-git-read` | 49.49 | 47.92 | -1.57 | 4 | 0 |
| `test-service-initialize` | 18.74 | 49.14 | +30.40 | 4 | 0 |

Die Tabelle zeigt pro Aufgabe **gerundete** Einzelwerte; Gesamtwerte sind aus den ungerundeten Original-JSONs summiert. Alle 20 Aufgaben wurden gleichmäßig auf Markdown-Links, Python-Imports, Python-Calls und Testbeziehungen verteilt.

## Aussagekraft und Antwortstichprobe

Die Antwortstichprobe über sechs Paare (`md-agents-roadmap`, `import-adapter-security`, `call-metarepo-process`, `test-agent-entry`, `test-consumption-wrapper`, `md-readme-product`) liefert in Baseline und Treatment die gleiche erwartete Zielidentität mit plausiblen Dateien und Zeilenangaben. Ihre Quellenangaben sind mit den genannten Source-Stellen und dem gebundenen Commit konsistent. **Das ist eine Plausibilitätsprüfung, keine unabhängige Vollprüfung aller Antwortbelege**. Insbesondere ist der lexikalische Ziel-ID-Treffer kein Korrektheits- oder Vollständigkeitsbeweis.

Die Aufgaben wurden gezielt aus vorhandenen **S1-Graphkanten** ausgewählt. Es wurden keine komplexen Refactorings durchgeführt und keine mutierenden Agentenaktionen auf Erfolg geprüft. Gemeldete Tokenzahlen sind keine gemessenen Geldkosten; Cacheanteile und Providerabrechnung sind nicht kontrolliert. Providerstreuung, Versuchsanordnung und externe Latenz können Unterschiede beeinflussen.

**Nicht belegt**: genereller Produktivitätsgewinn, bessere semantische Korrektheit, niedrigere Kosten, vollständiges Codeverständnis, höhere Architekturqualität. Die geringe Anzahl pro Beziehungstyp erlaubt keine stabile Untergruppenregel.

## Entscheidung für die produktive Nutzung

1. Für ein bekanntes Ziel, direkten Dateiinhalt oder einen einzelnen trivialen Import/Link zuerst normales `git show`, `rg` und Dateiöffnung verwenden. RepoGround für diese Fälle nicht pauschal vorschalten.
2. RepoGround **selektiv erproben** für unbekannte eingehende Abhängigkeiten, mehrstufige Aufrufketten, verteilte Test-Zuordnung, revisionsbezogene Auswirkungen und quellgebundene MCP-Agentenkontexte.
3. Für jeden Einsatz die reale Frage entscheiden lassen: Liefert der Graph andere beziehungsweise belegbar vollständigere Treffer als eine direkte Suche – und rechtfertigt das die Zusatzlatenz? Das ist eine zu prüfende Hypothese, **keine bereits bewiesene Routingregel**.
4. Der technische Performance-Patch (schnellere Validierung der großen Beziehungsgrafik) ist separat gegen **vollständige Abfragezeiten, Speicher, Ergebnisidentität und manipulierte Artefakte** zu bewerten. Eine 12-fache Verbesserung eines isolierten Validators impliziert weder 12-fach schnellere Agenten noch einen besseren Gesamtvergleich. Erst eine kleine reale Follow-up-Gegenprobe nach Deployment erlaubt eine neue Wirksamkeitsaussage.

## Reproduktion ohne 40 neue Providerläufe

In einem Python-Prozess über `trials/*.json` gruppieren nach `task_id` und `condition`, `status/exit_code/timed_out` prüfen, die oben genannten Prompt/Source/Commit/Model-Fingerprints paarweise vergleichen, `duration_seconds` summieren und Median berechnen, `reported_usage.{input_tokens,output_tokens,cached_input_tokens}` summieren sowie `repoground_mcp_calls` und `success=false` zählen. Die Transcripts lassen sich über `trace_sha256` in den JSONs prüfen. **Keine neue Agentenausführung erforderlich.**

## Separater technischer A/B-Benchmark (16 direkte Graphabfragen)

**Nicht Teil der 40 Agenten-Providerläufe.** Der vollständige produktive Graph vom Manifest SHA256 `3bc297e341c3d079b22f297cb867543327326cb724c16f2955bdfbe755e7bb2a` wurde aus demselben Worktree abgefragt. Der Baseline-Zweig ersetzt **ausschließlich** den geänderten Schema-Validator durch den zuvor verwendeten `validate_document(document, SCHEMA, ROLE)`-Aufruf. Manifest-/Hash-/Semantik-/Ausgabe-Pfade sind identisch.

Reproduktionsskript (lokaler Messbeleg, keine Produktivdatei): `/home/alex/.local/state/grabowski/repoground-pr1362-staging/perf-fast-schema-benchmark-20261029.py`; terminal erfolgreicher Job `grabowski-job-bf18281f0cf7` mit Original-JSON-Linien in `/home/alex/.local/state/grabowski/jobs/grabowski-job-bf18281f0cf7/stdout.log`.

| Bei jeweils 8 direkten Aufrufen | Original `jsonschema` | Optimiert `fastjsonschema 2.22.2` |
|---|---:|---:|
| Mittelwert komplette Abfrage | 12,604 s | 2,939 s |
| Median komplette Abfrage | 12,625 s | 2,932 s |
| Minimum/Maximum | 12,376/12,709 s | 2,912/2,974 s |
| Mittelwert Schema-Validierung | 10,359 s | 0,668 s |
| Mittelwert semantische Kantenprüfung | 1,634 s | 1,662 s |
| Gemessene Peak-RSS-Spanne (KiB) | 359.020–367.736 | 362.028–371.828 |

**4,29-fache Beschleunigung der vollständigen direkten Graphabfrage** bzw. rund **76,7 % weniger Latenz**. Die beiden Ziele waren `file:AGENTS.md` und `py:merger:repoground:adapters:metarepo.py:function:_should_process_entry`; Reihenfolge `legacy → fast → fast → legacy`, zwei Durchgänge pro Ziel und Modus. Alle 16 Abfragen lieferten denselben `status=available`, und für jedes Ziel stimmten die SHA256-Werte der vollständig serialisierten Antwort in sämtlichen 8 Aufrufen überein. Die Peak-RSS-Spannen stammen aus separaten Python-Prozessen; es handelt sich **nicht** um eine deduplizierte Dauer-Speicheranalyse.

Die Schema-Prüfung dominiert den beseitigten Flaschenhals; die semantische Kantenprüfung bleibt bewusst vollständig erhalten. Der Nachweis betrifft die **direkte Graphlesefunktion** und belegt nicht automatisch einen Vorteil für Codex-Agenten. Die kleinere Agenten-Gegenprobe ist erst **nach** Aktivierung der neuen produktiven Runtime aussagekräftig.
