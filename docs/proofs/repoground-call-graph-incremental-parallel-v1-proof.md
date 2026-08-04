# RepoGround Call-Graph Incremental and Bounded-Parallel v1 — T031 Proof

Status: implemented and locally validated
Bureau task: `RPU-V1-T031`
Bureau run: `BUR-RUN-20260804T062104Z-4e825c0891`
Base commit: `633568ce1e0880b729ff48e4ff77fd6ae69b351f`
Producer version: `python-call-graph-v1-cache-1-py3.10`
Measurement artifact: `repoground-call-graph-incremental-parallel-v1.measurement.json`
Measurement SHA-256: `5e5ec7e9518b5d55116485dd8980e9441edf970bfc300b83dfb96c1376f2b283`

## Problem

Der bisherige Python-Call-Graph-Producer analysierte bei jedem Aufbau sämtliche
Python-Dateien erneut und seriell. T031 durfte diese Kosten nur senken, wenn die
öffentliche V1-Ausgabe, Parse-Diagnostik und globale Auflösung einem sauberen
Vollaufbau entsprechen.

## Umgesetzter Vertrag

Die Erzeugung bleibt zweistufig:

1. **Dateianalyse:** Definitionen, Bindungen, Importzustand und rohe Call-Sites
   werden als unveränderlicher Snapshot erfasst. Jeder Cacheeintrag ist an den
   relativen Pfad, den SHA-256 des vollständigen Inhalts, die Producer-Version
   und die Python-Haupt-/Nebenversion gebunden.
2. **Globale Auflösung:** Alle neuen und wiederverwendeten Snapshots werden bei
   jedem Aufbau erneut zu einem vollständigen Modulbestand zusammengesetzt.
   Caller-/Callee-Auflösung und kanonische Sortierung laufen vollständig neu.

Der produktive `generate_call_graph_document`-Pfad verwendet einen
prozesslokalen, per `RLock` geschützten Standardcache. `extract_python_calls`
behält sein öffentliches Drei-Tupel bei und akzeptiert lediglich optionale
Cache-, Worker-, Speicher- und Messparameter. Das öffentliche
`python_call_graph`-Format und seine Version bleiben unverändert.

## Invalidierung

Tests belegen:

- geänderte Dateien werden über ihren neuen Inhalts-Hash neu analysiert;
- hinzugefügte Dateien sind neue Cache-Misses;
- gelöschte Dateien verschwinden beim atomaren Cache-Ersatz;
- umbenannte Dateien werden unter dem neuen Pfad neu analysiert;
- Producer- oder Python-Versionswechsel verwerfen ältere Einträge;
- fehlerhafte Dateien werden nicht als wiederverwendbare Snapshots gespeichert.

Im finalen Messkorpus waren 702 Python-Dateien vorhanden. 700 erfolgreiche
Dateisnapshots wurden gespeichert. Der unveränderte Lauf hatte 700 Treffer und
zwei erneute Prüfungen; der Ein-Datei-Lauf 699 Treffer und drei Neuprüfungen.

## Begrenzte Parallelität und Rückfall

- Standardmäßig höchstens vier Prozesse, harte Obergrenze 32;
- Parallelität erst ab acht Misses und 128 KiB Quelltext;
- höchstens zwei Aufträge pro Worker und Batch;
- standardmäßig 64 MiB logische Quelltext-Payload pro Batch;
- größere Einzeldateien werden seriell verarbeitet;
- fehlt `ProcessPoolExecutor`, läuft der vollständige serielle Pfad;
- bei Executor- oder Workerfehlern werden alle parallelen Teilergebnisse
  verworfen und sämtliche Misses vollständig seriell neu analysiert.

Die 64-MiB-Grenze ist eine deterministische Payload-Grenze im Elternprozess,
kein vollständiges RSS-Limit für ASTs oder Kindprozesse.

## Ergebnisgleichheit

Kalter Serienlauf, kalter Parallelaufbau, unveränderter Warmlauf und
Ein-Datei-Lauf erzeugten denselben kanonischen Ergebnis-Hash:

`c12547d4e4dad664f0eb0d8cbf3b8b063ea29db4ded8aa09e6653a94511a1295`

Der Ein-Datei-Lauf wurde zusätzlich gegen einen frischen seriellen Vollaufbau
des identischen temporären Repositoryzustands verglichen. Die Hashes waren
gleich. Bestehende und neue Tests prüfen außerdem identische Call-Reihenfolge
und identische Parse-Diagnostik.

