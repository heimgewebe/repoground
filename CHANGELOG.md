# Changelog

Alle nennenswerten Änderungen an RepoGround werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Das Projekt führt (noch) **keine** formalen Versions-Tags; Einträge sind daher
datums- und Track-basiert. Roadmap-Phasen/Tracks: siehe
[`docs/roadmap/repoground-master-roadmap.md`](docs/roadmap/repoground-master-roadmap.md).

## [3.0.0] - 2026-07-17

### Changed

- Renamed the public product, repository target, canonical Python namespace and
  command surface to RepoGround / `repoground` / `merger.repoground`.
- Replaced repoLens, rLens and RepoBrief product surfaces with RepoGround
  operations: build, query/search, graph, verify, ground, serve and MCP.
- Added tested 3.x compatibility bridges for existing imports, commands,
  environment variables and the currently running legacy service.
- Preserved persisted 2.x identifiers and immutable historical evidence instead
  of silently rewriting stored bundles or prior proofs.

## [2.4.0-rc.1] - 2026-07-11

### Added

- Deterministic, commit-bound RepoBrief source-candidate archives.
- SHA-256 manifest and checksum verification.
- Hash-locked runtime, development and browser dependency sets.
- Explicit upgrade and rollback procedure.
- Fail-closed licensing boundary for public distribution.

### Distribution boundary

This is an internal verification candidate, not a public software release. The
repository remains governed by `LicenseRef-RepoBrief-All-Rights-Reserved` until
a later owner decision explicitly replaces that boundary.

