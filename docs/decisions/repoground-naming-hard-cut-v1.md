# RepoGround naming hard cut

Status: accepted
Date: 2026-07-19

## Decision

RepoGround is the only active product, command, module, environment, runtime-path,
generator and MCP identity. Aliases and fallback inputs are removed immediately.
Unknown active use blocks closeout.

Versioned schema IDs, `kind` values and stored historical artifact identifiers are
not rewritten in-place. They retain their exact data meaning until a separately
versioned producer, schema and reader migration exists. This is preservation of
data semantics, not a public compatibility surface.

Rollback is a commit revert. It does not restore former aliases.
