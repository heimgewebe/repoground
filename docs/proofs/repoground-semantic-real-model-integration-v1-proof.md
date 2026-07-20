# RepoGround Semantic Real-Model Integration v1 — Proof

Status: implemented and locally verified after rebasing onto RepoGround main commit `f7f9ef29a45e0f3b43e303e8e4bf5bc888dfb1d3`. Executable review-hardening evidence was produced from branch head `70b355af943aaf2efb164b80cd424c94707742f1` before this final evidence-only proof update.

## Problem

RepoGround's semantic-dimension tests previously used controlled mock models. Those tests prove the intended normalization and fallback contracts, but they do not establish the concrete output shapes returned by the locked `sentence-transformers` library or the compatibility of a saved and reloaded local model with RepoGround's validation and cosine-scoring path.

The optional semantic dependency installation proof deliberately downloaded no model. A real pre-trained model would add separate artifact identity, licensing, availability, network and semantic-quality questions that are not required to test the runtime shape contract.

## Implemented integration lane

`scripts/ci/run_semantic_real_model_integration.py` now builds a small real `SentenceTransformer` pipeline from the installed library using its `BoW` and `Normalize` modules. The fixture:

- has an explicit eight-token vocabulary and therefore eight output dimensions;
- contains no downloaded or pre-trained model weights;
- is built and saved twice independently and requires the same canonical tree SHA-256 for both outputs;
- hashes canonical relative paths and file bytes while deliberately excluding modes, ownership and timestamps, which are enforced separately where required;
- is bound to tree SHA-256 `913b82d98b28add74e605bde8a807826ce1b995b783ddac158e7f0fdf5bcfc75`;
- is reloaded from a local path with `local_files_only=True`;
- emits actual NumPy query, single-document and document-batch embeddings;
- passes those embeddings through RepoGround's model cache, dimension validation and cosine scorer.

`scripts/ci/run_semantic_real_model_integration.sh` executes the runner in the same digest-pinned CPython 3.12 image as the semantic lock compiler. The model phase uses:

- Docker `--network none` plus an in-container requirement that `/sys/class/net` exposes only `lo`;
- a read-only root filesystem;
- a fixed unprivileged numeric identity, UID/GID `65532:65532`, instead of the host user;
- a process-local `umask 077` before any model artifacts are created;
- a temporary runtime copy produced only from regular files in `git archive HEAD`, normalized to file mode `0444` and directory mode `0555` before its read-only mount;
- explicit tar-member classification that rejects symbolic links, hard links, devices, FIFOs and unknown member types before extraction;
- a read-only dependency mount whose complete host path is rejected when any component is a symlink;
- host orchestration isolated with Python 3.10 `-I -S`, while the pinned CPython 3.12 container uses `-P -S`; `PYTHONSAFEPATH=1` suppresses automatic unsafe start-path insertion, and explicit `PYTHONPATH=/semantic-target:/work` supplies only the two allowlisted roots whose presence is checked fail-closed by `_require_explicit_import_roots()`;
- all Linux capabilities dropped;
- `no-new-privileges`;
- Hugging Face and Transformers offline flags;
- an additional Python socket guard.

The existing `semantic-lock` workflow now installs the 58-package SHA-256-locked dependency closure into a unique hidden `mktemp` directory inside the isolated checkout. The path deliberately remains relative because the lock compiler exposes only that checkout as `/work`; absolute host paths such as `RUNNER_TEMP` are outside its container namespace. The EXIT trap is installed before the directory is created, so cancellation and early failure do not leave a fixed shared path. After installation, read/execute access is added without write access for the fixed container identity, the network-disabled integration wrapper runs, and the target is removed. The normal RepoGround Python suite remains independent of Torch and SentenceTransformers.

The model is intentionally serialized twice from two independently constructed library objects. Replacing the second build with `copytree()` would prove only copy integrity, not deterministic library serialization. The container `/tmp` is a private Docker `tmpfs`; ordinary cleanup failures remain fatal rather than being hidden with `ignore_cleanup_errors=True`, while abrupt container termination removes the container-scoped `tmpfs` even though no Python cleanup handler can run after `SIGKILL`.

The workflow path filter also now watches the real renamed platform contract, `docs/release/repoground-semantic-platforms.v1.json`, instead of the obsolete pre-cutover filename.

The container image is not independently hard-coded in the integration wrapper. It is read from the digest-pinned `compiler.image` field in that platform contract. Updating the tag or digest therefore requires one explicit contract change, regenerated semantic locks, a new deterministic model-tree hash check, and renewed local and GitHub integration evidence. The `sentence-transformers==5.6.0` and `torch==2.13.0+cpu` roots are likewise compatibility pins for reproducibility; they are not an instruction to select versions dynamically at runtime.

## Real execution evidence

Hash-locked dependency installation:

```text
task_id: bf3e5668ed5b4bf9aab72b05
terminalization_sha256: dc972c5d40f3a9967260f777e37736475ed6b2e563ab859d0618929a76add175
lifecycle_receipt_sha256: 9fa4def82ad77baa48d5de8390c46749c92bc80bfdbc41cc214edc33675369ce
result: success
```

Exact final `semantic-lock` install-and-model sequence after correcting the checkout namespace:

