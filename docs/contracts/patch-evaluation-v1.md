# Patch Evaluation Artifact v1 (`repobrief.patch_evaluation`)

- Schema: [`merger/repoground/contracts/patch-evaluation.v1.schema.json`](../../merger/repoground/contracts/patch-evaluation.v1.schema.json)
- Consumer: [`merger/repoground/core/patch_evaluation.py`](../../merger/repoground/core/patch_evaluation.py)
- Example: [`merger/repoground/contracts/examples/patch-evaluation.v1.json`](../../merger/repoground/contracts/examples/patch-evaluation.v1.json)
- Boundary: [`docs/architecture/repobrief-agent-workbench-boundary.md`](../architecture/repobrief-agent-workbench-boundary.md) (owns tasks RBAW-V1-T002 / RBAW-V1-T003)

## What this contract is

A `repobrief.patch_evaluation` artifact is **bounded external evidence** emitted
by the *external* Patch Evaluation Sidecar. It records that a proposed patch was
applied in an isolated workspace and that a declared set of commands was run,
with the captured outcomes (exit codes, statuses, log references).

`authority` is pinned to the constant `external_evaluation_evidence`. That pin
is the whole point: a valid artifact can never be read as a merge authorization,
a review verdict, or a truth source.

> A valid patch-evaluation artifact is external evidence, not approval.

## What this contract is **not**

A valid artifact does not establish (these nine members of `does_not_establish`
are mandatory and enforced by the schema):

- `correctness`
- `test_sufficiency`
- `security_correctness`
- `runtime_behavior_outside_evaluated_commands`
- `merge_authorization`
- `merge_readiness`
- `regression_absence`
- `repo_understood`
- `claims_true`

A producer may additionally declare `truth`, `completeness`,
`review_completeness`, or `forensic_ready`. The `does_not_establish` vocabulary
is closed; unknown members fail validation.

## Authority boundary

RepoBrief **consumes** these artifacts read-only. RepoBrief does **not**:

- produce, execute, or repair them,
- apply patches or manage worktrees,
- run shells, tests, linters, or sandboxes,
- read secrets,
- interpret a `status: passed` artifact as approval.

The Sidecar is external precisely because applying patches and running commands
crosses the mutation boundary that RepoBrief's read-only evidence layer must not
cross. See the [Agent Workbench Boundary](../architecture/repobrief-agent-workbench-boundary.md).

## Shape

Root is a strict object (`additionalProperties: false`) with these required
fields:

| Field | Meaning |
| :--- | :--- |
| `kind` | const `repobrief.patch_evaluation` |
| `version` | const `v1` |
| `authority` | const `external_evaluation_evidence` |
| `producer` | Sidecar identity (`name`, `version`, optional `commit`/`url`) |
| `created_at` | ISO 8601 UTC timestamp |
| `input` | evaluated repo/branch/commit/PR/patch coordinates (provenance references only) |
| `repobrief_context` | read-only references to the snapshot, Workbench outputs, cited ranges, citations |
| `workspace` | isolated workspace metadata; `isolated` is required |
| `patch` | applied-patch metadata; `applied` is required |
| `command_policy` | declared policy bounding what the outcomes can mean |
| `commands_run` | the executed commands and their captured outcomes (core evidence surface) |
| `environment` | OS/runner/tool-version provenance |
| `status` | declared overall status: `passed`/`failed`/`mixed`/`error`/`incomplete` |
| `does_not_establish` | closed non-claim vocabulary; the nine mandatory members must be present |

Each `commands_run[]` entry requires `command` and `status`
(`passed`/`failed`/`error`/`skipped`/`timeout`). A recorded status describes only
the observed result of that exact command in that exact workspace; it does not
generalize to correctness or to runtime behavior elsewhere.

## Consumer API (read-only)

`merger/repoground/core/patch_evaluation.py` exposes:

- `load_patch_evaluation(path_or_obj)` — read JSON (or accept a mapping). Pure read.
- `validate_patch_evaluation(data)` — fail-closed schema validation, lens-family report. `pass` means only schema conformance.
- `summarize_patch_evaluation(data)` — bounded summary; pins `authority`, echoes declared `does_not_establish`, surfaces citations/ranges only as reference lists.
- `patch_evaluation_diagnostics(data)` — structured, non-fatal degradations (missing non-claims, non-isolated workspace, no recorded commands).

CLI (read-only): `python -m merger.repoground.cli.main repobrief patch-evaluation validate PATH [--summary]`.
Exit code `0` when the artifact validates, `1` when it fails validation, `2`
when it cannot be read.

## Deferred

- Linking consumed artifacts into bundle-manifest surfaces / MCP resources.

## External prototype harness (RBAW-V1-T004)

`tools/patch_evaluation_sidecar.py` is a deliberately external prototype producer.
It is not imported by RepoBrief core or exposed through RepoGround MCP. The CLI
accepts a strict, size-bounded JSON request, resolves an exact local base commit,
snapshots one declared diff, materializes the commit and its tree into an
independent Git repository, runs only explicit argv arrays with `shell=False`,
and emits this contract atomically outside the source repository.

The materialized repository has its own Git directory, configuration, refs, and
object database. Its objects are imported from a newly generated pack; alternates,
shared common directories, and multiply linked object files fail isolation
verification. Source-local hooks and configured clean, smudge, and process filters
are neutralized for Sidecar-owned Git operations. The source checkout itself is
not mounted into the command sandbox.

Declared commands require Linux and Bubblewrap. They run in a filesystem and PID
namespace with a private writable repository, home, and temporary directory;
required system directories are read-only. The caller's `PATH` and arbitrary
environment variables are not inherited. Background descendants are contained by
the PID namespace, and timeout cleanup sends TERM followed by an unconditional
KILL sweep. Network isolation is not asserted, so `network` remains `unknown`.
Credential safety also remains `unknown`: explicit `redact_argv_indexes` are
removed from command displays and bounded logs, and common secret-shaped options
are display-redacted, but arbitrary command output is not proven secret-free.

The optional `fail_fast` request field defaults to `false`. When enabled, commands
after the first non-passing result are recorded as `skipped`, which makes the
artifact `incomplete`. The `global_timeout_seconds` budget starts immediately
before the declared command loop. Validation, bounded source fingerprinting,
independent-repository materialization, cleanup, and artifact writing are outside
that command budget and have their own fixed limits or operation timeouts.

Request validation and read-only provenance preflight occur before artifact
production is guaranteed. An invalid request, unresolved base commit, unavailable
Bubblewrap runtime, unreadable source checkout, output collision, or unwritable
destination therefore fails without an artifact and without running a declared
command. Once mutable evaluation begins, operational failures produce
`status: error` when the destination remains writable.

The source drift fingerprint covers checked-out HEAD, Git status, tracked
worktree changes, staged-index changes, and the content of non-ignored untracked
files. Ignored files, unrelated refs, repository configuration, and the Git object
database are outside that fingerprint; declared commands cannot reach the source
checkout through the Bubblewrap mount namespace. A `passed` artifact establishes
only that every declared command returned success under these bounded conditions.
It does not establish correctness, test sufficiency, security correctness, merge
readiness, or merge authorization.
