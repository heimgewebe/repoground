# Guard Relation Cards v1b (Target Proof — `validates_schema`)

## Status und Scope

Diagnosis-only. Dieser PR implementiert keinen Contract, Producer,
Runtime-Validator, Consumer und keine CLI- oder Bundle-Integration. Untersucht
wird nur der Roadmap-Kandidat `validates_schema`; die präzisere Semantik lautet
`validates_instance_against_schema`.

## Festgeschriebener Snapshot

Alle Befunde beziehen sich auf
`05bbd0d608afa8faf581887a455d4dcf6fa15ae9`, den Merge-Commit von PR #798.
Das Inventar enthält 590 Pfade und 54 `*.schema.json`-Dateien; sein SHA-256 ist
`19ccdd599e32d683b97d71a86b05594b825440bda1b900d32a756517f637b50a`.
Das Audit liest diesen Baum mit `git ls-tree` und `git show`, nicht den Working
Tree.

## Reproduktionsoberfläche

| Artefakt | Rolle |
|---|---|
| `docs/proofs/guard-relation-cards-v1b-validates-schema-audit.json` | Spaltengebundenes, manuell reviewtes Flow-Manifest. |
| `docs/proofs/_repro/guard_relation_validates_schema_audit.py` | Typisiert die Flowzeilen, leitet Aggregate ab und prüft AST-Callsites. |
| `.github/workflows/lens-model.yml` | Führt Normal-, Wiederholungs- und `python -O`-Lauf aus und vergleicht sie bytegenau mit dem Manifest. |

Die qualitativen Schema-Bindungen und Fehlerpfade sind manuell geprüft. Die
Summen werden aus den einzelnen Flowdatensätzen berechnet; sie sind keine
separate Eingabewahrheit.

## Nichtimplementierung

Relation Card v1 bleibt `imports`-only. Im Snapshot existieren weder ein
`validates_schema`-Relationstyp noch Producer, Contract, Goldset oder
verbindlicher Consumer.

## Identitätsmodell

Der semantische Schlüssel besteht aus:

```text
source_path + relation_owner_symbol + engine_owner_symbol + schema_path
+ schema_fragment + activation_condition + target_scope
```

Der snapshot-lokale Callsite-Schlüssel ergänzt `relation_call_line` und
`engine_call_line`. Mit der Base-SHA wird daraus eine `snapshot_flow_id`. Diese
ID ist reproduzierbar innerhalb des Snapshots, aber nicht dauerhaft stabil:
Zeilenverschiebungen verändern sie.

`relation_call_line` ist die fachliche Engine- oder Helper-Aufrufstelle;
`engine_call_line` ist die tatsächliche `.validate()`- oder
`.iter_errors()`-Callsite.

## AST-Callsite-Gate

Der Scanner erhebt im Base-Snapshot
`(source_path, engine_owner_symbol, engine_call_line)` und vergleicht die Menge
mit dem Flow-Manifest. Zusätzlich prüft er:

- fünf `check_schema()`-Callsites;
- genau den bekannten Syntaxfehler in
  `merger/lenskit/tests/fixtures/entrypoints_test_project/invalid.py`;
- erklärte `jsonschema`-Texttreffer ohne Engine-Callsite;
- Testklassifikation über `lens_facets.infer_facets`.

Die deklarierte Grammatik umfasst die im Snapshot verwendeten
`.validate`-, `.iter_errors`- und `.check_schema`-Aufrufe sowie direkte
`jsonschema.validate`-Importaliasse. Intermodulare Aliasweitergabe, dynamische
Wrapper und Nicht-`jsonschema`-Validatoren liegen außerhalb des Scopes.
AST-Gleichheit beweist Callsite-Abdeckung innerhalb dieser Grammatik, nicht die
semantische Richtigkeit jeder Schema-Bindung.

## Befund

| Oberfläche | Wert |
|---|---:|
| akzeptierte In-Repo-Flows | 24 |
| semantische Schlüssel | 23 |
| Engine-Callsites inklusive externem Flow | 23 |
| Modul→Schema-Ziele | 21 |
| akzeptierte Module | 17 |
| akzeptierte Schema-Ziele | 18 |
| externer Flow | 1 |
| Meta-Engine-Callsites | 5 |
| manuell gebundene Meta-Schema-Flows | 6 |
| Test-Facet-Dateien mit Validierungs-API | 45 |
| Schema-Dateien ohne akzeptierte Beziehung | 36 |

Die Einheiten werden nicht zu einer globalen Summe vermischt.

Von 24 akzeptierten Flows sind 22 direkt und zwei delegiert. Bei
`relation_card_validate.validate_relation_card` liegen die Relation-Callsites an
226 und 235; beide delegieren an `_schema_check`, dessen Engine-Callsite 159 ist.

Der externe Flow verbindet `adapters.sources.refresh` Zeile 299 mit
`_validate_snapshot` Zeile 178 und
`metarepo/contracts/fleet/fleet.snapshot.schema.json`. Der Organism-Snapshot wird
nicht schema-validiert.

`range_resolver` erzeugt an einer Engine-Callsite zwei disjunkte Flows:
v1 bei `range_ref_version != "2"`, v2 bei `range_ref_version == "2"`.
Damit bestehen 22 unbedingte und zwei bedingte Flows.

Schema-Anforderungen: 21 `required`, 3 `optional`. Optional sind
`graph_index`, `pr_schau_bundle` und der Delta-Flow in `validate_merge_meta`.
Die weiteren Achsen stehen pro Flow im Manifest und werden vom Skript abgeleitet.

Der AST belegt fünf Meta-Callsites. Die Bindung an sechs konkrete Schemata beruht
auf manuellem Source-Review, weil `_schema_check` an derselben Callsite zwei
Schemata prüft.

## Consumer und Entscheidung

Es existiert kein implementierter oder verbindlich spezifizierter Consumer.
`Validator → Schema` ist nur die Darstellungsrichtung dieses Proofs.

**Ergebnis C — Persistenz zurückstellen.** Es fehlen Consumer, belegter
Persistenzvorteil, festgelegter Name und Contractrichtung sowie ein semantisches
Goldset. Die Abdeckung 18/54 ist ein Coverage-Befund, kein Persistenzblocker.

## Negativsemantik

Der Nachweis beweist weder Schema-Korrektheit noch Validator-Vollständigkeit,
Runtime-Ausführung, Testsuffizienz, Regressionsfreiheit, Change Impact,
Consumerbedarf, Repo-Verständnis oder Forensic Readiness. `load_only`,
`path_reference_only`, dynamisch konfigurierte und nicht auf `jsonschema`
basierende Validatoren wurden nicht vollständig inventarisiert.

## Reproduktion

```bash
BASE_SHA="05bbd0d608afa8faf581887a455d4dcf6fa15ae9"
SCRIPT="docs/proofs/_repro/guard_relation_validates_schema_audit.py"
COMMITTED="docs/proofs/guard-relation-cards-v1b-validates-schema-audit.json"

python3 "$SCRIPT" --repo "$PWD" --base-sha "$BASE_SHA" --output /tmp/a.json
python3 "$SCRIPT" --repo "$PWD" --base-sha "$BASE_SHA" --output /tmp/b.json
python3 -O "$SCRIPT" --repo "$PWD" --base-sha "$BASE_SHA" --output /tmp/o.json
cmp /tmp/a.json /tmp/b.json
cmp /tmp/a.json /tmp/o.json
cmp /tmp/a.json "$COMMITTED"
```
