import json
from pathlib import Path

TASK_ID = "TASK-GRAPH-QUALITY-GOLDSET-002"
board_path = Path("docs/tasks/board.md")
board = board_path.read_text(encoding="utf-8")
if TASK_ID not in board:
    row = "| TASK-GRAPH-QUALITY-GOLDSET-002 | Packaging Edge-Case Graph Goldset v1.1 | done | `docs/retrieval/graph_quality_goldset.v1.json`, `merger/lenskit/architecture/graph_quality_eval.py`, `merger/lenskit/tests/test_graph_quality_goldset.py`, `docs/diagnostics/graph-quality-baseline.{md,v1.json}`, `docs/proofs/graph-packaging-edge-case-goldset-proof.md` | Expands measurement for package imports, source-root gaps, ambiguous roots, invalid syntax and layer precedence. Producer and ranking remain unchanged. |\n"
    board_path.write_text(board.rstrip() + "\n" + row, encoding="utf-8")

index_path = Path("docs/tasks/index.json")
data = json.loads(index_path.read_text(encoding="utf-8"))
if not any(item.get("id") == TASK_ID for item in data["tasks"]):
    data["tasks"].append({
        "id": TASK_ID,
        "title": "Packaging Edge-Case Graph Goldset v1.1",
        "status": "done",
        "description": "Expands the graph-quality measurement surface without changing the graph producer or ranking.",
        "evidence": [
            "docs/retrieval/graph_quality_goldset.v1.json",
            "merger/lenskit/architecture/graph_quality_eval.py",
            "merger/lenskit/tests/test_graph_quality_goldset.py",
            "docs/diagnostics/graph-quality-baseline.v1.json",
            "docs/diagnostics/graph-quality-baseline.md",
            "docs/proofs/graph-packaging-edge-case-goldset-proof.md"
        ],
        "missing_evidence": [
            "No explicit source-root contract is implemented.",
            "The src-layout and namespace cases remain unresolved by design.",
            "No runtime, completeness, retrieval-benefit or default-ranking claim is established."
        ]
    })
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
