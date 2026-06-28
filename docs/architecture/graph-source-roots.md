# Architecture Graph Source Roots v1

## Status

This is the contract boundary required before the Python import graph may resolve configured roots such as `src/` layouts or namespace-package roots.

The schema is `merger/lenskit/contracts/architecture.source_roots.v1.schema.json`. A minimal example is `merger/lenskit/contracts/examples/source_roots_minimal.json`.

This slice defines and tests the declaration only. The graph producer, bundle producer, CLI, ranking, and graph-quality baseline do not consume it yet.

## Shape

```json
{
  "kind": "lenskit.architecture.source_roots",
  "version": "1.0",
  "roots": ["src"]
}
```

`roots` contains additional Python import roots relative to a repository. The repository root remains the existing implicit root and is not declared as `.`.

## Rules

Each root must be non-empty, relative, unique, and written in canonical POSIX form. Absolute paths, backslashes, leading `./`, repeated separators, and dot or parent segments are rejected.

List order has no precedence meaning. A future consumer must preserve ambiguity when different declared roots expose different files under the same module name.

The schema validates JSON shape and lexical path rules. A consumer must additionally check that declared directories exist in the selected repository snapshot and belong to the same source surface used for graph construction. Invalid declarations must fail closed or leave imports unresolved; they must not trigger directory-name guessing.

Schema validity alone therefore proves neither directory existence nor safe producer consumption. Those are contextual checks owned by the later consumer slice.

## Provenance boundary

The declaration says only that a caller explicitly supplied additional roots. It does not establish effective runtime `sys.path`, installed-package state, editable-install behavior, build-backend interpretation, runtime import order, or runtime causality.

## Planned consumer tests

A later producer slice must prove that explicit roots resolve the two G4b source-root cases, competing roots remain ambiguous, and absence of a declaration preserves current graph behavior.
