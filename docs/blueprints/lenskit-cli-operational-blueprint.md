# Lenskit CLI Operational Blueprint

Stand: 2026-05-27

## 1. Zweck

Dieser Blueprint definiert, wie Lenskit über CLI betrieben wird.
Er verhindert die Fehlinterpretation: Ein fehlendes globales `lenskit`-Kommando im `PATH` bedeutet **nicht**, dass die Modul-CLI nicht funktioniert.


## 1.1 Beziehung zu bestehender rLens-Client-Doku

Dieses Dokument ist ein operativer Readiness-Blueprint. Es ersetzt nicht
`docs/blueprints/rlens-cli-client-blueprint.md`.

- `docs/blueprints/rlens-cli-client-blueprint.md` beschreibt Client-API,
  Sicherheitsmodell, Profile und rLens-Client-Produktpfad.
- Dieses Dokument beschreibt, welche lokalen CLI-/Wrapper-/Service-Zustände
  nicht miteinander verwechselt werden dürfen.

## 2. CLI-Oberflächen

### Core / Module CLI

Die folgenden Modul-Aufrufe sind die maßgeblichen Core-CLI-Oberflächen:

```bash
python -m merger.lenskit.cli --help
python -m merger.lenskit.cli.main --help
python -m merger.lenskit.cli.main rlens-client --help
```

`rlens-client` ist die CLI-Client-Oberfläche.

### Optionaler rLens-Service-Launcher

```bash
python -m merger.lenskit.cli.rlens --help
```

`cli.rlens` ist der rLens-Service-Launcher und darf optional/serviceabhängig sein.
Ein Fehlschlag von `python -m merger.lenskit.cli.rlens --help` wegen fehlender Service-Dependencies
ist kein Gegenbeweis gegen Core-CLI-Readiness.

Voraussetzung: Die Befehle werden aus einem Kontext ausgeführt, in dem das Paket importierbar ist
(z.B. Repo-Root, aktivierte Projektumgebung, editable install oder passend gesetztes `PYTHONPATH`).

## 3. Aktueller bekannter Status

Stand: 2026-05-27.

Dieser Abschnitt ist eine lokale Momentaufnahme, kein dauerhafter Contract.
Die lokalen Wrapper-Angaben sind kein Contract und kein CI-Nachweis.
Sie dienen nur dazu, den geprüften Host-/User-Zustand nicht mit Modul-CLI-Readiness
zu verwechseln.
Nach Wechsel von Host, Python-Umgebung, Shell oder Installation ist §7 erneut auszuführen. Normativ bleibt die Trennung aus
§4: Modul-CLI-Readiness, Shell-Wrapper-Readiness, rLens-Service-Launcher-Readiness,
Service-Readiness und WebUI-Readiness sind verschiedene Zustände.

- Core / Module CLI:
  - `python -m merger.lenskit.cli --help`: verifiziert
  - `python -m merger.lenskit.cli.main --help`: verifiziert
  - `python -m merger.lenskit.cli.main rlens-client --help`: verifiziert
- rLens service launcher:
  - `python -m merger.lenskit.cli.rlens --help`: lokal verifiziert, optional/serviceabhängig
- globales `rlens`: vorhanden unter `/home/alex/.local/bin/rlens`
- globales `lenskit`: nicht vorhanden
- globale Wrapper-Aussagen beziehen sich auf den geprüften lokalen User-Kontext.

## 4. Readiness-Modell

### CLI readiness

CLI readiness meint Core / Module CLI.
Die Hilfe-/Command-Surface der Core-CLI ist erreichbar. Der serviceabhängige rLens-Launcher ist dafür
nicht zwingend erforderlich.

### rLens service launcher readiness

Separat von Core-CLI readiness.
Der Help-Aufruf prüft die Launcher-Importierbarkeit inklusive service-naher Dependencies,
aber nicht, ob der rLens-Service läuft.

### Shell wrapper readiness

Separater Komfortstatus.
Fehlt `lenskit` im `PATH`, ist das ein Packaging-/Convenience-Gap, kein CLI-Funktionsfehler.

### Service readiness

Separat von CLI readiness.
`rlens-client health` kann fehlschlagen, wenn kein rLens-Service läuft oder Base-URL/Token fehlen.

### WebUI readiness

Nicht aus CLI-Help ableitbar.

## 5. Nicht-Ziele

- keinen globalen `lenskit`-Wrapper anlegen
- keine automatische Installation
- keine Aussage, dass rLens-Service läuft
- keine Aussage, dass WebUI-Readiness verifiziert ist
- keine vollständige CLI-Referenz schreiben
- keine Runtime-Proof-Datei anlegen, außer ausdrücklich nötig

## 6. Optionaler späterer Promotion-Pfad für globales `lenskit`

Ein globaler `lenskit`-Wrapper darf später ergänzt werden, wenn:

- er auf die beabsichtigte Python-Umgebung zeigt
- er user-lokal bleibt
- `lenskit --help` funktional der Modul-CLI entspricht
- Drift zwischen Wrapper und Modulaufruf prüfbar bleibt

## 7. Verifikationskommandos

Core CLI checks:

```bash
python -m merger.lenskit.cli --help
python -m merger.lenskit.cli.main --help
python -m merger.lenskit.cli.main rlens-client --help
```

Optional service launcher / wrapper checks:

```bash
python -m merger.lenskit.cli.rlens --help
command -v lenskit || true
command -v rlens || true
```
