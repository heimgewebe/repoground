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
| `lenskit rlens-client health` | `GET /api/health` | Status, Version, Hub, Auth | ja | **umgesetzt (PR B)** |
| `lenskit rlens-client artifacts` | `GET /api/artifacts` | Artefaktliste | ja | **umgesetzt (PR B)** |
| `lenskit rlens-client latest --repo REPO` | `GET /api/artifacts/latest` | neuestes Artefakt | ja | **umgesetzt (PR B)** |
| `lenskit rlens-client jobs` | `GET /api/jobs` | Jobliste | ja | **umgesetzt (PR C)** |
| `lenskit rlens-client job JOB_ID` | `GET /api/jobs/{job_id}` | Jobdetails | ja | **umgesetzt (PR C)** |
| `lenskit rlens-client logs JOB_ID` | `GET /api/jobs/{job_id}/logs` | SSE-Logs bis `event: end` | optional | **umgesetzt (PR C)** |
| `lenskit rlens-client profiles` | — (lokal) | konfigurierte Host-Profile | ja | **umgesetzt (PR D)** |

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

### PR B: Read-only Client-Basis — teilweise umgesetzt

Umgesetzt:

- `merger/lenskit/cli/cmd_rlens_client.py` — HTTP-Client ohne neue Dependency
- Commands: `health`, `artifacts`, `latest --repo REPO`
- Base-URL-Priorität: `--base-url` > `RLENS_BASE_URL` > `http://127.0.0.1:8787`
- Bearer-Token-Auth: `--token` > `RLENS_TOKEN`; Token nie als Query-Parameter
- Token-Redaction in allen Fehlerausgaben
- Tests: `merger/lenskit/tests/test_cli_rlens_client.py` (44 Tests, kein echter Server)

Offen (folgende PRs):

- `run`, `cancel` (PR E) — nach API-/Sicherheitsreview
- Heim-PC/Heimserver-Betriebsentscheidung (Remote-Erreichbarkeit ist nicht behauptet)
- Automatischer SSE-Reconnect (optional)

### PR C: Jobs / Job / SSE Logs — umgesetzt

Umgesetzt:

- `jobs` (`GET /api/jobs`, optional `--status`, `--limit`)
- `job JOB_ID` (`GET /api/jobs/{job_id}`, `job_id` URL-encoded im Pfadsegment)
- `logs JOB_ID` (`GET /api/jobs/{job_id}/logs`, SSE-Stream)
  - korrektes Ende bei `event: end`
  - optional `--last-id` als Query-Parameter (`last_id=…`)
  - optional `--timeout` (Per-Read-Timeout, Default 300 s)
  - SSE-Parser unterstützt `id:`/`event:`/`data:` (Multiline-Data) und ignoriert Kommentar-Zeilen `:…`
  - Token-Redaktion auch in Stream-Daten

Sicherheitsinvarianten (durch Tests abgesichert):

- Token nie als Query-Parameter (auch nicht bei Logs/SSE)
- Token-Redaktion bei HTTP-Fehlern und in Stream-Ausgaben
- `Accept: text/event-stream` für Logs gesetzt
- `job_id` wird URL-encodiert; Pfadtraversal-Versuche fallen auf Server-Validierung

Offen (Reconnect):

- Automatischer Resume nach Stream-Abbruch ist nicht im MVP. Manueller Resume via `--last-id`.

### PR D: Host-Profile — umgesetzt

Umgesetzt:

- `--profile NAME` für alle `rlens-client`-Subkommandos
- `RLENS_PROFILE`-Env-Variable als Selektor
- Profil-Config: `$LENSKIT_RLENS_PROFILES` > `$XDG_CONFIG_HOME/lenskit/rlens-profiles.json` > `~/.config/lenskit/rlens-profiles.json`
- Schema:
  - `default_profile`: optionaler Profilname (string)
  - `profiles[NAME].base_url`: HTTP/HTTPS-URL (string)
  - `profiles[NAME].token_env`: Name einer Env-Variable, deren Wert als Bearer Token verwendet wird (string)
- Priorität Base-URL: `--base-url` > `RLENS_BASE_URL` > Profil-`base_url` (selektiert via `--profile` > `RLENS_PROFILE` > `default_profile`) > Default `http://127.0.0.1:8787`
- Priorität Token: `--token` > `RLENS_TOKEN` > Wert der Env-Variable aus Profil-`token_env`
- `lenskit rlens-client profiles [--json]`: listet Profile (redigiert; nur `base_url` und `token_env`-Name) und validiert Config strikt (unknown/forbidden keys -> `config_error`)
- Sobald eine Profil-Config-Datei existiert, wird sie bei `rlens-client`-Aufrufen strikt validiert (auch ohne explizite Profilselektion).
- Sicherheitsinvarianten (durch Tests abgesichert):
  - Existierende Profil-Config wird vor Netzwerkkommandos strikt validiert, auch bei `--token`/`RLENS_TOKEN`/`--base-url`/`RLENS_BASE_URL`-Overrides.
  - `token`/`rlens_token`/`secret`-Felder im Profil sind verboten -> `config_error` (Exit 2)
  - unbekannte Profil-Schlüssel -> `config_error`
  - Unbekanntes Profil -> `config_error`
  - Explizit angefordertes Profil ohne Config -> `config_error`
  - Explizit angefordertes Profil wird nie still ignoriert, auch nicht bei `--base-url`/`RLENS_BASE_URL`-Override -> `config_error`
  - Kein Profil/keine Config -> stiller Fallback auf Default
  - Profile-Listing gibt nur `base_url` und `token_env`-Name zurück, niemals Werte
- Tests: `merger/lenskit/tests/test_cli_rlens_client.py` (74 Tests, davon 29 für PR D)

Heim-PC/Heimserver-Betriebsentscheidung bleibt offen — der Profile-Mechanismus erleichtert nur die Konfiguration, behauptet keine Erreichbarkeit.

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
