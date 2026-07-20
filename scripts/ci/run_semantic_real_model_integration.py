from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import socket
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SENTENCE_TRANSFORMERS_VERSION = "5.6.0"
EXPECTED_TORCH_VERSION = "2.13.0+cpu"
FIXTURE_VOCAB = (
    "commons",
    "community",
    "shared",
    "water",
    "forest",
    "software",
    "garden",
    "knowledge",
)
FIXTURE_DIMENSIONS = len(FIXTURE_VOCAB)
EXPECTED_MODEL_TREE_SHA256 = (
    "913b82d98b28add74e605bde8a807826ce1b995b783ddac158e7f0fdf5bcfc75"
)
QUERY_TEXT = "community shared water"
CANDIDATE_TEXTS = (
    "community shared water garden",
    "proprietary enclosure",
)


def _framed_sha256(parts: Iterator[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def canonical_tree_sha256(root: Path) -> str:
    """Hash relative paths and bytes, deliberately excluding host metadata.

    File modes, ownership and timestamps are enforced separately where required.
    """
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("model tree must be a real directory")

    def parts() -> Iterator[bytes]:
        files: list[Path] = []
        for path in sorted(root.rglob("*")):
            relative_path = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise RuntimeError(f"model tree contains symlink: {relative_path}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise RuntimeError(
                    f"model tree contains non-regular entry: {relative_path}"
                )
            files.append(path)
        if not files:
            raise RuntimeError("model tree contains no files")
        for path in files:
            yield path.relative_to(root).as_posix().encode("utf-8")
            yield path.read_bytes()

    return _framed_sha256(parts())


def _require_dependency_target(path: Path) -> Path:
    if not path.is_absolute():
        raise RuntimeError("dependency target must be an absolute path")
    normalized = Path(os.path.normpath(os.fspath(path)))
    if normalized != path:
        raise RuntimeError("dependency target must be a normalized absolute path")

    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RuntimeError(
                "dependency target must contain no symlink components: "
                f"{current}"
            )
    if not path.is_dir():
        raise RuntimeError("dependency target must be a real directory")
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise RuntimeError("dependency target must resolve to itself")
    return resolved


def _dependency_target_argument(path: Path) -> Path:
    candidate = path if path.is_absolute() else Path.cwd() / path
    return _require_dependency_target(candidate)


def _require_version(distribution: str, expected: str) -> str:
    observed = importlib.metadata.version(distribution)
    if observed != expected:
        raise RuntimeError(
            f"{distribution} version mismatch: expected={expected} observed={observed}"
        )
    return observed


def _require_loopback_only_network(
    interface_root: Path = Path("/sys/class/net"),
) -> list[str]:
    if interface_root.is_symlink() or not interface_root.is_dir():
        raise RuntimeError("network interface root must be a real directory")
    interfaces = sorted(path.name for path in interface_root.iterdir())
    if interfaces != ["lo"]:
        raise RuntimeError(
            "real-model integration requires loopback-only networking: "
            f"observed={interfaces!r}"
        )
    return interfaces


@contextmanager
def deny_python_network() -> Iterator[None]:
    """Fail immediately if imported model code attempts a Python socket call."""

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("network access is forbidden during real-model integration")

    with (
        patch.object(socket.socket, "connect", blocked),
        patch.object(socket, "create_connection", blocked),
        patch.object(socket, "getaddrinfo", blocked),
    ):
        yield


def _build_model(output_path: Path) -> None:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.sentence_transformer.modules import BoW, Normalize

    model = SentenceTransformer(
        modules=[
            BoW(vocab=list(FIXTURE_VOCAB), unknown_word_weight=1.0),
            Normalize(),
        ],
        device="cpu",
    )
    model.save(str(output_path), create_model_card=False)


def _shape(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is None:
        raise RuntimeError("embedding output has no shape")
    return [int(part) for part in shape]


def _load_locked_runtime() -> dict[str, Any]:
    import numpy as np
    import sentence_transformers
    import torch
    from sentence_transformers import SentenceTransformer

    from merger.repoground.retrieval import query_core

    sentence_transformers_version = _require_version(
        "sentence-transformers", EXPECTED_SENTENCE_TRANSFORMERS_VERSION
    )
    torch_version = _require_version("torch", EXPECTED_TORCH_VERSION)
    if sentence_transformers.__version__ != sentence_transformers_version:
        raise RuntimeError("sentence-transformers package metadata/module mismatch")
    if torch.__version__ != torch_version:
        raise RuntimeError("torch package metadata/module mismatch")
    if torch.cuda.is_available():
        raise RuntimeError("real-model integration must remain CPU-only")
    return {
        "np": np,
        "SentenceTransformer": SentenceTransformer,
        "query_core": query_core,
        "sentence_transformers_version": sentence_transformers_version,
        "torch_version": torch_version,
        "numpy_version": np.__version__,
    }


def _generate_reproducible_model(temporary_root: Path) -> dict[str, Any]:
    first_model_path = temporary_root / "model-a"
    second_model_path = temporary_root / "model-b"
    _build_model(first_model_path)
    _build_model(second_model_path)

    first_tree_sha256 = canonical_tree_sha256(first_model_path)
    second_tree_sha256 = canonical_tree_sha256(second_model_path)
    if first_tree_sha256 != second_tree_sha256:
        raise RuntimeError("generated local model tree is not reproducible")
    if first_tree_sha256 != EXPECTED_MODEL_TREE_SHA256:
        raise RuntimeError(
            "generated local model tree identity changed: "
            f"expected={EXPECTED_MODEL_TREE_SHA256} observed={first_tree_sha256}"
        )
    files = [
        path.relative_to(first_model_path).as_posix()
        for path in sorted(first_model_path.rglob("*"))
        if path.is_file()
    ]
    return {
        "path": first_model_path,
        "tree_sha256": first_tree_sha256,
        "repeat_tree_sha256": second_tree_sha256,
        "files": files,
    }


def _require_direct_outputs(
    model_path: Path,
    *,
    sentence_transformer_class: Any,
    numpy_module: Any,
) -> dict[str, Any]:
    model = sentence_transformer_class(
        str(model_path),
        device="cpu",
        local_files_only=True,
    )
    values = {
        "query": model.encode(QUERY_TEXT, show_progress_bar=False),
        "single_document": model.encode(
            [CANDIDATE_TEXTS[0]], show_progress_bar=False
        ),
        "document_batch": model.encode(
            list(CANDIDATE_TEXTS), show_progress_bar=False
        ),
    }
    expected_shapes = {
        "query": [FIXTURE_DIMENSIONS],
        "single_document": [1, FIXTURE_DIMENSIONS],
        "document_batch": [2, FIXTURE_DIMENSIONS],
    }
    for name, value in values.items():
        if _shape(value) != expected_shapes[name]:
            raise RuntimeError(f"real {name} embedding shape changed")
        if not isinstance(value, numpy_module.ndarray):
            raise RuntimeError(f"real {name} output is no longer a NumPy array")
    return {
        f"{name}_{field}": observed
        for name, value in values.items()
        for field, observed in (
            ("type", type(value).__module__ + "." + type(value).__name__),
            ("shape", _shape(value)),
        )
    }


def _require_repoground_validation(
    model_path: Path,
    *,
    query_core: Any,
) -> tuple[dict[str, Any], list[float]]:
    query_core._MODEL_CACHE.clear()
    local_model = query_core._get_semantic_model(str(model_path))
    diagnostics: dict[str, Any] = {
        "enabled": True,
        "dimension_validation": "pending",
    }
    query_embedding, document_embeddings = query_core._validated_semantic_embeddings(
        semantic_model=local_model,
        query_text=QUERY_TEXT,
        candidate_texts=list(CANDIDATE_TEXTS),
        expected_dimensions=FIXTURE_DIMENSIONS,
        semantic_diagnostics=diagnostics,
    )
    if document_embeddings is None:
        raise RuntimeError("real document embeddings were not produced")
    scores = [
        float(value)
        for value in query_core._semantic_cosine_scores(
            query_embedding, document_embeddings
        )
    ]
    if len(scores) != len(CANDIDATE_TEXTS):
        raise RuntimeError("real-model score count mismatch")
    if not all(math.isfinite(value) for value in scores):
        raise RuntimeError("real-model scores must be finite")
    if not scores[0] > 0.8 or not math.isclose(scores[1], 0.0, abs_tol=1e-8):
        raise RuntimeError(
            f"real-model score ordering changed unexpectedly: {scores!r}"
        )
    expected_diagnostics = {
        "enabled": True,
        "dimension_validation": "pass",
        "actual_query_dimensions": FIXTURE_DIMENSIONS,
        "actual_document_dimensions": FIXTURE_DIMENSIONS,
    }
    if diagnostics != expected_diagnostics:
        raise RuntimeError(
            "real-model dimension diagnostics changed unexpectedly: "
            f"{diagnostics!r}"
        )
    return diagnostics, scores


def _integration_report(
    *,
    runtime: dict[str, Any],
    model: dict[str, Any],
    outputs: dict[str, Any],
    diagnostics: dict[str, Any],
    scores: list[float],
    network_interfaces: list[str],
) -> dict[str, Any]:
    return {
        "kind": "repoground.semantic_real_model_integration",
        "version": "v1",
        "status": "pass",
        "target": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "operating_system": sys.platform,
            "architecture": platform.machine().lower(),
            "accelerator": "cpu_only",
        },
        "runtime": {
            "sentence_transformers": runtime["sentence_transformers_version"],
            "torch": runtime["torch_version"],
            "numpy": runtime["numpy_version"],
            "torch_cuda_available": False,
        },
        "model": {
            "source": "generated_local_fixture",
            "modules": ["BoW", "Normalize"],
            "dimensions": FIXTURE_DIMENSIONS,
            "vocab_sha256": hashlib.sha256(
                json.dumps(FIXTURE_VOCAB, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "tree_sha256": model["tree_sha256"],
            "repeat_tree_sha256": model["repeat_tree_sha256"],
            "files": model["files"],
            "downloaded": False,
            "loaded_with_local_files_only": True,
        },
        "network": {
            "interfaces": network_interfaces,
            "loopback_only_observed": True,
            "python_socket_guard": True,
            "huggingface_offline": True,
            "transformers_offline": True,
        },
        "outputs": outputs,
        "repoground_validation": diagnostics,
        "cosine_scores": scores,
        "does_not_establish": [
            "pretrained_model_compatibility",
            "semantic_quality",
            "semantic_ranking_quality",
            "production_model_availability",
            "model_license_approval",
            "gpu_support",
            "cross_platform_installability",
            "default_promotion_readiness",
        ],
    }


def _require_explicit_import_roots(dependency_target: Path) -> None:
    required = {str(dependency_target), str(ROOT)}
    missing = sorted(required.difference(sys.path))
    if missing:
        raise RuntimeError(
            "required import roots are absent; invoke through the hardened wrapper: "
            f"{missing!r}"
        )


def run_integration(dependency_target: Path) -> dict[str, Any]:
    dependency_target = _require_dependency_target(dependency_target)
    _require_explicit_import_roots(dependency_target)
    # Keep all subsequently created model artifacts private by default.
    os.umask(0o077)
    os.environ.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "SENTENCE_TRANSFORMERS_HOME": "/tmp/repoground-semantic-model-cache",
        }
    )

    network_interfaces = _require_loopback_only_network()
    with deny_python_network():
        runtime = _load_locked_runtime()
        with tempfile.TemporaryDirectory(
            prefix="repoground-semantic-real-model-"
        ) as temporary_directory:
            model = _generate_reproducible_model(Path(temporary_directory))
            outputs = _require_direct_outputs(
                model["path"],
                sentence_transformer_class=runtime["SentenceTransformer"],
                numpy_module=runtime["np"],
            )
            diagnostics, scores = _require_repoground_validation(
                model["path"], query_core=runtime["query_core"]
            )
    return _integration_report(
        runtime=runtime,
        model=model,
        outputs=outputs,
        diagnostics=diagnostics,
        scores=scores,
        network_interfaces=network_interfaces,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run RepoGround semantic shape/scoring integration with a generated "
            "local SentenceTransformer model"
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dependency-target", type=Path)
    mode.add_argument("--validate-dependency-target", type=Path)
    args = parser.parse_args()

    if args.validate_dependency_target is not None:
        try:
            target = _dependency_target_argument(args.validate_dependency_target)
        except Exception as exc:
            parser.error(str(exc))
        print(target)
        return 0

    try:
        assert args.dependency_target is not None
        result = run_integration(args.dependency_target)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "kind": "repoground.semantic_real_model_integration",
                    "version": "v1",
                    "status": "fail",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
