"""Deterministic review-intent query planning.

The legacy router translates one natural-language query into one FTS expression.
Review questions often ask for several artifact roles at once, for example an
implementation, its tests, and its contract. Requiring every role word to occur
in one chunk suppresses exactly the cross-file evidence set the reviewer asked
for.

This module is intentionally planning-only. It classifies requested artifact
roles, builds bounded FTS lanes, and declares deterministic fusion semantics.
It does not read repository content, infer correctness, or promote itself to the
default query path.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence

TOKEN_RE = re.compile(r"\b\w+\b")

_REVIEW_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "both",
        "display",
        "do",
        "does",
        "during",
        "explain",
        "find",
        "for",
        "get",
        "give",
        "how",
        "in",
        "is",
        "its",
        "lenskit",
        "list",
        "locate",
        "me",
        "of",
        "or",
        "primary",
        "repository",
        "review",
        "search",
        "show",
        "the",
        "to",
        "used",
        "what",
        "where",
        "with",
    }
)

# A leading contract/test token is retained as an anchor for queries such as
# "contracts inventory ..."; elsewhere these tokens are role instructions.
_ROLE_BY_TOKEN = {
    "producer": "source",
    "production": "source",
    "implementation": "source",
    "checks": "source",
    "check": "source",
    "logic": "source",
    "selection": "source",
    "enforcement": "source",
    "resolution": "source",
    "tests": "test",
    "test": "test",
    "coverage": "test",
    "contract": "contract",
    "contracts": "contract",
    "schema": "contract",
    "json": "contract",
    "versions": "contract",
    "version": "contract",
    "report": "contract",
    "output": "contract",
    "cli": "cli",
    "command": "cli",
    "registration": "cli",
    "verification": "cli",
    "documentation": "docs",
    "inventory": "docs",
    "matrix": "docs",
}

_ROLE_TOKENS = frozenset(_ROLE_BY_TOKEN)

# Explicit variants avoid the false stemming produced by generic suffix rules.
_TERM_EXPANSIONS = {
    "artifact": ("artifacts",),
    "check": ("checks",),
    "checks": ("check",),
    "contract": ("contracts",),
    "contracts": ("contract",),
    "diagnostic": ("diagnostics",),
    "diagnostics": ("diagnostic",),
    "eval": ("evaluation",),
    "evaluation": ("eval",),
    "lens": ("lenses",),
    "manifest": ("manifests",),
    "map": ("maps",),
    "metric": ("metrics",),
    "metrics": ("metric",),
    "profile": ("profiles",),
    "query": ("queries",),
    "reference": ("references", "ref"),
    "references": ("reference", "ref"),
    "router": ("routers",),
    "rule": ("rules",),
    "rules": ("rule",),
    "schema": ("schemas",),
    "test": ("tests",),
    "tests": ("test",),
}

_ROLE_PATH_FILTERS = {
    "test": "path_tokens:test",
    "contract": (
        "(path_tokens:contract OR path_tokens:contracts "
        "OR path_tokens:schema OR path_tokens:json)"
    ),
    "cli": "path_tokens:cli",
    "docs": "path_tokens:docs",
}

REVIEW_ROUTER_DOES_NOT_ESTABLISH = (
    "The plan does not establish that a returned artifact is relevant or correct.",
    "Role-lane coverage does not establish review completeness.",
    "A missing lane hit does not establish repository absence.",
    "Goldset improvement does not establish improvement for unmeasured query classes.",
    "The opt-in plan does not establish readiness for default promotion.",
)


def _dedupe(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _term_group(token: str) -> str:
    variants = [token, *_TERM_EXPANSIONS.get(token, ())]
    if len(variants) == 1:
        return token
    return "(" + " OR ".join(variants) + ")"


def _join_groups(groups: Sequence[str], operator: str) -> str:
    if not groups:
        return ""
    if len(groups) == 1:
        return groups[0]
    return f" {operator} ".join(groups)


def _apply_path_filter(query: str, role: str) -> str:
    path_filter = _ROLE_PATH_FILTERS.get(role)
    if not path_filter:
        return query
    return f"({query}) AND {path_filter}"


def plan_review_query(query_text: str) -> Dict[str, Any]:
    """Build a deterministic, bounded review-artifact lookup plan.

    Lanes are ordered by first role mention. A source lane is an unqualified
    lexical lane; test/contract/CLI/docs lanes add FTS ``path_tokens`` filters.
    Strict variants require all anchor groups. Relaxed variants use OR only as
    a bounded fallback inside the same role lane.
    """
    if not isinstance(query_text, str):
        raise ValueError("query_text must be a string")

    tokens = TOKEN_RE.findall(query_text.lower())
    content_tokens = [token for token in tokens if token not in _REVIEW_STOPWORDS]

    roles: List[str] = []
    for token in content_tokens:
        role = _ROLE_BY_TOKEN.get(token)
        if role and role not in roles:
            roles.append(role)

    anchors: List[str] = []
    for index, token in enumerate(content_tokens):
        if token in _ROLE_TOKENS:
            if index == 0 and token in {"contract", "contracts", "test", "tests"}:
                anchors.append(token)
            continue
        anchors.append(token)
    anchors = _dedupe(anchors)

    if not anchors:
        anchors = _dedupe(content_tokens)

    groups = [_term_group(token) for token in anchors]
    strict_query = _join_groups(groups, "AND")
    relaxed_query = _join_groups(groups, "OR")

    lane_roles = list(roles)
    if "source" not in lane_roles:
        lane_roles.append("general")

    lanes: List[Dict[str, Any]] = []
    if strict_query:
        for role in lane_roles:
            lane_role = "general" if role == "source" else role
            strict_fts_query = _apply_path_filter(strict_query, lane_role)
            relaxed_fts_query = _apply_path_filter(relaxed_query, lane_role)
            lane: Dict[str, Any] = {
                "name": role,
                "strict_fts_query": strict_fts_query,
            }
            if relaxed_fts_query != strict_fts_query:
                lane["relaxed_fts_query"] = relaxed_fts_query
            lanes.append(lane)

    return {
        "version": "review_intent.v1",
        "intent": "review_artifact_lookup" if lanes else "unknown",
        "query": query_text,
        "anchor_terms": anchors,
        "requested_roles": roles,
        "lanes": lanes,
        "fusion": {
            "method": "round_robin_unique_path",
            "strict_before_relaxed": True,
            "compatibility_lane": "legacy",
            "lane_order": ["legacy", *[lane["name"] for lane in lanes]],
        },
        "does_not_establish": list(REVIEW_ROUTER_DOES_NOT_ESTABLISH),
    }
