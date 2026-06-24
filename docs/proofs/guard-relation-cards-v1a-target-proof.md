# Guard Relation Cards v1a (Target Proof)

## Status und Scope

Dieser PR enthält einen diagnosis-only Target-Proof für den ersten Guard-Relation-Slice `tests_by_name`.
Es ist **kein Produktionscode** enthalten. Der Scope ist strikt auf die Untersuchung einer namensbasierten Beziehung (`tests_by_name`) zwischen Testdateien und Zielpfaden begrenzt. Andere Guard-Relation-Kandidaten (z.B. `tests_by_path`, `validates_schema`) wurden in diesem Proof nicht bewertet.

## Live-Basis und Base-SHA

- **Repo**: `/home/alex/repos/lenskit` (heimgewebe/lenskit)
- **Branch**: `docs/guard-relation-cards-v1a-target-proof`
- **Base-SHA**: `58b8453ba6e355ab361743da75466dd6b0cc19a6`

## Belegter Ist-Zustand

- **Facet-Testklassifikation**: `merger/lenskit/core/lens_facets.py` akzeptiert `test_*.py`, `test_*.js`, `*_test.py`, `*.test.ts`, `*.spec.ts` als `test`-Marker. Die öffentliche API liefert Zuweisungen ohne Synthetik; `_normalize_path` bleibt lokal privat.
- **Pfadgrenzen**: C0/C1-Controls, surrogates, whitespace-only, absolute Pfade und Windows-Laufwerke werden am Eingang abgelehnt (Artifact-Boundary).
- **Relation-Card-v1-Grenzen**: Strikt `imports`-only. Die Relationskante `imports` ist fixiert. `S1` bleibt die Evidenzstufe und es findet keine eigenständige Erkennung statt.
- **Validator-Konvention**: Validatoren nutzen Dependency Diagnostics (z.B. jsonschema). Bei Fehlen erfolgt kein automatisches `skipped_unavailable` Minimal-Fallback, wenn es nicht implementiert ist.

## Exakte Klassifikationsmethode

Die Testklassifikation nutzt zwingend die bestehende öffentliche API `infer_facets` aus `merger/lenskit/core/lens_facets.py`. Das Inventar für die nachfolgenden Resolver-Messungen stammt aus dem Git-Baum des dokumentierten Base-Commits und wird vor der Auswertung dedupliziert und sortiert. Der PR-Branch und seine neu hinzugefügte Proof-Datei sind nicht Bestandteil der Messung.

## Regel-Treffer versus eindeutige Pfade

Ein Pfad kann potenziell mehrere Namensregeln erfüllen (obwohl dies hier nicht auftrat). Ein Pfad, der durch das Segment `fixtures` ausgeschlossen wird, gilt nicht als Testpfad.

Die frühere Zahl 209 beruhte auf einer nicht erhaltenen manuellen bzw. substringbasierten Messung und ist deshalb nicht vollständig forensisch rekonstruierbar. Die aktuelle, an den Base-Commit gebundene API-Messung ergibt:
- 208 rohe Markerpfade;
- 1 durch das Segment `fixtures` ausgeschlossenen Raw-Marker;
- 207 kontrollierte Testpfade.

Als mögliche zusätzliche Treffer einer unspezifischen Substring-Suche wurden `merger/lenskit/tests/_test_constants.py` und `scripts/check_no_test_stubs.py` identifiziert. Ohne das damalige Skript werden diese jedoch nicht als bewiesene Ursache der alten Zahl dargestellt.

## Marker-Verteilung und Überschneidungen

- **Gesamtzahl getrackter Pfade**: 589
- **Eindeutige kontrollierte Testpfade**: 207
- **Rohe Marker-Treffer**:
  - `test_*.py`: 202
  - `test_*.js`: 6
  - `*_test.py`: 0
  - `*.test.ts`: 0
  - `*.spec.ts`: 0
- **Fixture-Ausschlüsse**: 18 Dateien besitzen das exakte Pfadsegment `fixtures`. Davon erfüllt genau eine Datei einen rohen Testmarker und wird von `infer_facets()` ausgeschlossen: `merger/lenskit/tests/fixtures/architecture_import_graph/test_c.py`.
- **Markerüberschneidungen**: 0

## Exakte Resolveralgorithmen

Für alle Resolver gelten:
- Source muss durch die Facet-API als `test` klassifiziert sein.
- Source und Target stammen aus demselben deduplizierten und sortierten Snapshot-Inventar.
- Groß-/Kleinschreibung bleibt exakt.
- Testpfade werden als Target ausgeschlossen.
- Keine Behauptung der Existenz außerhalb des Inventars.
- Keine Fuzzy-Suche, keine Pfadnähe, kein Scoring, kein "erster Kandidat".

