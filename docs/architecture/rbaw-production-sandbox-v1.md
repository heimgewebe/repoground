# RBAW Production Sandbox v1

## Decision

The first production adapter for external patch evaluation uses a transient
`systemd --user` service on cgroup v2 and invokes the existing Bubblewrap
Sidecar unchanged.

The adapter is an execution boundary, not a second orchestrator. It accepts the
existing Sidecar request, snapshots the original request, rewritten execution
request, and patch, starts one transient unit with explicit aggregate limits,
reads the existing `repobrief.patch_evaluation` artifact, and emits a separate
runner receipt that binds producer identity, requested policy, effective systemd
properties, kernel cgroup values, accounting, artifact digest, and terminal
result.

## Alternatives

### Transient systemd service — selected

Advantages:

- reuses the host's existing cgroup-v2 and service lifecycle machinery;
- keeps the current Bubblewrap filesystem, PID, and network boundary;
- adds no image registry or VM image supply chain;
- provides `MemoryMax`, `MemorySwapMax`, `TasksMax`, `CPUQuota`,
  `RuntimeMaxSec`, IO bandwidth controls, accounting, kill-on-unit-stop, and a
  stable Invocation ID;
- permits readback of both configured properties and actual cgroup-v2 kernel
  files;
- can fail closed when the user manager or required controller delegation is
  unavailable.

Costs and limits:

- requires a working user systemd manager and delegated `cpu`, `memory`, `pids`,
  and `io` controllers;
- filesystem quota is implemented by a per-unit bounded tmpfs rather than a
  project quota;
- process stdout/stderr is deliberately discarded to prevent unbounded or
  secret-bearing content from entering the host journal; diagnostics must come
  from the bounded Sidecar logs, artifact, unit result, and runner receipt;
- the adapter is Linux-specific.

### Rootless container — deferred

A rootless container can express similar resource limits, but adds an image,
registry, runtime, and rootless-cgroup delegation contract. That would duplicate
parts of the current Bubblewrap and source-provenance boundary before a need for
an image-based environment has been demonstrated.

### MicroVM — deferred strongest tier

A MicroVM gives the strongest kernel boundary for hostile code. It also adds a
kernel/rootfs supply chain, boot lifecycle, artifact transport, networking, and
substantially higher operational cost. It remains the escalation path for code
that must not share the host kernel.

## Boundary composition

1. The runner validates paths and limits before mutation.
2. It hashes the original request and snapshots the rewritten execution request
   and patch into an owner-only staging directory.
3. The source repository and snapshots are read-only to the transient service.
4. One empty, current-user-owned, mode-`0700` directory is the only persistent
   writable content root and contains artifact, bounded logs, and receipt.
5. Sidecar workspace and scratch live in a size-bounded tmpfs.
6. The complete service process tree runs in one cgroup with aggregate memory,
   swap, CPU-rate, task-count, per-device IO-rate, and wall-clock limits.
7. Existing Sidecar per-command RLIMITs remain defense in depth.
8. `StandardOutput=null` and `StandardError=null` prevent service content from
   becoming an unbounded second log channel in the host journal.
9. The terminal unit remains loaded long enough to read systemd properties and
   `memory.max`, `memory.swap.max`, `pids.max`, `cpu.max`, and `io.max` from its
   actual cgroup.
10. The runner verifies request, patch, producer, output-root identity,
    accounting, Sidecar artifact, and policy readback before atomically
    publishing a receipt. An ambiguous directory-`fsync` after successful link
    publication is accepted only after complete JSON readback equality.
11. Cleanup requires the exact unit name, Invocation ID, staging device/inode,
    and output-root identity. Foreign resources are never adopted.

## Resource interpretation

- `workspace_max_bytes` is a hard tmpfs capacity for checkout, object pack,
  Sidecar home, and temporary files inside the service namespace.
- `memory_max_bytes` and `memory_swap_max_bytes` are aggregate cgroup limits.
- `cpu_quota_percent` is the aggregate CPU share. Together with
  `runtime_max_seconds` it yields a derived maximum CPU-time budget.
- `tasks_max` covers processes and threads in the complete unit.
- read/write bandwidth limits apply per discovered block-backed input or output
  device. Total derived byte ceilings multiply the per-device rate by runtime
  and device count.
- tmpfs IO is bounded by `workspace_max_bytes`; persistent logs remain bounded
  by the existing Sidecar request contract.

## Failure semantics

Missing controller delegation, an unusable user manager, non-exclusive output
root, ambiguous device resolution, property/kernel mismatch, namespace-policy
rejection, timeout, OOM kill, resource failure, producer or input drift, missing
or malformed Sidecar artifact, identity mismatch, or unproven cleanup produces
runner `status: error`.

A Sidecar `failed` artifact remains a patch-command failure and is not promoted
to infrastructure error merely because the service exits nonzero.

## Non-claims

The runner receipt is external runtime evidence. It does not establish patch
correctness, test sufficiency, security correctness, merge readiness, merge
authorization, or equivalence to a MicroVM boundary.
