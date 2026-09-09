from __future__ import annotations

from doctor_agent.common import MedicalAgentState, trace


def evaluation_harness(state: MedicalAgentState) -> MedicalAgentState:
    evaluation = {
        "red_flag_detected": bool(state.get("risk_assessment", {}).get("red_flags")),
        "retrieved_evidence_count": len(state.get("retrieved_evidence", [])),
        "clean_evidence_count": len(state.get("clean_evidence", [])),
        "dirty_evidence_dropped": len(state.get("dropped_evidence", [])),
        "selected_experts": state.get("selected_experts", []),
        "token_estimate": state.get("packed_context", {}).get("token_estimate"),
        "output_safe": state.get("output_safety", {}).get("output_safe"),
        "network_evidence_count": len(state.get("web_evidence", [])),
        "mcp_tool_success_count": sum(1 for event in state.get("tool_events", []) if event.get("status") == "success"),
        "vector_backend": state.get("vector_store_status", {}).get("backend"),
        "vector_points_count": state.get("vector_store_status", {}).get("points_count"),
        "embedding_model": state.get("vector_store_status", {}).get("embedding_model"),
        "llm_used": state.get("llm_generation", {}).get("used", False),
    }
    return {"evaluation_summary": evaluation, "trace": trace(state, "EvaluationHarness", "generated metrics")}
