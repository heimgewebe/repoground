# Lenskit CLI Operational Blueprint

Stand: 2026-05-27

## 1. Zweck

Dieser Blueprint definiert, wie Lenskit über CLI betrieben wird.
Er verhindert die Fehlinterpretation: Ein fehlendes globales `lenskit`-Kommando im `PATH` bedeutet **nicht**, dass die Modul-CLI nicht funktioniert.

## 2. CLI-Oberflächen

Die folgenden Modul-Aufrufe sind die maßgeblichen CLI-Oberflächen:

```bash
python -m merger.lenskit.cli --help
python -m merger.lenskit.cli.main --help
python -m merger.lenskit.cli.rlens --help
python -m merger.lenskit.cli.main rlens-client --help
```

Voraussetzung: Die Befehle werden aus einem Kontext ausgeführt, in dem das Paket importierbar ist
(z.B. Repo-Root, aktivierte Projektumgebung, editable install oder passend gesetztes `PYTHONPATH`).

## 3. Aktueller bekannter Status

Stand: 2026-05-27.

Dieser Abschnitt ist eine lokale Momentaufnahme, kein dauerhafter Contract. Nach Wechsel von Host,
Python-Umgebung, Shell oder Installation ist §7 erneut auszuführen. Normativ bleibt die Trennung aus
§4: Modul-CLI-Readiness, Shell-Wrapper-Readiness, Service-Readiness und WebUI-Readiness sind
verschiedene Zustände.

- `python -m merger.lenskit.cli --help`: verifiziert
- `python -m merger.lenskit.cli.main --help`: verifiziert
- `python -m merger.lenskit.cli.rlens --help`: verifiziert
- `python -m merger.lenskit.cli.main rlens-client --help`: verifiziert
- globales `rlens`: vorhanden unter `/home/alex/.local/bin/rlens`
- globales `lenskit`: nicht vorhanden
- globale Wrapper-Aussagen beziehen sich auf den geprüften lokalen User-Kontext.

## 4. Readiness-Modell

### CLI readiness

Die Hilfe-/Command-Surface der Modul-CLI ist erreichbar.

### Shell wrapper readiness

Separater Komfortstatus.
Fehlt `lenskit` im `PATH`, ist das ein Packaging-/Convenience-Gap, kein CLI-Funktionsfehler.

### Service readiness

Separat von CLI readiness.
`rlens-client health` kann fehlschlagen, wenn kein rLens-Service läuft oder Base-URL/Token fehlen.

### WebUI readiness

Nicht aus CLI-Help ableitbar.

## 5. Nicht-Ziele

- keinen `lenskit`-Wrapper anlegen
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

```bash
python -m merger.lenskit.cli --help
python -m merger.lenskit.cli.main --help
python -m merger.lenskit.cli.rlens --help
python -m merger.lenskit.cli.main rlens-client --help
command -v lenskit || true
command -v rlens || true
```
