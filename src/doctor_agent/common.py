from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, TypedDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MedicalAgentState(TypedDict, total=False):
    session_id: str
    user_id: str
    patient_id: str
    raw_message: str
    sanitized_message: str
    profile: dict[str, Any]
    history: list[dict[str, str]]
    knowledge_base: dict[str, Any]
    history_episodes: list[dict[str, Any]]
    semantic_safety: dict[str, Any]
    input_guard: dict[str, Any]
    linguistic_analysis: dict[str, Any]
    structured_case: dict[str, Any]
    guided_questions: list[str]
    risk_assessment: dict[str, Any]
    memory_context: dict[str, Any]
    selected_experts: list[str]
    expert_notes: list[dict[str, Any]]
    tool_plan: dict[str, Any]
    tool_events: list[dict[str, Any]]
    web_evidence: list[dict[str, Any]]
    retrieved_evidence: list[dict[str, Any]]
    vector_store_status: dict[str, Any]
    clean_evidence: list[dict[str, Any]]
    dropped_evidence: list[dict[str, Any]]
    fused_evidence: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    expert_analyses: list[dict[str, Any]]
    packed_context: dict[str, Any]
    final_answer: str
    llm_generation: dict[str, Any]
    output_safety: dict[str, Any]
    safety_review: dict[str, Any]
    follow_up_plan: dict[str, Any]
    memory_write: dict[str, Any]
    memory_audit: dict[str, Any]
    trace: list[str]
    evaluation_summary: dict[str, Any]


def contains_any(text: str, candidates: list[str]) -> bool:
    return any(c in text for c in candidates)


def is_negated(text: str, target: str, window: int = 6) -> bool:
    idx = text.find(target)
    if idx == -1:
        return False
    prefix = text[max(0, idx - window) : idx]
    negations = ["无", "没", "没有", "未见", "未出现", "并未", "不伴", "不显", "否认"]
    return any(neg in prefix for neg in negations)


def trace(state: MedicalAgentState, node_name: str, detail: str) -> list[str]:
    current = list(state.get("trace", []))
    current.append(f"{node_name}: {detail}")
    return current
