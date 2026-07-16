# RepoBrief Bundle Generations

RepoBrief bundle emission keeps the historical flat files readable, but a
completed bundle is also published as an immutable generation below the bundle
output root:

```text
<output-root>/.repobrief-generations/<bundle-stem>/<generation-id>/
```

The generation contains byte copies of the final bundle manifest, all manifest
`artifacts`, manifest-bound sidecar links (`post_emit_health_path`,
`bundle_surface_validation_path`, `export_safety_report_path`) and any final
output files that the merge path can prove it produced. Copies are regular files
only. Symlinks, absolute paths, traversal and files outside the output root are
rejected fail-closed. Flat legacy files are never hardlinked into a generation,
so later flat-file rewrites cannot mutate an already-published generation.

The `generation-id` is a SHA-256 over the final manifest hash plus the complete
published file set (`relative path`, byte count, SHA-256). Reusing an existing
generation is accepted only after verifying the existing tree exactly matches
the expected regular-file tree.

Publication writes a temporary sibling directory first. Files are copied and
fsynced there, with the final bundle manifest copied last. The temporary
directory is then renamed to the deterministic generation name using a
create-only, fail-closed rule. If a matching generation already exists, it is
verified and reused. If an error occurs before the current pointer switch, the
previous pointer remains authoritative.

The stable current selector is:

```text
<output-root>/.repobrief-generations/<bundle-stem>/current
```

On POSIX systems this is an atomically replaced relative symlink to the selected
generation directory. If symlinks are unavailable, RepoBrief writes an atomically
replaced `current.json` pointer containing `generation_id`, manifest `sha256`
and relative `manifest_path`; `resolve_bundle_manifest_path(...)` is the central
resolver for that fallback.

Compatibility rule: direct historical manifest paths remain readable and
mutable for legacy/finalization code. New completed merge results should expose
the current manifest path (or the resolved immutable manifest path on JSON
pointer fallback) as their canonical `bundle_manifest`, while retaining the flat
manifest as a legacy path for code that must finish profile-specific mutation
before publishing.

## Final health binding

`post_emit_health` remains outside the manifest artifact list to avoid a hash
cycle. After the final manifest write, Lenskit stores its SHA-256 in
`bundle_manifest_sha256` inside the health sidecar. A consumer can therefore
verify a byte-identical immutable generation even when the legacy absolute
`bundle_manifest_path` still names the flat publication path. A present but
invalid or mismatching hash fails closed.
## Portable create-only installation

Generation directories are installed with a native atomic create-only rename:
Linux uses `renameat2(..., RENAME_NOREPLACE)`; macOS and iOS use
`renameatx_np(..., RENAME_EXCL)`. Both variants operate on already validated
parent directory descriptors. An unknown platform or missing primitive fails
closed rather than falling back to a pathname `exists()` check.

## Operational boundaries and deliberate trade-offs

Generation discovery and verification hash artifact streams in bounded chunks;
large artifact payloads are never retained as one in-memory bundle image. The
manifest itself is still parsed as JSON and therefore remains memory-resident.

Hardlinks are deliberately not used. A source artifact remains mutable until
publication completes, and a hardlink would let a later source write mutate an
already published generation through the shared inode. Native reflinks could be
a future optimization only with copy verification and a portable fallback.

Duplicate declarations of one relative path are idempotent only when byte count
and SHA-256 are identical. Conflicting content for the same path fails closed.

A lane that has successfully used a `current` symlink remains in symlink mode.
If the storage environment later loses symlink support, publication stops rather
than silently changing pointer semantics. Recovery is an explicit administrative
operation: repair symlink support or remove the lane pointer while no publisher
is running, then allow a fresh pointer to be established.

Cache metadata identity is considered strong only when device, inode, mtime_ns
and ctime_ns are all non-zero. Weak or unavailable identity forces full content
verification; `strict` mode forces it regardless of metadata quality.

The publication protocol detects removal or replacement before and during the
pointer switch. It cannot make a `current` pointer permanently immune to a
privileged, uncooperative process deleting immutable generation directories
after publication; protecting that storage remains an operational boundary.