## [Unreleased]
### Fixed
- **Fleet publication (Bureau #671):** the publisher now uses only canonical RepoGround generator paths, fails the service run on generator or repository errors, and installs the hourly watcher under `repoground-publish-fleet-watch.*`.

### Changed
- **Fleet state projection:** the existing `repobrief.fleet-publication-state.v1` record gains additive source-commit, generator-commit, generator-input, manifest, publication-time, and bounded freshness fields without changing the persisted schema identity.


### Changed

- Relicensed RepoGround source and documentation from a restrictive
  inspection-only boundary to Apache-2.0 following the explicit owner
  decision of 2026-07-18.
- Added a permissive defensive name policy, voluntary-funding principles,
  public name-stewardship record, and free quarterly name-watch process.
- Kept binary, container, model, and bundled third-party publication outside
  the source-only clearance until each exact artifact is reviewed.

### Added
- **Full-Suite-CI-Gate (`test-suite.yml`, Komplettaudit 2026-07):** neuer
  Workflow führt die gesamte pytest-Suite (ohne `browser`/`doc_freshness_live`-
  Marker) sowie alle WebUI-JS-Tests unter Node aus. Bisher waren alle
  Test-Workflows pfad-gescoped, wodurch Feature-/Test-Drift auf `main`
  unsichtbar blieb (4 stale Test-Failures, 10 Browser-Errors). Audit-Register:
  `docs/architecture/inconsistencies.md` §8, Proof:
  `docs/proofs/repo-complete-audit-2026-07-proof.md`,
  Task: `TASK-REPO-FULL-AUDIT-001`.
- **Atlas FTS-Suchindex (Blaupause Phase 4 / ADR-009):** globaler SQLite-FTS5-Index
  unter `atlas/indexes/fts.sqlite` (`merger/lenskit/atlas/index.py`,
  `AtlasFTSIndex`). Löst das lineare JSONL-Scannen der Suchschicht ab —
  Scope/`ext`/Größe/Datum werden aus indizierten SQLite-Spalten bedient
  (Glob-/Name-/Path-Exaktheit und die generische `query`-Substring-Prüfung
  bleiben Python-Postfilter über den SQL-eingegrenzten Kandidaten, nicht via FTS).
  Indizierung läuft als best-effort Derivation-Schritt nach Snapshot-Abschluss;
  `atlas search` nutzt den Index, wenn er alle Kandidaten-Snapshots konsistent
  abdeckt, und fällt sonst transparent auf den linearen Scan zurück. Neue CLI:
  `atlas index rebuild`, `atlas index stats`, `atlas search --all-snapshots`,
  `atlas search --no-index`, `atlas scan --no-index`. Content-Suche: die
  FTS-`content`-Spalte ist vorbereitete Struktur, kein harter Vorfilter —
  alle metadaten-gefilterten Kandidaten werden stets per Live-Scan
  (`_content_match`) bestätigt. Damit sind Freshness-Gaps (Datei nach
  Indizierung mutiert) und alle sonstigen Subtoken-/Unicode-/Punctuation-
  Edge-Cases sicher: die Suche verliert nie Treffer gegenüber dem linearen
  Pfad. `snapshot_coverage_ok()` prüft jetzt zusätzlich die `files_fts`-
  Zeilenparität. Inkl. ADR-009, Auflösung der vier offenen Entscheidungen in
  `docs/architecture/atlas-fts-integration.md` und Tests (`test_atlas_index.py`,
  u. a. Freshness-Regression, Index/Linear-Äquivalenz für Content-Edge-Cases).
- `docs/GETTING_STARTED.md` — Einstieg (Dump erzeugen, Bundle lesen, suchen,
  Fehlerbehebung).
- `CONTRIBUTING.md` — Beitragsrichtlinien (Diagnose-first, Parität, Checks,
  Commit-/Branch-Konventionen, CI-Gates).
- `CHANGELOG.md` — dieses Dokument.
- `docs/glossary.md` — Glossar der load-bearing Begriffe (Artifact-Roles,
  Authority/Canonicality/Risk-Class, Evidence-Levels, Meta-Density, Range-Ref,
  Parity-Gates …).
- `docs/FAQ.md` — häufige Fragen (Range-Ref-Fehler, Ordner-Filter, Index leer …).
- `docs/proofs/weiterentwicklungsplan-2026-05-reconciliation-proof.md` — Abgleich
  eines externen Weiterentwicklungsplans gegen den realen Branch-Stand.
- Range-Resolver: `_load_schema` per `@lru_cache` memoisiert (Schemas sind
  immutable; vermeidet Re-Parse pro Chunk bei großen Bundles) + 2 Tests.

### Fixed
- **Stale Tests nach Artefakt-Erweiterungen (Komplettaudit 2026-07):**
  `test_merges_dir_drift.py` selektiert das Merge-Artefakt jetzt explizit
  (statt `artifact_ids[0]`, das seit TASK-SERVICE-002/003 der
  `pre_pull_report` sein kann); `test_per_repo_cohesion.py` kennt
  `.agent_entry_manifest.json` als Bundle-Level-Suffix; `browser`-markierte
  Tests skippen sauber, wenn pytest-playwright fehlt (Collection-Hook in
  `tests/conftest.py`).
- **Task-Registry-Drift:** `docs/tasks/board.md` und `docs/tasks/index.json`
  reconciled (8 fehlende Index-Tasks, 1 fehlender Board-Task,
  Tabellen-Render-Bruch durch Leerzeile).
- **Fleet-Metadaten:** `.ai-context.yml` und `.wgx/profile.yml` beschrieben
  das Repo `heimgewebe/tools` (bash-Tooling) statt lenskit; auf realen
  Repo-Inhalt korrigiert. Stale Blueprint-Aussage in der Master-Roadmap
  aktualisiert.
- `docs/architecture/system-map.lenskit.md`: veralteter „Bekannte Lücken"-Eintrag
  korrigiert — Föderations-Module sind vorhanden (`core/federation.py` u. a.);
  Status nun konsistent zur Master-Roadmap Phase 4 (vorhanden, Hardening offen).

## Baseline (Stand 2026-05)

Bereits ausgelieferte, getestete Capability-Tracks (Auszug — der Stand, gegen
den „Unreleased" anschließt):

- **Range-/Citation-Fundament:** `chunk_index` dual-range, `range-ref.v1`+`v2`,
  Citation-Map-Producer + Readiness-Validator, Pipeline-Emission ins Manifest
  (Producer gehärtet 2026-05-14).
- **Output-Health:** `output_health.json` mit `fts_content_non_empty`,
  `range_ref_resolution_ok`, `canonical_md_hash_ok`; Post-Emit-Health-Validator.
- **Super-Merger-Extras:** `ExtrasConfig` (Health, Organism-Index, Fleet-Panorama,
  Augment-/JSON-Sidecar, Delta-Reports, Heatmap); Coverage-/Meta-Density-Header;
  `meta_density=auto`.
- **Retrieval:** SQLite-FTS5-Index, Query/Eval/Trace, Graph-aware Reranking,
  Semantic Re-Ranking (Lexical → Embedding) mit `embedding-policy.v1`.
- **Federation:** Init/Add/Validate, föderierte Query, Cross-Repo-Links,
  Conflict-/Trace-Contracts (Hardening laufend).
- **Governance (Track C, C2.1–C2.9):** Authority/Risk-Class-Felder, Inference-
  Boundaries (`allowed/forbidden_inferences`), contract-statischer L3/L5-Lint
  (blockierend), experimenteller marker-gated AST-Lint (L1/L2/L4), Authority-
  Upgrade-Registry, Export-Gate.
- **Atlas:** persistente Snapshots, Delta-Berechnung, Registry/Planner/Search
  (History-Views/Hardening partiell).
- **Frontends/Service:** repoLens-CLI ↔ rLens-WebUI mit Parity-Guard + CI-Gate;
  FastAPI-Service; rLens-CLI-Client.

> Hinweis: „Baseline" ist eine zusammenfassende Momentaufnahme, kein
> Release-Tag. Für die belegte Detail-Historie siehe `docs/proofs/*` und die
> Git-History.
