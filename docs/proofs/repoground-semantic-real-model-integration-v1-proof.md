# RepoGround Semantic Real-Model Integration v1 — Proof

Status: implemented and locally verified from RepoGround main commit `701c28983e873892155d4b5148274392aea7a951` on branch `test/semantic-real-model-integration-v1`.

## Problem

RepoGround's semantic-dimension tests previously used controlled mock models. Those tests prove the intended normalization and fallback contracts, but they do not establish the concrete output shapes returned by the locked `sentence-transformers` library or the compatibility of a saved and reloaded local model with RepoGround's validation and cosine-scoring path.

The optional semantic dependency installation proof deliberately downloaded no model. A real pre-trained model would add separate artifact identity, licensing, availability, network and semantic-quality questions that are not required to test the runtime shape contract.

## Implemented integration lane

`scripts/ci/run_semantic_real_model_integration.py` now builds a small real `SentenceTransformer` pipeline from the installed library using its `BoW` and `Normalize` modules. The fixture:

- has an explicit eight-token vocabulary and therefore eight output dimensions;
- contains no downloaded or pre-trained model weights;
- is saved twice and requires the same canonical tree SHA-256 for both outputs;
- is bound to tree SHA-256 `913b82d98b28add74e605bde8a807826ce1b995b783ddac158e7f0fdf5bcfc75`;
- is reloaded from a local path with `local_files_only=True`;
- emits actual NumPy query, single-document and document-batch embeddings;
- passes those embeddings through RepoGround's model cache, dimension validation and cosine scorer.

`scripts/ci/run_semantic_real_model_integration.sh` executes the runner in the same digest-pinned CPython 3.12 image as the semantic lock compiler. The model phase uses:

- Docker `--network none` plus an in-container requirement that `/sys/class/net` exposes only `lo`;
- a read-only root filesystem;
- read-only repository and dependency mounts;
- all Linux capabilities dropped;
- `no-new-privileges`;
- Hugging Face and Transformers offline flags;
- an additional Python socket guard.

The existing `semantic-lock` workflow now installs the 58-package SHA-256-locked dependency closure into a temporary repository-local target, invokes the network-disabled integration wrapper, and removes the target through an EXIT trap. The normal RepoGround Python suite remains independent of Torch and SentenceTransformers.

The workflow path filter also now watches the real renamed platform contract, `docs/release/repoground-semantic-platforms.v1.json`, instead of the obsolete pre-cutover filename.

## Real execution evidence

Hash-locked dependency installation:

```text
task_id: 212c3188527b4def80bfd05e
terminalization_sha256: c71679798a88d4d36ea464c1aea7994d6215b2aa43f2e16b8f1af084eeea82a9
lifecycle_receipt_sha256: 5015eea9a0d43d2efb0a66d67715bf3ae6af7d4039cd5903e935fba29982f3d6
result: success
```

Hardened network-disabled integration wrapper after maintainability refactoring:

```text
task_id: 62f0abd4435e4f1b83c793bc
terminalization_sha256: 381a5d4848fbd78382873e7ae52dd667ebfa1a809f2ef4990d279542e0648a72
lifecycle_receipt_sha256: c47f129337d85ac04daec3d7fc7868cbd72047f3e409d90fe4d52ea230e70a71
result: success
```

Observed runtime and outputs:

```text
CPython: 3.12.3
sentence-transformers: 5.6.0
torch: 2.13.0+cpu
numpy: 2.5.1
CUDA available: false
observed network interfaces: [lo]
query output: numpy.ndarray, shape [8]
single-document output: numpy.ndarray, shape [1, 8]
document-batch output: numpy.ndarray, shape [2, 8]
model tree SHA-256 A: 913b82d98b28add74e605bde8a807826ce1b995b783ddac158e7f0fdf5bcfc75
model tree SHA-256 B: 913b82d98b28add74e605bde8a807826ce1b995b783ddac158e7f0fdf5bcfc75
RepoGround dimension validation: pass
actual query dimensions: 8
actual document dimensions: 8
cosine scores: [0.866025447845459, 0.0]
```

Dependency-free contract tests:

```text
python3 -m pytest \
  merger/repoground/tests/test_semantic_real_model.py \
  merger/repoground/tests/test_semantic_extension_lock.py -q

13 passed in 0.13s
```

Complete RepoGround Python suite:

```text
python3 -m pytest merger/repoground/tests -q

4371 passed, 2 skipped in 116.02s
```

Durable complete-suite task on the final code, workflow and wrapper:

```text
task_id: c501896e76264c08bcd45e78
terminalization_sha256: 8443f69c79127407469e175bc08d5be101caa4e8d93acd36f5aac94cfb756327
lifecycle_receipt_sha256: 9a891f1b7097811189816bc51165b393728c753666c943cfde1fed7ffedf64dc
persisted_output_sha256: 260720c8fbc7811eb3114e2a2345c02b4cb35a2d648f6a096eb1047200b896c5
```

Static and contract checks:

```text
changed-file Ruff: pass
Python syntax compilation: pass
workflow YAML parse: pass
wrapper bash syntax: pass
release contract: pass, findings=[]
maintainability ratchet: pass, new_count=0, resolved_count=2, findings=[]
git diff --check: pass
```

A repository-wide unconfigured `ruff check .` still reports 128 existing baseline findings in unrelated legacy and fixture files. No finding points to this slice; the changed-file Ruff check and the repository maintainability ratchet are the applicable fail-closed gates.

## Failure semantics

The integration fails closed when:

- the observed container network exposes any interface other than loopback;
- the dependency target is relative, symlinked or not a directory;
- installed SentenceTransformers or Torch versions differ from the locked roots;
- CUDA unexpectedly becomes the selected execution surface;
- either generated model tree differs from the other or from the committed hash;
- local model loading attempts a Python network operation;
- direct library output types or shapes change;
- RepoGround observes a dimension or score-count mismatch;
- scores are non-finite or no longer preserve the controlled fixture ordering.

## Boundaries

This proof establishes compatibility with a real, saved and reloaded SentenceTransformer pipeline built from the exact locked library versions. It does not establish compatibility with arbitrary pre-trained models, model availability, external model licensing, semantic quality, ranking quality on natural queries, GPU support, cross-platform installability, vulnerability absence or readiness to enable semantic reranking by default.
