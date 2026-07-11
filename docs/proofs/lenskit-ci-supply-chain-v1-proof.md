# Lenskit CI Supply Chain v1 — Proof

## Gegenstand

Die Lenskit-Workflows verwendeten überwiegend bewegliche Major-Tags wie `@v5`
oder `@v6`; zwei wiederverwendete Organisationsworkflows standen auf `@main`.
Ein solcher Name ist bequem aktualisierbar, kann aber zwischen zwei Läufen auf
einen anderen Commit zeigen, ohne dass sich Lenskit geändert hat.

Die Änderung trennt deshalb zwei Vorgänge:

1. **Laufzeit:** GitHub lädt ausschließlich einen im Lenskit-Commit festgelegten
   40-stelligen Commit-SHA.
2. **Aktualisierung:** Dependabot kann eine Änderung dieses SHA als eigenen PR
   vorschlagen. Erst ein geprüfter Merge verändert die Laufzeitabhängigkeit.

## Implementierungsbindung

```text
Basis                 174a865cd8577c152ca30a61618a0f4b8cdf0482
Technischer Commit    f6e0b91bde72641797465475ec2691aa82558e18
Git-Baum              e41835b26cc4d8a4324f385cfa981944f1cd1cea
```

Die früheren Tags und Branches wurden am 11. Juli 2026 über die GitHub
Tags-/Commit-API bis zum tatsächlichen Commitobjekt aufgelöst. Das vollständige
Inventar steht in:

- `docs/diagnostics/lenskit-ci-supply-chain-pins-20260711.json`

## Direkte Lenskit-Oberfläche

- 57 externe Action- oder Reusable-Workflow-Verwendungen wurden geprüft.
- 55 bewegliche Verweise wurden auf volle Commit-SHAs umgestellt; zwei
  Cross-Repository-Verweise waren bereits SHA-fest.
- Der Ratchet `scripts/ci/check_github_actions_pins.py` prüft Workflows und
  Composite Actions und blockiert Tags, Branches, dynamische Referenzen und
  Docker-Tags ohne Digest.
- `contracts-validate` führt den Ratchet bei Push, Pull Request und manueller
  Ausführung aus.
- Lokale Actions bleiben erlaubt; Docker-Actions benötigen einen
  `sha256`-Digest.
- Die Node-24-Vertragsprüfung verlangt bei bekannten JavaScript-Actions einen
  vollen SHA und einen sichtbaren `# vN`-Kommentar. Der Kommentar ist eine
  Reviewhilfe; ausgeführt wird allein der SHA.

## Rechte- und Secret-Audit

### Metrics

`actions: write` und `checks: write` wurden entfernt. Checkout, lokale
Metrikerzeugung und `upload-artifact` benötigen keinen schreibenden
`GITHUB_TOKEN`; verbleibend ist `contents: read`.

### Claude

`actions: read` wurde entfernt, weil keine zusätzliche CI-Berechtigung an die
Action konfiguriert ist. `contents`, `pull-requests`, `issues` und `id-token`
bleiben schreibend, weil der Workflow interaktive Änderungen ausführt und die
Dokumentation der exakt gepinnten Claude-Action diese Scopes für den verwendeten
Authentifizierungs- und Änderungsweg vorsieht. Eine weitere Kürzung würde die
beabsichtigte Funktion ändern, nicht nur härten.

### Heimgewebe-Befehle

Der aufrufende Lenskit-Workflow behält nur `contents: read`. Statt alle Secrets
zu vererben, übergibt er explizit die beiden vom gepinnten Reusable-Workflow
deklarierten Namen:

```text
HEIMGEWEBE_APP_ID
HEIMGEWEBE_APP_PRIVATE_KEY
```

Der fremde Workflow führt seine Schreiboperationen mit einem kurzlebigen
GitHub-App-Token aus. Der letzte belegte Vorlauf `29126802947` erzeugte dieses
Token erfolgreich. Ein neuer Lauf des geänderten Issue-Comment-Workflows ist
erst nach Veröffentlichung auf dem Default-Branch sinnvoll möglich.

## Tests vor dem Nachweiscommit

```text
GitHub Actions Pin Ratchet                     pass, 0 Findings
Pin-/Negativ-/Rechte-Tests                    6 passed
Node-24-/Metrics-Vertragstests                6 passed
Workflow-/Ruleset-/Contract-Fokustests       134 passed
YAML-Parse                                    22 Dateien gültig
git diff --check                              pass
Ruff auf neuen/geänderten Python-Dateien      pass
```

Eine breite Suite und GitHub-CI werden an den endgültigen PR-Head gebunden.

## Begrenzung: transitive Upstream-Abhängigkeiten

Die direkte Lenskit-Oberfläche ist SHA-fest. Das beweist jedoch noch keine
vollständig unveränderliche Laufzeitkette: Die beiden gepinnten fremden
Reusable-Workflows enthalten an ihren festgelegten Commits intern fünf
bewegliche Action-Aufrufe:

- Metarepo: `actions/create-github-app-token@v3`, `actions/github-script@v8`
- WGX: zweimal `actions/checkout@v4`, einmal `actions/setup-python@v5`

Diese internen Tags werden bei einem Lauf weiterhin durch GitHub aufgelöst. Der
Rest ist deshalb als eigener Task registriert:

- `TASK-LENSKIT-AUDIT-CI-SUPPLY-CHAIN-UPSTREAM-TRANSITIVE-001`

## Nichtaussagen

Der Nachweis etabliert weder Schadcodefreiheit noch Fehlerfreiheit der
gepinnten Abhängigkeiten. Er beweist keine vollständige Least-Privilege-Lage,
keine Workflowkorrektheit für jedes Ereignis, keine Testvollständigkeit, keine
Regressionsfreiheit, keine Runtime-Korrektheit und keine Release-Reife.
