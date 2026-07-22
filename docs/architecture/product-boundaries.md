# RepoGround product boundaries

Status: accepted architecture boundary for `REPOGROUND-LEGACY-RECONCILIATION-V1-T003`.

## Kernel

RepoGround's kernel is the repository/evidence pipeline: source acquisition, deterministic
bundles, retrieval, citations, architecture/navigation artifacts, health checks and read-only
consumer surfaces. A normal kernel operation must not delete source repositories or generic
input folders and must not implicitly start broad filesystem scans.

## Atlas: keep as an optional observation subsystem

**Decision: KEEP, explicitly bounded.**

Atlas has current first-party integration through `repoground atlas`, authenticated service
endpoints and the Web UI. Persisted Atlas artifacts also exist on the live host, so removal or
an immediate repository split would create migration work without evidence of a benefit.

The boundary is:

- Atlas is activated only by explicit Atlas CLI/API actions.
- Repository dumps, queries and fleet publications do not implicitly run Atlas.
- Atlas observations are evidence artifacts, not commands or deletion proposals.
- The service API owns primary artifacts named `atlas-<unix_ts>.json`; sidecars, separately
  generated terminal-observation snapshots and receipts sharing the `atlas-` prefix are not
  `AtlasArtifact` API records.
- Broad filesystem roots remain governed by the existing authentication, loopback and path
  security policy.

Observed maintenance cost is non-trivial: Atlas contains several high-complexity functions.
That cost is accepted for now because the subsystem has a real first-party surface and
persisted data. A future split requires a measured consumer/migration plan rather than a
static-reference count.

Migration path if Atlas is split later: preserve the `repoground atlas` command and
`/api/atlas` contract as compatibility adapters, move storage/scan implementation behind a
separate package or service, then remove adapters only after measured zero use.

## OmniWandler: remove from the active RepoGround repository surface

**Decision: REMOVE from the active tree.**

No current RepoGround CLI, service, systemd unit, import path or independent local consumer
was found. The implementation targets generic document/PDF/image folders, Pythonista UI and
OCR workflows rather than repository evidence. Its hub mode also defaults to deleting a
source folder after successful processing, which conflicts with RepoGround's evidence-first,
non-destructive kernel boundary.

No OmniWandler function is migrated into the kernel. Historical source remains recoverable
from Git history. A future generic-document product should live in its own repository and use
explicit non-destructive defaults.

## Standalone Repomerger: retire rather than inherit destructive behavior

**Decision: REMOVE from the active tree.**

The standalone Repomerger has no current import, CLI integration, service unit or measured
consumer. Its safe snapshot purpose is superseded by the canonical RepoGround dump/bundle
and fleet-publication paths. Its default behavior can delete source directories located next
to the script unless `--no-delete` is supplied; that behavior is intentionally not inherited
by RepoGround.

Historical documentation may still mention Repomerger as past architecture evidence. The
implementation remains recoverable from Git history, but it is no longer an active product
surface.

## Evidence and limits of this decision

The decision used current repository wiring, local cross-repository consumer search, running
processes, user-systemd inventory, live RepoGround service behavior, persisted Atlas artifacts
and the C901 maintenance baseline. It does **not** prove that an unavailable external machine
contains no old copy or that historical documentation has no archival value.

The product boundary is therefore operational rather than revisionist: active runtime and
package surfaces are made coherent, while historical proof artifacts are left intact.
