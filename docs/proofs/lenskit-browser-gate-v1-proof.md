# Lenskit Reproducible Playwright Browser Gate v1 — Proof

## Zweck

Die zehn mit `browser` markierten WebUI-Flows waren bislang aus der
Pflicht-Test-Suite ausgeschlossen. Das war kein bloßes Laufzeitdetail: Der
angegebene Browser-Requirements-Pfad ließ sich in einer frischen Umgebung nicht
installieren, weil `pytest==9.0.3` und `pytest-playwright==0.7.1` einander
widersprachen.

Für Laien: Die Tests existierten, aber die automatische Prüfanlage konnte ihre
Werkzeuge nicht zuverlässig zusammenbauen. Der neue Gate-Pfad bindet
Test-Plugin, Playwright-Version, Browser-Systemumgebung und Chromium-Revision an
einen überprüfbaren Vertrag.

## Implementierungsbindung

```text
Basis                 78237d69e4d87274b73ba619eb7da71b6eb77d08
Technischer Commit    6095fd4b3d74d72e0106699721a69b59715f1433
Git-Baum              12022c0f393a831ea6e29864dcb6e9240d1fdf8d
```

## Gewählter Vertrag

Top-Level-Pythonpakete sind exakt gepinnt:

```text
pytest                 9.0.3
pytest-asyncio         1.4.0
pytest-playwright      0.8.0
playwright             1.61.0
pytest-base-url        2.1.0
```

`pytest-playwright 0.8.0` unterstützt pytest 9. Ein pytest-Downgrade war daher
nicht nötig.

Die Browser- und Systemschicht kommt aus dem offiziellen Playwright-Python-Image:

```text
mcr.microsoft.com/playwright/python:v1.61.0-noble
@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69
```

Der Digest verhindert, dass der Workflow bei unverändertem Lenskit-Commit
später still ein anderes Image lädt. Der erweiterte Actions-Pin-Ratchet weist
zukünftig auch bewegliche `container:`- und `image:`-Verweise zurück. Die
Erkennung ist auf echte Job- und Service-Container begrenzt; Action-Argumente
mit einem gleichnamigen Feld erzeugen kein False Positive.

## CI-Gate

`test-suite.yml` enthält einen eigenen Job `browser-tests`:

1. Repository auschecken;
2. exakt gepinnte Browser-Testpakete installieren;
3. Paketversionen, Browserpfad und einen echten Chromium-Start prüfen;
4. alle zehn Browser-Flows mit Chromium ausführen;
5. Traces, Screenshots und Videos nur bei Fehlschlag sieben Tage aufbewahren.

Der bestehende `pytest-full`-Job schließt Browsertests weiterhin aus, damit die
Tests nicht doppelt oder ohne Browserumgebung laufen. Ihre Pflichtwirkung kommt
vom separaten Checknamen `browser-tests`.

Die Ruleset-Policy enthält diesen Check bereits. Der aktive GitHub-Ruleset wird
absichtlich erst nach einem grünen PR-Lauf und einem grünen Main-Lauf erweitert.
So entsteht kein Zustand, in dem `main` einen noch nie erzeugten Check verlangt.

## Lokaler Realnachweis

Ein nativer heim-pc-Lauf mit frischer virtueller Umgebung scheiterte noch vor
Chromium am mitgelieferten Node-Treiber (`V8 OS::SetPermissions`). Das ist als
lokale Hostgrenze dokumentiert und wurde nicht als Testfehler umgedeutet.

Der digestgebundene Container wurde anschließend mit read-only eingebundenem
Repository ausgeführt. Ergebnis:

```text
Python                              3.12.3
Playwright                          1.61.0
Chromium-Revision                   1228
Chromium-Version                    149.0.7827.55
Runtime-Smoke                       pass
Browser-Flows                       10 passed
Arbeitsbaum nach Test               unverändert
```

## Statische Validierung vor dem Nachweiscommit

```text
Browser-/Workflow-/Ruleset-Fokustests       31 passed
Ruff auf geänderten Python-Dateien          pass
Workflow-YAML-Parse                         pass
GitHub-Actions-Pin-Ratchet                  pass
Reusable-Workflow-Contract-Ratchet          pass
git diff --check                            pass
```

Eine breite Nicht-Browser-Suite, der erneute Containerlauf und GitHub-CI werden
an den endgültigen PR-Head gebunden.

## Noch offen vor Taskabschluss

- `browser-tests` muss am unveränderten PR-Head auf GitHub grün sein;
- derselbe Job muss nach Merge auf `main` grün sein;
- danach muss Ruleset `18784275` um `browser-tests` erweitert und live gegen
  die Policy validiert werden;
- erst der anschließende Closeout setzt den Task auf `done`.

## Nichtaussagen

Der Nachweis etabliert keine vollständige transitive Python-Sperrdatei, keine
Sicherheit des Containerinhalts, keine Cross-Browser-Kompatibilität, keine
vollständige Interaktions- oder Darstellungsabdeckung, keine Testvollständigkeit,
keine Regressionsfreiheit und keine Release-Reife.
