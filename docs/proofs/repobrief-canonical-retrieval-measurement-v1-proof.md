# RepoBrief Canonical Review Retrieval Measurement v1 — Proof

## Gegenstand

Der Snapshotpfad erzeugte bislang einen Retrieval-Bericht aus dem generischen
Beispiel `docs/retrieval/queries.md`. Dieser Bericht war diagnostisch brauchbar,
konnte aber die repository-spezifische Reviewqualität von Lenskit nicht messen.
Dadurch konnte ein formal guter Beispielwert neben einer schwachen realen
Reviewsuche stehen, ohne dass der Snapshotbericht den Unterschied sichtbar
machte.

Die Korrektur verdrahtet den vorhandenen 20-Fragen-Goldstandard
`docs/retrieval/review_queries.v1.json` in den Snapshotpfad. Sie ändert das
Standardranking ausdrücklich nicht, sondern misst den bestehenden lexikalischen
Retriever wahrheitsgemäß.

## Änderung

- Ein repository-lokaler, schema-valider Review-Goldstandard ist für die
  Snapshotmessung kanonisch.
- Fragen-Recall und Einzelziel-Recall werden getrennt ausgewiesen:
  Eine Frage gilt als Treffer, sobald mindestens ein erwartetes Ziel gefunden
  wird; beim Einzelziel-Recall zählt jeder erwartete Pfad oder Symbolname.
- Der Goldstandard selbst wird vor Sortierung und Begrenzung exakt aus der
  Messung ausgeschlossen. Das ist Messhygiene, keine Rankingverbesserung.
- Ein vorhandener, aber ungültiger kanonischer Goldstandard beendet die
  Messung fail-closed. Es erfolgt kein stiller Rückfall auf das Beispiel.
- Fehlt ein repository-spezifischer Goldstandard, bleibt der generische Bericht
  verfügbar, wird aber als `generic_example`, nichtkanonisch und nicht
  promotionsfähig markiert.
- Snapshotberichte setzen `default_promotion_allowed=false` und
  `promotion_status=blocked`. Auch ein später bestandener Schwellenwert wäre
  ohne getrennte Vergleichs- und Entscheidungsbelege keine Promotionsfreigabe.
- Das Retrieval-Eval-Schema koppelt kanonische Berichte an repository-spezifische
  Semantik, bestandene Goldstandardvalidierung und eine Reviewmessung. Es weist
  widersprüchliche Kombinationen zurück.

## Commitgebundener Realnachweis

Gemessener Code-Commit:

```text
8f24c2ab55a86a315b5066b4f399c3a1a9fd10f3
```

Befehl, mit temporärem Ausgabepfad:

```text
python3 -m merger.lenskit.cli.main repobrief snapshot create \
  --repo <sauberer Worktree des Commits> \
  --out <temporärer Ausgabepfad> \
  --profile local-private \
  --mode gesamt \
  --output-mode dual
```

Ergebnis des realen Lenskit-Snapshots:

```text
Snapshot-Finalisierung          pass
Post-Emit-Health                pass
Bundle-Surface-Validation       pass
Kanonischer Benchmark           pass
Fragen                          20
Fragen-Treffer                  1
Fragen-Recall@10                5.0 %
MRR                             0.05
Erwartete Einzelziele           60
Einzelziel-Treffer              1
Einzelziel-Recall@10            1.666667 %
Akzeptanzschwellen bestanden    1/20
Akzeptanzstatus                 fail
Default-Promotion               blocked
```

Die Nulltrefferquote ist `0.0`: Die Abfragen liefern Ergebnisse, aber fast nie
die erwarteten Reviewziele. Die Missdiagnostik ordnet 48 Ziele als im Index
vorhanden, aber außerhalb der Top 10 ein; zehn Ziele sind mehrdeutig und ein
Ziel fehlt im Index.

Der kompakte, commitgebundene Messbeleg liegt unter:

- `docs/diagnostics/repobrief-canonical-retrieval-measurement-20260711.json`

Der vollständige temporäre Retrieval-Bericht hatte:

```text
Bytes     156958
SHA-256   18a1817958771fc5b0f58f36bdc4bbccdc94004c256ac8b2252e5592d6f37b3e
```

## Lokale Validierung

Vor dem commitgebundenen Realnachweis:

```text
314 relevante Retrieval-, Manifest-, Graph- und Kontexttests bestanden
Ruff auf den geänderten Adapter- und Testdateien bestanden
F401/F821/F822/F823-Prüfung der historischen merge.py bestanden
git diff --check bestanden
```

Die abschließende breite Suite und GitHub-CI werden separat an den endgültigen
PR-Head gebunden.

## Sicherheits- und Autoritätsgrenzen

- Die Messung beweist keine Reviewvollständigkeit oder Antwortkorrektheit.
- Ein Treffer beweist nicht, dass die gefundene Stelle für eine konkrete Antwort
  ausreicht; ein Miss beweist nicht die Abwesenheit von Code oder Dokumentation.
- Formal grüne Bundle-Health bewertet Struktur und Integrität, nicht die
  Nützlichkeit des Rankings.
- Die Änderung verbessert weder Ranking noch Router und promotet kein neues
  Standardverhalten.
- Sie beweist keine Testvollständigkeit, Regressionsfreiheit,
  Runtime-Korrektheit oder vollständiges Repositoryverständnis.
