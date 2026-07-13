# RepoBrief Agent Impact Context v1

## Entscheidung

RepoBrief übernimmt ausgewählte Ideen aus `codegraph-ai/CodeGraph`, aber nicht
das Produkt als zweiten Dienst. Lenskit bleibt die einzige Bundle-, Provenienz-
und Agenten-Frontdoor. Die neue Fläche projiziert vorhandene Lenskit-Artefakte
read-only zu einem kompakten Arbeitskontext.

Übernommen werden:

- gerichtete eingehende und ausgehende Graphbeziehungen;
- verwandte Tests mit getrennten Evidenzklassen;
- ein gebündelter Kontext vor Änderungen;
- Einstiegspunkte sowie verknüpfte Verträge und Dokumentation;
- eine kleine, aufgabenspezifische Adapteraktion statt einer breiten MCP-Fläche.

Nicht übernommen werden:

- CodeGraph-Memory;
- ein zweiter persistenter Index oder eine zweite Dokumentationswahrheit;
- automatische PR-Kommentare;
- Reviewverdikte, Risikozahlen oder Mergefreigaben;
- proprietäre Pro- und Security-Flächen.

## Komponenten

- `merger/lenskit/core/agent_impact_context.py`
  erzeugt die reine deterministische Projektion.
- `merger/lenskit/core/repobrief_agent_impact_adapter.py`
  liest nur ausdrücklich registrierte und integritätsgeprüfte Bundle-Artefakte.
- `merger/lenskit/cli/agent_impact.py`
  stellt die opt-in Kommandozeilenfläche bereit.
- `merger/lenskit/core/agent_impact_eval.py`
  misst einen festen Goldset-Vergleich, ohne eine Standardbeförderung auszulösen.

## Eingaben

Die Projektion verwendet ausschließlich bereits erzeugte Artefakte:

| Rolle | Verwendung |
|---|---|
| `architecture_graph_json` | gerichtete Datei-/Modulbeziehungen und Evidenzniveau |
| `python_symbol_index_json` | exakte Symbolziele, Quellpfade und Range-Referenzen |
| `entrypoints_json` | CLI-, Web-, Worker-, Modul- und Test-Einstiegspunkte |
| `relation_cards_jsonl` | zusätzliche Navigationshinweise, nicht Wahrheit |
| `sqlite_index` | optionaler aufgelöster Query-Kontext für Verträge und Dokumentation |

`changed_paths` ist ein Kompositionspunkt für den bestehenden Delta Context.
Die neue Fläche parst oder appliziert selbst keinen Diff.

## Ausgabe

`agent-impact-context.v1` enthält:

- Zielpfade und gefundene Zielsymbole;
- `relations` mit `incoming|outgoing`, `edge_type`, `evidence_level` und
  ursprünglicher Evidence;
- `related_tests` mit `graph_edge`, `symbol_index_path_match` oder `heuristic`;
- `supporting_context` für Verträge und Dokumentation;
- relevante `entrypoints`;
- passende Relation Cards;
- Quellstatus, Bundle-Provenienz, Lücken und Kürzungen;
- im Modus `edit` eine priorisierte, begrenzte Erstleseliste.

Heuristiken bleiben sichtbar als Heuristiken. Eine bloße Namenskonvention wird
nicht zu Testabdeckung oder Laufzeitabhängigkeit hochgestuft.

## Kohärenz und Degradation

Die Kernartefakte müssen denselben `run_id` und denselben
`canonical_dump_index_sha256` tragen. Abweichende Identitäten oder untrusted
Integritätszustände blockieren die Projektion. Fehlende optionale Evidenz führt
zu `partial` oder `missing_target`, nicht zu stiller Vollständigkeit.

Damit bedeutet:

- `available`: Ziel ist belegt auffindbar und die verwendeten Kernartefakte sind kohärent;
- `partial`: Ziel ist auffindbar, aber Quellen oder Identitäten sind unvollständig;
- `missing_target`: weder Graph noch Symbolindex belegen das Ziel;
- `blocked`: Kernartefakte sind inkohärent oder integritätsseitig untrusted;
- `invalid`: die Anfrage verletzt Pfad-, Modus- oder Budgetgrenzen.

## Nutzung

```bash
python -m merger.lenskit.cli.agent_impact \
  --config /path/to/repobrief-readonly-adapter.json \
  --snapshot-id lenskit-main \
  --target-symbol build_agent_impact_context \
  --mode edit
```

Die Adapteraktion heißt `agent_impact_context`. Standardmäßig darf sie den
bestehenden read-only SQLite-Index als ergänzenden Query-Kontext lesen.
`--no-query-context` beschränkt die Projektion auf Graph, Symbole,
Einstiegspunkte und Relation Cards.

## Autoritätsgrenze

Die Fläche:

- schreibt nichts;
- erzeugt oder aktualisiert keinen Snapshot;
- führt Git, Shell, Tests oder Zielcode nicht aus;
- appliziert keinen Patch;
- erstellt oder verändert keinen Pull Request;
- speichert keine Agenten-Memory;
- behauptet keine vollständige Call-Graph-, Blast-Radius- oder Testabdeckung;
- erzeugt keine Review-, Security- oder Mergeentscheidung.

## Messstatus

Der zunächst committed Goldset ist ausdrücklich eine synthetische
Contract-Fixture. Er prüft Determinismus, Evidenztrennung, Degradation und die
Messpipeline. Er befördert die Aktion nicht zur Standardroute. Eine spätere
Beförderung erfordert eine getrennte Live-Bundle-Messung an realen
Repositoryänderungen.
