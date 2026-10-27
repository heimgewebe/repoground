# RepoGround deterministic event handoff (Thread 3, implementation wave 2)

**Status:** isolated implementation and tests only. This is a **write-side adapter** for a caller that already has authority to process Git/CI events. It does not itself register a webhook, poll GitHub, alter CI, deploy a service, notify an agent, or authorize a review/merge.

## Existing architecture and lifecycle

The current `repoground-publish-fleet-watch.timer` triggers the already present fleet publisher hourly; this module deliberately **does not add a competing scheduler**. A future publisher hook can invoke this script with an authenticated and validated event after that publisher has completed any allowed publication. There is **no such production hook wired by this branch yet**.

The event handler relies on the existing source-bound `build_evidence_pack` interface from the preceding Thread 3 consumer branch. It uses Git objects already present locally and a bundle already published; it does not refresh or generate bundles. Thread 1 graph and Thread 2 federation implementation files remain untouched.

## Publisher-facing CLI

Run only from an authorized operator-controlled publishing step, with an explicit writable outbox **outside the source checkout**.

```bash
python scripts/repoground-event-handoff.py \
  --repo-root /absolute/checked-out/repo \
  --outbox-root /absolute/managed/publisher/outbox \
  --bundle-manifest /absolute/existing.bundle.manifest.json \
  --event-file /absolute/authenticated-event.json \
  --format json --max-events 1

# Explicit bounded replay/backfill, at most 16 JSONL events:
python scripts/repoground-event-handoff.py \
  --repo-root /absolute/checked-out/repo \
  --outbox-root /absolute/managed/publisher/outbox \
  --event-file /absolute/replayed-events.jsonl \
  --format jsonl --max-events 16
```

Example event **shape** only, not a verified real webhook (40 lowercase hex commit IDs required in both fields):

```json
{
  "event_type": "git.commit",
  "event_id": "delivery-id-from-publisher",
  "repository": "heimgewebe/repoground",
  "base_revision": "0000000000000000000000000000000000000000",
  "target_revision": "1111111111111111111111111111111111111111"
}
```

A `ci.completed` event additionally needs `check_id` and `ci_conclusion`. The CI conclusion is **publisher-supplied metadata, not independently verified status**. The Git SHA names actual local commit objects, and the handler fails closed when a commit is missing, an event has changed identity, or the diff/report exceeds limits.

## Agent-visible read-only receipt lookup

Once an authorized publisher has generated an event receipt and passed its
SHA-256 `event_key`, any separately authorized local consumer can retrieve
**exactly that receipt** without running Git, creating a lockfile, refreshing
a bundle or writing to the outbox:

```bash
python scripts/repoground-event-handoff.py \
  --outbox-root /absolute/managed/publisher/outbox \
  --read-event-key <64-lowercase-hex-event-key>
```

The response includes the stored Evidence Pack, event source, SHA-256
`receipt_sha256`, and explicit freshness and authorization limits. The
reader validates event-key identity, input-event digest, stored Evidence Pack
digest and the base/target revision binding. Unknown keys return unavailable;
invalid or tampered receipts fail closed. The publisher alone owns writes.
In the isolated source lane this behavior is covered by three additional tests;
the updated focused combined event test suite passed **69 tests**.

## Dedup, concurrency and provenance

A canonical SHA-256 event identity is formed from event type, delivery ID and declared repository. The complete input event has a separate SHA-256; reusing the same identity with different input is an explicit conflict. The same event replay returns the identical persisted receipt with status `deduplicated`. Different event IDs are different events; this layer does not infer semantic equivalence from Git commit or content.

The **single** explicit publisher outbox is also the receipt store, not a second authoritative event ledger. One flock on its lockfile serializes concurrent writers; each canonical event gets one JSON receipt through write+fsync+atomic rename+directory fsync. No transient candidate work queue, magic `latest` pointer or implicit snapshot rebuild is introduced. The durable receipt records an event input hash, event key, Evidence Pack, pack SHA-256, revision/diff information, bundle provenance, model-independent consumer hint and explicit `does_not_establish` caveats.

The handler does **not** treat event fields as executable instructions. It does not fetch external Git objects or trigger code execution beyond read-only Git diff subprocess calls already allowed in the Evidence Pack. Each process consumes at most 16 explicitly supplied events, with one finite evidence computation per new identity. A failed batch can partially append receipts for earlier valid events; replay is safe and fills only missing events. Invalid JSON and schema errors are rejected before a new event is processed.

Event producer authentication, CI webhook verification, event age/lag metrics, scheduling/rate-limiting between invocations, fleet-wide backpressure, and retention cleanup **remain responsibilities of the existing publisher/primary system**, not claims provided by this handler. Do not deploy a direct public HTTP endpoint around this function.

## Functional acceptance

Tests use a real disposable Git repository and the actual evidence compiler: duplicate delivery -> one receipt, concurrent duplicate delivery -> one receipt, valid CI metadata -> labeled unverified CI result, same ID with altered revision -> fail-closed conflict, missing commits -> no completed receipt, unsafe outbox paths rejected, JSONL batch twice -> second run deduplicates every entry. Integration and smoke tests must run again at the exact eventual deployment revision.

