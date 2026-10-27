# RepoGround Agent Change Evidence Pack (Thread 3, implementation wave 1)

This document describes the **current source contract** on the associated implementation branch. It does not attest a deployed agent client, published pipeline or merged PR.

## Purpose and authority

`agent-evidence` reads **existing Git objects** and, optionally, one **already published RepoGround bundle**. It combines the existing `delta_context.compile_delta_context` projection with revision-bounded Git diff metadata. It never builds a snapshot on a read path. It makes no review, risk, test-sufficiency, merge, patch or deployment decision. Git/CI and the authorized agent remain primary sources for those decisions.

Six `--use-case` profiles share **one** underlying deterministic report: `explain-change`, `find-related-tests`, `contract-impact`, `cross-repo-impact`, `what-changed-since` and `source-and-proof`. A profile is a task label/hint request, **not** a guarantee the underlying index contains evidence for it.

## CLI

Use full 40-character SHA-1 Git object identities from the **same local checkout**; shell branches or arbitrary revision expressions are rejected.

```bash
python -m merger.repoground.cli agent-evidence \
  --repo-root /absolute/path/to/existing/repo \
  --base <40-character-git-commit> \
  --target <40-character-git-commit> \
  --bundle-manifest /absolute/path/to/existing.bundle.manifest.json \
  --use-case explain-change --budget-tokens 1200 --emit json

# Or the identical core as Markdown:
python -m merger.repoground.cli agent-evidence \
  --repo-root /absolute/path/to/existing/repo \
  --base <base-sha> --target <head-sha> --emit markdown
```

Leave out `--bundle-manifest` when unavailable: the report marks missing bundle evidence and falls back to the Git diff. Optional `--expected-diff-sha256` fails closed if the caller's expected Git diff differs. The canonical JSON's `response_sha256` is SHA-256 of sorted compact JSON **before the digest field is inserted**; Markdown prints that same digest.

Diff generation uses `git diff --no-ext-diff --no-textconv --no-renames --unified=3 base head --`. Reported line ranges are **diff hunk ranges**, not precise changed-line subsets. For deleted-line-only hunks and binary files, ranges may be unavailable; no fabricated line address is inserted. Multiple paths or truncated diffs are bounded and declared.

`status=warn` indicates missing bundle, dirty checkout, truncated display, compiler degradation or other explicitly reported gaps. `status=invalid` indicates an unsupported/unsafe revision, oversized diff, missing object or incomplete diff. Normal native `git diff`, `rg`, tests and CI remain first-class fallbacks.

## MCP

The existing stdio server advertises exactly one additional **read-only** tool, `change_evidence_pack`, **only when started with `--repo-root`**. Without `--repo-root`, the old MCP tool list remains unchanged. Its arguments include `base_revision`, `target_revision`, optional `use_case`, `context_budget_tokens` (1–4000), `expected_diff_sha256`, and the standard existing bundle selectors (`bundle_manifest` OR `repo`/`stem`). The existing manifest boundary and frozen-manifest handling apply. The result uses `structuredContent`; `live_freshness` is separately attached by the existing MCP server and is **not** included in the core `response_sha256`.

If no **healthy** bundle matches and no explicit manifest path was requested, the
MCP handler now returns **Git-only** evidence with `live_freshness.status=not_comparable`
and `implicit_refresh=false`, rather than blocking source-diff reporting.
Ambiguous selections and invalid/forbidden explicit manifests still fail
closed. The project launcher must nevertheless point to an existing bundle
root; it cannot create a missing publication directory from a reader.

The tool does not fetch Git objects. Commit objects not available locally must be obtained by the authorized Git/operator workflow; client MCP requests never fetch them implicitly.

## Evidence levels and limits

- `direct_git_diff`: Git reports the path and hunk range between the supplied commit objects.
- `name_candidate_not_verified_coverage`: an **actual tracked test path**
  at the target commit has exactly the expected `test_<module>.py` or
  `<module>_test.py` basename. This is useful for test selection but is
  **not proof the test exercises the changed implementation**.
- `changed_contracts`: explicit changed `contracts/` or schema-named paths
  from Git. Contract consumers and compatibility remain unknown.
- `change_status_counts`: directly reported added, deleted and modified paths.
- `bundle_navigation_hint_not_verified_impact`: An existing bundle artifact suggests navigation; this **does not establish a caller, contract, runtime effect or test obligation**.
- `unknown`: Bundle unavailable, stale or unmatched; relation candidates absent; ambiguous bundle identity; no evidence from other repos.

The output is limited to 2 MB Git diff, 30 changed-file display entries, 12 exact-name test-path candidates and 12 bundle hints, with a 15-second built-in Git read timeout. These limits are per request; no global event scheduling or rate limit is asserted. The Git worktree and missing-source boundaries are explicit.

## Real reproducible check

In the RepoGround source checkout (assuming the objects remain available), the real **PR #1351 merge first-parent** change set is:

- base: `274274ded84a94bc4c0af6a525b3485ba17e3b79`
- target and currently published bundle source: `bf2ad72785c47ede4b8b94ce2215b07e4773877e`
- observed Git diff SHA-256: `962184701c36d275c4da8d09b0d09d46f9be2fa4e8705a59cbd79ba87749d65b`
- observed 5 changed files, 0 relation hints; source-bound output status `warn` because this coding worktree was dirty and the strict candidate budget omitted some context.
- observed report SHA-256 for that *dirty worktree* instance: `8be0da923c3ea39cae2049ad1c3f631d3ffc4a47cf8036ebd77b47c18842ad3d`. This digest will change when the worktree becomes clean.

The first command must use the merge's **first parent**, not its second parent (which produced an empty diff in the observed repo). PR #1352 is still a distinct open roadmap PR; this report does not represent its head, because that Git object was not available in the local checkout and Grabowski's guarded Git interface refused an unclassified `fetch`. No bypass was attempted.

## Tests / still outstanding

Focused pytest with Nix-provisioned Python packages: **67 passed** for new evidence including tracked test candidates, Git-only MCP fallback, project launcher, and unchanged MCP/context compiler cases. Ruff: **all checks passed**. Independent review, PR integration and live consumer-client acceptance are separate gates. Later Thread 3 waves will add explicit publisher-owned idempotent Git/CI event receipts; **the read-only evidence endpoint is not an event watcher**. Extensions from Threads 1 and 2 must consume their versioned response contracts rather than editing their internal modules.
### Additional checks on the consumer branch

On the updated consumer head after Git-based test matching and MCP fallback
code changes, the **full RepoGround Python test suite** ran with an isolated
Nix Python dependency environment and four documented main-baseline failures
deselected. Result: **6115 passed, 12 skipped, 4 deselected**, 249.26 s.
The four excluded cases had failed identically on unchanged clean `main`.
This does not claim that every test passes without exceptions.

A real subprocess invocation of the **project MCP launcher** (referenced by
the tracked `.mcp.json` for Claude Code) completed JSON-RPC
`initialize` -> `tools/list` -> `tools/call` against the existing
RepoGround bundle and the actual merged PR #1351 Git diff. It advertised
`change_evidence_pack` with `readOnlyHint=true`, returned five changed
files, no write authority and `live_freshness=stale` for the newer checkout.
This verifies the actual MCP protocol, not autonomous Claude Code model usage.

The currently installed user Codex config points to an older RepoGround runtime
but **does not pass `--repo-root`**, so it does not advertise the new
Git-based evidence tool. The tracked Claude project launcher already passes
the required argument. No shared user config or runtime was modified here;
an authorized separate revision-bound consumer rollout remains necessary.
Actual Codex and Claude model-invocation traces are still unverified.
