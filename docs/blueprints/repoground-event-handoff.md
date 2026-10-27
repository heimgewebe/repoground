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

## Dedup, concurrency and provenance

A canonical SHA-256 event identity is formed from event type, delivery ID and declared repository. The complete input event has a separate SHA-256; reusing the same identity with different input is an explicit conflict. The same event replay returns the identical persisted receipt with status `deduplicated`. Different event IDs are different events; this layer does not infer semantic equivalence from Git commit or content.

The **single** explicit publisher outbox is also the receipt store, not a second authoritative event ledger. One flock on its lockfile serializes concurrent writers; each canonical event gets one JSON receipt through write+fsync+atomic rename+directory fsync. No transient candidate work queue, magic `latest` pointer or implicit snapshot rebuild is introduced. The durable receipt records an event input hash, event key, Evidence Pack, pack SHA-256, revision/diff information, bundle provenance, model-independent consumer hint and explicit `does_not_establish` caveats.

The handler does **not** treat event fields as executable instructions. It does not fetch external Git objects or trigger code execution beyond read-only Git diff subprocess calls already allowed in the Evidence Pack. Each process consumes at most 16 explicitly supplied events, with one finite evidence computation per new identity. A failed batch can partially append receipts for earlier valid events; replay is safe and fills only missing events. Invalid JSON and schema errors are rejected before a new event is processed.

Event producer authentication, CI webhook verification, event age/lag metrics, scheduling/rate-limiting between invocations, fleet-wide backpressure, and retention cleanup **remain responsibilities of the existing publisher/primary system**, not claims provided by this handler. Do not deploy a direct public HTTP endpoint around this function.

## Functional acceptance

Tests use a real disposable Git repository and the actual evidence compiler: duplicate delivery -> one receipt, concurrent duplicate delivery -> one receipt, valid CI metadata -> labeled unverified CI result, same ID with altered revision -> fail-closed conflict, missing commits -> no completed receipt, unsafe outbox paths rejected, JSONL batch twice -> second run deduplicates every entry. Integration and smoke tests must run again at the exact eventual deployment revision.

**Pending:** separate PR publication, independent source review, primary-publisher event hook under its authorized runtime lease, authenticated real Git/CI event integration, and downstream Claude Code/Codex/Grobowski consumption tests. This adapter alone does not establish production event handoff.
