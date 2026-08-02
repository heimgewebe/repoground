"""Public API for deterministic, provenance-bound decoded SCIP indexes.

The adapter does not run indexers, decode protobuf bytes, read repository files,
or promote external index data into repository truth.
"""
from merger.repoground.core._scip_adapter_benchmark import (
    benchmark_identity,
    evaluate_scip_adapter,
)
from merger.repoground.core._scip_adapter_common import ScipAdapterError
from merger.repoground.core._scip_adapter_normalize import normalize_scip_index

__all__ = [
    "ScipAdapterError",
    "benchmark_identity",
    "evaluate_scip_adapter",
    "normalize_scip_index",
]
