# GitHub Actions Node 24 native migration — proof

Date: 2026-07-10

## Decision

Lenskit no longer forces Node 24 onto actions that declare an older runtime. Instead, each locally referenced first-party JavaScript action uses the smallest reviewed major that declares `runs.using: node24` upstream:

| Action | Lenskit minimum | Upstream declaration |
|---|---:|---|
| `actions/checkout` | v5 | `node24` |
| `actions/setup-node` | v5 | `node24` |
| `actions/setup-python` | v6 | `node24` |
| `actions/upload-artifact` | v6 | `node24` |
| `github/codeql-action/{init,autobuild,analyze}` | v4 | `node24` |

Observed upstream `action.yml` blobs during this review:

- `actions/checkout@v5`: `767c416494ebd353bb13c8e2a97af6c539648576`
- `actions/setup-node@v5`: `fbc851b6e56c64db8ad81b50878c5cfe4531505d`
- `actions/setup-python@v6`: `7a9a7b634ec348b35b882f1f14fcaa4d41836a8e`
- `actions/upload-artifact@v6`: `28f04cc696830ad0609506e0888d8b3b83d5d616`
- CodeQL `init@v4`: `1b64e8d2a37962e01818d0ff1bba97bb56d045c6`
- CodeQL `autobuild@v4`: `b87da541d66725fab4511394c5e143ef16d1105c`
- CodeQL `analyze@v4`: `d70401c0a48ad4246c1ef34787e79f5cad4d8281`

The repository-wide `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` override is removed. A test ratchets the minimum major for every occurrence in `.github/workflows` and rejects any reintroduction of the override.

The external Claude action is a composite action and was not covered by the removed override in its workflow. Reusable workflows remain independently versioned producers; this change does not claim their internal action runtimes.

## Validation

```text
python3 -m pytest merger/lenskit/tests/test_github_actions_node_runtime.py -q
actionlint .github/workflows/*.yml
```

GitHub-hosted PR checks are the integration proof for action input/output compatibility.

## Non-claims

Major tags are mutable upstream references. This migration establishes the declared Node runtime and successful reviewed CI, not immutable supply-chain pinning, future compatibility, absence of upstream compromise, or correctness of reusable workflows maintained in other repositories.
