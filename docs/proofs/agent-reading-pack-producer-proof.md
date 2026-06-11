# Agent Reading Pack Producer Proof

- Arbeitspaket: D (PR 4) aus `docs/blueprints/lenskit-output-optimierung-v1.md`
- Artefaktrolle: `agent_reading_pack` (`authority=navigation_index`, `canonicality=derived`, `role_only`, `text/markdown`)

## Proof Basis

- Original producer proof basis (v1): 2026-05-20, `b59cf653d8b06012789ec2d14cbe31c8a978d709`
- Front-Door Hardening v1.1 verification basis: current PR commit at verification time
- The v1.1 sentinel and sections below are verified by targeted producer/CLI tests,
  not by the original 2026-05-20 proof run.

## Zweck

Belegt, dass der Agent Reading Pack als deterministisches, schema-valides und
hash-konsistentes Navigations-Einstiegsdokument in das Bundle-Manifest emittiert
wird. Der Pack ist **Navigation, nicht Wahrheit**: kanonische Quelle bleibt
`canonical_md`.

## Reproduktion

`write_reports_v2(..., output_mode="dual")` über ein kleines Repo (3 Quelldateien)
erzeugt ein vollständiges Bundle. Anschließend wird der Pack standalone über das
finalisierte Manifest re-produziert.

```bash
python3 -m merger.lenskit.cli.main agent-pack produce <stem>.bundle.manifest.json --json
```

## Befund (producer and contract verification)

### Manifest-Integration
- `manifest_schema_valid` (gegen `bundle-manifest.v1.schema.json`): **PASS**
- `role == agent_reading_pack` im Manifest: **true**
- `content_type`: `text/markdown`
- `authority` / `canonicality` / `interpretation.mode`: `navigation_index` / `derived` / `role_only`
- `regenerable` / `staleness_sensitive`: `true` / `true`
- `bytes` (Manifest) == Dateigröße: **PASS** (covered by producer/manifest integration tests)
- `sha256` (Manifest) == `sha256(Datei)`: **PASS** (covered by producer/manifest integration tests)

### Determinismus / Idempotenz
- Zwei aufeinanderfolgende Produktionen über dasselbe Manifest: gleiches `output_sha256` → **PASS**
- Standalone-Re-Run reproduziert den Pipeline-Pack **byte-identisch** (`standalone_reproduces_pipeline=true`).
  Beweisrelevant: der Producer überspringt die eigene Rolle (`agent_reading_pack`), daher ändert ein
  bereits im Manifest eingetragener Pack die Ausgabe nicht.
- `| agent_reading_pack |` erscheint nie als Tabellenzeile im Pack (`self_role_not_listed=true`).

### Inhaltliche Kernsektionen (v1.1)
- Sentinel: `<!-- ARTIFACT:agent_reading_pack VERSION:v1.1 AUTHORITY:navigation_index CANONICALITY:derived -->`
- Banner: `NAVIGATION, NOT TRUTH`
- `## BUNDLE_IDENTITY`, `## READING_POLICY`, `## ARTIFACT_ROLES`, `## OUTPUT_HEALTH_SUMMARY`,
  `## HOW_TO_SEARCH`, `## REQUIRED_READING_BY_TASK`, `## WHEN_CANONICAL_MD_ONLY_IS_INSUFFICIENT`,
  `## SIDECAR_USAGE_RULES`, `## ANSWER_COMPLIANCE_CHECKLIST`, `## DO_NOT_CLAIM`,
  `## TOP_CHUNK_SPANS`, `## EPISTEMIC_EMPTINESS`
- Governance-Block in `## TOP_CHUNK_SPANS`: maschinenlesbares JSON mit `applies_to: TOP_CHUNK_SPANS`,
  `risk_class: navigation`, `may_cite: false`, `must_resolve_to: role_specific_authority`,
  `does_not_prove: [semantic_importance, architecture_truth, complete_context]`
- (Migriert aus `## TOP_FILES`, PR A1; interne Konstante `TOP_FILE_LIMIT → TOP_CHUNK_SPAN_LIMIT`)
- Follow-up (post-A1): interne Legacy-Namen `top_files`, `compute_top_files`, `top_file_count`
  bleiben in A1 unverändert (öffentliches Output-Feld / Test-API); separater Cleanup geplant.
- `health_verdict`: `pass`
- `top_file_count`: 3 (canonical Byte-/Zeilenspannen je Quelldatei)
- `artifact_role_count`: 8

### Integritätshärtung
- SHA256-Mismatch von `canonical_md` oder `chunk_index_jsonl` gegenüber dem Manifest ⇒ harter Fehler,
  **kein** Pack wird geschrieben (Test `test_canonical_md_sha_mismatch_fails_hard`).
- **Fehlender oder ungültiger** `sha256` eines Wahrheitsankers ⇒ harter Fehler (kein neutraler Zustand;
  Tests `test_canonical_md_missing_sha_fails_hard`, `test_chunk_index_invalid_sha_fails_hard`).
- Soft-invalid Diagnostic-/Navigation-Artefakte (`output_health`, `sqlite_index`, `citation_map_jsonl`) mit
  Mismatch/fehlendem Hash ⇒ Warnung, Pack wird trotzdem erzeugt, das Artefakt wird jedoch **nicht als aktive
  Navigation gerendert**: FTS-Befehl und Citation-Guidance werden unterdrückt; `EPISTEMIC_EMPTINESS` weist den
  Grund aus (Tests `test_output_health_sha_mismatch_warns_not_fails`, `test_invalid_sqlite_index_suppresses_fts_command`,
  `test_invalid_citation_map_suppresses_citation_guidance`).
