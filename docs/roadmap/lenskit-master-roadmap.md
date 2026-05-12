# Lenskit Master Roadmap

## Zweck
Diese Datei ersetzt keine Fachblueprints und keine Architekturdocs.
Sie ordnet vorhandene Roadmaps in eine Reihenfolge, klärt Rollenbegriffe und verhindert Drift.
Leitlinien:
- Diagnose-first.
- Keine Pfad-Erfindung.
- Keine Implementierung in diesem PR.
- Keine Blaupausen-Megafusion.

## Prüfgrundlage
Prüfung erfolgte im aktuellen Branch per `test -f` und `rg`.
Gefunden:
- `docs/lenskit-upgrade-blaupause.md`
- `docs/atlas-blaupause.md`
- `docs/architecture/inconsistencies.md`
- `docs/architecture/artifact-inventory.md`
- `docs/architecture/artifact-drift-matrix.md`
- `docs/architecture/runtime-matrix.md`
- `docs/architecture/two-layer-artifact-pattern.md`
- `docs/contracts/contracts-matrix.md`
Optional erwartet, nicht im aktuellen Branch vorhanden:
- `docs/blueprints/lenskit-output-optimierung-v1.md`
- `docs/blueprints/range-ref-v2-semantic-boundary-split-preimage.md`
- `docs/blueprints/lenskit-evidence-address-architecture.md`
Einordnung:
- Fehlende `docs/blueprints/*`-Pfade werden nicht als kanonische Repo-Dateien behandelt.
- Evidence-Address-Architektur kann als aktueller PR-Kontext oder geplanter Blueprint existieren.
- In diesem Branch ist dafür kein Datei-Nachweis unter `docs/blueprints/` vorhanden.
Diagnosebefunde für Terminologie:
- Historische Begriffe (`chunk_index_sqlite`, `derived_index_json`) sind noch in älteren Blaupausen sichtbar.
- Kanonisch im Rollenmodell sind `sqlite_index` und `derived_manifest_json`.
- `output_health` ist in dieser Roadmap ein geplanter Health-/Diagnose-Track für spätere Citation-/Evidence-Prüfung, aber im aktuellen Branch nicht als vorhandene Bundle-Manifest-ArtifactRole zu behandeln.
- Federation ist nicht null, sondern partial/minimal vorhanden; Hardening offen.

## Namensdisziplin / Artifact Roles
| Alt / konzeptionell | Kanonisch |
| --- | --- |
| `merge_md` | `canonical_md` als ArtifactRole; `merge.md` als kanonisches Markdown |
| `chunk_index_sqlite` | `sqlite_index` |
| `derived_index_json` | `derived_manifest_json` |
| `*.derived_index.json` | Dateiname zur Role `derived_manifest_json` |
| `output_health_json` / `output_health` | `output_health` ist als Bundle-Manifest-ArtifactRole vorhanden und wird als Diagnoseartefakt emittiert; Citation-/Evidence-Health-Erweiterung bleibt geplant |
| `citation_map_jsonl` | Manifest-Role registriert; `derived`/`navigation_index`; kein Producer vorhanden |
Zusatz:
Rollenamen folgen `bundle-manifest.v1.schema.json`, nicht älteren Blueprint-Begriffen oder Dateinamen.

## Konfliktauflösung
1. Range-/Citation-Grundlagen vor Query-/Agent-/UI-Ausbau.
2. `citation_map_jsonl` ersetzt nicht `chunk_index_jsonl`.
3. `range-ref.v2` bleibt docs-first und v1-kompatibel.
4. `bundle_manifest` ist perspektivisch zentrale Registry; `dump_index_json` und `derived_manifest_json` bleiben Views bis zur Konsumentenmatrix.
5. Atlas bleibt Paralleltrack und blockiert Lenskit Evidence Addressing nicht.
6. Federation-Hardening erst nach lokaler Evidence-Address-Stabilisierung.
7. Semantic/Reranking erst nach Belegadressierung sowie Query-/Trace-Grundlagen.

## Gemeinsame Umsetzungsreihenfolge

### Phase 0 - Roadmap-Konsolidierung
Aktueller PR:
- [x] `docs/roadmap/lenskit-master-roadmap.md`
- [x] optionale kleine Korrektur in `docs/architecture/inconsistencies.md` bei belegtem Altbefund (Phase-6-Altbefund `agent_query_session` als resolved/closed dokumentiert)
Gate:
- keine widersprüchlichen Rollennamen
- keine erfundenen Blueprint-Pfade
- Reihenfolge Range/Citation vor Query/Agent/Federation/UI festgelegt

### Phase 1 - Range- und Citation-Fundament
Spätere PRs:
- [x] `docs/architecture/range-semantics.md`
- [x] `docs/proofs/citation-map-artifact-fit.md`
- [x] `citation-map.v1.schema.json` plus minimale Beispiele plus Schema-Test
- [x] Bundle-Manifest-Role `citation_map_jsonl`
- [x] `chunk_index` dual range mit `content_range_ref`, `canonical_range`, `source_range`
- [ ] Citation-Map-Producer, geplante Citation-/Evidence-Health-Prüfung in separater Folge-PR, Real-Dump-Proof
  - **Blocker (Diagnose 2026-05-12):** Real-Dump nicht verfügbar; Konsument nicht im Code definiert; Citation-Id-Regel nicht in Code fixiert. Siehe `docs/proofs/citation-map-producer-diagnosis.md`. Nächste Vorbedingungen: 1) Real-Dump mit dual ranges bereitstellen, 2) Konsument oder Validator benennen, 3) Citation-Id-Derivation als `core/citation_id.py` implementieren.
