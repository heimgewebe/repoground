# RepoBrief Semantic Extension Lock v1 – Proof

## Scope

This proof closes the optional semantic dependency-lock gap for one explicitly
supported target. It does not enable semantic reranking by default and does not
add the semantic stack to RepoBrief's core runtime lock.

## Supported target

- CPython 3.12
- Linux x86-64
- CPU-only Torch
- selected binary wheels only
- unsupported targets fail closed

The machine-readable boundary is
`docs/release/semantic-extension-platforms.v1.json`.

## Locked closure

The reviewed root pins are:

- `sentence-transformers==5.6.0`
- `torch==2.13.0+cpu`

The complete closure contains 58 packages. Each package is bound to one selected
wheel and one SHA-256 for the declared target. Torch is bound to its direct
CPython-3.12/Linux-x86-64 CPU wheel URL and SHA-256, avoiding dependency
selection through a broad extra index.

- input SHA-256: `6d741eed8d3ccf3d9fbdc2fef0c95df119d6fd561db42bf18603083909a1daf9`
- constraints SHA-256: `2eea6931d07bad9331499ce2aeff89e8740b1650be3650262acde9fe041a4624`
- lock SHA-256: `3e8a5accb5c50d525a68740b7f0c4009c97ebce54e1832c99e6a1ed92287fd2e`

The compiler runs in the digest-pinned image
`mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69`.
A second resolution using the committed constraints reproduced both generated
files byte-for-byte.

## Installation evidence

The lock was installed into a new empty target directory with
`--require-hashes`, `--only-binary=:all:` and no cache. The import probe ran with
global site packages disabled.

Observed result:

- all 58 packages installed;
- `sentence-transformers` imported as version `5.6.0`;
- Torch imported as version `2.13.0+cpu`;
- CUDA availability was `false`;
- no model was downloaded.

Structured evidence:
`docs/proofs/repobrief-semantic-extension-install-20260714.v1.json`.

## Preserved boundary

The semantic extension remains:

- optional;
- disabled by default;
- absent from the core runtime lock;
- unnecessary for snapshot reads and ordinary retrieval;
- outside any claim of review, answer or runtime correctness.

This evidence does not establish semantic quality, model quality or
availability, model-license approval, vulnerability absence, GPU support,
cross-platform installability or readiness for default promotion.
