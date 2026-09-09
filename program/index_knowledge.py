from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from program.rag_engine.retriever.qdrant_store import get_qdrant_store, index_knowledge_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the persistent Qdrant medical knowledge index.")
    parser.add_argument("--knowledge", type=Path, default=Path("program/data/level_a_medical_knowledge.json"))
    args = parser.parse_args()
    try:
        result = index_knowledge_file(args.knowledge)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        get_qdrant_store().close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())