```text
task_id: ac3b4188a2e14c4db2f3092e
terminalization_sha256: d38e5808d6dd138c724bd10d90917970b46832bed0538e4438d9d616357de7ad
lifecycle_receipt_sha256: f8edc02200edae47ebdde30f5ae04cef2e78ddcfab0bd730bebbe65eea6d0ea9
lock_sha256: 8846ffb3e549726c90af6945664b2c83778629690d052d13ab474c585269205f
result: success
checkout_target_cleanup: pass, no .semantic-real-model-target.* path remained
```

Hardened fixed-identity, network-disabled integration wrapper with commit-staged runtime and cleanup verification:

```text
task_id: 4397c82fb28a4ca79b3c40b7
terminalization_sha256: 3e8ca6b0b0d7dc7e2c767a7327b4959dc3176560c2e34c26cdbf20c629d2556a
lifecycle_receipt_sha256: 34faf9759b65c53a3c29f54f33b3eb59a67d2c9f749febf4a929e9f745f9ab94
persisted_output_sha256: bc7b1aa47e8500634b32df8729a2cbcb16c681e7af84f583fef310fd6755f475
result: success
runtime_copy_cleanup: pass, no repoground-semantic-runtime.* path remained
```

Committed review-hardening install-and-model rerun on head `70b355af943aaf2efb164b80cd424c94707742f1`:

```text
task_id: 3d05a7816b7640809c7353f4
terminalization_sha256: cf9cb332833b701f1bec8b07dfc16d11f08c0600267deaf0fba3ea2f6ca843be
lifecycle_receipt_sha256: 1258363910a8ce76dc73d4b289ae31f8a5349815b09c7b68c9edac5b3932872e
lock_sha256: 8846ffb3e549726c90af6945664b2c83778629690d052d13ab474c585269205f
result: success
install_status: 0
wrapper_status: 0
outer_cleanup_status: 0
checkout_target_cleanup: pass, no review-hardening target remained
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

Dependency-free contract tests after review hardening:

```text
python3 -m pytest \
  merger/repoground/tests/test_semantic_real_model.py \
  merger/repoground/tests/test_semantic_extension_lock.py -q

16 passed in 0.17s

task_id: f966b1e013d14b5c85f59499
terminalization_sha256: 20700a28d694297b38aa8109b2baa750d0493af991344abd1b99dc11474a3d33
lifecycle_receipt_sha256: 0289ec55c4019359451ef9743e5e31301a31807d217771fb60d266a89f1a1121
```

Complete RepoGround Python suite on committed review-hardening code:

```text
python3 -m pytest merger/repoground/tests -q -p no:cacheprovider

4399 passed, 2 skipped in 172.96s (0:02:52)

execution_task_id: db3bd0d1b2b243fe920d8116
execution_terminalization_sha256: 4a69ad2dfa6a5c1eed30b1df4de816bada14e31d427ac34a3524c69cd1f5d357
execution_lifecycle_receipt_sha256: b5dc4cca65b77f68355ef694dc80dc9402fdff5d142b4b39723654846936242b
exact_output_sha256: 17418259e88483a58cc5439e3893ac313ded9a479782c612b8c4fcbe40bcca36
readback_task_id: cd35487065c748a59aa7a7d0
readback_terminalization_sha256: f5fbc0977fd79b9d02b60a79dc6be97c114053bf25b5ef9f6bda3c08fa9304aa
readback_lifecycle_receipt_sha256: 2aba539c56df8dcad83be92ab0eeba779ea6f24786fca14aed3625dfd4c71b86
```

Static and contract checks:

```text
changed-file Ruff: pass
Python syntax compilation: pass
workflow YAML parse: pass
wrapper bash syntax: pass
local ShellCheck --severity=style: pass
ShellCheck task_id: 24678ba5474e4bb69e5190f6
ShellCheck terminalization_sha256: cd562fdf6aafad4b218d6b0eb8c1423c186069dc59b6fa9803cf34fdf5d322d3
ShellCheck lifecycle_receipt_sha256: ef43915955239af43632d3cc1bdd6a4602f6c71cd2edd7d52442586b0bccffcc
release contract: pass, findings=[]
maintainability ratchet: pass, new_count=0, resolved_count=3, findings=[]
git diff --check: pass
```

A repository-wide unconfigured `ruff check .` still reports 128 existing baseline findings in unrelated legacy and fixture files. No finding points to this slice; the changed-file Ruff check and the repository maintainability ratchet are the applicable fail-closed gates.

## Failure semantics

The integration fails closed when:

- the observed container network exposes any interface other than loopback;
- the dependency target is not normalized and absolute, contains a symlink in any path component, or is not a directory;
- the committed runtime archive contains a symlink, hard link or any other non-regular entry;
- the generated model tree contains a symlink or another non-regular entry;
- the explicit dependency and repository import roots are absent;
- installed SentenceTransformers or Torch versions differ from the locked roots;
- CUDA unexpectedly becomes the selected execution surface;
- either generated model tree differs from the other or from the committed hash;
- local model loading attempts a Python network operation;
- direct library output types or shapes change;
- RepoGround observes a dimension or score-count mismatch;
- scores are non-finite or no longer preserve the controlled fixture ordering.

## Boundaries

This proof establishes compatibility with a real, saved and reloaded SentenceTransformer pipeline built from the exact locked library versions. It does not establish compatibility with arbitrary pre-trained models, model availability, external model licensing, semantic quality, ranking quality on natural queries, GPU support, cross-platform installability, vulnerability absence or readiness to enable semantic reranking by default.
