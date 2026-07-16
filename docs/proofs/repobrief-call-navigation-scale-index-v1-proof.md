# RepoBrief Call-Navigation Scale Index v1 — T029 Proof

Status: implemented and locally validated
Bureau task: `RPU-V1-T029`
Base commit: `fafa115c1bb291742f5a7e10ba5ab21e33baa902`
Default implementation: bounded process-local in-memory index
Persisted sidecar promotion: `false`
Measurement artifact: `repobrief-call-navigation-scale-index-v1.measurement.json`
Measurement SHA-256: `ddd3b7e3a25d829683d0c75ca8f9f3020463fba9ce90a034db6b7f977b31e5d9`

## Problem

Die drei Call-Navigation-Zugriffe `find_references`, `get_callers` und
`get_callees` lasen und validierten bei jeder Anfrage den vollständigen
Call-Graph erneut. Danach liefen sie erneut linear über sämtliche Call-Zeilen.
Bei einem langlebigen MCP-Prozess wurden somit unveränderte, bereits geprüfte
Artefakte immer wieder geparst, gezählt und durchsucht.

T029 durfte diese Kosten nicht durch eine ungebundene zweite Wahrheit ersetzen.
Deshalb wurden drei Kandidaten mit identischen Abfragen verglichen:

1. der bisherige lineare Scan;
2. ein beim ersten validierten Laden aufgebauter RAM-Index;
3. ein vorab gespeicherter Sidecar-Index, der kryptografisch an die Call-Liste
   gebunden wird.

## Gewählter Vertrag

Der Produktionspfad verwendet einen unveränderlichen RAM-Index mit
Positionslisten. Die Positionslisten verweisen ausschließlich auf bereits
validierte Call- und Symbolzeilen; sie kopieren oder verändern deren Wahrheit
nicht.

Der Cache ist auf zwei Bundles begrenzt. Seine Bindung umfasst:

- SHA-256 des Manifests;
- Artefaktrolle und absoluten Pfad;
- im Manifest deklarierte SHA-256- und Bytewerte;
- Gerät, Inode, Dateigröße sowie Nanosekunden-Mtime und -Ctime.

Beim kalten Laden werden die tatsächlichen Bytes von Call-Graph und Symbolindex
gegen SHA-256 und Bytezahl des Manifests geprüft. Ändert sich eine Quelle, wird
der Cache verworfen und vollständig neu validiert. Auch eine gleich große
Änderung mit künstlich zurückgesetzter Mtime wird über die Ctime erkannt.
Ändert sich eine Quelle während des Ladens, schlägt der Zugriff geschlossen fehl.

## Ergebnisgleichheit
Für beide verpflichtenden Stufen waren die vollständigen linearen,
RAM-indizierten und Sidecar-indizierten Ergebnisobjekte bytegleich:
- synthetische 50.000-Call-Stufe:
  `e63d575bccd2baeeba7c70caf2a65d59eecfc27c9d93751f1baa4522f7d71755`;
- Lenskit-Repositorium mit 54.771 Calls:
  `cd7299bdaa4642e7f1ae88cb30c3a7416ee85ec99346cb59c7d231ab82219c44`.
Auch der kalte und warme MCP-Dreifachaufruf war bytegleich:
`4ff3d69e702d1e9d834b19cea6f2a72afab4bb86c62f5def47ff45879e1f8eac`.
## Messaufbau

Maschine:

- CPython 3.10.12;
- Linux-7.0.11-76070011-generic-x86_64-with-glibc2.35;
- 32 logische CPUs.

Konfiguration:

- 50.000 deterministisch erzeugte Calls;
- Lenskit als repräsentatives reales Repository;
- je 20 Referenz-, 20 Caller- und 20 Callee-Abfragen pro Algorithmus-Batch;
- 7 Wiederholungen für warme Algorithmus-Abfragen;
- 3 Wiederholungen für kalte Ladepfade;
- 10 Wiederholungen für warme MCP-Dreifachaufrufe.

Die realen Lenskit-Fixtures enthalten zwei absichtlich syntaktisch ungültige
Python-Dateien. Beide wurden als Parsefehler sichtbar gezählt und nicht
verschwiegen.

