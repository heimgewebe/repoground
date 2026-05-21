# Artifact Evidence Levels

Status: Draft matrix (Phase A policy docs).

Zweck: Definiert Ziel- und Ist-Evidenzniveau unabhängig von Profilnamen.

| level | required roles | required capabilities | required health checks | allowed warnings | forbidden skips | UI wording | agent wording |
|---|---|---|---|---|---|---|---|
| readable | canonical_md, bundle_manifest, pre_emit_health (legacy: output_health) | none beyond baseline runtime | canonical exists/hash ok; pre-health not fail | warn erlaubt, solange nicht fail | missing canonical/manifest/health | "Readable snapshot" | "Use canonical_md as sole truth." |
| navigable | readable + agent_reading_pack + chunk_index_jsonl | basic path/range capability | chunk index hash ok; navigation artifacts present | warn erlaubt bei nicht-strikten checks | missing agent pack/chunk index | "Navigable" | "Use pack for navigation, not proof." |
| citable | navigable + citation_map_jsonl | citation_map_validation_available | citation map validates against canonical ranges | warn bei runtime degradation sichtbar | missing/invalid citation map when requested | "Citable with constraints" | "Cite via citation_map IDs + canonical ranges." |
| range_strict | citable | jsonschema_available + secure_path_resolution_available | range_ref resolution strict ok (no env error) | keine environment_error-Warnung | skipped strict range checks | "Range strict" | "All range refs strictly validated." |
| searchable | navigable + sqlite_index | sqlite_fts5_available | sqlite rows == chunk count; fts non-empty where expected | warn nur wenn searchable nicht angefordert | missing sqlite when profile requires searchable | "Local search ready" | "Use sqlite as cache, never as truth." |
| diagnostic_full | canonical_md, bundle_manifest, pre_emit_health (or legacy output_health), post_emit_health, agent_reading_pack, chunk_index_jsonl, citation_map_jsonl, sqlite_index, dump_index_json, derived_manifest_json, index_sidecar_json, architecture_summary, optional retrieval_eval_json | post_emit_validation_available | post-emit conformance + skipped-role explanations | warn erlaubt, aber sichtbar und begründet | hidden skips for required diagnostics | "Diagnostic full" | "Includes debug sidecars and diagnostics." |
| forensic_strict | all diagnostic_full roles + claim_evidence_map | claim_evidence_map_available + strict capabilities | post-health pass, no skipped required checks, strict redaction policy | keine | any required skip; missing claim map | "Forensic strict (blocked until available)" | "Forensic profile currently unavailable." |

## Hinweis

Evidence-Level sind semantische Zielzustände. Profile sind Presets, die diese Levels anfordern; Health belegt den tatsächlich erreichten Level.

Migrationsregel Health (transitional naming):
- Bestehendes `output_health` entspricht während der Migration vorläufig `pre_emit_health`.
- `post_emit_health` wird zusätzlich eingeführt (post-hoc/zweiter Zeitpunkt).
- Bestehende Consumers von `output_health` bleiben kompatibel, bis der Split vollständig ausgerollt ist.