**Markertransformationen**:
- `test_<name>.py`  → `<name>.py`
- `<name>_test.py`  → `<name>.py`
- `test_<name>.js`  → `<name>.js`
- `<name>.test.ts`  → `<name>.ts`
- `<name>.spec.ts`  → `<name>.ts`

### Variante A (Globaler Basename)
1. Erwarteten Ziel-Basename aus der kontrollierten Testregel ableiten.
2. Im vollständigen Inventar exakt nach diesem Basename suchen.
3. Kandidaten mit Test-Facet entfernen.
4. `0` Kandidaten = `unmatched`.
5. `1` Kandidat = `structurally_matched`.
6. `>1` Kandidat = `ambiguous`.

### Variante B (Kontrollierte Root-Paare)
Mappt basierend auf definierten Präfixen. Im Test verwendete Root-Paare:
- `merger/lenskit/tests/` → `merger/lenskit/core/`
- `merger/lenskit/frontends/webui/tests/` → `merger/lenskit/frontends/webui/`

Für jedes identifizierte Testfile wird geprüft, ob es im Source-Root liegt. Wenn ja, wird der abgeleitete Basename an den Target-Root gehängt. Ist der Pfad im Inventar (und kein Test), gilt er als Kandidat.

### Variante C (Relativer Spiegel)
Sucht das Segment `tests` im Pfad und entfernt es für das Target:
- `<root>/tests/<test_name>` → `<root>/<target_name>`

### Variante D (Explizite Registry)
Eine Registry speichert explizite Zuordnungen. Ihre semantische Qualität hängt von Autorenschaft, Review, Aktualisierung und Driftkontrolle ab; sie ist nicht automatisch wahrer, nur expliziter. Im aktuellen Repository existiert keine solche Registry, weshalb sie quantitativ nicht gemessen wurde.

## Konsistente Messwerte

| Resolver | Structurally Matched (1) | Unmatched (0) | Ambiguous (>1) |
| --- | --- | --- | --- |
| A. Globaler Basename | 42 | 165 | 0 |
| B. Kontrollierte Root-Paare | 30 | 177 | 0 |
| C. Relativer Spiegel | 3 | 204 | 0 |

Die drei strukturellen Treffer von Variante C sind:

1. `merger/lenskit/frontends/webui/tests/test_atlas_payload.js`
   → `merger/lenskit/frontends/webui/atlas_payload.js`
2. `merger/lenskit/frontends/webui/tests/test_materialize.js`
   → `merger/lenskit/frontends/webui/materialize.js`
3. `scripts/docmeta/tests/test_check_planning_registration.py`
   → `scripts/docmeta/check_planning_registration.py`

(Für jede Variante gilt: `matched` + `unmatched` + `ambiguous` == 207 kontrollierte Testpfade)

## Vollständige Liste der strukturellen Kandidaten

<details>
<summary>Strukturell eindeutige Basename-Kandidaten (Variante A)</summary>

