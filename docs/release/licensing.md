# RepoGround licensing boundary

## Current decision

The repository uses the custom identifier
`LicenseRef-RepoGround-All-Rights-Reserved`. The full controlling text is the
root `LICENSE` file.

The practical rule is fail-closed:

- source may be inspected in the public repository;
- no general right to copy, modify, redistribute or publish is granted;
- CI may build internal verification candidates;
- CI must not publish those archives as GitHub Releases or downloadable build
  artifacts;
- third-party components keep their own license terms.

This is an explicit current decision, not a claim that a public open-source
license was selected. Replacing it requires a separate owner decision and a
review of third-party obligations.

## Identifier semantics

The `LicenseRef-...` value is a project-local identifier for a license text
that is not represented by a standard SPDX short identifier. It is carried in
release manifests so tooling does not silently infer a permissive license from
repository visibility.

## Owner decision recorded on 2026-07-12

The public-license decision is closed as **do not grant public redistribution rights at this time**. The controlling `LICENSE` text is unchanged. Third-party metadata review is recorded in `third-party-license-review.v1.json`; it does not authorize redistribution.