- Output-Pfad-Kollision mit **irgendeinem** im Manifest gelisteten Input-Artefakt ⇒ harter Fehler — der Schutz
  umfasst alle nicht-`agent_reading_pack`-Artefaktpfade, nicht nur erfolgreich verifizierte (Tests
  `test_output_collision_with_input_is_rejected`, `test_output_collision_with_unverified_manifest_artifact_is_rejected`).
- Pre-Load-Eingabefehler (Manifest fehlt/JSON kaputt) ⇒ **keine** Mutation bestehender Outputs
  (Test `test_stale_output_preserved_on_missing_manifest`).

### Range-Auflösung zeigt auf das Bundle-Manifest
- `HOW_TO_SEARCH` rendert `range get --manifest "<…>.bundle.manifest.json"` (nicht `dump_index`/`canonical_md`),
  da der Pack aus dem Bundle-Manifest erzeugt wird und dieses die natürliche Auflösungsbasis ist
  (Test `test_how_to_search_resolves_range_against_bundle_manifest`).
- `OUTPUT_HEALTH_SUMMARY` weist transparent aus, dass `agent_pack_present` in v1.1 `skipped` sein kann.
  Grund: In der Pipeline wird `output_health` **vor** der Pack-Emission berechnet — der In-Pipeline-Health-Report
  kann das Artefakt, das er zeitlich vorausläuft, strukturell **nicht** belegen (kein Hellsehen über noch nicht
  geschriebene Dateien). `pass`/`warning`/`fail` für `agent_pack_present` kann nur ein **Post-hoc-Lauf** liefern:
  ein eigenständiger `compute_output_health(..., agent_reading_pack_path=…, agent_reading_pack_expected=True)`
  oder der dedizierte Post-hoc-Validator aus Arbeitspaket H.

### CLI
- `agent-pack produce … --json` Exit-Code: **0**, `status=ok`.
- Fehlendes Manifest: Exit-Code **2**, `error_kind=path_read_error`.

## Front-Door Hardening v1.1

This slice adds task-specific required reading, canonical-md-only insufficiency
boundaries, sidecar usage rules, an answer-compliance declaration checklist and
prohibited claim classes to the existing Agent Reading Pack.

The Agent Reading Pack remains navigation only (`authority=navigation_index`,
`canonicality=derived`). `canonical_md` remains the only content truth. This
slice does not add schemas, sidecars, health gates, retrieval ranking,
consumption tracing or LLM/embedding dependencies.

Does not establish: answer correctness, repo understanding, claim truth, test
sufficiency, runtime correctness, review completeness, change impact or forensic readiness.

Targeted verification for this slice:

```bash
python -m pytest merger/lenskit/tests/test_agent_reading_pack.py merger/lenskit/tests/test_cli_agent_pack.py
```

Result: **50 passed**. The environment also reported one non-failing pytest
configuration warning for the unknown `asyncio_mode` option.

## Bundle-emission consistency guard

Producer and CLI tests prove that the v1.1 producer can render the expected front-door
surface. They do not, by themselves, prove that the tested bundle-emission path loaded
that producer. The manifest integration test therefore resolves the
`agent_reading_pack` artifact from a freshly emitted bundle manifest, reads the emitted
file, and requires the exact `VERSION:v1.1` sentinel, all five v1.1 front-door sections,
`change_impact`, and the boundary that relation or path proximity alone does not prove
change impact. A legacy `VERSION:v1` pack now fails this emission-level check.

`post_emit_health=pass` and `bundle_surface_validation=pass` remain artifact-integrity
and surface-coherence diagnoses. They do not automatically establish that the current
semantic Agent Reading Pack version was emitted, and they do not prove repo
understanding, claim truth, or answer safety. The emission-consistency assertion closes
that regression gap in the test process without promoting either diagnostic to a truth
gate. It does not prove that an already-running rLens service loaded the merged code;
that requires a fresh service load and a new real-dump check.

Targeted emission verification:

```bash
python -m pytest merger/lenskit/tests/test_bundle_manifest_integration.py::test_agent_reading_pack_emitted_schema_valid_and_hashed
```

## Tests

- `merger/lenskit/tests/test_agent_reading_pack.py` — 46 Tests (Producer, Determinismus, Härtung, Output-Kollisionsschutz, Soft-invalid-Rendering, pure Funktionen).
- `merger/lenskit/tests/test_cli_agent_pack.py` — CLI-Smoke.
- `merger/lenskit/tests/test_bundle_manifest_integration.py::test_agent_reading_pack_emitted_schema_valid_and_hashed` — Pipeline-Emission + Schema + Hash.
- `merger/lenskit/tests/test_output_health.py` — `agent_pack_present` Parametrisierung (skipped/pass/warning).
- `merger/lenskit/tests/test_role_completeness.py` — Enum/Schema-Synchronität inkl. neuer Rolle.

Gesamte (nicht-Browser) Suite: **1282 passed, 1 skipped** (`pytest -m "not browser"`, 7 deselected). `tools/parity_guard.py`: **PASS**.

## Abgrenzung / offene Punkte (v2)

Im Pack als `EPISTEMIC_EMPTINESS` ausgewiesen, noch nicht eingebettet:
Top-Level-Architektur, Entry-Points, dedizierter Contracts-Abschnitt,
Artifact-Lookup/Trace/Context-Lookup-Fluss, Driftpunkte, Claim-Evidence-Map
(letztere hängt an Arbeitspaket F). Die blockierende Erzwingung von
`agent_pack_present` ist Arbeitspaket H (Post-hoc-Validator) vorbehalten.
