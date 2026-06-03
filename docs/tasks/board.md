# Task Board

## Status-Legende
- `partial` – Kernimplementierung vorhanden, Restlücken dokumentiert
- `done` – vollständig abgeschlossen und verifiziert
- `open` – noch nicht begonnen
- `in-progress` – aktiv in Bearbeitung

## Aktive Tasks

| ID | Titel | Status | Evidence | Offene Punkte |
|----|-------|--------|----------|---------------|
| TASK-CTL-004 | Planning Registration Guard | partial | `scripts/docmeta/check_planning_registration.py`, `scripts/docmeta/tests/test_check_planning_registration.py`, `.github/workflows/task-index.yml` | Ratchet/Baseline-Modus fehlt; Frontmatter-Ausnahmefluss nicht contract-stabil; CI report-only, blocking/ratchet ausstehend |
| TASK-BUNDLE-001 | Real Dump Surface Self-Check Gate | done | `merger/lenskit/core/bundle_surface_validate.py`, `merger/lenskit/core/runtime_provenance.py`, `merger/lenskit/cli/cmd_bundle_surface.py`, `merger/lenskit/core/merge.py`, `merger/lenskit/contracts/bundle-surface-validation.v1.schema.json`, `merger/lenskit/tests/test_bundle_manifest_integration.py`, `docs/proofs/real-dump-surface-self-check-proof.md` | `forensic_strict`-CI-Promotion bleibt separater PR (Nicht-Ziel) |
| TASK-SERVICE-001 | rlens post-merge restart smoke | done | `scripts/rlens-post-merge-surface-smoke.sh`, `docs/proofs/rlens-post-merge-restart-smoke-proof.md`, `docs/systemd/rlens.service` | Keine Core-Änderung; der Slice dokumentiert nur, dass `rlens.service` nach Pull/Merge neu gestartet werden muss, und prüft den neuesten Dump maschinenlesbar. |
| TASK-FORENSIC-001 | Forensic Strict CI Canary | done | `.github/workflows/forensic-preflight-canary.yml`, `scripts/proofs/forensic_preflight_ci_canary.sh`, `scripts/proofs/forensic_preflight_calibration.sh`, `merger/lenskit/tests/test_forensic_preflight.py`, `docs/proofs/forensic-preflight-ci-canary-proof.md` | Vollständige blockierende `forensic_strict`-Promotion bleibt Folge-PR nach mehreren stabilen Canary-Läufen; PASS ist kein Truth-Verdict |
| TASK-NOISE-001 | Output Noise Hygiene A2 | done | `merger/lenskit/core/merge.py`, `merger/lenskit/core/output_health.py`, `merger/lenskit/core/post_emit_health.py`, `merger/lenskit/tests/test_output_noise_hygiene.py`, `docs/proofs/output-noise-hygiene-proof.md` | Vollständige `.gitignore`-Semantik und Noise-Ratchet/CI-Blocking bleiben Folge-PRs; `.github/` und `.wgx/` bleiben dumpbar. |
