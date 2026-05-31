# Instructions for Agents

## Frontend Feature Parity

This repository maintains two frontends:
1.  **repoLens** (Pythonista UI/CLI) - `merger/lenskit/frontends/pythonista/repolens.py`
2.  **rLens** (Web UI) - `merger/lenskit/frontends/webui/`

**Rule:** Any new feature added to the backend `JobRequest` model (`merger/lenskit/service/models.py`) MUST be implemented in BOTH frontends.

**Verification:**
Always run the parity guard script after modifying the `JobRequest` model or UI components:

```bash
python3 tools/parity_guard.py
```

This script checks for:
*   Backend model definition.
*   CLI arguments in `repolens.py`.
*   HTML IDs in `index.html`.
*   JS payload keys in `app.js`.

See `docs/PARITY_GUARD.md` for details.

## Documentation Order for Parity / Evidence Changes

For repolens-vs-rlens, evidence, or runtime-state changes, read in this order before patching:
1. `docs/roadmap/lenskit-master-roadmap.md`
2. `docs/testing/test-matrix.md`
3. Relevant `docs/proofs/*`

The parity-gate terms `content_parity_pass` and `diagnostic_parity_pass` are backed by a production module (`merger/lenskit/core/parity_gates.py` + `parity_state.py`) and are enforced via the `lenskit parity enforce --require {content,diagnostic}` CLI and the `Parity Gate` CI workflow (`.github/workflows/parity-gate.yml`).
They are not (yet) a service-runtime gate inside the rLens service; do not describe them as such. The required level is policy/profile-dependent — capability-degraded iOS/Pythonista hosts may require only `content` (see `docs/architecture/artifact-capability-matrix.md`).

Do not modify generated docs (`docs/_generated/*`) or commit local runtime artifacts. Changes to generated files are only permitted via the owning generator. For doc-freshness, the generator is: `python -m merger.lenskit.cli.main doc-freshness update --write`

## rLens CLI Client vs Service Launcher

`merger/lenskit/cli/rlens.py` is the rLens service entry point / launcher.

A planned rLens CLI client must be treated separately and is described in `docs/blueprints/rlens-cli-client-blueprint.md`. Agents must not silently reinterpret the launcher as an HTTP client. Before implementing CLI functionality, read the roadmap and blueprint.
