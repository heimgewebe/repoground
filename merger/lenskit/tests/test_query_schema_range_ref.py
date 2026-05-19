import json
import jsonschema
from merger.lenskit.retrieval import query_core
from merger.lenskit.retrieval import index_db

def test_schema_validates_both_cases(tmp_path):
    db_path = tmp_path / "index.sqlite"
    dump_path = tmp_path / "dump.json"
    chunk_path = tmp_path / "chunks.jsonl"

    ref_obj = {
        "artifact_role": "canonical_md",
        "repo_id": "r1",
        "file_path": "merged.md",
        "start_byte": 0,
        "end_byte": 10,
        "start_line": 1,
        "end_line": 1,
        "content_sha256": "h1"
    }

    chunk_data = [
        {
            "chunk_id": "c1", "repo_id": "r1", "path": "src/main.py", "content": "def main(): print('hello')",
            "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h1",
            "content_range_ref": ref_obj
        },
        {
            "chunk_id": "c2", "repo_id": "r1", "path": "src/other.py", "content": "def other(): print('missing_ref')",
            "start_line": 1, "end_line": 1, "layer": "core", "artifact_type": "code", "content_sha256": "h2"
        }
    ]
    with chunk_path.open("w", encoding="utf-8") as f:
        for c in chunk_data:
            f.write(json.dumps(c) + "\n")

    dump_path.write_text(json.dumps({"dummy": "data"}))
    index_db.build_index(dump_path, chunk_path, db_path)

    # Load schema
    schema_path = "merger/lenskit/contracts/query-result.v1.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # 1. With range_ref
    res_with_ref = query_core.execute_query(db_path, query_text="hello", k=1)
    assert len(res_with_ref["results"]) == 1
    assert "range_ref" in res_with_ref["results"][0]

    # Must validate cleanly against the strict schema
    jsonschema.validate(instance=res_with_ref, schema=schema)

    # 2. Without range_ref
    res_without_ref = query_core.execute_query(db_path, query_text="missing_ref", k=1)
    assert len(res_without_ref["results"]) == 1
    assert "range_ref" not in res_without_ref["results"][0]

    # Must validate cleanly against the strict schema
    jsonschema.validate(instance=res_without_ref, schema=schema)
    print("Schema validation successful for both states.")
