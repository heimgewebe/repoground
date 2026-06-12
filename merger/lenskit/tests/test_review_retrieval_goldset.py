import json
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_QUERIES_PATH = REPO_ROOT / "docs/retrieval/queries.v1.json"
REVIEW_QUERIES_PATH = REPO_ROOT / "docs/retrieval/review_queries.v1.json"
THIS_TEST_PATH = Path(__file__).resolve()
REQUIRED_FIELDS = {"query", "expected_patterns", "filters", "accept_criteria"}
ALLOWED_REVIEW_FIELDS = REQUIRED_FIELDS | {"category"}
REQUIRED_CATEGORIES = {
    "agent_pack",
    "claim_evidence",
    "citation_map",
    "post_emit_health",
    "bundle_surface",
    "bundle_manifest",
    "retrieval",
    "router",
    "cli",
    "contracts",
    "security",
    "source_acquisition",
    "pr_schau",
    "range_ref",
    "lenses",
}
REPO_PATH_PREFIXES = (".github/", "docs/", "merger/", "scripts/", "tools/")
REPO_PATH_SUFFIXES = (
    ".py",
    ".json",
    ".md",
    ".sh",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
)
ROOT_PATH_PATTERNS = {"Makefile", "README.md", "pyproject.toml", "package.json"}
TEXT_SEARCH_ROOTS = ("docs", "merger", "scripts", "tools")
SKIP_SEARCH_PARTS = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "_generated",
}
SKIP_SEARCH_SUFFIXES = {".db", ".sqlite", ".bundle", ".log", ".pyc"}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def base_queries() -> list[dict[str, Any]]:
    data = _load_json(BASE_QUERIES_PATH)
    assert isinstance(data, list), f"{BASE_QUERIES_PATH} must contain a top-level list"
    return data


@pytest.fixture(scope="module")
def review_queries() -> list[dict[str, Any]]:
    data = _load_json(REVIEW_QUERIES_PATH)
    assert isinstance(data, list), f"{REVIEW_QUERIES_PATH} must contain a top-level list"
    return data


def _is_repo_path_pattern(pattern: str) -> bool:
    return (
        pattern.startswith(REPO_PATH_PREFIXES)
        or "/" in pattern
        or pattern.endswith(REPO_PATH_SUFFIXES)
        or pattern in ROOT_PATH_PATTERNS
    )


def _missing_or_wrong_kind_path(pattern: str) -> str | None:
    path = REPO_ROOT / pattern
    if pattern.endswith("/"):
        if not path.is_dir():
            return f"{pattern} (expected directory)"
        return None
    if not path.is_file():
        return f"{pattern} (expected file)"
    return None


def _iter_searchable_files() -> list[Path]:
    excluded_paths = {REVIEW_QUERIES_PATH, THIS_TEST_PATH}
    files: list[Path] = []
    for root_name in TEXT_SEARCH_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path in excluded_paths:
                continue
            rel_parts = path.relative_to(REPO_ROOT).parts
            if any(part in SKIP_SEARCH_PARTS for part in rel_parts):
                continue
            if path.suffix in SKIP_SEARCH_SUFFIXES:
                continue
            files.append(path)
    return files


