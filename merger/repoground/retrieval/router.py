import re
from typing import Dict, Any

STOPWORDS = {
    "show", "find", "get", "where", "how", "what", "is", "are", "does", "do",
    "search", "list", "display", "locate", "explain", "give", "me"
}

INTENT_TRIGGERS = {
    "entrypoint": {"entrypoint", "start", "main", "cli", "cmd", "run", "execute", "entry", "boot"},
    "architecture": {"architecture", "structure", "design", "layer", "module", "component", "dependency"},
    "security": {"security", "auth", "token", "credential", "password", "secret", "vulnerability", "leak"},
    "test": {"test", "mock", "fixture", "assert", "spec", "verify", "suite"}
}

SYNONYMS = {
    "index": ["indexing", "build_index", "indexer"],
    "indexing": ["index", "build_index", "indexer"],
    "config": ["configuration", "settings", "options"],
    "configuration": ["config", "settings", "options"],
    "settings": ["config", "configuration", "options"],
    "db": ["database", "sqlite", "sql"],
    "database": ["db", "sqlite", "sql"],
    "error": ["exception", "fail", "failure", "crash"],
    "exception": ["error", "fail", "failure", "crash"],
    "auth": ["authentication", "login", "credentials", "security"],
    "authentication": ["auth", "login", "credentials", "security"]
}

def route_query(query_text: str, overmatch_guard: bool = False) -> Dict[str, Any]:
    r"""
    Parses the query text and extracts intents, removes stopwords,
    and performs synonym OR-expansion if overmatch_guard is False.

    Note on tokenization: Uses `\b\w+\b`, intentionally dropping characters
    like `-` or `+` to maintain robust behavior in SQLite FTS matching.
    """
    if not query_text:
        return {
            "intent": "unknown",
            "fts_query": "",
            "synonyms_used": []
        }

    # Normalize query
    tokens = re.findall(r'\b\w+\b', query_text.lower())

    # 1. Intent Extraction
    detected_intent = "unknown"
    best_pos = len(tokens) + 1

    for intent, triggers in INTENT_TRIGGERS.items():
        for idx, token in enumerate(tokens):
            if token in triggers and idx < best_pos:
                best_pos = idx
                detected_intent = intent

    # 2. Stopword Removal
    filtered_tokens = [t for t in tokens if t not in STOPWORDS]
    if not filtered_tokens:
        # If query was entirely stopwords, fallback to original tokens
        filtered_tokens = tokens

    # 3. Synonym OR-Expansion
    fts_parts = []
    synonyms_used = set()

    FTS_RESERVED = {"and", "or", "not", "near"}

    def safe_token(t: str) -> str:
        if t.lower() in FTS_RESERVED:
            return f'"{t}"'
        return t

    for token in filtered_tokens:
        if not overmatch_guard and token in SYNONYMS:
            expansions = [token] + SYNONYMS[token]
            synonyms_used.update(SYNONYMS[token])
            # Construct OR group, e.g., (index OR indexing OR build_index)
            safe_expansions = [safe_token(e) for e in expansions]
            or_group = " OR ".join(safe_expansions)
            fts_parts.append(f"({or_group})")
        else:
            fts_parts.append(safe_token(token))

    # Join the FTS parts
    fts_query = " AND ".join(fts_parts)

    return {
        "intent": detected_intent,
        "fts_query": fts_query,
        "synonyms_used": sorted(list(synonyms_used))
    }
