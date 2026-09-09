from __future__ import annotations

from agentic_rag_eval.token_budget import TokenBudget, TokenCache, pack_context
from doctor_agent.common import PROJECT_ROOT, MedicalAgentState, trace
from doctor_agent.memory.store import MedicalMemoryStore
from doctor_agent.nlp.encoder import get_medical_encoder


def context_budget_manager(state: MedicalAgentState) -> MedicalAgentState:
    payload = {
        "question": str(state.get("sanitized_message", state.get("raw_message", ""))),
        "profile": state.get("profile", {}),
        "history": state.get("history", []),
        "recalled_cold_history": state.get("recalled_cold_history", []),
        "session_id": str(state.get("session_id") or "demo-session"),
        "user_id": str(state.get("user_id") or "demo-user"),
        "patient_id": str(state.get("patient_id") or "default-patient"),
        "knowledge": state.get("fused_evidence", []),
        "similarity_threshold": 0.0,
        "max_knowledge_items": 6,
    }
    budget_total = int(state.get("context_budget_total", 2000))
    packed = pack_context(payload, TokenBudget(total=budget_total), cache=TokenCache(PROJECT_ROOT / ".cache" / "program-token"))
    cold_turns = packed.get("cold_history_for_vector_store", [])
    if cold_turns:
        encoder = get_medical_encoder()
        embeddings = encoder.embed_documents([str(turn.get("content", "")) for turn in cold_turns])
        cold_turns_with_model = [
            {**turn, "embedding_model": encoder.model_name, "turn_index": index}
            for index, turn in enumerate(cold_turns)
        ]
        store = MedicalMemoryStore.get_default_store()
        store.store_cold_dialogue_vectors(
            user_id=payload["user_id"],
            patient_id=payload["patient_id"],
            session_id=payload["session_id"],
            turns=cold_turns_with_model,
            embeddings=embeddings,
        )
        packed["history_metadata"]["cold_vectors_stored"] = len(cold_turns)

    return {
        "packed_context": packed,
        "trace": trace(
            state,
            "ContextBudgetManager",
            f"tokens={packed['token_estimate']}; hot={packed['history_metadata']['protected_turn_count']}; "
            f"cold={packed['history_metadata']['cold_turn_count']}",
        ),
    }
