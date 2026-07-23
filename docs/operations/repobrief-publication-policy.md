# RepoGround publication policy

`rb-publication-policy` manages the durable identity and retention contract for RepoGround publications. It does not generate RepoGround bundles itself. The publisher reserves a generation before writing payload data, completes the durable record after validating the bundle manifest, and runs retention through an explicit dry-run/apply cycle.

## Storage separation

Two disjoint roots are mandatory:

- **Evidence root:** durable publication records, pins, plans, locks and transaction journals. Record state transitions are written atomically; payload pruning never removes this evidence. Existing and newly created evidence/lock directories must be owned by the current user, must not be group- or world-writable, and symlinked directory chains are rejected. Metadata reads, hashes, atomic replacements and lock acquisition are anchored to already-open directory handles; parent replacement is detected. Lock files are opened without following symlinks and normalized to mode `0600`.
- **Payload root:** large, regenerable RepoGround bundle directories.

The policy refuses nested or identical roots. Retention removes only a validated payload directory. The durable record, identity digest, manifest digest, payload digest, byte count and prune receipt remain available after payload removal.

Default roots:

```text
Evidence: ~/.local/state/repobrief-publication-policy
Payload:  ~/repos/manifest-publications
```

Override them with `--evidence-root`, `--payload-root`, `RB_PUBLICATION_EVIDENCE_ROOT` or `RB_PUBLICATION_PAYLOAD_ROOT`.

## Canonical identity

A publication identity contains:

- owner-qualified repository key;
- publication lane/ref;
- full repository commit;
- RepoGround profile;
- canonical configuration SHA-256;
- RepoGround version;
- bundle schema;
- generator-input SHA-256.

The canonical JSON representation is hashed with SHA-256. `begin` is serialized per repository/lane. When a successful generation with the same identity and a present payload already exists, the result is `noop`; no second full artifact directory is allocated. A concurrent identical reservation returns `in_progress` after the first writer creates the durable record.

Compute an identity:

```bash
scripts/ops/rb-publication-policy identity \
  --repository heimgewebe__lenskit \
  --lane main \
  --repository-commit "$COMMIT" \
  --profile full-max \
  --configuration-sha256 "$CONFIG_SHA256" \
  --lenskit-version "$LENSKIT_VERSION" \
  --bundle-schema repobrief.bundle.v1 \
  --generator-inputs-sha256 "$GENERATOR_SHA256"
```

## Publication lifecycle

Reserve the intended payload path before generation:

```bash
scripts/ops/rb-publication-policy begin \
  [identity arguments] \
  --payload /managed/payload/root/heimgewebe__lenskit/main/<generation>
```

The result is one of:

- `created`: generate into the returned payload path;
- `in_progress`: an identical young reservation already exists;
- `noop`: an identical successful payload already exists.

After generation and bundle validation, complete the record:

```bash
scripts/ops/rb-publication-policy complete \
  --record <record-path> \
  --manifest <payload-path>/<bundle-manifest>
```

`complete` stores the manifest SHA-256, deterministic payload-tree SHA-256 and payload byte count in the evidence record. A failed generation is recorded with `fail --reason ...`; its evidence remains durable.

## Retention contract

The policy enforces non-reducible retention floors and retains the union of:

- the latest **3** successful full payloads;
- the newest successful payload for each of the latest **7 UTC days**;
- the newest successful payload for each of the latest **8 ISO weeks**;
- every explicit pin;
- incomplete or failed payloads younger than **48 hours**.

The values 3/7/8 and 48 hours are minimums, not merely defaults: CLI input and embedded plans cannot lower them. Daily and weekly anchors are deterministic. Explicit pins are separate evidence objects and therefore survive normal record updates. Failed TTL age starts at the failure timestamp; incomplete TTL age starts at reservation. An expired incomplete or failed record whose payload directory was never created is recorded as pruned without deleting any filesystem path; a missing successful payload remains a hard error.

Create a dry-run plan:

```bash
scripts/ops/rb-publication-policy plan \
  --repository heimgewebe__lenskit \
  --lane main \
  --output /safe/path/retention-plan.json
```

The plan binds every candidate to:

- exact record path and record SHA-256;
- exact payload path, bound again to the durable record before apply and recovery;
- device and inode identity;
- deterministic payload-tree SHA-256;
- byte count and retention reason.

Review the plan, then apply exactly its embedded hash:

```bash
scripts/ops/rb-publication-policy apply \
  --plan /safe/path/retention-plan.json \
  --expected-plan-sha256 <plan-sha256>
```

A pin added after planning causes apply to retain the generation. A changed record, changed payload, missing retained payload, unexpected metadata entry or unresolved transaction fails closed. Plans do not rely on a fixed wall-clock validity window: apply recomputes the current selection under the stream lock and skips candidates that are now retained; record, path and payload identity must still match exactly.

## Transaction and crash recovery

Apply journals each candidate before moving it. The payload is atomically renamed into a quarantine directory on the same payload filesystem, rehashed, then removed. The durable record is marked `pruned` only after deletion.

Interrupted transactions are recovered with:

```bash
scripts/ops/rb-publication-policy reconcile \
  --repository heimgewebe__lenskit \
  --lane main
```

Reconciliation is idempotent:

- a still-present source is retained and the transaction is terminalised safely;
- a quarantined generation that became pinned or policy-retained is restored;
- an unretained quarantined generation is deleted after identity verification;
- deletion completed before the final journal write is recorded without recreating payload;
- two copies, malformed paths, digest mismatch or a lost merely planned payload aborts.

## Pins

Pin a record with an explicit reason:

```bash
scripts/ops/rb-publication-policy pin \
  --record <record-path> \
  --reason "release comparison baseline"
```

Remove the pin with `unpin --record <record-path>`. Orphaned or malformed pin metadata fails retention planning instead of being ignored.

## Fleet publisher integration boundary

The existing fleet publisher already computes a scoped content identity and skips unchanged successful publications. The policy module supplies the stronger durable reservation, anchor selection, pin, TTL and evidence/payload separation contract.

RBV1-T026 is merged. This policy remains a separate control module and is not silently wired into the live fleet publisher by this change. Any production integration requires its own exact dry-run, payload-candidate binding and rollout evidence; this implementation performs no live retention by itself.
