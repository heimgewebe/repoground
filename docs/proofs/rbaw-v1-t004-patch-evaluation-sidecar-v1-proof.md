# RBAW-V1-T004 External Patch Evaluation Sidecar v1 proof

## Scope

This slice prototypes the mutable evaluation layer outside RepoBrief core. The
producer is `tools/patch_evaluation_sidecar.py`; the existing Patch Evaluation
Artifact schema and read-only RepoBrief consumer remain unchanged.

## Boundary checks

- The exact base commit and its tree are copied through a newly generated Git
  pack into a newly initialized repository. The evaluation repository has its
  own Git directory, configuration, refs, and object database; shared common
  directories, alternates, or multiply linked object files fail isolation
  verification.
- Source-local Git hooks and configured clean, smudge, and process filters are
  neutralized for every Sidecar-owned Git operation. Internal Git and Bubblewrap
  binaries are resolved from a fixed system path rather than the caller's
  `PATH`.
- The source checkout is not mounted into declared command execution. Commands
  run with `shell=False` inside Linux Bubblewrap filesystem and PID namespaces;
  the independent repository, private home, and private temporary directory are
  the only writable mounts, while required system directories are read-only and only an explicit `/etc` subset is exposed.
- Background descendants are contained by the PID namespace. Timed-out host
  process groups receive SIGTERM followed by an unconditional SIGKILL sweep.
- The patch is copied once into a private snapshot; its digest and applied bytes
  are therefore identical. Patch application fails before any declared command
  may run.
- The source drift fingerprint covers HEAD, Git status, tracked worktree diff,
  staged-index diff, and content of non-ignored untracked files. Ignored files,
  unrelated refs, repository configuration, and the source object database are
  outside the fingerprint; declared commands cannot reach the source checkout
  through the mount namespace.
- Request, patch, repository pack, object count, argv, context, changed-file,
  fingerprint, command-time, and log sizes are bounded. The source fingerprint
  also has a fixed time budget.
- `fail_fast` is optional and defaults to `false`; when enabled, later commands
  are recorded as `skipped`, so the artifact is `incomplete`.
- Explicit `redact_argv_indexes` are redacted from command displays and bounded
  logs. Arbitrary command output is not proven secret-free, so
  `secrets_policy` remains `unknown`.
- Network isolation is not asserted and `network` remains `unknown`.
- Empty log directories are removed. Independent-repository, patch-snapshot,
  and runtime cleanup are read back fail-closed; unproven cleanup or source drift
  forces artifact status `error`.
- The artifact is written atomically, records a SHA-256 digest of the producer
  source, and declares all nine mandatory non-claims.

## Adversarial coverage

The focused suite proves regressions for:

- source Git configuration and ref mutations remaining confined to the
  independent repository;
- clean, smudge, and process filters not executing during Sidecar-owned Git
  operations;
- the source checkout, including ignored files, being unavailable to declared
  commands;
- successful commands being unable to leave background descendants;
- timeout process-group cleanup;
- rename destination-path reporting;
- patch snapshot time-of-check/time-of-use binding;
- fake parent-`PATH` Git replacement being ignored;
- fail-fast command skipping;
- argv and log redaction;
- partial repository creation and forced cleanup failure;
- input and artifact-boundary size limits.

## Verification commands

```text
python -m pytest -q tests/test_patch_evaluation_sidecar.py merger/repoground/tests/test_patch_evaluation.py
# 47 passed in 5.60s

python -m pytest -q
# 4696 passed, 2 skipped

python -m ruff check tools/patch_evaluation_sidecar.py tests/test_patch_evaluation_sidecar.py
# All checks passed!

python -m ruff format --check tools/patch_evaluation_sidecar.py tests/test_patch_evaluation_sidecar.py
# 2 files already formatted

python scripts/ci/check_graph_maintainability.py --root . --format json
# status pass; current_count 200; baseline_count 203; new_count 0; resolved_count 3

python -m py_compile tools/patch_evaluation_sidecar.py tests/test_patch_evaluation_sidecar.py
# exit 0

git diff --check
# exit 0
```

The durable full-suite task is bound to argv SHA-256
`c3f2578d3a465d10ae97391fe2a54f1c10832286381277ce1355ccfb0bbac529`,
lifecycle receipt SHA-256
`d26feb16ef5ba99dc5f78f98320a47d775fb0b9024f12706d8693bb40c0c759f`,
and terminalization SHA-256
`31755fc3eeca8ca8de8372e75bf4eaa920e29f9c633433e84e2de83f90e26d71`.

## Does not establish

This proof and a passing prototype run do not establish correctness, test
sufficiency, security correctness, runtime behavior outside evaluated commands,
merge authorization, merge readiness, regression absence, repository
understanding, or truth of producer claims. Network isolation and complete
credential safety are not established. Linux and Bubblewrap are runtime
requirements for declared command execution.

Invalid requests and read-only provenance-preflight failures can terminate
without an artifact; they do not create an evaluation repository or run declared
commands. Operational failures after mutable evaluation begins emit
`status: error` when the artifact destination remains writable.
