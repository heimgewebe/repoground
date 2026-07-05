---
title: RepoBrief Scheduled Snapshots
status: draft
doc_type: architecture
canonicality: supporting
---

# RepoBrief Scheduled Snapshots

## Decision

Scheduled RepoBrief runs may keep important repositories supplied with current Brief Bundles, but the schedule is only an execution clock. It is not a new authority layer.

The scheduled path must call the explicit `repobrief snapshot create` command for configured repositories. It must not update source checkouts, create pull requests, apply patches, or interpret a green run as a review result.

## System role split

- RepoBrief owns snapshot generation and artifact health.
- The local user service owns cadence only.
- Bureau and Cabinet may consume summaries, but they do not canonize repository truth from a timer result.
- Grabowski should treat a scheduled Brief Bundle as evidence with freshness and provenance, not as proof that the repository is correct.

## Configuration model

Use a small per-repository environment file under `~/.config/repobrief/snapshots/`.

Each file should define:

```text
REPOBRIEF_REPO=%h/repos/lenskit
REPOBRIEF_OUT=%h/lenskit-out/repobrief/lenskit
REPOBRIEF_PROFILE=agent-portable
```

Optional:

```text
REPOBRIEF_OUTPUT_MODE=dual
REPOBRIEF_LENSKIT_ROOT=%h/repos/lenskit
```

## Unit sketch

A local user service can read the configured repository file and invoke the existing CLI. The service is intentionally a thin wrapper around one explicit command:

```ini
[Service]
Type=oneshot
EnvironmentFile=%h/.config/repobrief/snapshots/lenskit.env
WorkingDirectory=%h/repos/lenskit
ExecStart=/usr/bin/python3 -m merger.lenskit.cli.main repobrief snapshot create --repo ${REPOBRIEF_REPO} --out ${REPOBRIEF_OUT} --profile ${REPOBRIEF_PROFILE}
```

A timer may run this service daily with `Persistent=true` and a randomized delay. For several repositories, prefer one configured instance per repository or a small batch wrapper that only iterates configuration files and calls the same command.

## Safety requirements

1. Output directories stay outside source repositories.
2. Scheduled runs do not refresh or repair checkouts.
3. Missing configuration is a hard failure, not a silent pass.
4. A stale snapshot is acceptable only when it is labeled as stale or otherwise lacks freshness proof.
5. A generated bundle never establishes truth, completeness, runtime correctness, or test sufficiency.

## Recommended rollout

Start with `lenskit`, `bureau`, `cabinet`, `weltgewebe`, and `infra`. Add experimental repositories only when their output profile and storage budget are explicit.

Do not enable every repository blindly. The useful unit is not “everything is fresh”; the useful unit is “the system can say which briefings are fresh, stale, missing, or failed.”
