import json
import re
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema
except ImportError:
    jsonschema = None

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_ERRORS = 20


class GraphIndexCompilationError(ValueError):
    """Machine-readable fail-closed graph compiler error."""

    def __init__(self, code, message, *, source=None, errors=None):
        super().__init__(message)
        self.code = code
        self.source = source
        self.errors = tuple(errors or ())

    def as_dict(self) -> dict[str, Any]:
        result = {
            "code": self.code,
            "message": str(self),
            "errors": list(self.errors),
        }
        if self.source is not None:
            result["source"] = self.source
        return result


def _json_path(parts: Iterable[Any]) -> str:
    path = "$"
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _validation_errors(errors) -> list[str]:
    ordered = sorted(
        errors,
        key=lambda error: (_json_path(error.absolute_path), error.message),
    )
    result = [
        f"{_json_path(error.absolute_path)}: {error.message}"
        for error in ordered[:_MAX_ERRORS]
    ]
    omitted = len(ordered) - len(result)
    if omitted:
        result.append(f"... {omitted} additional validation error(s) omitted")
    return result


def load_source(path: Path, schema_name: str, source: str) -> dict[str, Any]:
    """Load and Draft-07 validate one compiler source."""

    if jsonschema is None:
        raise GraphIndexCompilationError(
            "validation_unavailable",
            "jsonschema is required for graph index compilation",
            source=source,
        )
    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except FileNotFoundError as exc:
        raise GraphIndexCompilationError(
            "source_not_found",
            f"{source} source does not exist: {path}",
            source=source,
        ) from exc
    except json.JSONDecodeError as exc:
        raise GraphIndexCompilationError(
            "invalid_json",
            f"{source} source is not valid JSON: {path}",
            source=source,
            errors=[f"line {exc.lineno}, column {exc.colno}: {exc.msg}"],
        ) from exc
    except OSError as exc:
        raise GraphIndexCompilationError(
            "source_unreadable",
            f"{source} source is unreadable: {path}",
            source=source,
            errors=[str(exc)],
        ) from exc

    schema_path = Path(__file__).parent.parent / "contracts" / schema_name
    try:
        with schema_path.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        jsonschema.Draft7Validator.check_schema(schema)
        validator = jsonschema.Draft7Validator(schema)
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise GraphIndexCompilationError(
            "schema_unavailable",
            f"schema for {source} is unavailable: {schema_path}",
            source=source,
            errors=[str(exc)],
        ) from exc

    errors = list(validator.iter_errors(document))
    if errors:
        raise GraphIndexCompilationError(
            "invalid_schema",
            f"{source} source does not satisfy {schema_name}",
            source=source,
            errors=_validation_errors(errors),
        )
    return document


def require_coherence(
    graph: dict[str, Any],
    entrypoints: dict[str, Any],
    *,
    expected_run_id: str | None,
    expected_canonical_sha256: str | None,
) -> tuple[str, str]:
    """Require source equality and optional current-bundle equality."""

    graph_run = graph["run_id"]
    entry_run = entrypoints["run_id"]
    graph_sha = graph["canonical_dump_index_sha256"]
    entry_sha = entrypoints["canonical_dump_index_sha256"]

    if not graph_run or not entry_run:
        raise GraphIndexCompilationError(
            "invalid_provenance",
            "run_id values must be non-empty",
            source="provenance",
        )
    if graph_run != entry_run:
        raise GraphIndexCompilationError(
            "provenance_mismatch",
            "source run_id values differ",
            source="provenance",
            errors=[f"graph={graph_run!r}", f"entrypoints={entry_run!r}"],
        )
    if graph_sha != entry_sha:
        raise GraphIndexCompilationError(
            "provenance_mismatch",
            "source canonical dump hashes differ",
            source="provenance",
            errors=[f"graph={graph_sha}", f"entrypoints={entry_sha}"],
        )

    if expected_run_id is not None:
        if not expected_run_id:
            raise GraphIndexCompilationError(
                "invalid_expected_provenance",
                "expected run_id must be non-empty",
                source="expected_provenance",
            )
        if graph_run != expected_run_id:
            raise GraphIndexCompilationError(
                "bundle_provenance_mismatch",
                "sources do not belong to the expected bundle run",
                source="expected_provenance",
                errors=[f"source={graph_run!r}", f"expected={expected_run_id!r}"],
            )

    if expected_canonical_sha256 is not None:
        if not _SHA256_RE.fullmatch(expected_canonical_sha256):
            raise GraphIndexCompilationError(
                "invalid_expected_provenance",
                "expected canonical dump hash is invalid",
                source="expected_provenance",
            )
        if graph_sha != expected_canonical_sha256:
            raise GraphIndexCompilationError(
                "bundle_provenance_mismatch",
                "sources do not belong to the expected dump index",
                source="expected_provenance",
                errors=[f"source={graph_sha}", f"expected={expected_canonical_sha256}"],
            )

    return graph_run, graph_sha
