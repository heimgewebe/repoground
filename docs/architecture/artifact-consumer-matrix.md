# Artifact Consumer Matrix

Status: Draft matrix (Phase A policy docs).  
Scope: repolens, rlens, CLI, health/diagnostics, tests.

Hinweis (Migration): `pre_emit_health` und `post_emit_health` sind Zielrollen. Während der Migration entspricht bestehendes `output_health` vorläufig `pre_emit_health`.

Zweck: Konsumentenlage je Artefaktrolle sichtbar machen, um stille Legacy-Brüche bei Profil-Defaults und Deprecations zu verhindern.

| role | producer | direct consumers | indirect consumers | runtime | required profiles | optional profiles | deprecation candidate | removal blocker | fallback path | tests covering consumer |
|---|---|---|---|---|---|---|---|---|---|---|
| canonical_md | merger pipeline | humans, agent pack, chunker, citation map, health | all profile consumers | all | all | none | no | truth role; mandatory invariant | none | bundle/health/parity tests |
| bundle_manifest | merger pipeline | health, agent pack, tooling, validators | UI summaries, parity, CI | all | all | none | no | registry role; mandatory invariant | none | manifest integration/schema tests |
| output_health | health core (current) | UI badges, CI, diagnostics, existing consumers | profile status summarizers | all | all (migration baseline) | none | no | current manifest/schema role; compatibility until split | evolves to pre_emit_health | output health tests |
| pre_emit_health | future health core (target role; legacy alias: output_health) | UI badges, CI, diagnostics | profile status summarizers | all | all | none | no | mandatory diagnostic baseline after split | current output_health during migration | output health tests |
| post_emit_health | future post-hoc health (target role) | UI badges, CI diagnostics | profile conformance reporting | agent+ runtimes | agent-portable, local-search, debug-full | lean profiles | no | required for strict profile evidence | degrade to pre+warn only | planned post-health tests |
| agent_reading_pack | agent-pack producer | LLM agents, reviewers | guided navigation flows | iOS/service/local | agent-portable+ | lean-readable, lean-evidence | no | primary agent onboarding path | direct canonical + manifest navigation | agent pack + integration tests |
| chunk_index_jsonl | chunker | range/get/query/search tools | citation map validation, diagnostics | all except minimal exports | agent-portable+ | lean profiles | no | required for navigation/search layers | canonical scan only (degraded) | range/query/parity tests |
| citation_map_jsonl | citation producer | citation validate, reviewers | evidence workflows, parity diagnostic | evidence runtimes | lean-evidence+ | lean-readable | no | required for citable level | range refs only (warn) | citation producer/validator tests |
| sqlite_index | sqlite builder | local search/query runtime | eval/diagnostics/search UX | local/service/ci | local-search, debug-full | agent-portable | yes (runtime dependent) | required for searchable level | chunk-index scan fallback | sqlite capability/stale tests |
| dump_index_json | merger index dump | legacy tools, debug scripts | diagnostics | debug/legacy | debug-full | local-search | yes | unknown consumers unresolved | chunk_index_jsonl | sidecar/report parsing tests |
| derived_manifest_json | derived producer | legacy tools, debug scripts | diagnostics | debug/legacy | debug-full | local-search | yes | unknown consumers unresolved | bundle_manifest | schema/role coverage tests |
| index_sidecar_json | sidecar producer | legacy readers/reports | diagnostics | debug/legacy | debug-full | local-search | yes | unknown consumers unresolved | agent_reading_pack + manifest | sidecar/report parsing tests |
| architecture_summary | summary producer | humans, debugging | CI/reporting docs | debug/ci | debug-full | local-search | maybe | unknown downstream tooling | canonical + manifest docs | (to add) |
| retrieval_eval_json | eval producer | CI, diagnostics | parity expected-flag gates | ci/debug | debug-full (when expected) | local-search | maybe | contract tests + CI checks | omit unless expected | retrieval eval + parity tests |
| claim_evidence_map | future producer | forensic/audit workflows | strict evidence gates | future | forensic-strict | none | no | not implemented yet | none | none yet |

## Regeln

- Keine Rolle wird aus einem Default-Profil entfernt, solange `direct consumers` oder `removal blocker` unklar ist.
- Für Kandidaten (`index_sidecar_json`, `dump_index_json`, `derived_manifest_json`) ist mindestens eine Übergangsphase mit Manifest-Warnung Pflicht.
- Diese Matrix ist eine Policy- und Diagnosegrundlage, kein Runtime-Gate per se.
