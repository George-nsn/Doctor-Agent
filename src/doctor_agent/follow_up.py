from __future__ import annotations

from doctor_agent.common import MedicalAgentState, trace


def follow_up_planner_agent(state: MedicalAgentState) -> MedicalAgentState:
    plan = {
        "follow_up_needed": state.get("risk_assessment", {}).get("risk_level") != "emergency",
        "follow_up_after": "24h",
        "watch_items": ["pain_severity", "fever", "vomiting", "medication_effect", "red_flags"],
        "red_flags_to_monitor": ["持续加重腹痛", "发热", "反复呕吐", "便血", "无法行走"],
    }
    return {"follow_up_plan": plan, "trace": trace(state, "FollowUpPlannerAgent", "created follow-up plan")}
