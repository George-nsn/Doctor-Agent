from __future__ import annotations

from typing import Any

from doctor_agent.common import MedicalAgentState, trace
from doctor_agent.memory.store import MedicalMemoryStore
from doctor_agent.nlp.encoder import get_medical_encoder


def memory_retrieve_agent(state: MedicalAgentState) -> MedicalAgentState:
    user_id = str(state.get("user_id") or "demo-user").strip()
    # Support patient_id directly on state or embedded in profile
    patient_id = str(
        state.get("patient_id")
        or state.get("profile", {}).get("patient_id")
        or "default-patient"
    ).strip()
    session_id = str(state.get("session_id") or "demo-session").strip()

    store = MedicalMemoryStore.get_default_store()

    # 1. Session tenant verification: ensure session is not bound to a different user/patient
    session_check = store.bind_and_validate_session(session_id, user_id, patient_id)
    if not session_check.get("valid", True):
        # Session collision detected across patients/users!
        # Enforce memory cleanliness: rebind to current patient and log warning
        store.log_audit(
            "session_tenant_conflict",
            user_id,
            patient_id,
            session_id,
            "rebound",
            f"Session had collision with {session_check.get('bound_to')}; cleanly rebound to current entity",
        )

    # 2. Retrieve isolated profile strictly for (user_id, patient_id)
    incoming_profile = state.get("profile", {})
    verified_profile = store.get_or_create_profile(user_id, patient_id, incoming_profile)

    # 3. Retrieve historical episodes strictly for (user_id, patient_id)
    episodes = store.get_episodes(user_id, patient_id, limit=5)
    recalled_cold_history: list[dict[str, Any]] = []
    if store.cold_dialogue_count(user_id, patient_id) > 0:
        question = str(state.get("sanitized_message", state.get("raw_message", ""))).strip()
        if question:
            query_embedding = get_medical_encoder().embed_query(question)
            recalled_cold_history = store.recall_cold_dialogue(
                user_id,
                patient_id,
                query_embedding,
                similarity_threshold=0.70,
                top_k=2,
            )

    isolation_key = f"{user_id}#{patient_id}"
    memory_context = {
        "user_id": user_id,
        "patient_id": patient_id,
        "session_id": session_id,
        "profile": verified_profile,
        "episodes": episodes,
        "recalled_cold_history": recalled_cold_history,
        "isolation_key": isolation_key,
        "session": state.get("structured_case", {}),
    }

    audit_info = {
        "isolation_status": "clean",
        "tenant": isolation_key,
        "episodes_loaded": len(episodes),
        "session_valid": session_check.get("valid", True),
    }

    return {
        "patient_id": patient_id,
        "profile": verified_profile,
        "history_episodes": episodes,
        "recalled_cold_history": recalled_cold_history,
        "memory_context": memory_context,
        "memory_audit": audit_info,
        "trace": trace(
            state,
            "MemoryRetrieveAgent",
            f"loaded clean memory for [{isolation_key}] with {len(episodes)} episodes",
        ),
    }


def memory_write_guard(state: MedicalAgentState) -> MedicalAgentState:
    user_id = str(state.get("user_id") or "demo-user").strip()
    patient_id = str(state.get("patient_id") or "default-patient").strip()
    session_id = str(state.get("session_id") or "demo-session").strip()
    expected_isolation_key = f"{user_id}#{patient_id}"

    mem_ctx = state.get("memory_context", {})
    actual_isolation_key = mem_ctx.get("isolation_key")

    store = MedicalMemoryStore.get_default_store()

    # Zero-trust memory write guard: prevent cross-tenant writes if context was tainted
    if actual_isolation_key and actual_isolation_key != expected_isolation_key:
        store.log_audit(
            "memory_write_rejected",
            user_id,
            patient_id,
            session_id,
            "rejected",
            f"Isolation key mismatch: state is {expected_isolation_key} but memory_context is {actual_isolation_key}",
        )
        memory = {
            "episode_summary": {},
            "security_review": "rejected",
            "reason": "cross_tenant_memory_taint_detected",
        }
        return {
            "memory_write": memory,
            "trace": trace(state, "MemoryWriteGuard", "REJECTED: cross-tenant taint detected"),
        }

    sanitized_message = str(state.get("sanitized_message", state.get("raw_message", "")))
    risk_level = str(state.get("risk_assessment", {}).get("risk_level", "unknown"))
    red_flags = list(state.get("risk_assessment", {}).get("red_flags", []))
    follow_up = state.get("follow_up_plan", {})

    summary_text = f"用户咨询：{sanitized_message}；风险等级：{risk_level}。"
    if red_flags:
        summary_text += f" 红旗征：{', '.join(red_flags)}。"

    # Persist episode strictly under (user_id, patient_id)
    episode_record = store.record_episode(
        user_id=user_id,
        patient_id=patient_id,
        session_id=session_id,
        summary=summary_text,
        risk_level=risk_level,
        red_flags=red_flags,
        follow_up=follow_up,
    )

    memory = {
        "episode_summary": {
            "episode_id": episode_record["episode_id"],
            "summary": summary_text,
            "follow_up": follow_up,
        },
        "profile_updates": [],
        "security_review": "passed",
        "isolation_key": expected_isolation_key,
    }

    return {
        "memory_write": memory,
        "trace": trace(state, "MemoryWriteGuard", f"clean episode recorded for [{expected_isolation_key}]"),
    }
