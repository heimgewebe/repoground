# Artifact Capability Matrix

Status: Draft matrix (Phase A policy docs).

Zweck: Sichtbar machen, welche Laufzeit welche Prüffähigkeit besitzt und welche Degradation bei fehlenden Capabilities gilt.

| capability | ios/repolens | rlens/service | heim-pc | heimserver | ci | required_for_level | degradation_if_missing | test evidence |
|---|---:|---:|---:|---:|---:|---|---|---|
| jsonschema_available | optional | required for strict | recommended | recommended | required | range_strict | `range_strict` nicht erreichbar; health `warn` bei environment_error | jsonschema degradation + output health tests |
| sqlite_fts5_available | optional | likely | likely | likely | required for search tests | searchable | searchable nicht erreichbar; fallback auf chunk navigation | sqlite capability tests |
| post_emit_validation_available | required for strict agent profile | required | recommended | recommended | required | diagnostic_full / strict profile conformance | nur pre-health möglich, post-status degradiert | planned post-health tests |
| citation_map_validation_available | required for citable | required | recommended | recommended | required | citable | citable nur mit warn/degradation | citation validator tests |
| claim_evidence_map_available | future | future | future | future | future | forensic_strict | forensic_strict blockiert | none yet |
| secure_path_resolution_available | sandboxed | required | required | required | required | range_strict (operational) | range/get eingeschränkt; potential warn/fail depending profile | path security + range tests |
| redaction_enabled | optional | optional | optional | optional | conditional required (if requested) | forensic/secure export policies | sensitive export warn/fail when requested | policy tests pending |
| local_filesystem_access | sandbox-limited | yes | yes | yes | yes | local-search/debug-full operability | limited artifact emissions depending runtime | runtime matrix docs + integration tests |
| ios_sandbox_runtime | yes | no | no | no | no | runtime default selection | profile may degrade to portable-only | runtime docs |
| service_runtime | no | yes | optional | yes | optional | local-search/debug service paths | service-only features disabled | service tests |

## Regel

Ein Profil kann angefordert werden; bestehendes `output_health` (während der Migration: Legacy-Pre-Health) und später `post_emit_health` bestimmen, ob es vollständig erfüllt oder degradiert erreicht wurde.
