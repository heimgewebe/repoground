# RepoGround: authenticated Fleet Git/CI event bridge — proof

Date: 2026-10-27. Source-only; production activation is not claimed.

## Source and role separation

Parent RepoGround PR #1358 HEAD `7013c03ac39eeea1dc001db7b5bf84bc58b33369`,
itself based on #1357. Independent work lane
`67acfcf58396153787811bc9bb1c92c9`, branch
`feat/repoground-thread3-fleet-auth-events-20261027`.
Changes are limited to the existing Fleet publisher, a targeted test module
and this proof. No modifications to the original #1357/#1358 leased files.

## Method and truth boundaries

The installed `repoground-publish-fleet-watch.timer` runs hourly, and
`repoground-publish-fleet-watch.service` invokes the existing publisher with
`--if-changed --retention 3 --limit 8`. The new source hook uses that publisher,
its remote-head observation, existing state and bundle, and #1358's
`publish_event` / `read_event_receipt` functions. No new scheduler, webhook
server, daemon or deployment exists.

The publisher checks provider-authenticated GitHub REST responses using the
operator's logged-in `gh api` client. It requires the returned Git commit SHA
and the completed CI check-run `head_sha` to equal the observed source SHA.
This is **authenticated API polling**, **not** a signed webhook. The #1358
event core still marks its own input as
`caller_assertion_not_verified_remote_event`; authentication and provider
response digests are separate publisher observations. They must not be
transformed into a claim of core-verified GitHub provenance.

The exact bundle is held with `use_manifest_binding` through publication and
readback. Receipt readback checks content integrity. Re-delivery reuses the
initial publisher-observed time after validated readback, allowing deterministic
deduplication. Event ID conflicts fail closed. The existing Fleet lock
serializes production polls; #1358 maintains its own per-receipt file lock.
No automatic code, review, merge or deployment effects occur.

The outbox is outside source repositories and is append-only within a
512-receipt-per-repository capacity bound; it does not silently delete pinned
historical evidence. The most recent 16 CI runs for one current HEAD are
examined per poll. Incomplete pagination reports `partial` rather than
pretending to cover every check run.

## Real live-provider probe, distinct from production

The successful Grabowski systemd task `5848b63bcbab4c76a202c3c1`
(argv SHA-256 `4ff698cf285d0324e4aaecc95e0de7f9a0b731de62f1ba6859279dc98ac8fcdc`)
used the actual GitHub API and Git objects for RepoGround main at
`bf2ad72785c47ede4b8b94ce2215b07e4773877e`, with manifest SHA-256
`3cb05bc19c98662eb4a4104adbe1317e18d002883b055a7fac99f097bbf0452f`.

The isolated **temporary** outbox produced 17 files on the first delivery
(one `git.commit`, sixteen `ci.completed`); all 17 were deduplicated on
redelivery, with no new files. Exact read-only receipt retrieval succeeded.

- Git event key:
  `4281b3fe625b22b13b459d95566b5e26f2115ff88869c18c03ab72cca0a7524d`
- Git event receipt SHA-256:
  `812084403dc3e34cd5f5c0de276e33f99ae92c5f61d775bbbad05130fef2c40d`
- CI example event key:
  `8d91ac09db5886fbc25db31ffc0d14660e4ed83e2bb6f8e551eca723ce370dbb`
- CI example receipt SHA-256:
  `1dfef181a49584efb01aa27838b723336a2dd938b33b02a431cfc001720c3407`

Status `partial` identifies the 16-check-run first-page limit. Test output
was removed with its temporary directory. No claim of production outbox
delivery or currently active source can be made from this result.

## Checks and remaining gates

Targeted NixOS pytest: **335 passed, 2 deselected** for existing baseline
sandbox environment failures. Ruff check: **pass**. Regression coverage
includes real event identity, dedup, provider mismatches, check-run conflicts,
integrity tamper, unsafe time, missing authorization and retention capacity;
the original #1358 tests independently cover concurrent first delivery.

