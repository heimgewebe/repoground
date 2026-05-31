# Changelog

Alle nennenswerten Änderungen an Lenskit werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Das Projekt führt (noch) **keine** formalen Versions-Tags; Einträge sind daher
datums- und Track-basiert. Roadmap-Phasen/Tracks: siehe
[`docs/roadmap/lenskit-master-roadmap.md`](docs/roadmap/lenskit-master-roadmap.md).

## [Unreleased]

### Added
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
