import json
from pathlib import Path

TASK_ID = "TASK-GRAPH-SOURCE-ROOTS-CONTRACT-001"

board_path = Path("docs/tasks/board.md")
board = board_path.read_text(encoding="utf-8")
if TASK_ID not in board:
    row = "| TASK-GRAPH-SOURCE-ROOTS-CONTRACT-001 | Explicit Graph Source Roots v1 Contract | done | `merger/lenskit/contracts/architecture.source_roots.v1.schema.json`, `merger/lenskit/contracts/examples/source_roots_minimal.json`, `merger/lenskit/tests/test_architecture_source_roots_schema.py`, `docs/architecture/graph-source-roots.md`, `docs/proofs/graph-source-roots-contract-proof.md` | Contract-first G4c slice: canonical relative roots and ambiguity boundaries are formalized; producer, bundle, CLI, ranking and baseline consumption remain open. |\n"
    board_path.write_text(board.rstrip() + "\n" + row, encoding="utf-8")

index_path = Path("docs/tasks/index.json")
data = json.loads(index_path.read_text(encoding="utf-8"))
if not any(item.get("id") == TASK_ID for item in data["tasks"]):
    data["tasks"].append({
        "id": TASK_ID,
        "title": "Explicit Graph Source Roots v1 Contract",
        "status": "done",
        "description": "Defines and tests explicit additional Python import roots before graph-producer consumption.",
        "evidence": [
            "merger/lenskit/contracts/architecture.source_roots.v1.schema.json",
            "merger/lenskit/contracts/examples/source_roots_minimal.json",
            "merger/lenskit/tests/test_architecture_source_roots_schema.py",
            "docs/architecture/graph-source-roots.md",
            "docs/proofs/graph-source-roots-contract-proof.md"
        ],
        "missing_evidence": [
            "No graph producer, bundle producer or CLI consumer is implemented.",
            "Repository-context directory validation remains a consumer obligation.",
            "No runtime import, graph completeness, retrieval benefit or default-ranking claim is established."
        ]
    })
    index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
