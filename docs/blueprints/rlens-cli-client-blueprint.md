# rLens CLI Client Blueprint

## Status

Blueprint / Zielarchitektur / Vor-Implementierungsdokument.

Diese Datei beschreibt den geplanten rLens CLI Client. Sie implementiert nichts und behauptet nicht, dass Remote-Zugriff bereits funktioniert.

## These

Ein rLens CLI Client soll rLens auf Heim-PC und Heimserver bedienbar machen, ohne WebUI-Zwang und ohne unsichere Netzöffnung.

## Antithese

Ein CLI, das nur `http://127.0.0.1:8787` kennt, funktioniert nur auf dem Host, auf dem rLens selbst läuft. Auf dem Heimserver meint `127.0.0.1` den Heimserver, nicht den Heim-PC.

Außerdem: `merger/lenskit/cli/rlens.py` ist bereits vorhanden und trägt die Bezeichnung „rLens Service Entry Point (Canonical)". Dieses Modul startet den Service — es ist kein HTTP-Client. Agenten dürfen den Launcher nicht still zu einem HTTP-Client umdeuten.

## Synthese

Das CLI wird als HTTP-Client mit expliziter Base-URL, Token-Modell und Host-Profilen geplant. Default bleibt lokal und sicher. Remote-Betrieb ist ein bewusst aktivierter Modus, kein impliziter Nebeneffekt. Der Launcher bleibt unangetastet.

## Abgrenzung zum bestehenden Launcher

| Modul | Rolle | Gegenstand dieses Blueprints |
| --- | --- | --- |
| `merger/lenskit/cli/rlens.py` | rLens Service Entry Point / Launcher — startet den Service-Prozess | Nein |
| geplanter CLI Client | HTTP-Client gegen laufende rLens HTTP-API | Ja — Zielarchitektur, keine Implementierung |

Der geplante CLI Client darf den Launcher nicht ersetzen, umbenennen oder neu interpretieren.

## Ziel

- Read-only CLI Client für die bestehende rLens HTTP-API.
- Nutzbar auf Heim-PC und Heimserver.
- Geeignet für Diagnose, Artefaktprüfung, Jobsicht und spätere Automation.
- Kein Ersatz für den bestehenden Service-Launcher.
- Kein Server-Startkommando im MVP.
- Keine CI-Erzwingung im Blueprint-PR.

## Nicht-Ziele

- Keine neue Service-API.
- Kein Port-Forwarding.
- Kein Internet-Ingress.
- Keine Secrets im Repo.
- Keine Vermischung mit `merger/lenskit/cli/rlens.py`, solange dieses Modul Service Entry Point bleibt.

## Maschinenmodell

| Maschine | Rolle | Möglicher rLens-Modus | CLI-Folge |
| --- | --- | --- | --- |
| Heim-PC | Interaction Layer | rLens lokal | Default `http://127.0.0.1:8787` sinnvoll |
| Heimserver | Service Layer | rLens lokal oder Client zu anderem Host | Base-URL muss explizit gesetzt werden |
| iPad / Access Layer | Bedienoberfläche | kein primärer Service-Host | später optional nur via SSH/Blink/Browser |

## Verbindungsmodell

### Profil `local`

- `RLENS_BASE_URL=http://127.0.0.1:8787`
- gilt nur für den Host, auf dem rLens läuft

### Profil `heim-pc`

- `RLENS_BASE_URL=http://heim-pc:8787` oder Tailnet-Name
- funktioniert nur, wenn rLens nicht ausschließlich an Loopback gebunden ist oder ein Tunnel existiert
- Blueprint darf Remote-Erreichbarkeit nicht behaupten

### Profil `heimserver`

- lokal: `http://127.0.0.1:8787`, falls rLens auf Heimserver läuft
- remote: explizite Base-URL zu Heim-PC oder anderem rLens-Host

## Sicherheitsmodell

- Default bleibt loopback.
- Kein Port-Forwarding.
- Kein öffentlicher Bind ohne Auth.
- Token bevorzugt über `Authorization: Bearer`.
- Query-Token nur, wenn bestehende API es für Kompatibilität benötigt.
- Token niemals in Logs, Debug-Ausgaben oder Exceptions.
- Remote-Betrieb nur über LAN/Tailscale/SSH-Tunnel und nur nach expliziter Entscheidung.
- `--debug` muss Token redigieren.

## Konfigurationsmodell

Priorität Base-URL:

1. `--base-url`
2. `RLENS_BASE_URL`
3. optional später Profil-Config
4. Default `http://127.0.0.1:8787`

