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
