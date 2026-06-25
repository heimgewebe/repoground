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
| `docs/proofs/guard-relation-cards-v1b-validates-schema-audit.json` | Reviewtes Flow-Manifest (manuelle Eingabe) **und** neu berechneter `derived`-Report. |
| `scripts/proofs/guard_relation_validates_schema_audit.py` | Liest den Base-Snapshot, lädt `infer_facets` aus der Base, leitet receiver-aufgelöste Callsites und Aggregate ab und prüft das Manifest fail-closed dagegen. |
| `merger/lenskit/tests/test_guard_relation_validates_schema_audit.py` | Falsifikationstests: Grammatik, Snapshot-Bindung und Ablehnung manipulierter Manifeste. |
| `.github/workflows/lens-model.yml` | Eigener Job `validates-schema-target-proof` (`fetch-depth: 0`): Lint, Falsifikationstests, Regenerieren + Bytevergleich und ein Negativ-Control (manipuliertes Manifest muss scheitern). |

Manuelle Eingaben (reviewte Flowzeilen, `meta`, `text_only`) und maschinell
abgeleitete Beobachtungen (`derived`) sind getrennt. Der `derived`-Report wird bei
jedem Lauf **neu aus dem Snapshot berechnet**, nicht aus dem Manifest kopiert; der
Bytevergleich prüft den neu berechneten Report. Summen sind abgeleitet, keine
separate Eingabewahrheit. Die Gates verwenden `require`/`AuditError` statt `assert`
und bleiben unter `python -O` aktiv.

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

## AST-Callsite-Gate (receiver-aufgelöst, base-gebunden)

Der Scanner liest den Base-Snapshot über `git`-Subprozesse (isolierte Git-Umgebung)
und klassifiziert Testpfade über `infer_facets`, das **aus der Base** geladen wird,
nicht aus dem Working Tree. Erkannt werden nur jsonschema-Receiver, die intra-modular
statisch gebunden sind:

- `import jsonschema [as …]` und `jsonschema.validate(…)`;
- `from jsonschema import validate [as …]`;
- `Draft7Validator`/`Draft202012Validator`-Konstruktoren (direkt, als Attribut des
  jsonschema-Modulalias, als lokal zugewiesene Validator-Variable oder gechaint);
- `.check_schema(…)` auf denselben Bindungen.

Jede `.validate`/`.iter_errors`/`.check_schema`-Stelle mit einem **nicht** so
gebundenen Receiver wird als `unresolved_candidate` geführt, nicht stillschweigend
verworfen. Validatoren, die über einen projektlokalen Loader
(`_load_jsonschema()` / `importlib.import_module`) bezogen werden, sind damit
absichtlich `unresolved` und gelten als `manual_source_review`.

Falsifizierbares Gate (exakte Mengengleichheit, fail-closed):

```text
reviewed_engine == resolved_engine ∪ unresolved_engine
reviewed_meta    == resolved_meta    ∪ unresolved_meta
```

Eine falsche Callsite-Zeile, eine fehlende oder überzählige Flowzeile und jeder
**neue** unresolved-Kandidat brechen diese Gleichheit. Zusätzlich müssen
Schema-Ziele als Blob im Base-Tree existieren, `text_only`-Treffer ohne
Engine-Callsite vollständig erklärt sein und genau ein Parsefehler
(`…/invalid.py`) auftreten. Die Falsifikationstests belegen, dass das Gate
manipulierte Manifeste (falsche Zeile, fehlendes Schema, entfernte
Manual-Review-Zeile) tatsächlich ablehnt.

AST-Gleichheit beweist Callsite-Abdeckung innerhalb dieser Grammatik, nicht die
semantische Richtigkeit jeder Schema-Bindung.

## Befund

| Oberfläche | Wert |
|---|---:|
| akzeptierte In-Repo-Flows | 24 |
| semantische Schlüssel | 23 |
| Engine-Callsites inklusive externem Flow | 23 |
| – davon receiver-aufgelöst (`derived_ast`) | 20 |
| – davon `manual_source_review` (Loader-Indirektion) | 3 |
| Modul→Schema-Ziele | 21 |
| akzeptierte Module | 17 |
| akzeptierte Schema-Ziele | 18 |
| externer Flow | 1 |
| Meta-Engine-Callsites | 5 |
| – davon receiver-aufgelöst (`derived_ast`) | 2 |
| – davon `manual_source_review` | 3 |
| manuell gebundene Meta-Schema-Flows | 6 |
| Schema-Dateien (gesamt, abgeleitet) | 54 |
| Schema-Dateien ohne akzeptierte Beziehung (abgeleitet) | 36 |
| Test-Facet-Dateien mit aufgelöster Engine-Callsite | 41 |
| Test-Facet-Dateien nur mit unresolved-Kandidat | 4 |
| Test-Facet-Dateien mit irgendeiner Validierungs-API (Union) | 45 |

Die Einheiten werden nicht zu einer globalen Summe vermischt. Alle Schema- und
Testzahlen werden aus dem Snapshot abgeleitet, nicht hartkodiert.

**Provenienz (derived vs. manual).** Von 23 Engine-Callsites löst die Grammatik 20
über jsonschema-Receiver auf; die übrigen drei
(`lens_card_validate:136`, `pr_delta_card_validate:135`,
`relation_card_validate/_schema_check:159`) beziehen jsonschema über
`_load_jsonschema()`/`importlib` und sind daher `manual_source_review`. Analog
sind 2 der 5 Meta-Callsites `derived_ast`, 3 `manual_source_review`. Die volle
Liste je Klasse steht im `derived`-Report des Audit-JSON.

**Testdatei-Zählung (44/45/41 aufgelöst).** Unter der strengen receiver-aufgelösten
Grammatik enthalten **41** Test-Facet-Dateien eine aufgelöste jsonschema-Engine-
Callsite; **4** weitere (`test_claim_evidence_map`, `test_lens_cards`,
`test_lens_facets`, `test_primary_lens_audit`) enthalten nur unresolved-Kandidaten;
die **Union** ist **45**. Die frühere „45“ war die Union unter einer generischen
`.validate`-Grammatik, die frühere „44“ eine Zwischenregel. Die Differenz ist ein
Grammatik-Artefakt, kein Faktum; alle drei Listen stehen im Audit-JSON.

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
SCRIPT="scripts/proofs/guard_relation_validates_schema_audit.py"
COMMITTED="docs/proofs/guard-relation-cards-v1b-validates-schema-audit.json"

# regenerate the derived report and compare byte-for-byte
python3 "$SCRIPT" --repo "$PWD" --base-sha "$BASE_SHA" --output /tmp/a.json
cmp /tmp/a.json "$COMMITTED"

# falsification tests (the gate must reject tampered manifests)
python3 -m pytest -q \
  merger/lenskit/tests/test_guard_relation_validates_schema_audit.py

# negative control: a tampered manifest must fail closed
python3 - "$COMMITTED" > /tmp/tampered.json <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
d["flows"][0] = d["flows"][0].replace("|39|", "|990|")
print(json.dumps(d))
PY
! python3 "$SCRIPT" --repo "$PWD" --base-sha "$BASE_SHA" \
    --manifest /tmp/tampered.json --output /tmp/rejected.json
```
