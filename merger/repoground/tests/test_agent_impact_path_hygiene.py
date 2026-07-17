from __future__ import annotations

import pytest

from merger.repoground.core.agent_impact_refinement import (
    is_repository_relative_path,
    resolved_query_test_candidates,
)


def _query_context(path: str) -> dict:
    return {
        "query": {
            "source_citation_projection": {
                "items": [
                    {
                        "path": path,
                        "citation_id": "candidate",
                        "range_status": "resolved",
                    }
                ]
            }
        }
    }


@pytest.mark.parametrize(
    "path",
    [
        "./tests/test_job_finalizer.py",
        "tests/./test_job_finalizer.py",
        "tests/test_job_finalizer.py/.",
        "tests/../test_job_finalizer.py",
    ],
)
def test_repository_path_rejects_raw_dot_segments(path: str) -> None:
    assert is_repository_relative_path(path) is False
    assert resolved_query_test_candidates(_query_context(path)) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_job_finalizer.py",
        "src/tests/finalizer_test.py",
        "test_root.py",
    ],
)
def test_repository_path_keeps_canonical_test_paths(path: str) -> None:
    assert is_repository_relative_path(path) is True
    candidates = resolved_query_test_candidates(_query_context(path))
    assert [item["path"] for item in candidates] == [path]
