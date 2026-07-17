---
status: active
---

# RepoGround CLI Operational Blueprint

Stand: 2026-07-17

## Zweck

Dieser Blueprint trennt die verschiedenen RepoGround-Betriebsoberflächen. Ein
fehlender globaler Wrapper, ein nicht laufender Dienst oder ein nicht
konfigurierter HTTP-Client darf nicht fälschlich als Ausfall der Modul-CLI
interpretiert werden.

## Kanonische Oberflächen

### Modul-CLI

Die kanonische Moduloberfläche ist:

```bash
python -m merger.repoground --help
python -m merger.repoground build --help
python -m merger.repoground query --help
python -m merger.repoground graph --help
python -m merger.repoground ground --help
python -m merger.repoground serve --help
python -m merger.repoground mcp --help
python -m merger.repoground service-client --help
```

Der installierbare Komfortstarter ist `repoground`. Seine Abwesenheit im
jeweiligen `PATH` ist ein Packaging- oder Installationszustand, kein Gegenbeweis
zur Modul-CLI.

### Service-Launcher

`merger.repoground.cli.serve` startet den lokalen RepoGround-Dienst. Der
Launcher ist kein HTTP-Client. Seine Importierbarkeit kann von optionalen
Service-Abhängigkeiten abhängen.

### Service-Client

`repoground service-client` ist der kanonische HTTP-Client gegen einen bereits
laufenden RepoGround-Dienst. `rlens-client` bleibt während RepoGround 3.x ein
warnender Alias derselben Implementierung.

Der ältere Plan mit Implementierungshistorie bleibt unter
`docs/blueprints/rlens-cli-client-blueprint.md` erhalten. Der alte Dateiname und
darin dokumentierte frühere Befehle sind historische beziehungsweise
kompatible 2.x/3.x-Oberflächen, nicht die aktuelle Benennung.

## Readiness-Modell

### Modul-CLI-Readiness

Die Parser- und Hilfsoberfläche der Core-CLI ist importierbar und erreichbar.
Dies sagt nichts über einen laufenden Dienst, Netzwerkzugriff oder globale
Installation aus.

### Wrapper-Readiness

Die Verfügbarkeit des Befehls `repoground` im `PATH` ist host- und
benutzerabhängig und kein dauerhafter Repository-Contract. Sie wird mit
`command -v repoground` separat geprüft. Fehlt der Wrapper, bleibt die
Modul-CLI über `python -m merger.repoground` verwendbar.

### Service-Launcher-Readiness

Der Launcher kann importiert und gestartet werden. Daraus folgt noch nicht,
dass der Dienst bereit, erreichbar oder korrekt konfiguriert ist.

### Service-Client-Readiness

`repoground service-client health` benötigt einen erreichbaren Dienst sowie die
passende Base-URL und gegebenenfalls ein Token. Ein Verbindungsfehler ist kein
Core-CLI-Fehler.

### WebUI-Readiness

WebUI-Readiness ist weder aus CLI-Hilfe noch aus einem erfolgreichen
Service-Client-Import ableitbar.

## Kompatibilitätsvertrag

Während RepoGround 3.x dürfen alte Einstiege weiter bestehen, wenn sie:

1. eine Deprecation-Warnung ausgeben,
2. zur kanonischen Implementierung delegieren,
3. keine eigenen Defaults oder einen zweiten Codepfad besitzen,
4. persistierte v1/v2-Kennungen nicht still umdeuten.

Dies gilt insbesondere für `rlens-client`, `repobrief`, `rlens`, `repolens` und
`merger.lenskit`.

## Verifikation

```bash
python -m merger.repoground --help
python -m merger.repoground service-client --help
python -m merger.repoground rlens-client --help
repoground --help
```

Zusätzlich müssen die CLI-, Alias-, Importidentitäts- und
Namenshygiene-Regressionstests grün sein.

## Nicht-Ziele

Dieser Blueprint begründet nicht:

- dass der RepoGround-Dienst läuft,
- dass eine Remote-Verbindung erlaubt oder erreichbar ist,
- dass WebUI-Readiness besteht,
- dass jeder Host einen globalen Wrapper besitzt,
- dass Legacy-Delegates entfernt werden dürfen,
- dass ein erfolgreicher Help-Aufruf Produkt- oder Release-Reife beweist.