## Messergebnisse
### Synthetische 50.000-Call-Stufe
| Messwert | Linear | RAM-Index | Sidecar |
| --- | ---: | ---: | ---: |
| Warmer Abfrage-Batch, Median | 764,47 ms | 54,98 ms | 56,03 ms |
| Beschleunigung gegenüber linear | 1,00× | 13,91× | 13,64× |
| Kaltes Laden/Aufbauen, Median | 247,95 ms | 397,37 ms | 355,79 ms |
| Indexaufbau | — | 314,06 ms | vorab |
| nach Aufbau gebundener Indexspeicher | — | 7.352.413 Byte | — |
| Spitzenbedarf beim Indexaufbau | — | 13.283.439 Byte | — |
| zusätzliche Bundlegröße | 0 | 0 | 3.989.698 Byte / 13,25 % |
### Lenskit mit 54.771 Calls
| Messwert | Linear | RAM-Index | Sidecar |
| --- | ---: | ---: | ---: |
| Warmer Abfrage-Batch, Median | 978,85 ms | 43,35 ms | 41,73 ms |
| Beschleunigung gegenüber linear | 1,00× | 22,58× | 23,46× |
| Kaltes Laden/Aufbauen, Median | 381,19 ms | 524,88 ms | 540,70 ms |
| Indexaufbau | — | 440,88 ms | vorab |
| nach Aufbau gebundener Indexspeicher | — | 10.606.696 Byte | — |
| Spitzenbedarf beim Indexaufbau | — | 19.589.982 Byte | — |
| zusätzliche Bundlegröße | 0 | 0 | 6.598.947 Byte / 16,90 % |
### Öffentlicher MCP-Pfad auf 50.000 Calls
- erster kalter Dreifachaufruf: 1.642,02 ms;
- kalter Dreifachaufruf, Median: 770,91 ms;
- warmer Dreifachaufruf, Median: 5,65 ms;
- warmer p95: 6,02 ms;
- nach dem ersten kalten Dreifachaufruf gebundener Python-Speicher:
  92.761.368 Byte;
- beim ersten kalten Dreifachaufruf gemessener Python-Peak:
  143.183.769 Byte.
Der hohe erste Peak enthält neben den Indexstrukturen auch das vollständige
synthetische Call-Graph- und Symbolindex-JSON, geparste Python-Objekte,
öffentliche Ergebnisobjekte und `tracemalloc`-Messaufwand. Er ist deshalb nicht
mit dem isolierten Indexaufbau-Peak gleichzusetzen.
## Entscheidung

Der RAM-Index wird gewählt:

- Er beseitigt wiederholte lineare Scans und wiederholte Vollvalidierung.
- Er verändert die öffentlichen Antworten nicht.
- Er vergrößert das Bundle nicht.
- Er ist klein genug, um auf zwei aktive Bundlezustände begrenzt zu werden.
- Er kann nach jeder Quellenänderung vollständig neu aufgebaut werden.

Der lineare Produktionspfad wird verworfen, weil seine Kosten mit jeder Anfrage
erneut proportional zur Call-Anzahl wachsen.

Der Sidecar wird nicht befördert. Er bietet im warmen Zustand praktisch keinen
Vorteil gegenüber dem RAM-Index, vergrößert die gemessenen Bundles aber um
13,25 % bis
16,89 % und würde einen
zusätzlichen Artefaktvertrag schaffen. Seine Implementierung bleibt nur im
Benchmark erhalten, damit diese Entscheidung reproduzierbar überprüft werden
kann.

## Integrität und Regressionen

Tests belegen insbesondere:

- bytegleiche lineare und indizierte Ergebnisse;
- exakte und Teilstring-Suche einschließlich kurzer Suchbegriffe;
- Caller- und Callee-Auswahl über Symbolidentität;
- unveränderliche Positionslisten;
- von Cache-Daten vollständig abgetrennte öffentliche Listen, Wörterbücher und Artefaktmetadaten;
- deterministische und quellgebundene Sidecar-Projektion;
- Cache-Wiederverwendung bei unveränderten Quellen;
- Invalidierung nach Call-Graph- oder Symbolindexänderung;
- Ablehnung von SHA-256- oder Bytezahlabweichungen;
- Erkennung gleich großer Änderungen trotz zurückgesetzter Mtime;
- identische kalte und warme öffentliche Antworten;
- LRU-Begrenzung auf zwei Bundles;
- MCP-Transport- und Fehlerverträge.

## Reproduktion

```bash
python -m merger.lenskit.scripts.bench_call_navigation \
  --repo . \
  --output /tmp/repobrief-call-navigation-scale-index-v1.json
```

Der Standardlauf verwendet zwingend die 50.000-Call-Stufe. Kleinere Werte sind
nur für schnelle Vertragstests vorgesehen und tragen
`fixed_acceptance_tier=false`.

## Nicht belegt

Dieser Abschluss belegt nicht:

- identische Laufzeiten auf anderen Maschinen;
- identische Beschleunigung in jedem Repository;
- vollständige statische oder dynamische Call-Graph-Auflösung;
- Laufzeiterreichbarkeit oder dynamischen Dispatch;
- dass zwei Cache-Einträge für jeden zukünftigen Dienst optimal sind;
- dass ein persistierter Index nie sinnvoll werden kann;
- allgemeine Produkt-, Review- oder Merge-Reife außerhalb des geprüften Diffs.

## Nächste Aufgabe

`RPU-V1-T030` darf die Producer- und Resolverstruktur refaktorieren und
systematische AST-Varianten generieren. Es soll die hier eingeführte
Call-Navigation-Indexierung nicht mit einer neuen Resolverwahrheit vermischen.
