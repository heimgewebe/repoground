import json
import pytest

from merger.repoground.retrieval import query_core
from merger.repoground.retrieval import index_db

@pytest.fixture
def eval_index(tmp_path):
    db_path = tmp_path / "index.sqlite"
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"

    ref_obj = {
        "artifact_role": "canonical_md",
        "repo_id": "r1",
        "file_path": "merged.md",
        "start_byte": 0,
        "end_byte": 40,
        "start_line": 1,
        "end_line": 3,
        "content_sha256": "h1"
    }

    # Code snippet: "def test_eval():\n    return 'hello eval'\n"
    # Derived range logic requires it to exist on disk if it falls back to source
    source_file = tmp_path / "src" / "test.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("def test_eval():\n    return 'hello eval'\n", encoding="utf-8")

    chunk_data = [
        {
            "chunk_id": "c1",
            "repo_id": "r1",
            "path": "src/test.py",
            "content": "def test_eval():\n    return 'hello eval'\n",
            "start_line": 1,
            "end_line": 2,
            "layer": "core",
            "artifact_type": "code",
            "content_sha256": "h1",
            "content_range_ref": ref_obj,
            "start_byte": 0,
            "end_byte": 40,
            "source_file": "src/test.py"
        },
        {
            "chunk_id": "c_derived",
            "repo_id": "r1",
            "path": "src/test.py",
            "content": "return 'hello eval'",
            "start_line": 2,
            "end_line": 2,
            "layer": "core",
            "artifact_type": "code",
            "content_sha256": "h1",
            "content_range_ref": None, # Force derived provenance fallback
            "start_byte": 17,
            "end_byte": 40,
            "source_file": "src/test.py"
        }
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")
    index_db.build_index(dump_path, chunk_path, db_path)
    return db_path


def test_context_snippet_passthrough(eval_index):
    """Prueft, dass resolved_code_snippet dem originalen Chunk-Content entspricht."""
    res = query_core.execute_query(
        eval_index,
        query_text="hello",
        k=5,
        build_context=True,
        context_mode="exact"
    )

    hits = res["context_bundle"]["hits"]
    # Finde den explicit hit
    hit = next(h for h in hits if h["hit_identity"] == "c1")

    assert hit["provenance_type"] == "explicit"
    assert hit["range_ref"] is not None
    # Das extrahierte Snippet muss dem originalen Chunk-Content entsprechen
    assert hit["resolved_code_snippet"] == "def test_eval():\n    return 'hello eval'\n"


def test_provenance_validity(eval_index):
    """Stellt sicher, dass provenance_type explizit und nicht leer ist."""
    res = query_core.execute_query(eval_index, query_text="hello", k=5, build_context=True)

    hits = res["context_bundle"]["hits"]
    assert len(hits) == 2

    for hit in hits:
        assert hit["provenance_type"] in ["explicit", "derived"]

        if hit["provenance_type"] == "explicit":
            assert hit.get("range_ref") is not None
        else:
            assert hit.get("derived_range_ref") is not None

def test_context_contains_expected_snippet(eval_index):
    """Prueft, dass der extrahierte Kontext den exakten erwarteten Text enthaelt."""
    res = query_core.execute_query(eval_index, query_text="hello", k=5, build_context=True)

    hits = res["context_bundle"]["hits"]
    hit = next(h for h in hits if h["hit_identity"] == "c1")

    assert "hello eval" in hit["resolved_code_snippet"]

def test_no_silent_provenance_downgrade(eval_index):
    """Verhindert, dass explizite Range-Refs heimlich zu abgeleiteten werden, ohne Fehler."""
    # Der explicit hit hat ein range_ref. Wenn wir den resolver_status checken, darf er nicht gefailed sein
    # In context_builder ist ein Downgrade als Fallback implementiert, ABER das hit objekt MUSS das flaggen.
    res = query_core.execute_query(eval_index, query_text="hello", k=5, build_context=True)

    hits = res["context_bundle"]["hits"]
    hit = next(h for h in hits if h["hit_identity"] == "c1")

    # explicit provenance muss preserved bleiben
    assert hit["provenance_type"] == "explicit"
    assert hit.get("range_ref") is not None
    # derived darf in diesem fall optional befuellt sein, aber type MUSS explicit sein

    # Wenn wir c_derived angucken, muss er derived sein, weil range_ref None ist
    hit_derived = next(h for h in hits if h["hit_identity"] == "c_derived")
    assert hit_derived["provenance_type"] == "derived"
    assert hit_derived.get("range_ref") is None