Before operational acceptance: commit and publish this isolated branch as a
reviewed stacked PR after #1358, merge #1357 and #1358 via Captain, run
the complete refreshed CI/reviews, prove two distinct real agent consumers,
and obtain the installed Fleet timer's *own* authenticated event creation
and readback. Longer CI-history replay and safe retention at capacity need
an explicit review, not an implicit success claim.

## Review findings corrected before final head

The first published stacked PR #1360 head
`7bfbd14a8d3c79c5482fb12e0e1032c62a345a86` received two substantive Codex review findings.
Both were corrected in the same original PR branch before merge:

1. P1: the managed wrapper launches Python in isolated `-I` mode.
   The Fleet source script now bootstraps **only its own resolved
   release/source root**, allowing the read-only `merger` event modules
   to be imported without trusting current cwd or PYTHONPATH. An isolated
   subprocess test proves the imported event entrypoint.
2. P2: deduplication of an existing receipt after a new same-revision bundle
   generation **does not re-label the stored event with the new manifest SHA**.
   `bundle_manifest_sha256` now comes from the integrity-checked
   original receipt; `observed_manifest_sha256` and
   `bundle_generation_binding` separately disclose the newly
   observed publication. The regression explicitly changes the bundle
   manifest's run ID and checks both generations.

A further authentication hardening rejects **anonymous GitHub API polling**.
Each authorized polling iteration now first completes authenticated GET
`/user` and validates the returned login and numeric GitHub user ID.
The publisher persists only SHA-256 principal binding in the bounded
per-event summary, never a credential. The underlying event adapter
still honestly labels its caller-supplied event data as unverified.

Post-fix checks on the isolated checkout:
- Focused source/event regression: **30 passed**, exit 0.
- Ruff: **all checks passed**, exit 0.
- Whole RepoGround Python suite, now also under `python -I -B -m pytest`:
  **6150 passed, 12 skipped, 4 deliberately deselected unchanged-main
  environment failures**, exit 0. Grabowski task
  `3755fbc1881e4a7e96f843f1`, output SHA-256
  `387ec10b940f35052c93401283bab37f1ed56dbf756503f66993a67e283d935a`.

A second real, logged-in GitHub REST probe with the fixed isolated
Python `-I` runtime was performed in Grabowski task
`2b99f8b6dda249e1a908503c`, output SHA-256
`f3e1c0860b972cf15a03472f65bc75ce2577a03bf31a4a045a656ec4bd62e274`.
It produced one real Git commit + 16 real completed CI-event receipts,
with 17/17 duplicate deliveries deduplicated, verified bundle alignment
and authenticated GH principal binding. Status remained `partial`
because of the deliberate first-page check-run limit; this is still a
**temporary functional demonstration**, not productive timer delivery.

## Second real coding-agent consumer: Codex CLI

Separately from the Grabowski RepoGround MCP caller, an actual
`codex exec --sandbox read-only --skip-git-repo-check --ephemeral --json`
session (task `c842e31e6dda4c8f84fe5322`) loaded the pre-existing
`~/.codex/config.toml` RepoGround MCP server. The actual Codex
JSONL trace, SHA-256
`4c16d0234c2f6f41b79bcf237b9159ed6740be36a2c73b2566360c53e60b23a8`,
includes successful `repoground.query_existing_index` and
`repoground.ask_context` MCP tool calls with the exact
published manifest SHA-256
`3cb05bc19c98662eb4a4104adbe1317e18d002883b055a7fac99f097bbf0452f`
(RepoGround base commit
`bf2ad72785c47ede4b8b94ce2215b07e4773877e`).

The tool responses returned real MCP source locations and tests, including
`merger/repoground/cli/mcp_stdio.py`,
`merger/repoground/core/mcp_tools.py`,
`merger/repoground/tests/test_mcp_stdio.py`,
`test_mcp_stdio_e2e.py` and `test_mcp_query_routing.py`.
Codex explicitly reported `live_freshness=not_comparable`
because this global stdio configuration has no `--repo-root`,
and no assertion of PR-head completeness, review approval, coverage,
merge readiness or deployed code was made.

The two real consumers have now been exercised independently, but
**they have not yet consumed the final merged #1357/#1358/#1360 code**.
Fresh post-Captain readbacks remain mandatory.