| Testpfad | Kandidatenziel |
| --- | --- |
| `merger/lenskit/frontends/webui/tests/test_atlas_payload.js` | `merger/lenskit/frontends/webui/atlas_payload.js` |
| `merger/lenskit/frontends/webui/tests/test_materialize.js` | `merger/lenskit/frontends/webui/materialize.js` |
| `merger/lenskit/tests/test_agent_entry_manifest.py` | `merger/lenskit/core/agent_entry_manifest.py` |
| `merger/lenskit/tests/test_agent_export_gate.py` | `merger/lenskit/core/agent_export_gate.py` |
| `merger/lenskit/tests/test_agent_reading_pack.py` | `merger/lenskit/core/agent_reading_pack.py` |
| `merger/lenskit/tests/test_anti_hallucination_ast_lint.py` | `merger/lenskit/core/anti_hallucination_ast_lint.py` |
| `merger/lenskit/tests/test_anti_hallucination_lint.py` | `merger/lenskit/core/anti_hallucination_lint.py` |
| `merger/lenskit/tests/test_bundle_surface_validate.py` | `merger/lenskit/core/bundle_surface_validate.py` |
| `merger/lenskit/tests/test_citation_id.py` | `merger/lenskit/core/citation_id.py` |
| `merger/lenskit/tests/test_citation_validate.py` | `merger/lenskit/core/citation_validate.py` |
| `merger/lenskit/tests/test_claim_evidence_map.py` | `merger/lenskit/core/claim_evidence_map.py` |
| `merger/lenskit/tests/test_clock.py` | `merger/lenskit/core/clock.py` |
| `merger/lenskit/tests/test_context_quality.py` | `merger/lenskit/core/context_quality.py` |
| `merger/lenskit/tests/test_doc_freshness.py` | `merger/lenskit/core/doc_freshness.py` |
| `merger/lenskit/tests/test_export_safety_report.py` | `merger/lenskit/core/export_safety_report.py` |
| `merger/lenskit/tests/test_federation_query.py` | `merger/lenskit/retrieval/federation_query.py` |
| `merger/lenskit/tests/test_forensic_preflight.py` | `merger/lenskit/core/forensic_preflight.py` |
| `merger/lenskit/tests/test_graph_index.py` | `merger/lenskit/architecture/graph_index.py` |
| `merger/lenskit/tests/test_ipad_fs_scan.py` | `merger/lenskit/frontends/pythonista/ipad_fs_scan.py` |
| `merger/lenskit/tests/test_lens_card_validate.py` | `merger/lenskit/core/lens_card_validate.py` |
| `merger/lenskit/tests/test_lens_cards.py` | `merger/lenskit/core/lens_cards.py` |
| `merger/lenskit/tests/test_lens_facets.py` | `merger/lenskit/core/lens_facets.py` |
| `merger/lenskit/tests/test_lenses.py` | `merger/lenskit/core/lenses.py` |
| `merger/lenskit/tests/test_metarepo.py` | `merger/lenskit/adapters/metarepo.py` |
| `merger/lenskit/tests/test_output_health.py` | `merger/lenskit/core/output_health.py` |
| `merger/lenskit/tests/test_parity_state.py` | `merger/lenskit/core/parity_state.py` |
| `merger/lenskit/tests/test_policy_loader.py` | `merger/lenskit/cli/policy_loader.py` |
| `merger/lenskit/tests/test_post_emit_health.py` | `merger/lenskit/core/post_emit_health.py` |
| `merger/lenskit/tests/test_pr_delta_card_validate.py` | `merger/lenskit/core/pr_delta_card_validate.py` |
| `merger/lenskit/tests/test_pr_delta_cards.py` | `merger/lenskit/core/pr_delta_cards.py` |
| `merger/lenskit/tests/test_pr_explain.py` | `merger/lenskit/cli/pr_explain.py` |
| `merger/lenskit/tests/test_range_resolver.py` | `merger/lenskit/core/range_resolver.py` |
| `merger/lenskit/tests/test_relation_card_validate.py` | `merger/lenskit/core/relation_card_validate.py` |
| `merger/lenskit/tests/test_relation_cards.py` | `merger/lenskit/core/relation_cards.py` |
| `merger/lenskit/tests/test_repo_sync.py` | `merger/lenskit/service/repo_sync.py` |
| `merger/lenskit/tests/test_router.py` | `merger/lenskit/retrieval/router.py` |
| `merger/lenskit/tests/test_runtime_provenance.py` | `merger/lenskit/core/runtime_provenance.py` |
| `merger/lenskit/tests/test_source_acquisition.py` | `merger/lenskit/service/source_acquisition.py` |
| `merger/lenskit/tests/test_stale_check.py` | `merger/lenskit/cli/stale_check.py` |
| `merger/lenskit/tests/test_yaml_compat.py` | `merger/lenskit/core/yaml_compat.py` |
| `scripts/docmeta/tests/test_check_planning_registration.py` | `scripts/docmeta/check_planning_registration.py` |
| `tests/test_parity_guard.py` | `tools/parity_guard.py` |

</details>

## Trennung strukturell versus semantisch

Es ist essenziell zu trennen:
- `invalid_source`: Strukturierter Eingabefehler / Fail-Closed.
- `not_a_test`: Gültiger Pfad, aber keine kontrollierte Testquelle.
- `unmatched`: Kontrollierte Testquelle, kein Kandidat.
- `ambiguous`: Kontrollierte Testquelle, mehrere Kandidaten; keine Auswahl.
- `structurally_matched`: Genau ein Basename-Kandidat.

Ein eindeutiger Basename (`structurally_matched`) bedeutet nur: Im untersuchten Inventar existiert genau ein Nicht-Test-Pfad mit dem erwarteten Basename.
Er bedeutet **nicht**:
- Dieser Test testet genau dieses Modul.
- Der Test deckt das Modul vollständig ab.
- Die Zuordnung ist fachlich korrekt.
- Der Test schützt vor Regressionen.

