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
| TASK-NOISE-002 | Real-Dump Noise Hygiene Runtime/Surface Proof | done | `scripts/rlens-post-merge-surface-smoke.sh`, `merger/lenskit/tests/test_rlens_post_merge_surface_smoke.py`, `docs/proofs/output-noise-hygiene-real-dump-proof.md` | Operator-Host-Smoke nach `systemctl --user restart rlens` ist grün; vollständige `.gitignore`-Semantik und Noise-Ratchet/CI-Blocking bleiben Folge-PRs. |
| TASK-SERVICE-002 | rLens Pre-Pull vor Merge (bounded repo-sync mutation) | done | `merger/lenskit/service/repo_sync.py` (two-phase plan/apply), `merger/lenskit/service/models.py`, `merger/lenskit/service/runner.py`, `merger/lenskit/service/app.py` (pre_pull-bewusstes Reuse), `merger/lenskit/cli/cmd_rlens_client.py`, `merger/lenskit/frontends/webui/{index.html,app.js}`, `merger/lenskit/frontends/pythonista/repolens.py`, `tools/parity_guard.py`, `merger/lenskit/tests/{test_repo_sync,test_service_runner_pre_pull,test_service_reuse,test_cli_rlens_client,test_pythonista_pre_pull}.py`, `merger/lenskit/frontends/webui/tests/test_pre_pull_payload.js`, `docs/service-api.md` | Zweiphasig fast-forward-only über alle Surfaces; `effective_pre_pull = pre_pull and not plan_only`; abschaltbar (`pre_pull`, Default an). Clone fehlender Repos, Omnipull-Vollintegration und Auto-Restart des Self-Repos bleiben bewusst Nicht-Ziele. |
