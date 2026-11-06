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
2. **Choose a task profile only when needed:** use Git and direct file reads for ordinary code, diff and test questions. Only seek a bounded RepoGround profile when published snapshot status, historical provenance or cross-repository S1 evidence could change the answer.
3. **Read RepoGround evidence only when relevant:** compare source/revision and SHA-256 of the *bundle manifest*, declared *artifact* and embedded *pack/evidence* separately. A published S1 relation proves only its source-bound declaration, not a built or running service. `canonical_md` remains source-content truth.
4. **Plan in the agent:** the coding agent decides the change and states what it will and will not mutate. RepoGround does not produce review verdicts or autonomous patch decisions.
5. **Execute through Grabowski:** perform writes in an owner-bound isolated checkout. Never reset or reuse foreign dirty work, leases, or processes.
6. **Read back reality:** re-read Git, CI, and relevant runtime state. A failed or ambiguous mutation is not treated as completed until authoritative readback proves it.

Stop without mutation when the current revision, task/claim, lease ownership, or required evidence cannot be established. A RepoGround context pass does not establish correctness, test sufficiency, merge readiness, runtime health, or permission to deploy.

## Using RepoGround as an actual agent tool (selective, evidence-based)

**Current operational decision (2026-11-06):** RepoGround is productive but **optional**.
Two separate, frozen, real Codex A/C task pairs showed different uses: the
ordinary Nixer source-diff case had **zero MCP calls** and no attributable benefit;
the published Nixer S1-evidence case had nine MCP calls, five byte-/SHA-verified
content reads and an otherwise Git-inaccessible publication-status answer.
That single positive pair took 27.13% less wall time and 35.82% fewer input
tokens; neither speedup nor broad agent quality is established causally or
statistically. The 2026-10-27 [mass-expansion program](docs/roadmap/repoground-massive-expansion-program.md)
remains historical planning, **not a standing mandate** to expand features or
require RepoGround before ordinary Git work. No new global adoption gate.

1. For ordinary code questions, diffs, local symbol inspection, basic PR review
   and test selection, **start with Git and bounded direct source reads**.
   Do not fetch RepoGround solely because an MCP tool is connected.
2. For questions whose answer depends on a *published* bundle, its freshness,
   manifest/artefact hashes, explicit S1 cross-repository relationships or
   evidence gaps, use the smallest healthy, revision-bound RepoGround reader.
   Check the original manifest and the referenced artifact's exact hash; keep
   `manifest_sha256`, the role's `artifact.sha256`, `pack_sha256` and
   `evidence_sha256` distinct. A missing publication is **unknown**, not
   proof of a missing source dependency.
3. Treat S1 Flake declarations as source-bound facts only. Verify source Git
   blobs when they matter; separately inspect Nix evaluation, built closure,
   active generation and real service status before any runtime assertion.
   Read-only resource metadata or unverified MCP content does not establish
   verified artifact-byte use; do not label that automatically a transport
   failure. Never invent a runtime dependency from a static relation.
4. When RepoGround is missing, stale, ambiguous or forbidden, continue via
   Git and relevant primary sources. Do not add stop gates, extra releases or
   repeated trials merely to satisfy retrieval. Do not generalize a one-pair
   descriptive performance difference.
5. This repository's instructions do not configure Claude, Codex or Grabowski
   in other repositories. Any separate consumer integration needs its own
   narrowly scoped change and live readback.

This remains a non-agentic, deterministic read surface. RepoGround does not approve
patches, tests, merges, releases, or deployments.

## RepoGround CLI Client vs Service Launcher

`merger/repoground/cli/serve.py` is the RepoGround service entry point / launcher.

The active module-CLI, service launcher, and HTTP service-client boundaries are documented in `docs/blueprints/repoground-cli-operational-blueprint.md`. Agents must not silently reinterpret the launcher as an HTTP client. The older implementation history remains in `docs/blueprints/rlens-cli-client-blueprint.md` and is not the active naming contract. Before changing CLI functionality, read the roadmap and the active operational blueprint.