Gate:
- `citation_map_jsonl` nie `canonical_content` oder `content_source`
- `canonical_range` und `source_range` getrennt
- Backcompat: alte Bundles ohne Citation Map brechen nicht

### Phase 2 - Query / Context / Trace
Spätere PRs:
- Query-Ergebnisse referenzieren optional `citation_id`
- Context Bundle referenziert Citations, erfindet sie nicht
- Trace macht Provenance sichtbar
Gate:
- lokale Citation Map validiert
- Context/Trace E2E nachweisbar

### Phase 3 - Graph Runtime
Spätere PRs:
- Graph verbessert Retrieval optional
- Graph ersetzt kein Evidence Addressing
- Recovery-/Policy-Hardening separat abschließen
Gate:
- Graph-Einfluss erklärbar und rückverfolgbar

### Phase 4 - Federation / Cross-Repo
Spätere PRs:
- erst nach lokal stabiler Evidence Address
- Identity Engine und Conflict Handling härten
- `cross_repo_links` und `federation_conflicts` als partial/minimal weiterführen
Gate:
- lokale Citation-/Range-Semantik stabil
- Cross-Bundle-Konfliktstatus sichtbar

### Phase 5 - Agent Control Surface
Spätere PRs:
- Agent Profiles, Query Sessions, Evidence Packs, MCP nach Query/Trace/Citation-Grundlagen
- Agent nutzt Evidence, erzeugt aber keine Citation-Wahrheit
Gate:
- Evidence refs validierbar
- Unsicherheit und Provenance sichtbar

### Phase 6 - UI / Service / Produktisierung
Spätere PRs:
- UI zeigt Status und Provenance
- Service/API erzeugt keine neue Wahrheitsschicht
Gate:
- Artifact Lookup stabil
- Sicherheits- und Backcompat-Guards grün

### Phase 7 - Semantic / Reranking
Spätere PRs:
- Semantic Retrieval und Reranking nach Evidence Addressing
- Retrieval-Eval-Härtung fortführen
Gate:
- Ranking-Verbesserung ersetzt keine Belegqualität

## Paralleltrack Atlas
- Atlas = physische Wahrnehmung / Filesystem-Snapshot
- Lenskit = Knowledge Compiler / Evidence Runtime
- Details bleiben in `docs/atlas-blaupause.md`
- Atlas blockiert Range-/Citation-Fundament nicht
Optionale spätere Stichpunkte:
- Cross-root growth reports
- Content parser policy
- Remote collector / SSH model
- Watch-mode event schema
- Knowledge-map output

## Statusmodell
- `implementation`: `none` | `partial` | `done`
- `tests`: `missing` | `partial` | `present`
- `hardening`: `missing` | `partial` | `complete`
- `gate`: `open` | `passed`
Begründung:
- Historische `[x]`-Listen bleiben lesbar.
- Die Master-Roadmap trennt Implementation, Tests, Hardening explizit.

## Nicht jetzt
- keine UI vor Citation-/Query-Grundlagen
- keine Federation-Härtung vor lokaler Evidence Address
- kein Evidence Use in Citation Map v1
- keine SQLite-Wahrheit
- keine Löschung von `dump_index_json` oder `derived_manifest_json` ohne Konsumentenmatrix
- keine semantische Reranking-Priorisierung vor Belegadressierung
- keine Einführung von `output_health` als ArtifactRole ohne eigenen Contract-/Manifest-PR
- keine Implementierung in diesem PR

## Nächste konkrete PRs
PR 0:
- [x] `docs/roadmap/lenskit-master-roadmap.md`
- [x] optionale kleine Korrektur in `docs/architecture/inconsistencies.md`, nur bei belegtem Altbefund (belegter Altbefund vorhanden und minimal eingeordnet)
PR 1:
- [x] `docs/architecture/range-semantics.md`
- [x] `docs/proofs/citation-map-artifact-fit.md`
PR 2:
- [x] `citation-map.v1.schema.json` (`merger/lenskit/contracts/citation-map.v1.schema.json`)
- [x] minimale Beispiele (`merger/lenskit/contracts/examples/citation_map_minimal.jsonl`)
- [x] Schema-Test (`merger/lenskit/tests/test_citation_map_schema.py`)
PR 3 (teilweise erledigt):
- [x] Bundle-Manifest-Role `citation_map_jsonl`
- [x] Chunk-Index dual range (`canonical_range`, `source_range` zusätzlich zu `content_range_ref`)
- [ ] Citation-Map-Producer plus Real-Dump-Proof
Diagnosehinweis für Priorisierung:
- `merge.md` bleibt kanonische Vollquelle; JSON-Artefakte sind Einstieg/Index/Metadaten.
- Ein schwacher Retrieval-Eval-Stand priorisiert Evidence-/Retrieval-Grundlagen vor Semantic/Reranking.
