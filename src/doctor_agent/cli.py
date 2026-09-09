from __future__ import annotations

import argparse
import json
from pathlib import Path

from doctor_agent.agent_system import run_case
from doctor_agent.common import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Doctor Agent Medical Multi-Agent system.")
    parser.add_argument("--case", type=Path, default=PROJECT_ROOT / "data" / "sample_case.json")
    parser.add_argument("--knowledge", type=Path, default=PROJECT_ROOT / "data" / "mock_medical_knowledge.json")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "reports" / "program-demo" / "sample_case_result.json")
    args = parser.parse_args()

    result = run_case(args.case, args.knowledge)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("Medical Agent MVP completed")
    print(f"Risk: {result.get('risk_assessment', {}).get('risk_level')}")
    print(f"Experts: {', '.join(result.get('selected_experts', []))}")
    print(f"Evidence: {len(result.get('fused_evidence', []))} fused / {len(result.get('dropped_evidence', []))} dropped")
    print(f"Tokens: {result.get('packed_context', {}).get('token_estimate')}")
    print(f"Output: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
