# Instructions for Agents

## Frontend Feature Parity

This repository maintains two frontends:
1.  **RepoGround** (Pythonista UI/CLI) - `merger/repoground/frontends/pythonista/build.py`
2.  **RepoGround** (Web UI) - `merger/repoground/frontends/webui/`

**Rule:** Any new feature added to the backend `JobRequest` model (`merger/repoground/service/models.py`) MUST be implemented in BOTH frontends.

**Verification:**
Always run the parity guard script after modifying the `JobRequest` model or UI components:

```bash
python3 tools/parity_guard.py
```

This script checks for:
*   Backend model definition.
*   CLI arguments in `repoground.py`.
*   HTML IDs in `index.html`.
*   JS payload keys in `app.js`.

See `docs/PARITY_GUARD.md` for details.

## Documentation Order for Parity / Evidence Changes

For repoground-vs-repoground, evidence, or runtime-state changes, read in this order before patching:
1. `docs/roadmap/repoground-master-roadmap.md`
2. `docs/testing/test-matrix.md`
3. Relevant `docs/proofs/*`

The parity-gate terms `content_parity_pass` and `diagnostic_parity_pass` are backed by a production module (`merger/repoground/core/parity_gates.py` + `parity_state.py`) and are enforced via the `repoground parity enforce --require {content,diagnostic}` CLI and the `Parity Gate` CI workflow (`.github/workflows/parity-gate.yml`).
They are not (yet) a service-runtime gate inside the RepoGround service; do not describe them as such. The required level is policy/profile-dependent — capability-degraded iOS/Pythonista hosts may require only `content` (see `docs/architecture/artifact-capability-matrix.md`).

Do not modify generated docs (`docs/_generated/*`) or commit local runtime artifacts. Changes to generated files are only permitted via the owning generator. For doc-freshness, the generator is: `python -m merger.repoground.cli.main doc-freshness update --write`

## Agent Operating Flow

For coding, review, or repository-maintenance work, use this order:

1. **Bind live state:** read the current Git head, dirty state, open PRs, CI, and active worktree/lease ownership.
2. **Choose a task profile:** select the smallest RepoGround profile that matches the question or change boundary.
3. **Read RepoGround evidence:** use bounded RepoGround context and citations for navigation; `canonical_md` remains the only content truth.
4. **Plan in the agent:** the coding agent decides the change and states what it will and will not mutate. RepoGround does not produce review verdicts or autonomous patch decisions.
5. **Execute through Grabowski:** perform writes in an owner-bound isolated checkout. Never reset or reuse foreign dirty work, leases, or processes.
6. **Read back reality:** re-read Git, CI, and relevant runtime state. A failed or ambiguous mutation is not treated as completed until authoritative readback proves it.

Stop without mutation when the current revision, task/claim, lease ownership, or required evidence cannot be established. A RepoGround context pass does not establish correctness, test sufficiency, merge readiness, runtime health, or permission to deploy.

## RepoGround CLI Client vs Service Launcher

`merger/repoground/cli/serve.py` is the RepoGround service entry point / launcher.

The active module-CLI, service launcher, and HTTP service-client boundaries are documented in `docs/blueprints/repoground-cli-operational-blueprint.md`. Agents must not silently reinterpret the launcher as an HTTP client. The older implementation history remains in `docs/blueprints/rlens-cli-client-blueprint.md` and is not the active naming contract. Before changing CLI functionality, read the roadmap and the active operational blueprint.
