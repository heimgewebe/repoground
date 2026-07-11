# RepoBrief Status Truth Reconciliation v1 — Proof

## Ausgangslage

Der Auditpunkt F-06 war kein einzelner falscher Status, sondern eine
Bedeutungsdrift zwischen vier Oberflächen:

1. `docs/tasks/index.json` enthielt 90 Tasks;
2. `docs/tasks/board.md` enthielt nur 89 Taskzeilen und ließ
   `TASK-LENSKIT-MAIN-REQUIRED-CHECKS-001` aus;
3. die Board-Legende erklärte `done` als „vollständig abgeschlossen“, obwohl
   mehrere Tasks ausdrücklich nur einen begrenzten Slice schließen;
4. Roadmaps und Blaupausen enthielten Häkchen und Gate-Sprache, ohne klar zu
   sagen, dass diese keine kanonischen Taskstatus sind;
5. die Doc-Freshness-Registry verfolgte nur drei ausgewählte Claims. Ihr grüner
   Bericht durfte daher nicht als allgemeine Roadmap- oder Dokumentreife gelesen
   werden.

Vor der Änderung:

```text
Taskindex                            90
Boardzeilen                          89
fehlender Boardtask                  TASK-LENSKIT-MAIN-REQUIRED-CHECKS-001
done im Taskindex                    83
open im Taskindex                     7
verfolgte Freshness-Claims            3
Upgrade-Blaupause-Checkboxen        147
```

## Implementierungsbindung

```text
Basis                 fe8b002201e7a732f1101928a83514d9875f64dc
Technischer Commit    4e60a413ff4eab483b4e8089ef97da9a9eb05bd5
Git-Baum              2a57b07de0fb3d048bd1233e04040f4856de6286
```

## Autoritätsordnung

| Oberfläche | Rolle | Autorität |
|---|---|---|
| `docs/tasks/index.json` | kanonischer Taskstatus | task control |
| `docs/tasks/board.md` | menschenlesbare vollständige Projektion | keine unabhängige Taskautorität |
| `docs/status/repobrief-status-truth.v1.json` | begrenzte Reife- und Governance-Projektion | `governance_projection` |
| Roadmaps und Blaupausen | Ziel-, Reihenfolge- und Ordnungsdokumente | keine Taskstatus-Autorität |
| `docs/doc-freshness-registry.yml` | ausgewählte deklarierte Claims | `diagnostic_signal` |
| Health-/CI-Berichte | Ergebnis ihrer benannten technischen Checks | keine Produkt- oder Release-Reife |

`done` bedeutet nun ausschließlich: Der **deklarierte Task-Scope** ist
abgeschlossen und belegt. Separate Folgetasks, Phasengates oder bekannte
Grenzen dürfen weiter offen sein.

## Maschinenlesbarer Vertrag

`repobrief-status-truth.v1.schema.json` erzwingt unter anderem:

- getrennte Produkt-, Release- und Betriebsreife;
- explizite Nichtfolgerungen aus `done`;
- Roadmaps als nicht-kanonische Statusflächen;
- Freshness-Coverage `selected_declared_claims_only`;
- ausdrücklich ausgewählte Auditpakete mit Scope, Verifikationsgrad, Promotion und Begrenzungen;
- Health-Pass ohne Ableitung von Produktreife, Release-Reife,
  Reviewvollständigkeit, Testvollständigkeit, semantischer Wahrheit oder
  allgemeiner Runtime-Korrektheit.

Die aktuelle Projektion klassifiziert den Systemstand als `mixed`:

- Final Control Plane und Browser-Gate sind für ihre begrenzten Scopes auf
  `main` beziehungsweise in Runtime belegt;
- kanonisches Review-Retrieval ist gemessen, aber deutlich unter seinen
  Schwellen und nicht zur Default-Promotion freigegeben;
- Release-/Lizenzbelege fehlen;
- Graph-/Maintainability-Ratchets fehlen;
- zwei gepinnte fremde Reusable-Workflows enthalten intern noch bewegliche
  Action-Verweise.

Daraus folgt ausdrücklich **keine** Produkt- oder Release-Reife.

## Drift-Ratchet

`scripts/docmeta/check_status_truth.py` prüft im bestehenden
`planning-registration`-Job:

- vollständige ID-, Titel- und Statusparität zwischen Index und Board;
- eindeutige, scope-lokale `done`-Semantik;
- Taskzählungen der Reifeprojektion;
- Roadmap-Markierungen und fehlende Statusautorität;
- Begrenzung und Anzahl der verfolgten Freshness-Claims;
- Statusbindung der ausdrücklich ausgewählten Auditpakete;
- offene Folgetasks gegen den Taskindex;
- verbotene Health- und Readiness-Inferenzen.

Negativtests belegen mindestens:

- fehlender Boardtask wird blockiert;
- Statusabweichung wird blockiert;
- fehlende Roadmap-Grenze wird blockiert;
- falsche Freshness-Claimzahl wird blockiert;
- überhöhte Release-Reife wird blockiert;
- abgeschlossene Release-Evidenz kann spätere Release-Reife zulassen;
- unbelegte Produktreife bleibt separat blockiert.

Der Check erzeugt keinen neuen GitHub-Checknamen. Er läuft im bestehenden
`planning-registration`-Job und vermeidet damit eine zweite Merge-Gate-Welt.

## Freshness-Ausbau

Die Registry wird von drei auf sieben ausgewählte Claims erweitert:

- scope-lokale Board-`done`-Semantik;
- Upgrade-Blaupause als Zielarchitektur;
- Master-Roadmap als Ordnungsdokument;
- Agent-Operationalisierungsroadmap als Planfläche.

Sie bleibt trotzdem unvollständig. Ein grüner Freshness-Bericht bedeutet nur,
dass diese sieben Claims zu ihrer jeweils deklarierten Evidenz passen.

## Lokale Validierung vor Belegcommit

```text
Status Truth Ratchet                 pass, 0 Findings
Schema validation                    pass
Status-Truth Positiv-/Negativtests  12 passed
Nachbar-/Workflow-/Freshness-Tests 157 passed
Planning Registration Ratchet        0 Findings
Workflow YAML parse                  pass
GitHub Actions pin ratchet           pass
Ruff                                 pass
git diff --check                     pass
```

Breite Suite, PR-CI und Main-CI werden an den endgültigen Head gebunden.

## Nichtaussagen

Der Nachweis etabliert keine vollständige Dokumenterfassung, keine semantische
Wahrheit aller Claims, keine vollständige Evidenzbewertung jedes Tasks, keine
Test- oder Reviewvollständigkeit, keine Regressions- oder Schwachstellenfreiheit,
keine Produktreife und keine Release-Reife.
