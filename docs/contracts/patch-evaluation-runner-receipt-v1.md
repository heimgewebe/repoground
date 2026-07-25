# Patch Evaluation Runner Receipt v1

- Schema: `merger/repoground/contracts/patch-evaluation-runner-receipt.v1.schema.json`
- Producer: `tools/patch_evaluation_systemd_runner.py`
- Underlying evidence: `repobrief.patch_evaluation` v1
- Architecture: `docs/architecture/rbaw-production-sandbox-v1.md`

## Meaning

A runner receipt records how one external Patch Evaluation Sidecar process tree
was bounded and how its transient systemd unit terminated. It binds:

- the original request, immutable rewritten execution request, and patch snapshot;
- the transient unit name, Invocation ID, and cgroup path;
- exact requested aggregate resource limits and a SHA-256 readback of the effective systemd policy;
- terminal systemd result and accounting values;
- the path, SHA-256, and declared status of the existing Sidecar artifact;
- identity-bound unit, staging, and dedicated persistent-output-root readback.

The receipt does not replace or reinterpret the Sidecar artifact. A Sidecar
`failed` status remains a command failure. Runner `error` means the execution
boundary, resource policy, artifact binding, or cleanup could not be proven.

## Status precedence

1. Missing evidence, policy failure, resource kill, timeout, identity mismatch,
   or unproven cleanup yields `error`.
2. Otherwise the receipt mirrors the Sidecar artifact status.
3. `passed` remains external evidence only and is never merge authorization.

## Aggregate limits

The selected adapter uses one transient `systemd --user` service on cgroup v2.
Memory, swap, task count, CPU quota, per-device IO bandwidth, and runtime apply
to the complete process tree. Sidecar workspace and scratch are mounted on a
bounded per-unit tmpfs. Existing Sidecar command-level RLIMITs remain defense in
depth. The persistent output root must be empty, current-user-owned, mode `0700`,
and shared by the Sidecar artifact, bounded command logs, and runner receipt.

`StandardOutput=null` and `StandardError=null` are mandatory and read back from
the retained unit. This prevents arbitrary command output from becoming a
second, unbounded host-journal channel. Diagnostic content remains in the
Sidecar's bounded logs and artifact; systemd result and accounting remain in the
runner receipt.

The runner reads the effective systemd properties back from the retained
terminal unit and verifies the corresponding cgroup-v2 kernel files:
`memory.max`, `memory.swap.max`, `pids.max`, `cpu.max`, and `io.max`. A receipt
can mirror the Sidecar status only when both layers match the request and their
canonical combined readback is bound by `policy_readback_sha256`.

The producer digest is captured before launch and read back after completion.
The rewritten request and patch snapshots are likewise rehashed and their
read-only modes checked before the receipt may be published.

Receipt publication is atomic and refuses overwrite. If directory `fsync`
returns an ambiguous error after the no-overwrite hard link succeeded, the
publication is accepted only when the entire JSON value reads back equal to the
intended receipt.

The maximum CPU-time and block-IO byte fields are derived hard ceilings:

- `cpu_time_max_usec = runtime_max_seconds × cpu_quota_percent × 10,000`
- `io_*_total_max_bytes = runtime_max_seconds × io_*_bandwidth_per_device_bps × io_device_count`

Tmpfs writes are instead bounded by `workspace_max_bytes`.

## Authority boundary

`authority` is fixed to `external_runtime_evidence`. The closed non-claim set
states that the receipt does not establish correctness, test sufficiency,
security correctness, merge readiness, merge authorization, or MicroVM
equivalence.
