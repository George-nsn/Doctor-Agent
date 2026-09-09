from __future__ import annotations

import argparse
import json
from pathlib import Path

from doctor_agent.common import PROJECT_ROOT
from doctor_agent.rag.qdrant_store import get_qdrant_store, index_knowledge_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the persistent Qdrant medical knowledge index.")
    parser.add_argument("--knowledge", type=Path, default=PROJECT_ROOT / "data" / "level_a_medical_knowledge.json")
    args = parser.parse_args()
    try:
        result = index_knowledge_file(args.knowledge)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        get_qdrant_store().close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())