**Pending:** separate PR publication, independent source review, primary-publisher event hook under its authorized runtime lease, authenticated real Git/CI event integration, and downstream Claude Code/Codex/Grobowski consumption tests. This adapter alone does not establish production event handoff.

## Verification and integration blockers observed 2026-10-27 (Europe/Berlin)

The implementation uses two **clean isolated Git branches**, not main:

- Agent Evidence Pack head: `8034a774de7a490ca29f82700432ff850a240a68` (two commits, starts at published main `bf2ad72785c47ede4b8b94ce2215b07e4773877e`).
- Event Handoff baseline commit: `473c4508c312402db46ccecdd3001e68d2060b41`, **stacked on** the preceding agent branch.
- Main stayed clean during work; Großer Adler independently observed exact commit/branch/status read-only.
- Focused combined pytest after event hardening: **66 passed**. Ruff on all changed Python paths: **passed**. Real MCP `tools/list` advertised `change_evidence_pack` with read-only annotations and real `tools/call` returned 5 changes on existing PR #1351 merge, exact Git diff SHA-256 `962184701c36d275c4da8d09b0d09d46f9be2fa4e8705a59cbd79ba87749d65b`; source freshness correctly `stale` relative to this newer event branch.
- Real Git event rehearsal for the same **merged** PR #1351 diff: first delivery `published`, second `deduplicated`, **one** JSON receipt, five changed files, clean Git worktree; evidence SHA-256 `e23170ef9c48ea342680f72237e2ca263f72db02df1de792ecdc25e97d1efc01`. The event delivery is explicitly **synthetic**, not claimed to be a verified GitHub webhook.
- Complete repository pytest run in an initially incomplete ephemeral Nix test environment: **6077 passed, 47 failed, 12 skipped**. Of those, 43 of the failures disappeared when the exact missing format validator (`rfc3339-validator`), Python `ruff`, and other test dependencies were provisioned and the seven affected test files re-ran (**547 passed, 4 failed**).
- The **remaining four failures also reproduce on clean unchanged main** with the same Nix test environment: one malformed-input symlink diagnostic, two fleet worktree smudge-filter fixtures whose subprocess PATH lacks `sed`, and one `latest_complete` symlink/validation error-category mismatch. These are baseline/environment failures, not demonstrated regressions introduced by this branch. **A completely green full suite and GitHub CI have not been established**.

Publishing both feature branches was attempted through Grabowski's guarded `branch-publish` action. The default `origin` is HTTPS and is rejected by the SSH-only push policy. A same-repository SSH remote passed identity preflight, but publication returned `Permission denied (publickey)`. **Subsequent primary-evidence checks contradicted the initial diagnosis that the dedicated key was unregistered:** GitHub's public account keys include the exact dedicated key fingerprint, the private key unlocks without a passphrase, and a direct probe using the complete hardened SSH flags authenticated successfully. A concurrently changing, shared `.git/config` with another lane's separately leased temporary SSH remote creates an unresolved publication/transport race; the failed receipt does **not** prove a credential defect. No Thread 3 branch has been verified published. Preserve the SSH-only security gate and repair the publication path using a separate stable exact remote lease after parallel publication work completes; do not reuse another lane's remote or weaken SSH.

Großer Adler's read-only Git observation does not constitute a completed independent code review. Gegner's countercheck endpoint returned HTTP 429; no successful independent countercheck is claimed.

**Integration sequence after the credential gate is resolved:** publish the Evidence Pack branch as its own PR, run GitHub CI and risk-scaled review, integrate it; then publish/rebase the stacked event PR and verify CI/publisher-hook replay at exact promoted commits. Thread 1 and Thread 2 contracts can be joined later through versioned adapters only, without editing their concurrent internal graph/history/federation sources.
## Additional event-branch end-to-end verification

After adding explicit receipt retrieval and tamper checks, the *entire*
RepoGround Python suite ran on the stacked event branch with the same four
independently reproduced clean-main failures intentionally deselected:
**6123 passed, 12 skipped, 4 deselected**, 248.05 seconds, exit 0.
The focused event/MCP suite passed 69 tests before this whole-repo run.

An additional **real Git commit-diff rehearsal** generated one event receipt
for merged PR #1351 and then invoked the actual
`scripts/repoground-event-handoff.py --read-event-key` CLI.
Result: `published` -> `available` for the *same* event payload,
five changed files, a clean checkout, event key
`0e53b3605e137776148ef47e624c005fd0cf7d3eccabd3ed504e31144087b219`,
and readback receipt SHA-256
`adeabd51cfcd3183fcfe35f18abd73c3c3657b412effbd613536d1ce9364a8ff`.
The source Git change was real; its event delivery was synthetic and explicitly
not a GitHub-webhook authenticity test. The temporary receipt directory
was deleted after verification.

The first consumer branch subsequently advanced to
`503f5afb8eb69431b256f77606b5a62c8997b524` after this stacked
event branch was created. Do **not** claim the event branch already contains
that later first-branch change: rebase this second branch onto the
first integrated consumer head and rerun all admission tests before merging.
