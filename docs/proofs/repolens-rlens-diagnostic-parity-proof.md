# repolens ↔ rlens Diagnostic Parity Proof

- Datum: 2026-05-21
- Repo HEAD (Basis): 0daf0518488bf3a0d5ba9d3388421fdff18113c4
- Roadmap-Item: PR 4 — "repolens diagnostic parity hardening"

## Zweck

Belegen, dass `repolens` (CLI/Pythonista-Frontend) und `rlens` (Service)
nicht nur **Content-Paritaet**, sondern auch **Diagnostic-Paritaet** erreichen,
wenn sie auf derselben Quelle durch dieselbe `write_reports_v2`-Pipeline laufen
und der Host die erforderlichen Capabilities bereitstellt (`jsonschema`,
`sqlite`/`fts5`). Der Beweis nutzt den realen Gate-Runtime
(`build_parity_state` + `evaluate_parity_gates`) gegen echte Bundle-Manifests,
nicht handgebaute State-Dicts.

## Methode

1. Golden-Repo mit Code- und Doc-Datei anlegen.
2. `run_rlens_fixture` und `run_repolens_fixture` (beide rufen
   `write_reports_v2` mit identischer Konfiguration; nur `generator.name`/
   `generator.platform` unterscheiden sich) erzeugen je ein vollstaendiges
   Bundle inklusive Bundle-Manifest.
3. `build_parity_state(left_manifest, right_manifest)` baut den kanonischen
   State; `evaluate_parity_gates` wertet beide Gates aus.

Belegt durch `merger/lenskit/tests/test_parity.py::test_e2e_repolens_rlens_reach_diagnostic_parity`
und `::test_e2e_parity_enforce_cli_on_real_bundles`.

## Ergebnis (State-Dict)

```json
{
  "source_paths_equal": true,
  "source_sha256_equal": true,
  "source_chunk_coverage_equal": true,
  "fts_logically_equal": true,
  "output_health_verdict_pass": true,
  "range_ref_resolution_ok": true,
  "no_health_errors": true,
  "no_health_warnings": true,
  "manifest_hash_bytes_consistent": true,
  "retrieval_eval_json_expected": true,
  "retrieval_eval_json_manifested": true,
  "citation_map_jsonl_expected": true,
  "citation_map_jsonl_valid": true,
  "fts_non_empty_expected": true,
  "fts_non_empty": true
}
```

- `content_parity_pass`: True
- `diagnostic_parity_pass`: True
- `content_reasons`: []
- `diagnostic_reasons`: []

Verglichene Artefakte (in beiden Bundles vorhanden, kein left/right-only):

```
agent_reading_pack, canonical_md, chunk_index_jsonl, citation_map_jsonl,
derived_manifest_json, dump_index_json, index_sidecar_json, output_health,
retrieval_eval_json, sqlite_index
```

## Profilgrenze (iOS/Pythonista)

Diagnostic-Paritaet ist capability-abhaengig, nicht frontend-abhaengig. Die
`repolens`-Pipeline ist identisch mit `rlens`; ob volle Diagnostic-Paritaet
erreicht wird, haengt am Host:

| Capability | volle Diagnostic-Paritaet | bei Fehlen (Degradation) |
|---|---|---|
| `jsonschema` | erforderlich fuer `citation_map_jsonl_valid` | Citation-Validierung degradiert → Diagnostic-Paritaet faellt auf Content-Paritaet + verbleibende Diagnose |
| `sqlite`/`fts5` | erforderlich fuer `fts_non_empty` / `sqlite_index` | Search/FTS-Diagnose degradiert; Content-Paritaet bleibt (gleich leere FTS bricht Content-Paritaet nicht) |

Auf vollwertigen Hosts (CI, heim-pc, heimserver, rlens/service) erreicht
`repolens` Diagnostic-Paritaet. Auf eingeschraenkten iOS/Pythonista-Hosts ohne
`jsonschema`/`fts5` ist die explizite Profilgrenze: Content-Paritaet bleibt
verbindlich, Diagnostic-Artefakte degradieren gemaess
`docs/architecture/artifact-capability-matrix.md`. Die Policy wird per
`lenskit parity enforce --require {content,diagnostic}` durchgesetzt:
eingeschraenkte Profile fordern `content`, vollwertige Profile `diagnostic`.

## Grenze des Belegs

Dieser Beleg ist ein **Pipeline-/Host-Beleg auf vollwertigem Host** mit
`jsonschema` und `sqlite`/`fts5` verfuegbar. Er belegt nicht, dass ein echter
iOS/Pythonista-Host ohne `jsonschema` oder ohne FTS5-Capability dieselbe
Diagnostic-Paritaet erreicht. Fuer solche Hosts mit degradierten Capabilities
bleibt die explizite Profilgrenze aus
`docs/architecture/artifact-capability-matrix.md` (Abschnitt
"Diagnostic-Paritaet als Profilgrenze") gueltig: Diagnostic-Parität ist
capability-abhängig, nicht frontend-abhängig; repolens auf solchen Hosts muss
nur Content-Paritaet garantieren.

## Einordnung

- Erfuellt das Roadmap-Item "repolens diagnostic parity hardening" (PR 4) mit
  E2E-Beleg statt nur Gate-Unit-Tests.
- `content_parity_pass`/`diagnostic_parity_pass` sind ab jetzt nicht mehr nur
  dokumentierte Test-Semantik, sondern via `lenskit parity enforce` und dem
  `Parity Gate`-CI-Workflow erzwungen.