Die semantische Präzision der strukturell eindeutigen Kandidaten wurde ohne Goldset nicht bestimmt. Im aktuellen Snapshot wurden keine Basename-Ambiguitäten beobachtet. Zukünftige gleichnamige Dateien können zusätzliche Ambiguität erzeugen.

## Consumeranalyse einschließlich Retrieval v2

Kein aktuell implementierter oder verbindlich spezifizierter Consumer benötigt `tests_by_name` oder eine persistierte `tests_by_name`-Card. Retrieval v2 nennt relation-aware Ranking als möglichen Folgescope. Die vorhandene Roadmap legt jedoch weder fest, dass Retrieval v2 gerade `tests_by_name` benötigt, noch dass dafür persistierte Guard Relation Cards erforderlich sind.

## Offene Relationsrichtung

Die Relationsrichtung bleibt offen, bis eine konkrete Consumerfrage festgelegt ist.
- `Target → Test` ist für eine change-zentrierte Frage plausibel ("Welche strukturellen Testkandidaten gehören zu diesem geänderten Ziel?").
- `Test → Target` ist für eine test-zentrierte Frage plausibel ("Welches Ziel legt der Name dieser Testdatei nahe?").
Keine bidirektionale Persistenz wird empfohlen.

## Contractoptionen & Entscheidung

Das Gate für einen persistierten `tests_by_name`-Contract ist vorerst geschlossen.

Ein On-Demand-Matcher ist kein unmittelbarer Folgetask, bleibt aber eine mögliche spätere Evaluationsmaßnahme.

Andere Guard-Relation-Kandidaten und deren mögliche Implementierung wurden in diesem Proof nicht bewertet.

Begründung:
- Kein aktiver oder verbindlich spezifizierter Consumer.
- Semantische Präzision ohne Goldset unbekannt.
- Persistenzbedarf nicht belegt.
- Richtung und Identität hängen vom Consumer ab.

Falls später ein persistierter Contract entsteht, müssen Identität, Source-Kohärenz und Jsonschema-Ausfallverhalten separat entschieden werden. Dieser Proof entscheidet diese Punkte nicht abschließend.

## Bedingte Alternative On-Demand-Matcher

Ein On-Demand-Matcher bleibt eine mögliche spätere Evaluationsmaßnahme, ist aber kein unmittelbarer Folgetask dieses Proofs. Er wird erst sinnvoll, wenn eine konkrete Consumerfrage oder ein Goldset aufgebaut werden soll.

Falls später ein allgemeiner Inventar-Matcher entsteht, ist zu prüfen, ob die bestehende private Normalisierung kontrolliert wiederverwendet werden kann oder ein separater öffentlicher Repo-Path-Refactor gerechtfertigt ist. Dieser Proof entscheidet keinen solchen Refactor.

## Offene epistemische Leerstellen

Es fehlt eine verbindliche Consumerfrage, die `tests_by_name` benötigt und den Persistenzbedarf, die Relationsrichtung sowie die Qualitätsanforderungen festlegt.

## Negativsemantik

Die Negativsemantik der Lens-Karten bleibt erhalten. Die Evidenzstufe `S1` aus `architecture.graph.v1` wird nicht übernommen, da `S1` bei Relation Cards die übernommene Evidenzprovenienz für Importkanten ist. Ein Namensmatch besitzt diese Herkunft nicht.

Für einen möglichen späteren `tests_by_name`-Contract wäre mindestens folgende Negativsemantik erforderlich:

- `test_sufficiency`
- `regression_absence`
- `runtime_correctness`

Eine strukturelle Namenszuordnung behauptet damit weder, dass der Test ausreicht, noch dass er Regressionen ausschließt oder Runtime-Korrektheit beweist.

Diese Liste ist eine vorgeschlagene Contractgrenze. Dieser Proof führt keinen Contract ein.

## Reproduktionshinweise

Das Inventar wird mit
`git ls-tree -r --name-only 58b8453ba6e355ab361743da75466dd6b0cc19a6`
direkt aus dem Git-Baum des dokumentierten Base-Commits gewonnen.

Die Testklassifikation erfolgt über `infer_facets()`. Vor der Messung
wurde verifiziert, dass `merger/lenskit/core/lens_facets.py` gegenüber
diesem Base-Commit unverändert ist.

Das Skript klassifiziert die Pfade via `infer_facets`, schließt Testpfade als Target-Ziele aus und wendet dann deterministisch die Namensderivationen auf die deduplizierte Pfadliste an. Mehrdeutige Treffer (`ambiguous`) werden getrennt von fehlenden Matches (`unmatched`) gezählt.
