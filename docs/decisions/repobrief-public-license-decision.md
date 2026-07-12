# RepoBrief public license decision

Status: decided on 2026-07-12

## Decision

No public redistribution license is granted at this time. The current
`LicenseRef-RepoBrief-All-Rights-Reserved` text remains the
controlling repository notice, and public release remains blocked without
separate written permission.

GitHub's official licensing guidance distinguishes public visibility from an
open-source grant and notes that an explicit license is needed for others to
use, change and distribute software. SPDX permits a `LicenseRef-...` identifier
for terms that are not on the SPDX License List. These references support the
metadata shape; this document is not legal advice.

## Third-party review

The three committed Python lock profiles were installed with
`--require-hashes` in the pinned Python 3.12 Playwright container. Metadata for
57 distributions is recorded in
`docs/release/third-party-license-review.v1.json`.

The current source candidate does not vendor those packages. Even so, some
installed metadata is ambiguous or classifier-only. A later public source,
wheel, container or binary release must review the exact included artifact,
resolve ambiguous entries from upstream license texts, and generate applicable
notices.

## Reopening the decision

This decision may be reopened when the owner names a proposed public license and
an exact distribution form. Until both are explicit, internal deterministic
release candidates may be built, but publication remains fail-closed.
