# RepoGround MCP stdio

RepoGround can run as a local Model Context Protocol server over standard input and output.
The server exposes existing RepoGround bundles and handlers; it does not invent a second
snapshot or grounding implementation.

## Start

Use the launcher by absolute path. It adds its own RepoGround checkout to the Python import path,
so the MCP client does not need to start inside the repository:

```bash
python3 /absolute/path/to/repoground/scripts/repoground-mcp-stdio.py \
  --bundle-root /absolute/path/to/briefs \
  --repo-root /absolute/path/to/repository
```

`--bundle-root` may name either a directory containing `*.bundle.manifest.json` files or
one exact bundle manifest. `--repo-root` is optional for the default read-only server, but
without it live freshness is reported as `not_comparable` and no Git probe runs.

The module form remains valid when the RepoGround checkout or installed package is already on
Python's import path:

```bash
python3 -m merger.repoground.cli.mcp_stdio \
  --bundle-root /absolute/path/to/briefs \
  --repo-root /absolute/path/to/repository
```

## Project-local configuration

The repository tracks `.mcp.json`, which starts `scripts/repoground-mcp-project.py`.
For a checkout opened as an MCP-aware project, this is the canonical configuration. The launcher
binds `--repo-root` to that checkout and uses `~/.local/share/repoground/bundles` by default.
Set `REPOGROUND_BUNDLE_ROOT` only when an operator intentionally uses another existing bundle
root. Snapshot creation remains disabled unless `REPOGROUND_MCP_ENABLE_SNAPSHOT_CREATE=1`.

## Generic MCP client configuration

Clients that accept an MCP stdio command can use this shape:

```json
{
  "mcpServers": {
    "repoground": {
      "command": "python3",
      "args": [
        "/absolute/path/to/repoground/scripts/repoground-mcp-stdio.py",
        "--bundle-root",
        "/absolute/path/to/briefs",
        "--repo-root",
        "/absolute/path/to/repository"
      ]
    }
  }
}
```

The client-specific file location or registration command varies. The absolute launcher,
bundle root, and optional repository root are the stable RepoGround side of the contract.

## Exposed tools

Read-only by default:


<!-- repoground-mcp-tools:start -->
- `bundle_discover`: List healthy existing bundles or select one by repository identity/stem.
- `snapshot_status`: Read health, availability and freshness for one selected existing bundle.
- `ask_context`: Build a cited context pack from one existing RepoGround bundle.
- `query_existing_index`: Route exact symbol-definition questions to the symbol index; otherwise use exact AND and labelled OR fallback with bounded cited ranges.
- `range_get`: Resolve one exact bundle range reference without reading a live workspace.
- `grounding_verify`: Verify declared citations and ranges against an existing RepoGround bundle.
- `live_freshness`: Compare snapshot Git provenance with the configured local checkout without refreshing it.
- `find_symbol`: Locate Python symbol definitions by name with exact path and line range.
- `find_references`: List bounded static call sites for a callee name.
- `get_callers`: Group uniquely resolved callers for one exact target symbol.
- `get_callees`: Group uniquely resolved outgoing calls for one exact caller symbol.
<!-- repoground-mcp-tools:end -->

Snapshot-targeting read tools accept either `bundle_manifest` or the agent-facing
`repo`/`stem` selectors. An exact manifest cannot be combined with selectors. The
server selects only a unique healthy publication and rejects missing or ambiguous
selection instead of falling back to an older unrelated bundle.

Tool calls return the complete typed payload once in `structuredContent`. The text
content is only a small status summary, so clients do not receive the same large
JSON object twice. `query_existing_index` routes explicit symbol-definition
questions through the exact symbol index first. For broader content questions it
shares `ask_context`'s exact-AND then labelled relaxed-OR retrieval strategy.
Context is bounded globally and per hit; empty and duplicate excerpts are omitted.

The call-navigation tools read only bundle-registered `python_call_graph_json` and `python_symbol_index_json` artifacts. They validate artifact integrity and provenance coherence before returning symbol relations. `S1` means one unique local target under the producer's bounded static rules; it does not mean the target executes at runtime. `S0` preserves uncertainty instead of guessing.

Optional explicit write tool:

- `snapshot_create`: available only with `--enable-snapshot-create` and an explicit
  `--repo-root` at server startup.

When enabled, the MCP client may select the snapshot profile and bounded generation options,
but it cannot choose another source repository or output root. The source remains the startup
`--repo-root`; output remains the startup `--bundle-root` directory, or the parent directory
when `--bundle-root` names one exact manifest. Existing timeout, size, path, and output-not-inside-
repository guards still apply.

Snapshot profiles whose canonical policy sets `redaction_required=true` now enable secret
redaction by default before generation. An explicit `--no-redact-secrets` override for such a
profile is rejected before the output directory is created. The JSON result records whether
redaction was enabled, required by the profile, and selected explicitly or by the safe profile
default.

## Exposed resources

The server lists and reads the existing resource surface:

- `repoground://snapshot/{stem}/manifest`
- `repoground://snapshot/{stem}/canonical`
- `repoground://snapshot/{stem}/reading-pack`
- `repoground://snapshot/{stem}/health`
- `repoground://snapshot/{stem}/availability`
- `repoground://snapshot/{stem}/artifact/{role}`

Resource results retain the existing health, availability, and snapshot-bound freshness
metadata. When `--repo-root` is configured, the result metadata also includes live freshness.

### Canonical resource identity

Only `repoground://snapshot/...` resource URIs are accepted. Former schemes are
rejected before bundle lookup; there is no translation flag or read-only alias.
The rule is defined by
[`repoground-naming-hard-cut.v1.json`](../contracts/repoground-naming-hard-cut.v1.json).

## Freshness meanings

- `fresh`: snapshot commit equals local `HEAD`, and both the snapshot and current tree are clean;
- `stale`: the commit differs, the current tree is dirty, or the snapshot was created dirty;
- `unknown`: required snapshot provenance or cleanliness evidence is missing or does not identify
  the configured checkout;
- `not_comparable`: no checkout was configured, Git is unavailable, or current cleanliness
  cannot be established.

A manifest-recorded local path is evidence, not permission. Only the operator-provided
`--repo-root` authorizes a Git probe. A read never invokes `snapshot_create`, `git fetch`,
`git pull`, or another repair action. Staleness is reported, not hidden.

## Security boundary

- tool-supplied manifests must remain inside the configured bundle root;
- an optional citation map must remain inside the selected bundle directory;
- the MCP client cannot select an arbitrary Git checkout: the probe is bound to `--repo-root`;
- optional snapshot writes cannot replace the startup repository or output root;
- the Git probe disables optional locks, fsmonitor, global Git configuration, system Git
  configuration, and terminal prompts;
- the server has no TCP or HTTP listener and writes only MCP JSON-RPC messages to stdout;
- Git push/pull/fetch, shell execution, patches, pull requests, secrets, reviews, fixes, and
  merges remain outside the server authority.

Successful access or a `fresh` verdict does not establish repository truth, answer correctness,
test sufficiency, review completeness, runtime correctness, or merge readiness.