Priorität Token:

1. `--token`
2. `RLENS_TOKEN`
3. optional später Secret-Datei außerhalb des Repos
4. kein Token im Repo

Optionale spätere Profile:

```text
~/.config/lenskit/rlens-profiles.json
```

## MVP-Kommandos read-only

| Kommando | Route | Ausgabe | JSON | Status |
| --- | --- | --- | --- | --- |
| `lenskit rlens-client health` | `GET /api/health` | Status, Version, Hub, Auth | ja | MVP |
| `lenskit rlens-client artifacts` | `GET /api/artifacts` | Artefaktliste | ja | MVP |
| `lenskit rlens-client latest` | `GET /api/artifacts/latest` | neuestes Artefakt | ja | MVP |
| `lenskit rlens-client jobs` | noch zu prüfen | Jobliste | ja | MVP, falls API vorhanden |
| `lenskit rlens-client job JOB_ID` | noch zu prüfen | Jobdetails | ja | MVP, falls API vorhanden |
| `lenskit rlens-client logs JOB_ID` | `GET /api/jobs/{job_id}/logs` | SSE-Logs bis `event: end` | optional | später (PR C) |

## Namensentscheidung

Nicht `lenskit rlens`, weil dieser Name bereits semantisch nahe am Service-Launcher liegt.

Bevorzugt:

```text
lenskit rlens-client ...
```

Alternativen:

```text
lenskit service ...
lenskit rlensctl ...
```

Entscheidung offen bis Implementierungs-PR.

## Exit-Codes

| Code | Bedeutung |
| ---: | --- |
| 0 | Erfolg |
| 1 | Remote/API/HTTP/Netzwerkfehler |
| 2 | CLI/Input/Config-Fehler |
| 3 | Auth-Fehler, optional |
| 4 | SSE/Streaming-Protokollfehler, optional |

## Heim-PC / Heimserver Beispiele

Heim-PC lokal:

```bash
RLENS_BASE_URL=http://127.0.0.1:8787 lenskit rlens-client health --json
```

Heimserver mit eigenem lokalem rLens:

```bash
RLENS_BASE_URL=http://127.0.0.1:8787 lenskit rlens-client health --json
```

Heimserver als Client zu Heim-PC (nur wenn rLens auf Heim-PC erreichbar gemacht wurde oder ein Tunnel existiert):

```bash
RLENS_BASE_URL=http://heim-pc:8787 lenskit rlens-client health --json
```

## Offene Entscheidungsfragen

1. Soll rLens auf Heimserver selbst laufen?
2. Soll Heimserver nur Client zu Heim-PC sein?
3. Soll Remote-Zugriff über Tailscale, LAN-DNS oder SSH-Tunnel laufen?
4. Bleibt `RLENS_BASE_URL=http://127.0.0.1:8787` der Client-Default? (`RLENS_HOST` bleibt Launcher-/Service-Konfiguration und ist nicht die Client-Base-URL.)
5. Soll es host-spezifische Tokens geben?
6. Wie heißt das CLI endgültig: `rlens-client`, `service`, `rlensctl`?
7. Welche Job-Listen-/Job-Detail-Routen sind API-stabil dokumentiert?

## Implementierungsplan

### PR A: Blueprint und Roadmap

- diese Datei
- Roadmap-Eintrag
- Test-Matrix-Hinweis
- AGENTS-Hinweis
- kein Code

### PR B: Read-only Client-Basis

- HTTP-Client ohne neue Dependency
- `health`, `artifacts`, `latest`
- Token-Redaction-Test
- Base-URL-Resolution-Test

### PR C: SSE Logs

- `logs JOB_ID`
- korrektes Ende bei `event: end`
- Reconnect optional später

### PR D: Host-Profile

- optionale Profil-Config
- Heim-PC/Heimserver-Beispiele
- kein Secret im Repo

### PR E: Mutierende Kommandos

- `run`
- `cancel`
- nur nach API-/Sicherheitsreview

## Akzeptanzkriterien für PR B

- `--base-url` überschreibt Env.
- `RLENS_BASE_URL` überschreibt Default.
- Default ist `http://127.0.0.1:8787`.
- Token wird als Bearer Header gesendet.
- Token erscheint nicht in Fehlerausgaben.
- Netzwerkfehler liefern Exit-Code 1.
- Config/Input-Fehler liefern Exit-Code 2.
- Tests nutzen keine echte lokale rLens-Instanz.
