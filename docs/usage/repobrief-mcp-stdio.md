# RepoBrief MCP stdio

RepoBrief can run as a local Model Context Protocol server over standard input and output.
The server exposes existing RepoBrief bundles and handlers; it does not invent a second
snapshot or grounding implementation.

## Start

Use the launcher by absolute path. It adds its own Lenskit checkout to the Python import path,
so the MCP client does not need to start inside the repository:

```bash
python3 /absolute/path/to/lenskit/scripts/repobrief-mcp-stdio.py \
  --bundle-root /absolute/path/to/briefs \
  --repo-root /absolute/path/to/repository
```

`--bundle-root` may name either a directory containing `*.bundle.manifest.json` files or
one exact bundle manifest. `--repo-root` is optional for the default read-only server, but
without it live freshness is reported as `not_comparable` and no Git probe runs.

The module form remains valid when the Lenskit checkout or installed package is already on
Python's import path:

```bash
python3 -m merger.lenskit.cli.repobrief_mcp_stdio \
  --bundle-root /absolute/path/to/briefs \
  --repo-root /absolute/path/to/repository
```

## Generic MCP client configuration

Clients that accept an MCP stdio command can use this shape:

```json
{
  "mcpServers": {
    "repobrief": {
      "command": "python3",
      "args": [
        "/absolute/path/to/lenskit/scripts/repobrief-mcp-stdio.py",
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
bundle root, and optional repository root are the stable RepoBrief side of the contract.

## Exposed tools

Read-only by default:

- `ask_context`: builds the existing cited context pack from one registered bundle;
- `grounding_verify`: runs the existing declaration and evidence verifier;
- `live_freshness`: compares the snapshot commit and cleanliness with the configured checkout.

Optional explicit write tool:

- `snapshot_create`: available only with `--enable-snapshot-create` and an explicit
  `--repo-root` at server startup.

When enabled, the MCP client may select the snapshot profile and bounded generation options,
but it cannot choose another source repository or output root. The source remains the startup
`--repo-root`; output remains the startup `--bundle-root` directory, or the parent directory
when `--bundle-root` names one exact manifest. Existing timeout, size, path, and output-not-inside-
repository guards still apply.

## Exposed resources

The server lists and reads the existing resource surface:

- `repobrief://snapshot/{stem}/manifest`
- `repobrief://snapshot/{stem}/canonical`
- `repobrief://snapshot/{stem}/reading-pack`
- `repobrief://snapshot/{stem}/health`
- `repobrief://snapshot/{stem}/availability`
- `repobrief://snapshot/{stem}/artifact/{role}`

Resource results retain the existing health, availability, and snapshot-bound freshness
metadata. When `--repo-root` is configured, the result metadata also includes live freshness.

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
