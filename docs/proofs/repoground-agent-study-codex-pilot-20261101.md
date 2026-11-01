# RepoGround – erster realer Codex-A/B/C-Pilot (1. November 2026)

**Messart:** echte, revisionsgebundene Agentensitzungen mit dem unveränderten
frozen Taskset, keine Simulation und keine Extrapolation aus
Direktabfrage-Benchmarks. **Ergebnis:** `not_established` – ein selektiver
Agentennutzen ist bislang nicht nachgewiesen.

## Versuchsbindung

| Dimension | Tatsächlicher Wert |
| --- | --- |
| Run-ID | `study-20261101-codex-r3` |
| Taskset-SHA256 | `c09d2ed62456b1ad385f82e906be38ffc2a6ba02205b535d0ef4935ba9c59980` |
| `protocol_key` | `7bd39c8bbb7f5e5f60e8aee2005a6b856057e56182a2788ff7a5479d77e70ab7` |
| Provider / Modell | Codex CLI, `openai-codex-cli`, `gpt-5.6-sol` |
| Modellkonfiguration | `model_reasoning_effort=medium`; Temperatur nicht als unterstützter Parameter behauptet |
| Runnerkennung | `codex-jsonl-study-v1-0232ec6c3a4880f8-codex-cli-0.164.0` |
| Runner-Datei-SHA256 | `0232ec6c3a4880f8ca0b7e832dcb4174aa94c604b2192126e6f19db08bcaf3d8` |
| Git-Revision des Originalrunners | `e78b2c42a43583837e78194c395a109972fe281d`, Folge-PR [#1386](https://github.com/heimgewebe/repoground/pull/1386) |
| Prompt-/Toolvertrag | `codex-study-prompt-v1`, `codex-study-readonly-v1-mcp-ad8dbc2577601bc2` |
| Host / Cachepolicy | `heim-pc-nixos26.05-x86_64` / `controlled` |
| Quelle und Wiederholungen | sechs vorregistrierte Pilotaufgaben × drei Arme × zwei Wiederholungen |
| Reale abgeschlossene Versuche | 36 von 36, alle mit gültigem Receipt und hashgebundenem Rohtrace |
| Provider-/Antwortstatus | 33 `success`, 3 `failed` wegen ungültiger strukturierter Agentenantwort |
| Unabhängige semantische Antwortbewertungen | **0**; keine als korrekt zertifizierte Antwort |

**Eingefrorene Quellen** (jeweils tatsächliche Git-Revision; keine
aktuelle `main`-Behauptung):

| Repository | Source-SHA | Manifest-SHA256 |
| --- | --- | --- |
| RepoGround | `0fe8e5fd972c69b0d816b6bf124e10e6f5a43112` | `157afedc73e220fa1f3b415b2e93725ef0ce19d2977530f97aab7d56a15a730c` |
| Grabowski | `3fbe93d2f4c7a99c3c1aaf2c35952bac3541d98f` | `e65acfc1ed101a86fecfb7bf7cddf35bf71a63fe72030ad367e3fdcd2cffaebd` |
| Commonthing | `8dbc8c53ea7f26e218d419ac401eef44b29f9333` | `a77c76ee1901e9fad4e3859d3e64135804d3c75a5a903eb9a565fbc16143ca90` |

Alle drei Snapshot-Manifeste waren an den identischen
Generator-Commit `0fe8e5fd972c69b0d816b6bf124e10e6f5a43112`
sowie einen passenden Health-PASS- und Quellenbeleg gebunden.

## Tatsächlich gemessene A/B/C-Zahlen

Alle Zeit-Mittelwerte in dieser Tabelle berücksichtigen **je zwölf
reale Versuche einschließlich der drei fehlgeschlagenen Agentenantworten**.
Provider-Tokens sind tatsächlich von Codex gemeldet, keine
Kostenumrechnung.

| Kennzahl | A: nur Git | B: RepoGround verpflichtend | C: RepoGround selektiv |
| --- | ---: | ---: | ---: |
| Gültige Receipts | 12/12 | 12/12 | 12/12 |
| Erfolgreiche Agentenantworten im Formatvertrag | 10/12 | 11/12 | 12/12 |
| Mittelwert gesamte Aufgabe | 22,982 s | 31,047 s | 24,276 s |
| Median gesamte Aufgabe | 21,382 s | 29,495 s | 19,716 s |
| Gemeldete Input-Tokens (gesamt) | 1.571.020 | 2.796.803 | 2.133.219 |
| Gemeldete Output-Tokens (gesamt) | 20.428 | 24.874 | 22.366 |
| Gemeldete Cache-Input-Tokens | 1.326.976 | 2.473.728 | 1.868.160 |
| Tatsächliche RepoGround-MCP-Aufrufe | 0 | 41 | **0** |
| Strukturelle Übereinstimmung mit vorregistriertem Outcome **und** Goldpfaden | 10/12 | 10/12 | **7/12** |

Die letzte Zeile ist eine **mechanische** Prüfung von
Antwortstatus, Pflichtpfaden und erlaubten Pfaden.
Sie prüft **nicht** die semantische Richtigkeit der Erklärung.
Eine formatgültige Antwort ist nicht automatisch sachlich korrekt.

**Gepaarte Rohzeitdifferenzen** über alle zwölf Fall×Wiederholungs-Paare,
einschließlich der Fehler (noch kein qualitätsbereinigter Wirksamkeitsvergleich):

- **B minus A:** im Mittel **+8,065 s**; Median **+9,158 s**;
  in **10/12** Paaren langsamer. Gesamt-Input-Tokens um rund
  **78 %** höher.
- **C minus A:** im Mittel **+1,294 s**; Median **+2,214 s**;
  in **8/12** Paaren langsamer. Gesamt-Input-Tokens um rund
  **36 %** höher.
- **C nutzte RepoGround in keinem der zwölf Läufe.** Der selektive
  Arm verhielt sich somit in der Werkzeugwahl wie Git-only, erzielte
  aber nicht dieselben Antworten und Kosten. Es wäre falsch,
  aus `C` einen erfolgreichen RepoGround-Einsatz abzuleiten.

Die drei Fehler betrafen ausschließlich die absichtlich
erfundene Grenzfall-Funktion `frobnicate_interstellar_penguin_engine`:
**A zweimal**, **B einmal**, **C keinmal**. Die tatsächlich
verursachende Klasse lautet jeweils `invalid_agent_answer`,
nicht Ausfall des Providerzugangs und nicht fehlendes Token-Receipt.
Die Originalantworten wurden in den Rohtraces bewahrt;
die Bewertungsfälle wurden nicht zu gültigen Erfolgen umetikettiert.

## Belegqualität, Provenienz und Grenzen

- 36 echte JSONL-Transkripte wurden vom Studienrunner mit
  tatsächlich vorhandenen `turn.completed`-Providerwerten geprüft;
  alle zugehörigen Quellen- und Tool-Kontrakte bestanden.
- Die Ausgabe enthält **135 Quellenzitate**, deren
  Git-Commit-/Datei-/Zeilengrenzen bei einer separaten mechanischen
  Gegenprobe **135/135** innerhalb tatsächlicher Git-Blobs lagen.
  **Das ist keine Aussage über inhaltliche Belegpassung.**
  Drei fehlgeschlagene Antworten lieferten keine Zitate.
- Die eigentliche Evaluationsroutine meldet
  `decision=not_established` und
  **null unabhängige begutachtete Fallblöcke**; folglich
  keine fachlich belastbaren, task-geclusterten 95-%-Intervalle.
  Fehlende menschliche/sonstige unabhängige Qualitätsgrades
  werden nicht nachträglich erfunden.
- **Bekannte R3-Messgrenze (nach Review):** Drei echte `live_freshness`-MCP-Antworten meldeten `status=fresh`, wurden vom ursprünglichen universellen `status=available`-Prädikat aber fälschlich als fehlgeschlagene Toolaufrufe klassifiziert. Die Original-JSONL-Traces bestätigen **3/3 `fresh`**. Es handelt sich um eine Toolstatus-Fehlklassifikation, nicht um drei RepoGround-Ausfälle. Die 41 MCP-Aufrufe, Modellantworten, Gesamtzeiten und Provider-Tokens bleiben echte Rohwerte; die R3-Originalreceipts bleiben unangetastet. Der korrigierte Runner besitzt eine andere SHA und benötigt künftig einen eigenen Protokollschlüssel.
- Die beobachteten einzelnen Codex-Toolzeiten beruhen auf lokal
  empfangenen Start-/End-Ereignissen. Bei gemeinsam ausgelieferten
  Events ist ein `0 ms`-Wert möglich, ohne dass das Tool wirklich
  null Laufzeit beansprucht hätte.
- Cacheanteile, Providerlast und übrige Agentenvarianz beeinflussen
  die Dauer. Eine einzelne 6-Fälle-Kohorte beweist keinen kausalen
  Mehrwert. Abgerechnete Kosten sind mangels Providerrechnung **unbekannt**,
  nicht null.
- Zwei vorgelagerte Instrumentierungsversuche (`r1`/`r2`)
  entdeckten einen Arbeitsverzeichnis-Importfehler und eine vom
  Modell erzeugte ungültige Pfadangabe. Beide bleiben als
  **getrennte** fehlerhafte Protokollkohorten im privaten State.
  Sie wurden weder mit den 36 `r3`-Läufen vermischt noch
  heimlich neu ausgeführt.

**Kanonische Hashbindung des ursprünglichen r3-Datensatzes:**

| Originalbeleg | SHA256 |
| --- | --- |
| Run-Plan-Datei | `4c74717f45c0738b4c8cc44aab4b8dbf16b68436bd8a75109f3974e3c1f9de66` |
| Kanonisch sortierter Index aus allen 36 `{request_id,receipt_sha256,trace_sha256,status}` | `b8cff13a668fc66901a745796f82421bff92dc54a8e1619c80e530dd1e827785` |
| JSON-Auswertungsdatei | `313829977906a6ddc15a22c88938ced29b362f359c9b37fd9c5e1873bd1224c6` |
| Markdown-Auswertungsdatei | `5cfffbdfb50a6b5ad69a71693193080c7fce4a27160b3d43b85a51e833423dc6` |

Die Rohdateien bleiben **privat** unter
`/home/alex/.local/state/grabowski/repoground-agent-study-codex-live-20261101/`
in `receipts-r3/`, `traces/` und
`study-plan-r3/`; dies ist ein Hostpfad, **kein öffentlich
archivierter Download**. Dieser veröffentlichbare Bericht
enthält keine Tokeninhalte, Benutzergeheimnisse oder Provider-Traces.

## Entscheidung und nächster Vergleich

**Kein produktiver Zwang zu RepoGround.** Im vorliegenden
Pilot liefert B gegenüber A durchschnittlich mehr
Ende-zu-Ende-Latenz und gemeldete Input-Tokens;
C benutzt RepoGround überhaupt nicht und erfüllt
mechanische Goldpfade sogar seltener als A.
Daher besteht **kein begründeter Anlass**, RepoGround
allen Coding-Agenten verpflichtend vorzuschalten.

Ein unabhängiger, auf die eingefrorenen Git-Zeilen
bezogener Antwortreview ist Voraussetzung,
bevor eine Route als qualitätsverbessernd gelten kann.
Anschließend kann das unveränderte Taskset mit
einer **neuen, korrekt versionierten Runner-/Modell-/
Generator-Konfiguration** wiederholt werden.
Der hier gemessene Originalrunner ist durch seine
SHA256 und den Git-Commit reproduzierbar archiviert;
nachfolgende Code-Refactorings sind eine neue
Runnerrevision und dürfen nicht als identischer
`protocol_key` ausgegeben werden.