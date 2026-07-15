# RepoBrief publication policy

`rb-publication-policy` manages the durable identity and retention contract for RepoBrief publications. It does not generate RepoBrief bundles itself. The publisher reserves a generation before writing payload data, completes the durable record after validating the bundle manifest, and runs retention through an explicit dry-run/apply cycle.

## Storage separation

Two disjoint roots are mandatory:

- **Evidence root:** durable publication records, pins, plans, locks and transaction journals. Record state transitions are written atomically; payload pruning never removes this evidence.
- **Payload root:** large, regenerable RepoBrief bundle directories.

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
- RepoBrief profile;
- canonical configuration SHA-256;
- Lenskit version;
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

The default policy retains the union of:

- the latest **3** successful full payloads;
- the newest successful payload for each of the latest **7 UTC days**;
- the newest successful payload for each of the latest **8 ISO weeks**;
- every explicit pin;
- incomplete or failed payloads younger than **48 hours**.

Daily and weekly anchors are deterministic. Explicit pins are separate evidence objects and therefore survive normal record updates. Failed TTL age starts at the failure timestamp; incomplete TTL age starts at reservation.

Create a dry-run plan:

```bash
scripts/ops/rb-publication-policy plan \
  --repository heimgewebe__lenskit \
  --lane main \
  --output /safe/path/retention-plan.json
```

The plan binds every candidate to:

- exact record path and record SHA-256;
- exact payload path;
- device and inode identity;
- deterministic payload-tree SHA-256;
- byte count and retention reason.

Review the plan, then apply exactly its embedded hash:

```bash
scripts/ops/rb-publication-policy apply \
  --plan /safe/path/retention-plan.json \
  --expected-plan-sha256 <plan-sha256>
```

A pin added after planning causes apply to retain the generation. A changed record, changed payload, missing retained payload, unexpected metadata entry or unresolved transaction fails closed.

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

Integration with `scripts/ops/rb-publish-fleet` must occur only after the active RBV1-T026 retention hardening is merged. Until then, the policy is intentionally implemented in disjoint files so the in-flight publisher, its tests and its retention documentation are not overwritten or concurrently edited.
