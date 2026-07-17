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
verified and reused.

Publishers for one bundle lane serialize installation and pointer selection with
`.publish.lock`. This lock coordinates Lenskit publishers; it is not presented as
a security boundary against a privileged process that ignores advisory locks.
The lane directory itself is opened once and remains descriptor-bound across the
lock, pointer snapshot, generation installation, pointer switch, post-switch
verification and rollback. While holding that binding, the publisher captures and
validates the exact previous pointer state, verifies the complete generation,
revalidates the captured symlink target or exact JSON bytes immediately before
the switch, atomically switches the single pointer entry, and verifies the
complete generation again. A changed pre-switch pointer fails closed without
overwrite. A failed post-switch verification restores the captured
symlink or exact JSON payload. On a first publication it removes the newly
created pointer instead. A failed rollback or a replaced lane path is reported
separately and never disguised as a successful publication.

The stable current selector is:

```text
<output-root>/.repobrief-generations/<bundle-stem>/current
```

On supported POSIX systems this is an atomically replaced relative symlink to the
selected generation directory. Temporary creation, target readback, rename,
cleanup and parent-directory `fsync` all run relative to one already-opened and
validated lane descriptor. Parent-path replacement before or after the rename is
detected. Cleanup removes only the publisher's unchanged temporary symlink.

A new lane falls back to an atomically replaced `current.json` only when the host
or filesystem explicitly reports that descriptor-bound symlink creation is not
supported. Permission failures and other unexpected errors fail closed instead
of silently changing pointer semantics. The JSON pointer contains
`generation_id`, manifest `sha256` and relative `manifest_path`;
`resolve_bundle_manifest_path(...)` is the central resolver for that fallback.

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
large artifact payloads are never retained as one in-memory bundle image. Tree
walking is iterative rather than Python-recursive, and every directory scanner
and file descriptor is closed deterministically. This avoids a recursion-limit
failure on deeply nested but otherwise valid trees. The manifest itself is still
parsed as JSON and therefore remains memory-resident. `post_emit_health` is
capped at 16 MiB and `current.json` at 1 MiB before JSON decoding.

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

The publication protocol detects removal, replacement and content mutation
before the pointer switch and rechecks the complete file tree immediately after
the switch. If that second check fails, the previous pointer is restored.

A filesystem does not provide one atomic transaction spanning both an installed
generation tree and a separate pointer entry. Nor does portable atomic rename
provide compare-and-swap against a privileged writer that ignores the lane lock;
the exact pre-switch revalidation narrows but cannot mathematically eliminate
that final instruction window. A reader that opens the pointer in the narrow
interval between the atomic switch and a failing post-switch check may therefore
observe the attempted generation before rollback. Readers must
follow the existing contract: capture the pointer once and verify the selected
manifest/content hashes. The protocol also cannot make `current` permanently
immune to a privileged, uncooperative process mutating or deleting generation
content after a successful publication. Protecting that storage remains an
operational boundary.
