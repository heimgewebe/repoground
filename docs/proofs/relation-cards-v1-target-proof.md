# Relation Cards v1 — Target Proof

Status: **abgeschlossen** (Post-Merge). Der Task `TASK-RELATION-CARD-001` ist abgeschlossen und post-merge verifiziert (PR #796, `f12d9e6d`).

Dieser Slice führt eine bewusst kleine, imports-only Relation-Card-Projektion ein:

```text
architecture.graph.v1 → Relation-Card-Producer → relation-card.v1 → Source-aware Validator
```

Relation Cards **erkennen keine Beziehungen**. Sie projizieren bereits erkannte
Graphkanten in kleine, schema-validierte Navigationsobjekte.

## Ausgangslage

- Relation Cards waren im Working Tree **nicht implementiert** (kein
  `relation-card.v1.schema.json`, kein `relation_cards.py`, kein
  `relation_card_validate.py`, keine Tests). Nur Dokumentation nannte sie
  (`docs/architecture/lens-model.md`, `docs/blueprints/lenskit-agent-front-door-hardening.md`).
- Architecture Graph und Importgraph existierten bereits:
  `merger/lenskit/contracts/architecture.graph.v1.schema.json` und
  `merger/lenskit/architecture/import_graph.py:generate_import_graph_document`.
- Der erste Slice ist bewusst **imports-only** und lokal (`file → file`).
- `TASK-RELATION-CARD-001` war nicht vergeben; kein paralleler Branch/PR bearbeitet
  denselben Slice (GitHub: 0 offene PRs; `git ls-remote` zeigt keine
  `*relation*card*`-Branches).
- Base: `origin/main = 6e48bcb3640fc8bddb7e67da779858cf19c38114` (sauber, aktuell).

## Source Authority

```text
architecture.graph.v1
  edge_type   = import
  evidence_level = S1
  source/target node kind = file (lokale Repo-Pfade)
```

Belege am tatsächlichen Code (nicht aus dem Merge-Dump):

| Prämisse | Beleg |
| --- | --- |
| nur `import`-Kanten produziert | `import_graph.py:161-163,261-263`; Fixture `expected.graph.json` (alle 18 Kanten `import`); `coverage.edge_counts_by_type = {"import": 18}` |
| nur `S1` produziert | `import_graph.py:162,262`; Fixture alle `evidence_level: "S1"` |
| File-Node-ID/Pfad | `import_graph.py:110,119` (`node_id = "file:{rel_path}"`, `path = rel_path`); Fixture `file:a.py` → `path: "a.py"` |
| externe Nodes unterscheidbar | `import_graph.py:146-157` (`kind = "external"`, `path = ""`); Fixture `module:os` → `kind: "external"`, `path: ""` |
| lokale `file → file`-Kanten existieren | Fixture: `file:a.py → file:b.py` (Z. 3), `file:pkg/__init__.py → file:pkg/submodule.py` (Z. 1 **und** 2), `file:sub/__init__.py → file:sub/x.py` (Z. 1) |
| Evidence-Form | `import_graph.py:138-143` (`source_path`, `start_line`, `end_line`); `evidence.source_path == src`-Datei |
| Dedup im Sourcegraph | `import_graph.py:269-276` (Key `(src, dst, start_line)`) |
| Sortierung im Sourcegraph | `import_graph.py:267,276` |

Die Arbeitsannahme „`import_graph.py` produziert Python-Importkanten mit
`edge_type=import` und `evidence_level=S1`" wurde am aktuellen Code **bestätigt**.

## Architekturentscheidung

```text
Relation Cards projizieren vorhandene Graphkanten.
Sie erkennen keine Beziehungen selbst.
```

- Der Producer (`produce_relation_cards(graph_mapping)`) liest **keine** Dateien,
  scannt **kein** Repository, ruft **keinen** Git-Prozess auf, baut **keinen**
  Graphen und nutzt **kein** Tree-sitter / keine Textsuche. Einzige Eingabe ist ein
  bereits geladenes `architecture.graph.v1`-Mapping.
- Vor der Projektion wird die Source gegen `architecture.graph.v1.schema.json`
  validiert. Fehlt `jsonschema`, schlägt die Produktion **fail-closed** fehl
  (`SourceValidationError`). Unbekannte/schemawidrige Edge-Typen scheitern bereits
  an dieser Sourcevalidierung — sie werden nicht still ignoriert.

### Adressmodell

Eine Card trägt `source`/`target` als `{ "kind": "repo_path", "path": <repo_path> }`.
`repo_path` verwendet **byte-identisch** dasselbe Facet-v1-/Lens-Card-Pfadpattern
(geprüft in `test_relation_cards.py::TestContract::test_repo_path_pattern_matches_lens_card`
und im ECMAScript-Paritätsgate `test_lens_facet_pattern_ecma.js`). Damit sind
absolute Pfade, `..`-Traversal, Backslashes, Windows-Drive-Präfixe, leere und
whitespace-only Pfade ausgeschlossen.

Bewusste, dokumentierte Abweichung: Die Endpoint-Hülle `{kind: "repo_path", …}`
ist die bestehende `navigation_ref`-Konvention, das innere Feld heißt aber `path`
(der etablierte Repo-Pfad-Feldname der Card-Familie) statt `target`, weil
`source.target`/`target.target` irreführend wäre. Es wird keine neue Metasprache
eingeführt.

### Source Rule / Ableitungsart

```text
relation        = imports                        (const)
source_rule     = architecture_graph_import_edge (const)
derivation_type = heuristic                      (const)
evidence_level  = S1                             (const)
authority       = navigation_index               (const)
canonicality    = derived                        (const)
```

Der aktuelle Repo-Graphproducer verwendet Python-AST.
Die Relation Card selbst trägt jedoch keine Python-AST-Provenienz,
weil architecture.graph.v1 diese Herkunft nicht contractuell enthält.

`derivation_type = heuristic` ist bewusst gewählt (nicht `direct`): Der
zugrunde liegende Importgraph ist ein statisches S1-Heuristik-Artefakt
(`import_graph.py` Docstring: „This artifact is S1 (static heuristic) and does not
represent runtime causality"). Die Heuristik bleibt **sichtbar** und wird nie still
zu einer Runtime-/Kausal-Abhängigkeit aufgewertet.

### Deduplizierung / Determinismus

- Identität einer Card: `(source.path, target.path, evidence.source_path,
  start_line, end_line)`. Exakt identische Cards werden dedupliziert; **distinct**
  Sourcekanten mit unterschiedlichen Evidence-Positionen werden **nicht**
  zusammengelegt (Beleg: `pkg/__init__.py → pkg/submodule.py` Z. 1 und 2 erzeugen
  zwei Cards).
- Sortierung: `(source.path, target.path, relation, evidence.source_path,
  start_line, end_line)`.
- Eingabereihenfolge verändert weder Inhalt noch Reihenfolge der Ausgabe
  (`TestDeterminism`, `TestProducer::test_input_order_does_not_change_output`).
- Keine aktuelle Uhrzeit in der fachlichen Cardidentität.

## Zurückgestellte Relationstypen

Explizit **nicht** in v1 (jeweils nicht ausreichend source-belegt für diesen
deterministischen, lokalen Slice):

- **`mentions`** — bräuchte eine Text-/String-Referenz-Quelle; `import_graph.py`
  emittiert keine `string-ref`-Kanten zwischen lokalen Dateien.
- **`tests`, `validates`** — überschneiden sich mit Guard Relation Cards (Slice 15)
  und würden Test-/Validierungs-Suffizienz suggerieren. Bewusst ausgeklammert
  (`keine Testrelation, keine Validierungsrelation, keine Guardrelation`).
- **`documents`** — bräuchte eine Doc-zu-Code-Quelle, die der Importgraph nicht
  liefert.
- **`produces`, `consumes`** — Artefakt-/Datenfluss-Semantik ohne deterministische
  Graphquelle in v1.
- **`same_surface`** — Surface-Clustering ohne kontrollierte Einzelkanten-Quelle.

Diese Einschränkung ist **kein** Urteil, dass die Typen ungeeignet sind; sie sind
für diesen v1-Slice nur nicht ausreichend source-belegt.

## Externe Nodes

Ausschlusspolicy:

- Projiziert wird nur, wenn **beide** Endpunkte `kind == "file"` sind. Externe
  `module:`-Nodes (`kind == "external"`, `path == ""`) sowie `package`/`module`-Kind-Nodes
  ohne Repo-Pfad werden **deterministisch ausgeschlossen** (übersprungen), bevor ein
  Pfad gelesen wird.
- Eine **eligible** `file → file`-`import`-`S1`-Kante mit ungültigem Datei-Pfad
  (leer, absolut, `..`-Traversal) ist hingegen eine korrupte/feindliche Source und
  schlägt **fail-closed** fehl (`SourceValidationError`) — nicht „still ignoriert".
- Der Contract erweckt nicht den Eindruck, externe Nodes seien unterstützt
  (`endpoint` ist strikt `repo_path`).

Abgrenzung „ignorieren" vs. „fail-closed":

| Fall | Verhalten |
| --- | --- |
| nicht unterstützter, aber schema-valider Edge-Typ (`require`, …) | deterministisch ignoriert |
| `import`-Kante mit `evidence_level != S1` | deterministisch ignoriert |
| Endpunkt ist `external`/`module`/`package` | deterministisch ignoriert |
| schemawidrige Source (z. B. fehlendes `coverage`, unbekannter `edge_type`) | fail-closed an der Sourcevalidierung |
| `file → file`-`import`-`S1`-Kante mit absolutem/Traversal-Pfad | fail-closed (`SourceValidationError`) |
| `jsonschema` fehlt | fail-closed (`SourceValidationError`) |

Die Ausgabe ist damit **keine** vollständige Projektion aller Graphkanten, sondern
eine v1-Projektion der unterstützten Teilmenge.

## Evidence

- **S1 bleibt S1.** `evidence_level` ist `const "S1"`; der Producer kopiert
  ausschließlich S1-Kanten.
- **`heuristic` bleibt sichtbar.** `derivation_type` ist `const "heuristic"`.
- **Keine semantische Aufwertung.** Evidence (`source_path`/`start_line`/`end_line`)
  wird verbatim übernommen und nie erweitert. Der Validator prüft die Erhaltung
  explizit (`evidence_preservation`-Check) und fängt eine Aufwertung selbst dann ab,
  wenn ein permissives Schema sie am Card-Schema vorbeiließe
  (`test_relation_card_validate.py::TestEvidencePreservation`).

## Nicht-Ziele

Dieser Slice führt **nicht** ein:

- automatische Emission;
- Bundle-/Manifestintegration;
- CLI;
- Frontend;
- Retrieval-Reranking;
- Guard Relation Cards (Slice 15);
- Testabdeckungsbewertung;
- Impactanalyse;
- Runtime-Kausalität;
- Cross-Repo-Relationen;
- Symbolrelationen;
- jede Änderung an der Sourcegraph-Produktionslogik (`import_graph.py`,
  `graph_index.py`).

## Öffentliche APIs

```python
# merger/lenskit/core/relation_cards.py
produce_relation_cards(graph_mapping) -> list[dict]

# merger/lenskit/core/relation_card_validate.py
validate_relation_card(card, *, source_graph, schema=None, source_schema=None) -> dict
```

Validator-Checkshape (unverändert aus der Lens-Card-/PR-Delta-Card-Konvention):
`status` / `checks[].name` / `checks[].status` / `checks[].detail` /
`checks[].validation.{mode,engine,reason}` / `dependencies`. Checkreihenfolge:
`schema_validation` → `source_schema_validation` → `source_producer_coherence` →
`evidence_preservation`.

## Gates

Ausgeführte Befehle und reale Ergebnisse (lokal, `jsonschema 4.26.0`,
`pytest 8.3.4`, `ruff 0.15.8`, Node 24-kompatibel):

```text
# 1) Fokussierte Relation-Card-Tests
python3 -m pytest -q merger/lenskit/tests/test_relation_cards.py \
                     merger/lenskit/tests/test_relation_card_validate.py
→ 79 passed

# 2) Graphregressionen
python3 -m pytest -q merger/lenskit/tests/test_architecture_import_graph.py \
                     merger/lenskit/tests/test_graph_e2e.py \
                     merger/lenskit/tests/test_graph_index.py
→ 6 passed

# 3) Anti-Hallucination-Lint-Tests
python3 -m pytest -q merger/lenskit/tests/test_anti_hallucination_lint.py
→ 43 passed

# 4) Vollständiger Lens-Model-Testlauf
Befehlsquelle:
.github/workflows/lens-model.yml

Lokale Ausführung:
isolierter Reparatur-Worktree für PR #796

Workflow-Referenz:
Job: lens-model
Step: Run lens model tests

Ergebnis:
548 passed
# 5) Schema-Metavalidierung (draft-07), inkl. relation-card.v1.schema.json
→ lens-facet/lens-card/pr-delta-card/relation-card: meta-valid

# 6) Ruff (Lens-Model-Core + Tests)
Befehlsquelle:
.github/workflows/lens-model.yml

Lokale Ausführung:
isolierter Reparatur-Worktree für PR #796

Workflow-Referenz:
Job: lens-model
Step: Ruff (lens model core and tests)

Ergebnis:
All checks passed!

# 7) ECMAScript-Pfadpattern-Parität (relation-card in die Parität aufgenommen)
node merger/lenskit/tests/test_lens_facet_pattern_ecma.js
→ lens-facet/lens-card path patterns: ECMAScript Unicode parity OK

# 8) Governance-Lint
python3 -m merger.lenskit.cli.main governance lint
→ PASS (contracts_scanned: 54, errors: 0, deferred: 0), exit 0

# 9) Parity Guard
python3 tools/parity_guard.py
→ [SUCCESS] Parity Check Passed, exit 0

# 10) Planning-Registration-Tests
python3 -m pytest -q scripts/docmeta/tests/test_check_planning_registration.py \
                     merger/lenskit/tests/test_planning_registration_ratchet.py
→ 173 passed

# 11) Planning-Registration-Ratchet
python3 -m scripts.docmeta.check_planning_registration --ratchet \
  --baseline docs/tasks/planning-registration-baseline.json --format json
→ new_findings=0, invalid_exceptions=0, control_errors=0, exit 0
   (Baseline unverändert; keine neue Drift verschluckt)

# 12) git diff --check
git diff --check
→ clean
```

Umgebung: `jsonschema 4.26.0`, `pytest 8.3.4`, `ruff 0.15.8`, `node` (ECMAScript
`u`-Flag-Parität). Die Befehle wurden tatsächlich ausgeführt; die obigen
Ergebnisse sind real.

Hinweis zur Umgebung: Die ursprüngliche Implementierung wurde auf dem durch die Session vorgegebenen
Branch claude/focused-rubin-2q6f4j erstellt.

Die nachfolgende Härtung erfolgte in einem isolierten Git-Worktree
../lenskit-relation-cards-harden, der vom damaligen Remote-PR-Head
8b153298ce51df6cc50cac1a8e23830d87ada4b7 abgeleitet wurde.

Der Härtungscommit wurde nach erneuter Remote-Head-Prüfung ohne Force-Push
auf den bestehenden PR-Branch übertragen.

Die abschließende Reparatur des Evidence-Preservation-Guards und die erneute
Gate-Ausführung erfolgten in einem separaten Reparatur-Worktree für PR #796.

## Post-Merge-Reconciliation
Relation Cards v1 wurden mit PR #796 als Merge-Commit
`f12d9e6d407d2ccc7ff95b29d823795bec24ba93` nach `main` übernommen.
Die folgende fokussierte Regression wurde anschließend auf diesem
`origin/main`-Stand ausgeführt:
```text
python3 -m pytest -q \
  merger/lenskit/tests/test_relation_cards.py \
  merger/lenskit/tests/test_relation_card_validate.py \
  merger/lenskit/tests/test_architecture_import_graph.py
81 passed
```
Zusätzlich bestanden Ruff, Schema-/Workflow-Gates, Planning Registration,
Doc-Freshness und `git diff --check` im Reconciliation-Lauf.

Dieser Nachweis bestätigt ausschließlich den definierten imports-only
Contract/Core/Validation/Test-Slice. Er beweist keine automatische Emission,
Bundle-, CLI- oder Retrieval-Integration, keine Guard Relations und keinen
tatsächlichen Agenten- oder Retrievalnutzen.
