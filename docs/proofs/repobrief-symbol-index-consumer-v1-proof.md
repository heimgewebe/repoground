# RepoBrief Symbol Index Consumer v1 proof

Task: `RPU-V1-T007`

Status: implementation proof for wiring the existing Python AST Symbol Index into RepoBrief consumer surfaces.

## Implemented surfaces

This slice exposes the existing Python AST symbol index as a bounded RepoBrief navigation surface:

```text
python_symbol_index_json
```

The symbol index is generated for single-repo bundles from Python source files via the standard-library AST parser. Target code is parsed as text; it is not imported or executed.

## Bundle and manifest registration

The bundle manifest now accepts and registers role `python_symbol_index_json` with:

- contract: `python-symbol-index` / `v1`;
- authority: `navigation_index`;
- canonicality: `derived`;
- risk class: `navigation`;
- `regenerable: true`;
- `staleness_sensitive: true`.

Profile availability includes the role. Public-share excludes it, so export-safe profiles do not retain the Python symbol surface.

## Agent Reading Pack

The Agent Reading Pack now includes a `SYMBOL_INDEX` section when the artifact is present. The section names the read-only CLI command and repeats the non-claims.

## Read-only consumer command

The new consumer command is:

```bash
python -m merger.lenskit.cli.main repobrief symbol search \
  --bundle-manifest <manifest> \
  --q <symbol-or-module-text>
```

Optional filters:

```bash
--kind class|function|async_function
--path <path-substring>
--k <max-results>
```

The consumer reads only an existing `python_symbol_index_json` artifact. It does not build the symbol index, refresh a snapshot, import target modules, execute target code, mutate Git, create files or alter bundle artifacts.

## Returned evidence shape

Each hit carries:

- symbol id;
- kind;
- name;
- qualified name;
- module;
- source path;
- start and end lines;
- source-line range reference;
- decorators if present.

This gives agents a lightweight path into source locations for later canonical/citation checks.

## Validation scope

Tests cover:

- manifest registration and schema validity;
- generated symbol document schema validity;
- Agent Reading Pack guidance;
- read-only symbol search;
- CLI symbol search;
- missing artifact diagnostics without creation;
- kind and path filters;
- public-share profile exclusion;
- static AST symbol extraction remains deterministic.

## Non-claims

The symbol index and its consumers do not establish:

- call graph completeness;
- dependency completeness;
- import success;
- runtime behavior;
- test sufficiency;
- review impact;
- merge readiness;
- source truth;
- repo understanding;
- answer correctness.
