# Lenskit Recursive Reusable Workflow Pinning — technischer Nachweis

## Zweck

Dieser Nachweis schließt die von Lenskit tatsächlich erreichte GitHub-Actions-Kette
rekursiv. „Rekursiv“ bedeutet: Nicht nur Lenskit selbst und der unmittelbar
aufgerufene Fremdworkflow werden geprüft. Ruft dieser Fremdworkflow einen weiteren
Fremdworkflow auf, muss auch dafür ein eigener Inhalts-Hash und eine vollständige
`uses`-Inventur vorliegen.

## Bindung

```text
Lenskit-Basis          5929d595c4786cf877bea3663a6b1cb9f4de9c82
Technischer Commit     f2d059dd581f1197549c07bea0d7e026689bac2c
Technischer Git-Baum   a76f3e21df6260b17ab0cfa240cf47a16b455233
Vertragsversion        1.1
```

Maschinenlesbarer Nachweis:

- `docs/diagnostics/lenskit-ci-supply-chain-transitive-closeout-20260712.json`

## Kritischer Selbstreview und Korrektur

Die erste Prüfung erfasste nur die unmittelbar in den beiden Fremdworkflows
stehenden `uses`-Zeilen. Dabei war der WGX-Verweis auf den metarepo-Observatory-
Workflow zwar selbst commitgepinnt, dieser Workflow enthielt intern aber noch
`actions/checkout@v6` und `actions/setup-node@v6`.

Damit war die anfängliche Aussage einer vollständigen transitiven Schließung
nicht haltbar. Der unveröffentlichte Lenskit-Stand wurde verworfen und die Kette
von innen nach außen korrigiert:

1. metarepo PR #647 pinnt beide inneren Actions und lässt den bestehenden
   Pin-Prüfer dauerhaft auf den Observatory-Workflow laufen.
2. WGX PR #639 bindet den Guard an den gehärteten metarepo-Merge.
3. Lenskit verlangt nun für jeden rekursiv erreichten Fremdworkflow einen
   passenden Closure-Eintrag mit Commit, SHA-256 und eigener `uses`-Inventur.

## Gemergte Kette

### Lenskit → metarepo command dispatch

- metarepo PR #646
- Merge `75ab0d5a5a90b79f2cd527d1b9a263d0f1a24043`
- Workflow-SHA-256 `7914e34042f0cc55308f03dc43ad9ae1f2c5d7c083778f646ee1e12e5d4cd5f0`
- zwei direkte externe Verweise, beide vollständige Commit-SHAs
- 14 PR-Prüfungen erfolgreich

### Lenskit → WGX guard

- WGX PR #639
- Merge `a7466bf2c3cb7fa3b261bfb2d008612abc0f85b1`
- Workflow-SHA-256 `33784ef4748427adc0a183d44d118e445121ba91b3bc5f9d457b913bf292e19e`
- vier direkte externe Verweise, darunter ein weiterer Fremdworkflow
- 20 PR-Prüfungen erfolgreich, 4 bewusst übersprungen
- 12 Main-Prüfungen erfolgreich

### WGX guard → metarepo observatory validation

- metarepo PR #647
- Merge `dda0d036b3b4db935d3acbaa4c1b0fc76637cea9`
- Workflow-SHA-256 `e4b488f5b65e7bea50ea3c84979f162dd461965f782115d578b24bacdcc1eb15`
- zwei direkte externe Verweise, beide vollständige Commit-SHAs
- 14 PR-Prüfungen erfolgreich, 1 bewusst übersprungen
- 11 Main-Prüfungen erfolgreich, 2 bewusst übersprungen

## Neuer Ratchet

Der lokale Vertrag und sein Prüfer erzwingen jetzt:

- exakten Caller-Pfad, Job und Upstream-Commit;
- gültigen SHA-256 für jeden aufgezeichneten Fremdworkflow;
- vollständige 40-stellige Commit-SHAs für alle aufgezeichneten externen
  `uses`-Verweise;
- genau einen Closure-Eintrag für jeden direkt erreichten Fremdworkflow;
- dieselbe Prüfung erneut innerhalb jedes Closure-Eintrags;
- weiterhin die Caller-Rechte, Secret-Namen und Ereignisbedingungen.

Negativtests blockieren unter anderem fehlende Closure-Einträge, abgetrennte
Closure-Einträge, bewegliche Actions auf zweiter Ebene, ungültige Inhalts-Hashes
und einen nicht inventarisierten dritten Fremdworkflow.

## Inventur

```text
Direkte Lenskit uses-Verweise                       62
Direkte bewegliche Lenskit-Verweise                  0
Aufgezeichnete Fremdworkflow-Knoten                   3
Erste Remote-Ebene: externe uses                      6
Zweite Remote-Ebene: externe uses                     2
Gesamte aufgezeichnete externe uses                   8
Offene Fremdworkflow-Kanten                           0
Bewegliche Referenzen im aufgezeichneten Graphen      0
Fokustests                                           19 bestanden
Python-Gesamttests                                  3.757 bestanden, 1 übersprungen
Web-UI-JavaScript-Suiten                                5 bestanden
Workflow-YAML-Dateien                                  21 gültig
Ruff, Status- und Planungsprüfungen                     pass
Zwei bytegleiche Release-Kandidaten                     pass
Remote-Git-Objekte gegen Hash und Inventar              pass
```

## Noch offen vor dem Taskabschluss

Der technische Commit ist fokussiert und breit lokal geprüft. Der Task bleibt
offen, bis der Lenskit-PR am endgültigen Head und der anschließende Main-Nachlauf
erfolgreich belegt sind.

## Nichtaussagen

Commit-Pinning verhindert unbemerkte Tag-Verschiebungen im aufgezeichneten
Graphen. Es beweist keine Schadcodefreiheit, vollständige Workflowkorrektheit,
korrekte Secrets, automatische Erfassung nicht aufgezeichneter Abhängigkeiten,
vollständige Least-Privilege-Rechte, Testvollständigkeit, Regressionsfreiheit,
Produktreife oder Release-Reife.
