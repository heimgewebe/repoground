from pathlib import Path


path = Path("merger/lenskit/core/merge.py")
content = path.read_text(encoding="utf-8")
old = "if arch_graph_path.exists() and entrypoints_path.exists():"
new = "if arch_graph_path.exists() or entrypoints_path.exists():"
if content.count(old) != 1:
    raise SystemExit(f"expected one graph-source presence condition, found {content.count(old)}")
path.write_text(content.replace(old, new, 1), encoding="utf-8")
