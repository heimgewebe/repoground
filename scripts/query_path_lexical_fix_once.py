from pathlib import Path


path = Path("merger/lenskit/retrieval/query_core.py")
text = path.read_text(encoding="utf-8")
old = '''            if graph_index_path.is_absolute():
                graph_resolved = graph_index_path.resolve()
                if graph_resolved.parent != graph_root:
                    raise RuntimeError(
                        "Graph Index and SQLite index must share one directory"
                    )
                graph_relative_path = graph_resolved.name
'''
new = '''            if graph_index_path.is_absolute():
                if graph_index_path.parent != graph_root:
                    raise RuntimeError(
                        "Graph Index and SQLite index must share one directory"
                    )
                graph_relative_path = graph_index_path.name
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one caller-path resolution block, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
