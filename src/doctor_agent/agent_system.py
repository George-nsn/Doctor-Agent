from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# pyright: reportMissingImports=false
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from doctor_agent.common import MedicalAgentState
from doctor_agent.consult.parser import guided_intake_agent, input_guard, intake_agent
from doctor_agent.consult.planner import (
    answer_composer_agent,
    emergency_response_agent,
    expert_agents,
    output_safety_guard,
)
from doctor_agent.consult.triage import department_router_agent, safety_triage_agent
from doctor_agent.context_budget import context_budget_manager
from doctor_agent.evaluation import evaluation_harness
from doctor_agent.follow_up import follow_up_planner_agent
from doctor_agent.memory.memory import memory_retrieve_agent, memory_write_guard
from doctor_agent.rag.hybrid import medical_hybrid_retriever, search_router_agent
from doctor_agent.rag.network import network_medical_search_agent
from doctor_agent.rag.resolver import evidence_fusion_agent, web_evidence_cleaner


def build_graph():
    graph = StateGraph(MedicalAgentState)
    nodes = {
        "input_guard": input_guard,
        "intake": intake_agent,
        "guided_intake": guided_intake_agent,
        "safety_triage": safety_triage_agent,
        "emergency_response": emergency_response_agent,
        "memory_retrieve": memory_retrieve_agent,
        "department_router": department_router_agent,
        "search_router": search_router_agent,
        "network_medical_search": network_medical_search_agent,
        "medical_retrieval": medical_hybrid_retriever,
        "web_evidence_cleaner": web_evidence_cleaner,
        "evidence_fusion": evidence_fusion_agent,
        "expert_agents": expert_agents,
        "context_budget": context_budget_manager,
        "answer_composer": answer_composer_agent,
        "output_safety": output_safety_guard,
        "follow_up": follow_up_planner_agent,
        "memory_write": memory_write_guard,
        "evaluation": evaluation_harness,
    }
    for name, func in nodes.items():
        graph.add_node(name, RunnableLambda(func))
    graph.set_entry_point("input_guard")

    graph.add_edge("input_guard", "memory_retrieve")
    graph.add_edge("memory_retrieve", "intake")
    graph.add_conditional_edges("intake", route_after_intake, {"ask_more": "guided_intake", "triage": "safety_triage"})
    graph.add_edge("guided_intake", "answer_composer")
    graph.add_conditional_edges("safety_triage", route_after_triage, {"emergency": "emergency_response", "continue": "department_router"})
    graph.add_edge("emergency_response", "output_safety")
    graph.add_edge("department_router", "search_router")
    graph.add_edge("search_router", "network_medical_search")
    graph.add_edge("network_medical_search", "medical_retrieval")
    graph.add_edge("medical_retrieval", "web_evidence_cleaner")
    graph.add_edge("web_evidence_cleaner", "evidence_fusion")
    graph.add_edge("evidence_fusion", "expert_agents")
    graph.add_edge("expert_agents", "context_budget")
    graph.add_edge("context_budget", "answer_composer")
    graph.add_edge("answer_composer", "output_safety")
    graph.add_edge("output_safety", "follow_up")
    graph.add_edge("follow_up", "memory_write")
    graph.add_edge("memory_write", "evaluation")
    graph.add_edge("evaluation", END)
    return graph.compile()


def route_after_intake(state: MedicalAgentState) -> str:
    if state.get("structured_case", {}).get("missing_slots") and not state.get("semantic_safety", {}).get("medical_red_flags"):
        return "ask_more"
    return "triage"


def route_after_triage(state: MedicalAgentState) -> str:
    if state.get("risk_assessment", {}).get("risk_level") == "emergency":
        return "emergency"
    return "continue"


def run_case(case_path: Path, knowledge_path: Path) -> dict[str, Any]:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    return run_payload(case, knowledge)


def run_payload(case: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    app = build_graph()
    return app.invoke(
        {
            "session_id": case.get("session_id", "demo-session"),
            "user_id": case.get("user_id", "demo-user"),
            "patient_id": case.get("patient_id") or case.get("profile", {}).get("patient_id") or "default-patient",
            "raw_message": case["message"],
            "profile": case.get("profile", {}),
            "history": case.get("history", []),
            "knowledge_base": knowledge,
            "trace": [],
        }
    )
