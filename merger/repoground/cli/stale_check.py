import sys
import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Optional

def _compute_file_sha256(path: Path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None

def _get_sha_from_db(index_path: Path) -> Optional[str]:
    try:
        # We use .resolve().as_uri() to ensure the path is correctly escaped for the URI connection string.
        # This prevents reserved URI characters in filesystem paths (like '?' or '#') from being
        # incorrectly interpreted as URI delimiters (query or fragment components).
        uri = f"{index_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            c = conn.cursor()
            row = c.execute("SELECT value FROM index_meta WHERE key='canonical_dump_index_sha256'").fetchone()
            if row:
                return row[0]
            row = c.execute("SELECT value FROM index_meta WHERE key='dump_sha256'").fetchone()
            if row:
                return row[0]
    except Exception:
        # We catch Exception here as a failsafe against URI parsing errors or unexpected DB state
        # to ensure the fallback never crashes the main stale check flow.
        pass
    return None

def check_stale_index(index_path: Path, stale_policy: str = "warn") -> bool:
    """
    Checks if the given SQLite index is stale by comparing the
    'canonical_dump_index_sha256' in the adjacent derived manifest with the actual
    hash of the adjacent dump_index.json (canonical index).
    Behavior depends on stale_policy ('warn', 'fail', 'ignore').
    Returns True if stale, False otherwise.
    """
    if stale_policy == "ignore":
        return False

    def undeterminable(reason: str = "missing/ambiguous manifests or dump") -> bool:
        if stale_policy == "fail":
            print(
                f"Error: Cannot determine staleness/validity for '{index_path.name}' (policy=fail): {reason}.",
                file=sys.stderr
            )
            return True
        return False

    try:
        # Expected naming: <base>.chunk_index.index.sqlite
        # Derived manifest: <base>.derived_index.json
        # Dump manifest: <base>.dump_index.json
        if not index_path.name.endswith(".index.sqlite"):
            return undeterminable("not an .index.sqlite file")

        base_name = index_path.name.replace(".chunk_index.index.sqlite", "").replace(".index.sqlite", "")
        dir_path = index_path.parent

        derived_path = dir_path / f"{base_name}.derived_index.json"
        dump_path = dir_path / f"{base_name}.dump_index.json"

        recorded_sha = None

        if not derived_path.exists() or not dump_path.exists():
            # Fallback discovery: Check if exactly one exists in the directory
            all_derived = list(dir_path.glob("*.derived_index.json"))
            all_dump = list(dir_path.glob("*.dump_index.json"))

            if len(all_derived) == 1 and len(all_dump) == 1:
                derived_path = all_derived[0]
                dump_path = all_dump[0]
            elif len(all_dump) == 1:
                dump_path = all_dump[0]
                recorded_sha = _get_sha_from_db(index_path)
            elif dump_path.exists():
                recorded_sha = _get_sha_from_db(index_path)
            elif not all_dump and not dump_path.exists():
                return undeterminable("dump manifest missing")
            else:
                return undeterminable("missing/ambiguous manifests or dump")

        if recorded_sha is None:
            if derived_path.exists():
                derived_data = json.loads(derived_path.read_text(encoding="utf-8"))
                recorded_sha = derived_data.get("canonical_dump_index_sha256")
            else:
                recorded_sha = _get_sha_from_db(index_path)

        if not recorded_sha:
            return undeterminable()

        if not dump_path.exists():
            return undeterminable("dump manifest missing")

        actual_sha = _compute_file_sha256(dump_path)

        if actual_sha is None:
            return undeterminable("unreadable dump manifest")

        if recorded_sha != actual_sha:
            if stale_policy == "fail":
                print(
                    f"Error: The index '{index_path.name}' is stale. "
                    f"The canonical dump_index.json has changed. Failing as per stale-policy.",
                    file=sys.stderr
                )
            elif stale_policy == "warn":
                print(
                    f"Warning: The index '{index_path.name}' appears to be stale. "
                    f"The canonical dump_index.json has changed.",
                    file=sys.stderr
                )
            return True

        return False
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        # Fail silently if JSON parsing or file IO fails under warn, but fail under fail policy
        return undeterminable()

    return False
