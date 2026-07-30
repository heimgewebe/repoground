# Observed call overlay S2 proof boundary

Task: `RPU-V1-T026`

## Result

RepoGround can record which calls one named command actually performed, as a
separate artifact next to the static Python Call Graph v1. The overlay is
`lenskit.python_observed_call_overlay` / `1.0`, produced only by the explicitly
operator-invoked command `repoground observed-calls produce` and read back by
`repoground observed-calls callers|callees`.

Nothing in the static bundle pipeline produces or consumes it. The static
producer still does not import or execute repository code; the overlay exists
because somebody asked for one command to be traced, and it says so.

## Evidence model

`S2` means: *this relation was observed while this command ran in this
environment at this source revision.* It is not a third resolution status of
the static graph and it is not stored in the static graph.

Every relation carries:

- `relation_type: "observed_calls"` and `evidence_level: "S2"`;
- `observation_run_id`, equal to the document's observation identity;
- `observed_call_count`, the number of times the edge was taken;
- the call site (`call_site_line`, `call_site_range_ref`) when the calling
  frame is repo-local;
- caller and callee endpoints with their raw runtime coordinates
  (`*_path`, `*_runtime_name`, `*_runtime_first_line`) and, when they bind, the
  Python Symbol Index identity (`*_symbol_id`, `*_qualified_name`, `*_kind`,
  definition range).

The document itself carries the observation: `command`, `command_string`,
`environment` (interpreter version, implementation, platform, executable, hash
seed), `source_revision` (git commit and dirty flag) and
`observation_fingerprint_sha256` over all of it. An overlay whose revision
cannot be resolved is refused at production time and again by the validator —
a relation that cannot name its revision is not S2 evidence.

## Binding runtime frames to symbols

Endpoints bind by *exact anchor equality*, not range containment. CPython
anchors a decorated definition's code object at its first decorator line, so
the producer computes the anchor the same way (`min(def line, decorator
lines)`) and reuses the Symbol Index id scheme. Every other outcome is named
rather than guessed:

| `binding_status` | `binding_reason` | meaning |
| :--- | :--- | :--- |
| `bound` | `unique_symbol_containment` | exactly one definition owns this code object |
| `module_scope` | `module_frame` | a module body, which has no symbol id |
| `unbound` | `no_matching_symbol` | comprehension, generator expression, lambda or other unnamed code object |
| `unbound` | `ambiguous_symbol_containment` | more than one definition matched; refused instead of picked |
| `unbound` | `path_outside_repository` | the calling frame is import machinery, stdlib or a dependency |

## Measured run

One command traced against this repository at `merger/repoground/tests/test_python_call_graph.py`
(`-m pytest … -q -p no:randomly`, 47 passed / 10 skipped, ~4.4 s including
tracing):

| Measure | Value |
| :--- | ---: |
| observed relations | 543 |
| observed call events | 28483 |
| callee `bound` / `module_scope` / `unbound` | 418 / 5 / 120 |
| relations with both endpoints addressable | 320 |
| `matches_s1` against the static graph | 292 |
| `absent_from_static_graph` | 251 |
| static S1 pairs in the repository | 14347 |
| static S1 pairs also observed | 225 |
| static S1 pairs **not** observed by this command | 14122 |

All 120 unbound callees are `<genexpr>`, `<dictcomp>`, `<listcomp>`,
`<setcomp>` and `<lambda>` frames. They are kept rather than filtered, because
they are real observed calls; consumers that want definition-level edges filter
on `callee_binding_status == "bound"` or read `fully_bound_relation_count`.

## Separation from S0/S1

The last row of the table is the point of the whole artifact. One command
exercised 225 of 14347 statically resolved edges. The other 14122 are not dead,
not unreachable and not suspect — they were simply not on this command's path.

The separation is enforced, not just documented:

- the overlay has no `calls` array and no `resolution_statuses`; a document
  carrying either is refused (`observed_call_overlay_static_fields_present`);
- an overlay relation carrying `S0` or `S1` is refused
  (`observed_call_overlay_static_evidence_level_present`);
- a static call graph carrying `S2` is refused
  (`python_call_graph_observed_evidence_present`);
- reading the two together only annotates `static_correspondence`
  (`matches_s1`, `matches_s0_candidate`, `absent_from_static_graph`,
  `static_graph_not_supplied`). `matches_s0_candidate` does **not** promote the
  static site to S1; the static graph still says candidate.

## Negative semantics

`absence_semantics` states in the document that a relation missing from the
overlay means the traced command did not exercise it in this environment at
this revision. `does_not_establish` additionally names `dead_code`,
`unreachable_code`, `complete_call_graph`, `runtime_reachability`,
`static_resolution_upgrade`, `dynamic_dispatch_resolution`,
`coverage_sufficiency`, `test_sufficiency`, `review_completeness` and
`merge_readiness`; the producer adds `deterministic_reproduction` and
`environment_equivalence`. The read surface repeats the same list.

An overlay is a record of one run. A second run of the same command may observe
a different set of edges, and the overlay does not claim otherwise.

## Validation scope

`merger/repoground/tests/test_observed_call_overlay.py` (30 tests) traces a
fixture package inside a real temporary git checkout and covers: repo-local
edge recording; JSON Schema conformance; full observation identity and the
five ways an incomplete identity is refused; relations bound to a foreign
observation; refusal of a checkout without a revision, at producer and CLI
level; decorated-definition anchoring; module-scope callers; foreign callers
without a citable call site; counter drift; both directions of static-evidence
contamination; the dynamically dispatched call that is observed while staying
S0 statically; the statically resolved edge the trace never took; navigation
correspondence with and without a static graph; invalid queries and invalid
overlays; and a command that raises, whose partial observations are kept with
the failure recorded in `execution_outcome` and `skipped_errors`.

## What this does not establish

The overlay does not establish coverage sufficiency, test adequacy, runtime
correctness, reproducibility across runs or environments, completeness of the
call graph, or merge readiness. Tracing runs the target command in-process:
that is a deliberate operator action with the operator's own side effects, and
RepoGround does not review, sandbox or vouch for the command it was asked to
observe.
