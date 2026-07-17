# RepoGround API Query Contracts

This document strictly specifies the response structures returned by the `/api/query` endpoint in RepoGround, specifically outlining the integration of `output_profile`, `context_bundle`, and `query_trace`.

## 1. Raw Result (No Output Profile)
**Condition:** `output_profile` is not specified or is empty.

**Contract:**
* Returns the raw internal evaluation result.
* The structure does **not** contain a top-level `hits` array.
* The structure contains a top-level `results` array with un-projected query artifacts.
* `context_bundle` appears if context-building is triggered by any of the following:
    * Explicitly via `build_context_bundle=True`
    * Implicitly via `context_mode != "exact"`
    * Implicitly via `context_window_lines > 0`
* `query_trace` appears **only** if `trace=True` is explicitly requested.
* Internal fields used during execution (e.g., `_raw_content`) are deliberately stripped from the result mapping.

## 2. Projected Context Bundle (With Output Profile)
**Condition:** `output_profile` is specified (e.g., `agent_minimal`, `ui_navigation`) and `trace` is not requested.

**Contract:**
* Returns the canonical **Context-Bundle** structure directly at the top level.
* Replaces the `results` structure with the standardized `hits` array format as defined by the Context-Bundle schema.
* The structure contains a top-level `hits` array with fully formatted context blocks.
* Additional profile-specific projection is applied to reduce noise:
    * **`agent_minimal` profile:**
        * Explicitly strips the `explain` (verbose scoring breakdown) and `graph_context` blocks from each hit to optimize for token-constrained agent consumption.
        * Explicitly strips `surrounding_context` if it evaluates to `null`.

## 3. The Trace Wrapper (Output Profile + Trace)
**Condition:** Both `output_profile` and `trace=True` are specified.

**Contract:**
* Because the Context-Bundle schema strictly forbids arbitrary additional properties, `query_trace` **must not** be injected directly into the bundle.
* Instead, a wrapper object is returned containing exactly two keys:
    1. `context_bundle`: The fully projected Context-Bundle (following the rules in Section 2).
    2. `query_trace`: The full diagnostic execution trace (including `timings`, `status`, etc.).
* Agents and downstream consumers must expect this wrapped structure when requesting diagnostic traces alongside a projected profile.
