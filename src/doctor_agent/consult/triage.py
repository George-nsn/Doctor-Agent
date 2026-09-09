from __future__ import annotations

from doctor_agent.common import MedicalAgentState, is_negated, trace
from doctor_agent.safety_semantics import red_flag_canonicals


def safety_triage_agent(state: MedicalAgentState) -> MedicalAgentState:
    text = str(state.get("sanitized_message", state.get("raw_message", "")))
    red_flags = red_flag_canonicals(text)
    for flag in ["胸痛", "喘不上气", "呼吸困难", "出汗", "便血", "持续高热", "意识异常", "疼痛越来越重"]:
        if flag in text and not is_negated(text, flag) and flag not in red_flags:
            red_flags.append(flag)
    if "胸口压榨痛" in text and "胸痛" not in red_flags:
        red_flags.append("胸痛")
    pain_score = state.get("structured_case", {}).get("pain_severity")
    high_pain = False
    if isinstance(pain_score, str) and "/" in pain_score:
        try:
            high_pain = int(pain_score.split("/", 1)[0]) >= 7
        except ValueError:
            high_pain = False
    medication_no_effect = state.get("structured_case", {}).get("medication_trial", {}).get("effect_after_taking") == "no_effect"
    risk = (
        "emergency"
        if {"胸痛", "出汗"}.issubset(set(red_flags)) or "喘不上气" in red_flags
        else "medium"
        if red_flags or high_pain or medication_no_effect
        else "low"
    )
    return {
        "risk_assessment": {
            "risk_level": risk,
            "red_flags": red_flags,
            "semantic_red_flags": state.get("semantic_safety", {}).get("medical_red_flags", []),
            "action": "recommend_emergency" if risk == "emergency" else "continue_answer",
        },
        "trace": trace(state, "SafetyTriageAgent", f"risk={risk}"),
    }


def department_router_agent(state: MedicalAgentState) -> MedicalAgentState:
    symptoms = state.get("structured_case", {}).get("symptoms", [])
    experts = ["GeneralPracticeAgent"]
    if any(symptom in symptoms for symptom in ["右下腹痛", "腹痛", "恶心"]):
        experts.append("GastroenterologyAgent")
    if state.get("structured_case", {}).get("medication_trial", {}).get("medications_taken"):
        experts.append("PharmacistAgent")
    if state.get("risk_assessment", {}).get("risk_level") == "emergency":
        experts.append("EmergencyResponseAgent")
    experts = list(dict.fromkeys(experts))
    return {"selected_experts": experts, "trace": trace(state, "DepartmentRouterAgent", ",".join(experts))}
