# RepoGround Retrieval System

## Optional Semantic Reranking

The local semantic re-ranking feature (F1b) remains opt-in. RepoGround's default
retrieval, snapshot reads and release core do not import or require the semantic
stack.

### Supported reproducible installation

The only supported locked target is **CPython 3.12 on Linux x86-64, CPU-only**.
Run from the repository root:

```bash
python3 -m pip install \
  --only-binary=:all: \
  --require-hashes \
  -r requirements/repoground-semantic-linux-x86_64-py312.lock.txt
```

Other Python versions, operating systems, architectures and GPU builds are not
covered by this lock and must fail closed rather than silently selecting a
different Torch or transitive wheel. The legacy
`merger/repoground/requirements-semantic.txt` records the root intent only; it is
not the reproducible installation surface.

The lock can be regenerated and checked in the pinned compiler container with:

```bash
scripts/release/compile_semantic_lock.sh --check
```

### Current F1b Limitations

- `provider` is currently limited to `local` only.
- `similarity_metric` is fixed to `cosine`.
- Without the optional packages, semantic reranking is unavailable and behavior follows the configured fallback policy.
- Installing the packages does not download or approve a model and does not prove semantic quality.
- `dimensions` configurations are not yet actively validated.
