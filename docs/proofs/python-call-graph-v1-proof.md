# Python call graph v1 proof boundary

Task: `RPU-V1-T023`

## Result

Lenskit emits the additive bundle role `python_call_graph_json` from Python source text and exposes three bounded read-only RepoBrief MCP tools:

- `find_references` lists static call sites matching a callee name and keeps their S0/S1 evidence visible;
- `get_callers` first selects one exact target symbol from the coherent Python Symbol Index, then returns only S1 call edges whose `resolved_target_ids` contain that symbol;
- `get_callees` first selects one exact caller symbol, then groups its S1 targets while retaining candidate, ambiguous and unresolved S0 call sites separately.

A tool request that names more than one exact symbol fails closed unless an optional path disambiguates it. Equal names in different files are not merged into one target.

## Evidence model

Every `ast.Call` record carries:

- source path, line/column range and `range_ref`;
- enclosing module, class, function or async-function identity, including the exact definition start/end range for symbol callers;
- callee expression and simple name when present;
- relation type `calls` or `constructs`;
- evidence level `S0` or `S1`;
- resolution status and reason;
- resolved or candidate symbol IDs.

`S1` means exactly one local target was resolved under the modelled static bindings. Bare-name recursion is upgraded only for one uniquely bound top-level function; a same-named method body or a redefined module function remains S0. Parameters, assignments, local imports, loop/with/except targets, comprehensions, walrus targets, nested definitions, lambda parameters, nonlocal bindings and invalid receiver names prevent an unsafe upgrade. Shadowed, ambiguous, dynamic, foreign and unindexed calls remain S0. `global` may reach an unambiguous module binding. Function decorators, defaults and annotations as well as class decorators, bases and keywords are visited before entering the newly defined scope, so their calls are not attributed to the definition being created.

The producer parses source through the standard-library AST. It does not import or execute repository code. Unique local class construction is represented as an S1 `constructs` relation; method resolution through `self` or `cls` is limited to the actual first parameter of a direct method in the enclosing class.

## Bundle and provenance coherence

The call graph and Python Symbol Index are generated in the single-repository bundle path with the same `run_id` and `canonical_dump_index_sha256`. The role is registered as:

- contract `python-call-graph` / `v1`;
- authority `navigation_index`;
- canonicality `derived`;
- risk class `navigation`;
- regenerable and staleness-sensitive;
- excluded from `public-share` profiles.

Consumers verify artifact bytes through the bundle manifest, validate the v1 record model and aggregate counters, require coherent call/symbol identities, and bind each symbol caller to the exact Symbol Index definition range. Duplicate definitions with the same legacy symbol ID remain separate callers; mismatched caller ranges and absent resolved targets fail closed.

## Agent surface

The Agent Reading Pack contains a `CALL_GRAPH_INDEX` section. It points to the registered artifact and explains the three tools, the S0/S1 distinction and the negative semantics. Every stdio tool result also carries the existing live-freshness projection; reads never rebuild a bundle, refresh a snapshot or mutate Git.

## Validation scope

Focused tests cover:

- direct, imported and aliased calls;
- direct recursion, constructors and same-class receiver methods;
- parameter, assignment, local-import, loop, comprehension, walrus, nested-definition, lambda and nonlocal shadowing;
- function decorator/default and class base/body attribution;
- duplicate definitions, equal symbol names in different files and duplicate caller IDs with distinct definition ranges;
- strict artifact shape, aggregate counters and call/symbol provenance binding;
- target-identity-based callers and caller-identity-based callees;
- explicit unresolved call sites;
- MCP transport, live freshness and a real launcher subprocess round trip;
- real single-repository bundle emission and schema validation.

The complete focused and repository-wide validation counts are recorded in the pull request and its exact-head CI, not frozen as timeless contract values in this document.

## Compatibility

The artifact is additive. Existing bundles and profiles without `python_call_graph_json` remain readable; call-navigation requests against such bundles return an explicit missing result. No existing retrieval ranking or default context route consumes call relations in this slice.

## Does not establish

This slice does not establish complete call-graph coverage, runtime reachability, dynamic dispatch resolution, dependency completeness, import success, test sufficiency, review completeness, security correctness, agent-quality improvement, default-promotion readiness or merge readiness.
