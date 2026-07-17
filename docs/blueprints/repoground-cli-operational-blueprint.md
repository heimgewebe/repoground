# RepoGround CLI Operational Blueprint

Stand: 2026-05-27

## 1. Zweck

Dieser Blueprint definiert, wie RepoGround über CLI betrieben wird.
Er verhindert die Fehlinterpretation: Ein fehlendes globales `repoground`-Kommando im `PATH` bedeutet **nicht**, dass die Modul-CLI nicht funktioniert.


## 1.1 Beziehung zu bestehender RepoGround-Client-Doku

Dieses Dokument ist ein operativer Readiness-Blueprint. Es ersetzt nicht
`docs/blueprints/repoground-cli-client-blueprint.md`.

- `docs/blueprints/repoground-cli-client-blueprint.md` beschreibt Client-API,
  Sicherheitsmodell, Profile und RepoGround-Client-Produktpfad.
- Dieses Dokument beschreibt, welche lokalen CLI-/Wrapper-/Service-Zustände
  nicht miteinander verwechselt werden dürfen.

## 2. CLI-Oberflächen

### Core / Module CLI

Die folgenden Modul-Aufrufe sind die maßgeblichen Core-CLI-Oberflächen:

```bash
python -m merger.repoground.cli --help
python -m merger.repoground.cli.main --help
python -m merger.repoground.cli.main repoground-client --help
```

`repoground-client` ist die CLI-Client-Oberfläche.

### Optionaler RepoGround-Service-Launcher

```bash
python -m merger.repoground.cli.serve --help
```

`cli.repoground` ist der RepoGround-Service-Launcher und darf optional/serviceabhängig sein.
Ein Fehlschlag von `python -m merger.repoground.cli.serve --help` wegen fehlender Service-Dependencies
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
§4: Modul-CLI-Readiness, Shell-Wrapper-Readiness, RepoGround-Service-Launcher-Readiness,
Service-Readiness und WebUI-Readiness sind verschiedene Zustände.

- Core / Module CLI:
  - `python -m merger.repoground.cli --help`: verifiziert
  - `python -m merger.repoground.cli.main --help`: verifiziert
  - `python -m merger.repoground.cli.main repoground-client --help`: verifiziert
- RepoGround service launcher:
  - `python -m merger.repoground.cli.serve --help`: lokal verifiziert, optional/serviceabhängig
- globales `repoground`: vorhanden unter `/home/alex/.local/bin/repoground`
- globales `repoground`: nicht vorhanden
- globale Wrapper-Aussagen beziehen sich auf den geprüften lokalen User-Kontext.

## 4. Readiness-Modell

### CLI readiness

CLI readiness meint Core / Module CLI.
Die Hilfe-/Command-Surface der Core-CLI ist erreichbar. Der serviceabhängige RepoGround-Launcher ist dafür
nicht zwingend erforderlich.

### RepoGround service launcher readiness

Separat von Core-CLI readiness.
Der Help-Aufruf prüft die Launcher-Importierbarkeit inklusive service-naher Dependencies,
aber nicht, ob der RepoGround-Service läuft.

### Shell wrapper readiness

Separater Komfortstatus.
Fehlt `repoground` im `PATH`, ist das ein Packaging-/Convenience-Gap, kein CLI-Funktionsfehler.

### Service readiness

Separat von CLI readiness.
`repoground-client health` kann fehlschlagen, wenn kein RepoGround-Service läuft oder Base-URL/Token fehlen.

### WebUI readiness

Nicht aus CLI-Help ableitbar.

## 5. Nicht-Ziele

- keinen globalen `repoground`-Wrapper anlegen
- keine automatische Installation
- keine Aussage, dass RepoGround-Service läuft
- keine Aussage, dass WebUI-Readiness verifiziert ist
- keine vollständige CLI-Referenz schreiben
- keine Runtime-Proof-Datei anlegen, außer ausdrücklich nötig

## 6. Optionaler späterer Promotion-Pfad für globales `repoground`

Ein globaler `repoground`-Wrapper darf später ergänzt werden, wenn:

- er auf die beabsichtigte Python-Umgebung zeigt
- er user-lokal bleibt
- `repoground --help` funktional der Modul-CLI entspricht
- Drift zwischen Wrapper und Modulaufruf prüfbar bleibt

## 7. Verifikationskommandos

Core CLI checks:

```bash
python -m merger.repoground.cli --help
python -m merger.repoground.cli.main --help
python -m merger.repoground.cli.main repoground-client --help
```

Optional service launcher / wrapper checks:

```bash
python -m merger.repoground.cli.serve --help
command -v repoground || true
command -v repoground || true
```