def test_review_retrieval_goldset_uses_existing_query_format(
    base_queries: list[dict[str, Any]],
    review_queries: list[dict[str, Any]],
) -> None:
    assert REVIEW_QUERIES_PATH.is_file()
    assert base_queries, f"{BASE_QUERIES_PATH} must not be empty"
    assert review_queries, f"{REVIEW_QUERIES_PATH} must not be empty"

    base_fields = set(base_queries[0])
    assert base_fields == REQUIRED_FIELDS
    for index, query_case in enumerate(review_queries):
        label = f"query[{index}]"
        assert isinstance(query_case, dict), f"{label}: expected object, got {type(query_case).__name__}"
        label = f"{label} {query_case.get('query')!r}"
        fields = set(query_case)
        assert REQUIRED_FIELDS <= fields, (
            f"{label}: missing fields {sorted(REQUIRED_FIELDS - fields)}"
        )
        assert fields <= ALLOWED_REVIEW_FIELDS, (
            f"{label}: unexpected fields {sorted(fields - ALLOWED_REVIEW_FIELDS)}"
        )
        assert isinstance(query_case["expected_patterns"], list), (
            f"{label}: expected_patterns must be a list"
        )
        assert query_case["expected_patterns"], (
            f"{label}: expected_patterns must not be empty"
        )
        assert all(
            isinstance(pattern, str) and pattern.strip()
            for pattern in query_case["expected_patterns"]
        ), f"{label}: expected_patterns must contain non-empty strings"
        assert isinstance(query_case["filters"], dict), f"{label}: filters must be an object"
        assert isinstance(query_case["accept_criteria"], dict), (
            f"{label}: accept_criteria must be an object"
        )


def test_review_retrieval_goldset_has_minimum_size_and_unique_queries(
    review_queries: list[dict[str, Any]],
) -> None:
    assert len(review_queries) >= 20
    invalid_queries = [
        index
        for index, query_case in enumerate(review_queries)
        if not isinstance(query_case.get("query"), str) or not query_case["query"].strip()
    ]
    assert invalid_queries == [], f"empty or non-string query text at indices {invalid_queries}"

    query_texts = [query_case["query"].strip() for query_case in review_queries]
    duplicates = sorted(
        query for query in set(query_texts) if query_texts.count(query) > 1
    )
    assert duplicates == [], f"duplicate query text after stripping whitespace: {duplicates}"


def test_review_retrieval_goldset_covers_blueprint_categories(
    review_queries: list[dict[str, Any]],
) -> None:
    categories = {query_case.get("category") for query_case in review_queries}

    assert None not in categories, "every review query must declare a category"
    assert categories == REQUIRED_CATEGORIES, (
        f"missing categories: {sorted(REQUIRED_CATEGORIES - categories)}; "
        f"unexpected categories: {sorted(categories - REQUIRED_CATEGORIES)}"
    )


def test_review_retrieval_goldset_expected_path_patterns_exist(
    review_queries: list[dict[str, Any]],
) -> None:
    patterns = {
        pattern
        for query_case in review_queries
        for pattern in query_case["expected_patterns"]
    }
    path_patterns = {pattern for pattern in patterns if _is_repo_path_pattern(pattern)}
    symbolic_patterns = patterns - path_patterns

    assert _is_repo_path_pattern("README.md")
    assert _is_repo_path_pattern("Makefile")
    assert _is_repo_path_pattern("other/package.json")
    assert not _is_repo_path_pattern("run_query")
    assert not _is_repo_path_pattern("range_ref_resolution")
    assert path_patterns, "goldset must contain path-like expected_patterns"
    assert symbolic_patterns, "goldset must contain symbolic expected_patterns"

    path_issues = sorted(
        issue
        for pattern in path_patterns
        if (issue := _missing_or_wrong_kind_path(pattern)) is not None
    )
    assert path_issues == [], f"missing or wrong-kind path patterns: {path_issues}"


def test_review_retrieval_goldset_symbolic_patterns_exist_in_repo_text(
    review_queries: list[dict[str, Any]],
) -> None:
    remaining_patterns = {
        pattern
        for query_case in review_queries
        for pattern in query_case["expected_patterns"]
        if not _is_repo_path_pattern(pattern)
    }
    searchable_files = _iter_searchable_files()

    assert searchable_files, "no searchable repository text files found"

    for path in searchable_files:
        if not remaining_patterns:
            break
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        found = {pattern for pattern in remaining_patterns if pattern in text}
        remaining_patterns -= found

    assert remaining_patterns == set(), (
        "symbolic patterns not found outside the goldset and its guard test: "
        f"{sorted(remaining_patterns)}"
    )