## Messaufbau

- CPython 3.10.12;
- Linux 7.0.11, x86_64, glibc 2.35;
- 32 logische CPUs;
- vollständiger Python-Bestand des geprüften RepoGround-Worktrees;
- 702 Python-Dateien, 8.853.965 Byte;
- Korpusmanifest:
  `48474b3cb4aaf509b38c214cdc0441c476bbb43ba625266b809ba09325384eb1`;
- drei Wiederholungen je Pfad;
- vier Worker und 64 MiB Payload-Grenze;
- kleine Änderung: ein Kommentar in der größten Python-Datei einer temporären
  Korpuskopie; der echte Worktree wurde nicht verändert.

## Messergebnisse

| Pfad | Median | p95 | Beschleunigung |
| --- | ---: | ---: | ---: |
| kalt, seriell | 16.006,58 ms | 17.400,55 ms | 1,00× |
| kalt, vier Prozesse | 10.267,54 ms | 11.707,53 ms | 1,56× |
| unverändert, warmer Cache | 4.341,36 ms | 4.928,70 ms | 3,69× |
| eine Datei geändert | 5.491,76 ms | 6.242,78 ms | 2,91× |

Daraus folgen gegenüber der Serienbaseline:

- kalte Parallelität: 35,9 Prozent weniger Zeit;
- unveränderter Cachelauf: 72,9 Prozent weniger Zeit;
- Ein-Datei-Lauf: 65,7 Prozent weniger Zeit.

Der Parallelpfad analysierte alle 702 Dateien ohne Rückfall. Die größte
beobachtete gebündelte Payload betrug 402.407 Byte und lag unter 64 MiB.

Mit `tracemalloc` beobachteter Peak im Elternprozess:

- kalt seriell: 156.208.461 Byte;
- kalt parallel: 157.200.473 Byte;
- unverändert warm: 120.715.772 Byte;
- kleine Änderung: 124.323.552 Byte.

Kindprozess-RSS ist darin nicht enthalten.

## Qualitäts- und Wartbarkeitsbelege

- Fokussierter Producer-Test: `58 passed, 10 skipped`;
- direkte Veröffentlichungsgrenze: `115 passed, 10 skipped`;
- Goldset-/Agentenwirkungstests: `95 passed, 10 skipped`;
- vollständiger RepoGround-Testbestand: `5387 passed, 12 skipped`;
- Ruff-Lint: grün;
- Ruff-Format: kanonisch;
- Graph-Wartbarkeitsratchet: grün;
- fixer Goldstandard:
  - S1-Präzision `1.0`;
  - Ziel-Recall `1.0`;
  - keine Fallregression;
  - Kontextpfadreduktion `0.5454545454545454`;
  - Call-Records-SHA-256
    `6a26b3a4f0e2ba55d0e1a59c53b7980cc9204e9e7d6718103eab80b4100220e`;
  - Goldset-SHA-256
    `beab71b88895dd173d2622a9ad5bf3aae36b5cf37b2a430a8b26348e9533c681`.

## Entscheidung

Beide Optimierungen werden beibehalten. Sie liefern auf dem repräsentativen
Korpus messbare Gewinne, bleiben bytegleich zum seriellen Producer und bestehen
alle Qualitäts- und Wartbarkeitsgates. Der globale Resolver bleibt bewusst
vollständig; dies begrenzt die Maximalbeschleunigung, verhindert aber veraltete
Beziehungen zwischen geänderten und unveränderten Dateien.

Es wird kein persistierter Cache und kein neues öffentliches Artefaktformat
eingeführt.

## Reproduktion

```bash
python -m merger.repoground.scripts.bench_call_graph_build . \
  --repetitions 3 \
  --max-workers 4 \
  --output docs/proofs/repoground-call-graph-incremental-parallel-v1.measurement.json
```

## Nicht belegt

Dieser Abschluss belegt nicht:

- dieselbe Beschleunigung auf jedem Repository oder jeder Maschine;
- ein hartes Gesamt-RSS-Limit einschließlich Kindprozessen;
- semantische Vollständigkeit des statischen Call-Graphen;
- Laufzeiterreichbarkeit oder dynamischen Dispatch;
- Nutzen eines persistenten, prozessübergreifenden Caches;
- Produktionskapazität, SLO-Erfüllung oder Mergefreigabe außerhalb des
  revisionsgebundenen PR-Prozesses.
