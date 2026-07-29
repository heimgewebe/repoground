# T020 proof: loaded-host process budget for the patch sidecar

Task: `REPOGROUND-LEGACY-RECONCILIATION-V1-T020`.

## Problem

The sidecar previously wrapped Bubblewrap with:

```text
prlimit --nproc=256 -- bwrap ...
```

On Linux, `RLIMIT_NPROC` is counted for the process's **real user ID**. It is
not a child-process or PID-namespace quota. When the operator user already owns
at least 256 processes, Bubblewrap can fail before the isolated payload starts
with:

```text
bwrap: Creating new namespace failed: Resource temporarily unavailable
```

That couples a bounded command policy to unrelated pre-existing host load.

## Change

`patch_evaluation_sidecar_process_budget.py` is installed as the final sidecar
overlay. Immediately before each `prlimit` argv is built, it:

1. counts visible `/proc/<pid>/status` entries whose real UID equals
   `os.getuid()`;
2. treats the existing `_MAX_COMMAND_PROCESSES` value (`256`) as an
   **incremental budget**;
3. calculates `absolute_limit = current_real_uid_processes + 256`;
4. clamps that value to the inherited hard `RLIMIT_NPROC`;
5. fails closed when the inherited hard limit leaves no positive headroom;
6. emits an explicit `soft:hard` pair to `prlimit`.

Example from the bound failure model:

```text
current real-UID processes: 270
configured incremental budget: 256
inherited hard limit: 31422
applied RLIMIT_NPROC: 526:526
```

The old absolute `256` is therefore not reused.

## Security boundaries retained

The change does not remove or weaken:

- Bubblewrap PID, IPC, UTS, network and best-effort cgroup namespace isolation;
- read-only system and Git-metadata mounts;
- address-space, output-file, open-file and CPU limits;
- command timeout and bounded log capture;
- source/workspace fingerprinting and cleanup checks.

A finite inherited hard `RLIMIT_NPROC` is never raised. Concurrent host process
growth consumes sidecar headroom and can still make a command fail, which is a
fail-closed outcome.

## Epistemic boundary

Linux does not provide a strict per-command quota through `RLIMIT_NPROC`:
processes are accounted by real UID. If unrelated same-UID processes terminate
after the baseline is measured, some absolute headroom becomes available. The
implementation therefore claims only a bounded **launch-time incremental
budget**, not a globally isolated per-command kernel quota.

A cgroup `pids.max` implementation would provide a stronger subtree quota, but
it would require proven delegated cgroup ownership on every supported runtime.
That larger operational change is not introduced here.

## Regression coverage

`tests/test_patch_evaluation_sidecar_process_budget.py` proves:

- `/proc` counting uses the real UID and tolerates normal process-table races;
- a loaded-host baseline of 270 produces `526:526`, not the legacy absolute
  `256`;
- a finite inherited hard limit only reduces the effective budget;
- zero inherited headroom fails closed;
- generated `prlimit` argv uses the dynamic explicit soft/hard value;
- on non-root Linux, a deliberately small incremental budget rejects a fork
  storm while allowing the bounded command to start.

The existing patch-sidecar and host-readback suites continue to cover
Bubblewrap startup, filesystem/network isolation, mutation rejection, bounded
logs, provenance and cleanup.

## Delivery boundary

This slice changes only the sidecar wrapper, one new overlay module, its tests
and this proof. It does not touch `service/app.py`, the active T012 service split
or any historical/dirty RepoGround worktree. It does not by itself mark T020 or
its parent initiative verified; merge, CI and current-head readback remain
required.
