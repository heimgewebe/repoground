# RBAW Production Sandbox v1 — Implementation Proof

## Bound revision

Implementation base: RepoGround `24eee84dd845fcf5f3a4a82c9e42e64428e76d6d`.

## Implemented slice

`tools/patch_evaluation_systemd_runner.py` wraps the existing external Sidecar
without importing it into RepoGround core.

The runner:

- requires Linux, cgroup v2, a working systemd user manager, and the `cpu`,
  `memory`, `pids`, and `io` controllers;
- validates bounded numeric limits and requires one empty, current-user-owned
  mode-`0700` persistent output root;
- separately hashes the original request, snapshots the rewritten execution
  request and patch with read-only modes, and verifies both snapshots after
  execution;
- resolves every block-backed source/output device before mutation;
- launches one UUID-named transient user service with aggregate memory, swap,
  task, CPU, runtime, and IO-rate limits;
- gives the unit a bounded tmpfs for all Sidecar workspace and scratch data;
- exposes the source and snapshots read-only and only the dedicated output root
  writable;
- preserves the existing Bubblewrap network-deny and per-command RLIMIT layers;
- suppresses service stdout/stderr with effective `null` output properties so
  arbitrary content cannot become an unbounded host-journal channel;
- retains terminal units long enough to read Invocation ID, cgroup path, result,
  exit information, accounting, effective systemd properties, and the actual
  `memory.max`, `memory.swap.max`, `pids.max`, `cpu.max`, and `io.max` kernel
  files;
- distinguishes a valid Sidecar `failed` artifact from systemd resource failure;
- treats OOM, timeout, signal, resource, missing artifact, malformed artifact,
  or unproven cleanup as runner `error`;
- binds the pre-launch runner/Sidecar producer digest, verifies it after
  execution, and atomically publishes a strict receipt that hashes the Sidecar
  artifact and combined systemd/kernel policy readback;
- accepts an ambiguous directory-`fsync` after successful receipt linking only
  after complete JSON readback equality;
- cleans only the exact unit Invocation ID and staging device/inode identity,
  and refuses receipt publication if the output-root identity changed.

## Regression coverage

The 20 tests in `tests/test_patch_evaluation_systemd_runner.py`,
`tests/test_patch_evaluation_systemd_runner_cleanup.py`, and
`tests/test_patch_evaluation_systemd_runner_output.py` cover:

- aggregate CPU and multi-device IO ceiling derivation;
- strict numeric limit validation;
- bounded immutable request/patch snapshots and read-only modes;
- request rewrite and original/effective digest binding;
- exclusive persistent-output-root enforcement;
- exact systemd property and namespace-policy generation;
- actual kernel cgroup readback for memory, swap, tasks, CPU, and multi-device
  IO;
- canonical combined systemd/kernel policy hashing;
- atomic receipt no-overwrite behavior;
- producer digest binding across wrapper, support module, and Sidecar;
- block-device resolution fail-closed behavior;
- receipt example/schema conformance;
- cleanup refusal after Invocation-ID drift;
- cleanup-readback failure classification;
- explicit `LoadState=not-found` as the only unit-absence proof;
- successful cleanup only after bound stop and absence readback;
- insertion of `StandardOutput=null` and `StandardError=null` before the service
  payload boundary;
- rejection of journal-backed process output;
- acceptance only after effective null-output readback;
- full receipt JSON readback after an ambiguous directory-`fsync`.

## Deliberate non-claim

CI unit tests exercise policy construction and failure semantics without claiming
a live delegated user cgroup. Bureau #979 remains open until a real host run binds
systemd version, delegated controllers, unit Invocation ID, cgroup path, enforced
limits, patch digest, accounting, terminal status, and cleanup readback.

A MicroVM remains the later strongest tier for code that must not share the host
kernel.
