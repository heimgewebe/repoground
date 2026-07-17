"""Deterministic process-local indexes for validated call navigation records.

The indexes contain only integer positions into their validated source arrays. They
are not a second source of truth and must be rebuilt whenever the bound source
artifact changes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

CallRow = dict[str, Any]
SymbolRow = dict[str, Any]
CallerIdentity = tuple[str | None, str, str | None, str | None, int | None, int | None]


def _freeze_postings(
    values: Mapping[Any, list[int]],
) -> Mapping[Any, tuple[int, ...]]:
    return MappingProxyType(
        {key: tuple(positions) for key, positions in values.items()}
    )


def _trigrams(value: str) -> frozenset[str]:
    if len(value) < 3:
        return frozenset()
    return frozenset(value[index : index + 3] for index in range(len(value) - 2))


def caller_identity_from_call(call: CallRow) -> CallerIdentity:
    return (
        call.get("caller_symbol_id"),
        str(call.get("path", "")),
        call.get("caller_qualified_name"),
        call.get("caller_kind"),
        call.get("caller_start_line"),
        call.get("caller_end_line"),
    )


def caller_identity_from_symbol(symbol: SymbolRow) -> CallerIdentity:
    return (
        symbol.get("id"),
        str(symbol.get("path", "")),
        symbol.get("qualified_name"),
        symbol.get("kind"),
        symbol.get("start_line"),
        symbol.get("end_line"),
    )


def _call_position_key(call: CallRow) -> tuple[str, int, int]:
    return (
        str(call.get("path", "")),
        int(call.get("start_line", 0) or 0),
        int(call.get("start_col", 0) or 0),
    )


def _validated_positions(value: Any, *, call_count: int, label: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError(f"persisted call navigation index {label} is invalid")
    positions = tuple(value)
    valid = all(
        isinstance(position, int)
        and not isinstance(position, bool)
        and 0 <= position < call_count
        for position in positions
    )
    if (
        not valid
        or len(positions) != len(set(positions))
        or positions != tuple(sorted(positions))
    ):
        raise ValueError(f"persisted call navigation index {label} is invalid")
    return positions


def _persisted_postings(
    projection: Mapping[str, Any], field: str, call_count: int
) -> Mapping[str, tuple[int, ...]]:
    raw = projection.get(field)
    if not isinstance(raw, dict):
        raise ValueError(f"persisted call navigation index {field} is invalid")
    result: dict[str, tuple[int, ...]] = {}
    for key, positions in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"persisted call navigation index {field} key is invalid")
        result[key] = _validated_positions(
            positions,
            call_count=call_count,
            label=f"{field} positions",
        )
    return MappingProxyType(result)


def _caller_identity(value: Any) -> CallerIdentity:
    if not isinstance(value, list) or len(value) != 6:
        raise ValueError("persisted caller identity is invalid")
    symbol_id, path, qualified_name, kind, start_line, end_line = value
    if symbol_id is not None and not isinstance(symbol_id, str):
        raise ValueError("persisted caller symbol id is invalid")
    if not isinstance(path, str):
        raise ValueError("persisted caller path is invalid")
    if qualified_name is not None and not isinstance(qualified_name, str):
        raise ValueError("persisted caller qualified name is invalid")
    if kind is not None and not isinstance(kind, str):
        raise ValueError("persisted caller kind is invalid")
    for line in (start_line, end_line):
        if line is not None and (
            not isinstance(line, int) or isinstance(line, bool) or line < 1
        ):
            raise ValueError("persisted caller line is invalid")
    return symbol_id, path, qualified_name, kind, start_line, end_line


def _persisted_caller_positions(
    projection: Mapping[str, Any], call_count: int
) -> Mapping[CallerIdentity, tuple[int, ...]]:
    raw = projection.get("caller_positions")
    if not isinstance(raw, list):
        raise ValueError("persisted call navigation caller_positions is invalid")
    callers: dict[CallerIdentity, tuple[int, ...]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("persisted caller position entry is invalid")
        identity = _caller_identity(item.get("identity"))
        if identity in callers:
            raise ValueError("persisted caller identity is duplicated")
        callers[identity] = _validated_positions(
            item.get("positions"),
            call_count=call_count,
            label="caller positions",
        )
    return MappingProxyType(callers)


@dataclass(frozen=True, slots=True)
class CallNavigationIndex:
    """Bounded lookup tables over one validated call-record sequence."""

    calls: tuple[CallRow, ...]
    simple_name_positions: Mapping[str, tuple[int, ...]]
    expression_trigram_positions: Mapping[str, tuple[int, ...]]
    resolved_target_positions: Mapping[str, tuple[int, ...]]
    candidate_target_positions: Mapping[str, tuple[int, ...]]
    caller_positions: Mapping[CallerIdentity, tuple[int, ...]]

    @classmethod
    def build(cls, calls: Sequence[CallRow]) -> CallNavigationIndex:
        simple_names: defaultdict[str, list[int]] = defaultdict(list)
        expression_trigrams: defaultdict[str, list[int]] = defaultdict(list)
        resolved_targets: defaultdict[str, list[int]] = defaultdict(list)
        candidate_targets: defaultdict[str, list[int]] = defaultdict(list)
        callers: defaultdict[CallerIdentity, list[int]] = defaultdict(list)

        frozen_calls = tuple(calls)
        for position, call in enumerate(frozen_calls):
            simple_name = str(call.get("simple_name", "") or "").casefold()
            expression = str(call.get("callee_expression", "") or "").casefold()
            if simple_name:
                simple_names[simple_name].append(position)
            for trigram in _trigrams(expression):
                expression_trigrams[trigram].append(position)
            for target_id in call.get("resolved_target_ids", []):
                resolved_targets[str(target_id)].append(position)
            for target_id in call.get("candidate_target_ids", []):
                candidate_targets[str(target_id)].append(position)
            callers[caller_identity_from_call(call)].append(position)

        return cls(
            calls=frozen_calls,
            simple_name_positions=_freeze_postings(simple_names),
            expression_trigram_positions=_freeze_postings(expression_trigrams),
            resolved_target_positions=_freeze_postings(resolved_targets),
            candidate_target_positions=_freeze_postings(candidate_targets),
            caller_positions=_freeze_postings(callers),
        )

    @classmethod
    def from_persisted_projection(
        cls,
        calls: Sequence[CallRow],
        projection: Mapping[str, Any],
        source_calls_sha256: str,
    ) -> CallNavigationIndex:
        """Reconstruct the benchmark sidecar only when it matches its call source."""
        frozen_calls = tuple(calls)
        if (
            projection.get("kind") != "lenskit.python_call_navigation_index"
            or projection.get("version") != "1.0"
            or projection.get("source_calls_sha256") != source_calls_sha256
            or projection.get("source_call_count") != len(frozen_calls)
        ):
            raise ValueError("persisted call navigation index source binding mismatch")
        call_count = len(frozen_calls)
        return cls(
            calls=frozen_calls,
            simple_name_positions=_persisted_postings(
                projection, "simple_name_positions", call_count
            ),
            expression_trigram_positions=_persisted_postings(
                projection, "expression_trigram_positions", call_count
            ),
            resolved_target_positions=_persisted_postings(
                projection, "resolved_target_positions", call_count
            ),
            candidate_target_positions=_persisted_postings(
                projection, "candidate_target_positions", call_count
            ),
            caller_positions=_persisted_caller_positions(projection, call_count),
        )

    def _expression_candidates(self, query: str) -> set[int]:
        trigrams = _trigrams(query)
        if not trigrams:
            return set(range(len(self.calls)))
        postings = [
            self.expression_trigram_positions.get(item, ()) for item in trigrams
        ]
        if not postings or any(not positions for positions in postings):
            return set()
        smallest, *remaining = sorted(postings, key=len)
        candidates = set(smallest)
        for positions in remaining:
            candidates.intersection_update(positions)
            if not candidates:
                break
        return candidates

    def reference_calls(self, query: str) -> list[CallRow]:
        """Return the same ordered call rows as the v1 linear reference search."""
        exact_positions = set(self.simple_name_positions.get(query, ()))
        candidate_positions = exact_positions | self._expression_candidates(query)
        matched: list[tuple[int, str, int, int, int, CallRow]] = []
        for position in candidate_positions:
            call = self.calls[position]
            simple_name = str(call.get("simple_name", "") or "").casefold()
            expression = str(call.get("callee_expression", "") or "").casefold()
            exact = simple_name == query
            if not exact and query not in expression:
                continue
            path, line, col = _call_position_key(call)
            matched.append((0 if exact else 1, path, line, col, position, call))
        matched.sort(key=lambda item: item[:5])
        return [item[-1] for item in matched]

    def target_related_calls(self, target_id: str, query: str) -> list[CallRow]:
        """Return rows relevant to get_callers without scanning unrelated calls."""
        positions = (
            set(self.resolved_target_positions.get(target_id, ()))
            | set(self.candidate_target_positions.get(target_id, ()))
            | set(self.simple_name_positions.get(query, ()))
        )
        return [self.calls[position] for position in sorted(positions)]

    def calls_for_symbol(self, symbol: SymbolRow) -> list[CallRow]:
        identity = caller_identity_from_symbol(symbol)
        return [
            self.calls[position] for position in self.caller_positions.get(identity, ())
        ]

    def persisted_projection(self, source_calls_sha256: str) -> dict[str, Any]:
        """Create the deterministic sidecar candidate used only by the benchmark."""

        def string_map(values: Mapping[str, tuple[int, ...]]) -> dict[str, list[int]]:
            return {key: list(values[key]) for key in sorted(values)}

        callers = [
            {"identity": list(key), "positions": list(self.caller_positions[key])}
            for key in sorted(
                self.caller_positions,
                key=lambda item: tuple(
                    "" if value is None else str(value) for value in item
                ),
            )
        ]
        return {
            "kind": "lenskit.python_call_navigation_index",
            "version": "1.0",
            "source_calls_sha256": source_calls_sha256,
            "source_call_count": len(self.calls),
            "simple_name_positions": string_map(self.simple_name_positions),
            "expression_trigram_positions": string_map(
                self.expression_trigram_positions
            ),
            "resolved_target_positions": string_map(self.resolved_target_positions),
            "candidate_target_positions": string_map(self.candidate_target_positions),
            "caller_positions": callers,
        }


@dataclass(frozen=True, slots=True)
class SymbolNavigationIndex:
    """Exact-name lookup over one validated Python symbol-index sequence."""

    symbols: tuple[SymbolRow, ...]
    rows_by_id: Mapping[str, tuple[SymbolRow, ...]]
    exact_query_positions: Mapping[str, tuple[int, ...]]

    @classmethod
    def build(cls, symbols: Sequence[SymbolRow]) -> SymbolNavigationIndex:
        rows_by_id: defaultdict[str, list[SymbolRow]] = defaultdict(list)
        exact_queries: defaultdict[str, list[int]] = defaultdict(list)
        frozen_symbols = tuple(symbols)
        for position, symbol in enumerate(frozen_symbols):
            rows_by_id[str(symbol["id"])].append(symbol)
            queries = {
                str(symbol.get("name", "")).casefold(),
                str(symbol.get("qualified_name", "")).casefold(),
            }
            for query in queries:
                if query:
                    exact_queries[query].append(position)
        return cls(
            symbols=frozen_symbols,
            rows_by_id=MappingProxyType(
                {key: tuple(rows) for key, rows in rows_by_id.items()}
            ),
            exact_query_positions=_freeze_postings(exact_queries),
        )

    def select(self, query: str, path_filter: str | None) -> list[SymbolRow]:
        matches = []
        for position in self.exact_query_positions.get(query, ()):
            symbol = self.symbols[position]
            if (
                path_filter
                and path_filter not in str(symbol.get("path", "")).casefold()
            ):
                continue
            matches.append(symbol)
        return sorted(
            matches,
            key=lambda item: (
                str(item.get("path", "")),
                int(item.get("start_line", 0) or 0),
                str(item.get("qualified_name", "")),
                str(item.get("id", "")),
            ),
        )


def linear_reference_calls(calls: Iterable[CallRow], query: str) -> list[CallRow]:
    """Reference implementation retained for benchmark and equivalence tests."""
    matched: list[tuple[int, str, int, int, int, CallRow]] = []
    for position, call in enumerate(calls):
        simple_name = str(call.get("simple_name", "") or "").casefold()
        expression = str(call.get("callee_expression", "") or "").casefold()
        exact = simple_name == query
        if not exact and query not in expression:
            continue
        path, line, col = _call_position_key(call)
        matched.append((0 if exact else 1, path, line, col, position, call))
    matched.sort(key=lambda item: item[:5])
    return [item[-1] for item in matched]


def linear_target_related_calls(
    calls: Iterable[CallRow], target_id: str, query: str
) -> list[CallRow]:
    return [
        call
        for call in calls
        if target_id in call.get("resolved_target_ids", [])
        or target_id in call.get("candidate_target_ids", [])
        or str(call.get("simple_name", "") or "").casefold() == query
    ]


def linear_calls_for_symbol(
    calls: Iterable[CallRow], symbol: SymbolRow
) -> list[CallRow]:
    identity = caller_identity_from_symbol(symbol)
    return [call for call in calls if caller_identity_from_call(call) == identity]
