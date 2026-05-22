# Agent Reading Pack Producer Proof

- Datum: 2026-05-20
- Repo HEAD (Basis): b59cf653d8b06012789ec2d14cbe31c8a978d709
- Arbeitspaket: D (PR 4) aus `docs/blueprints/lenskit-output-optimierung-v1.md`
- Artefaktrolle: `agent_reading_pack` (`authority=navigation_index`, `canonicality=derived`, `role_only`, `text/markdown`)

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

## Befund (frischer Lauf, dump stem `proofrepo-max-…_merge`)

### Manifest-Integration
- `manifest_schema_valid` (gegen `bundle-manifest.v1.schema.json`): **PASS**
- `role == agent_reading_pack` im Manifest: **true**
- `content_type`: `text/markdown`
- `authority` / `canonicality` / `interpretation.mode`: `navigation_index` / `derived` / `role_only`
- `regenerable` / `staleness_sensitive`: `true` / `true`
- `bytes` (Manifest) == Dateigröße: **true** (3990 == 3990)
- `sha256` (Manifest) == `sha256(Datei)`: **true**

### Determinismus / Idempotenz
- Zwei aufeinanderfolgende Produktionen über dasselbe Manifest: gleiches `output_sha256` → **PASS**
- Standalone-Re-Run reproduziert den Pipeline-Pack **byte-identisch** (`standalone_reproduces_pipeline=true`).
  Beweisrelevant: der Producer überspringt die eigene Rolle (`agent_reading_pack`), daher ändert ein
  bereits im Manifest eingetragener Pack die Ausgabe nicht.
- `| agent_reading_pack |` erscheint nie als Tabellenzeile im Pack (`self_role_not_listed=true`).

### Inhaltliche Kernsektionen (v1)
- Sentinel: `<!-- ARTIFACT:agent_reading_pack VERSION:v1 AUTHORITY:navigation_index CANONICALITY:derived -->`
- Banner: `NAVIGATION, NOT TRUTH`
- `## BUNDLE_IDENTITY`, `## READING_POLICY`, `## ARTIFACT_ROLES`, `## OUTPUT_HEALTH_SUMMARY`,
  `## HOW_TO_SEARCH`, `## TOP_CHUNK_SPANS`, `## EPISTEMIC_EMPTINESS`
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
- `OUTPUT_HEALTH_SUMMARY` weist transparent aus, dass `agent_pack_present` in v1 `skipped` sein kann.
  Grund: In der Pipeline wird `output_health` **vor** der Pack-Emission berechnet — der In-Pipeline-Health-Report
  kann das Artefakt, das er zeitlich vorausläuft, strukturell **nicht** belegen (kein Hellsehen über noch nicht
  geschriebene Dateien). `pass`/`warning`/`fail` für `agent_pack_present` kann nur ein **Post-hoc-Lauf** liefern:
  ein eigenständiger `compute_output_health(..., agent_reading_pack_path=…, agent_reading_pack_expected=True)`
  oder der dedizierte Post-hoc-Validator aus Arbeitspaket H.

### CLI
- `agent-pack produce … --json` Exit-Code: **0**, `status=ok`.
- Fehlendes Manifest: Exit-Code **2**, `error_kind=path_read_error`.

## Tests

- `merger/lenskit/tests/test_agent_reading_pack.py` — 24 Tests (Producer, Determinismus, Härtung, Output-Kollisionsschutz, Soft-invalid-Rendering, pure Funktionen).
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
