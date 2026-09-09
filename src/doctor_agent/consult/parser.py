from __future__ import annotations

import re

from doctor_agent.common import MedicalAgentState, contains_any, is_negated, trace
from doctor_agent.nlp.linker import analyze_medical_text
from doctor_agent.safety_semantics import red_flag_canonicals, semantic_safety_scan


def input_guard(state: MedicalAgentState) -> MedicalAgentState:
    raw = str(state.get("raw_message", ""))
    semantic = semantic_safety_scan(raw)
    sanitized = semantic["sanitized_text"]
    risk = semantic["input_risk"]
    return {
        "semantic_safety": semantic,
        "input_guard": {
            "input_risk": risk,
            "blocked_instructions": semantic["blocked_spans"],
            "detected_signals": semantic["input_signals"],
            "sanitized_user_message": sanitized,
            "next_action": semantic["next_action"],
        },
        "sanitized_message": sanitized,
        "trace": trace(state, "InputGuard", f"risk={risk}"),
    }


def intake_agent(state: MedicalAgentState) -> MedicalAgentState:
    text = str(state.get("sanitized_message", state.get("raw_message", "")))
    dictionary = state.get("knowledge_base", {}).get("dictionary", {})
    linguistic_analysis = analyze_medical_text(text, dictionary)
    symptoms = red_flag_canonicals(text)
    for symptom in ["右下腹痛", "腹痛", "胸痛", "出汗", "喘不上气", "恶心", "发热", "便血", "呕吐"]:
        if symptom in text and not is_negated(text, symptom) and symptom not in symptoms:
            symptoms.append(symptom)
    if "右下腹" in text and "痛" in text and "右下腹痛" not in symptoms and not is_negated(text, "右下腹"):
        symptoms.append("右下腹痛")
    if ("肚子疼" in text or "肚子痛" in text) and "腹痛" not in symptoms and not is_negated(text, "肚子"):
        symptoms.append("腹痛")
    if "胸口压榨痛" in text and "胸痛" not in symptoms:
        symptoms.append("胸痛")
    pain_score = None
    score_match = re.search(r"(\d+)\s*分", text)
    if score_match:
        pain_score = f"{score_match.group(1)}/10"
    medication_effect = None
    if "没什么效果" in text or "无效" in text:
        medication_effect = "no_effect"
    medication_taken = ["止痛药"] if "止痛药" in text or "止疼药" in text else []
    missing = []
    if not any(symptom.endswith("痛") or symptom.endswith("疼") for symptom in symptoms):
        missing.append("pain_location")
    if not pain_score and any("痛" in symptom or "疼" in symptom for symptom in symptoms):
        missing.append("pain_severity")
    if not contains_any(text, ["昨晚", "今天", "小时", "天", "第一次"]):
        missing.append("duration_or_onset")
    structured = {
        "chief_complaint": symptoms[0] if symptoms else "unknown",
        "symptoms": symptoms,
        "pain_severity": pain_score,
        "duration": "昨晚开始" if "昨晚" in text else None,
        "medication_trial": {"medications_taken": medication_taken, "effect_after_taking": medication_effect},
        "missing_slots": missing,
    }
    return {
        "linguistic_analysis": linguistic_analysis,
        "structured_case": structured,
        "trace": trace(
            state,
            "IntakeAgent",
            f"nlp={linguistic_analysis['backend']}, symptoms={symptoms}, missing={missing}",
        ),
    }


def guided_intake_agent(state: MedicalAgentState) -> MedicalAgentState:
    missing = state.get("structured_case", {}).get("missing_slots", [])
    questions = []
    if "pain_location" in missing:
        questions.append("疼痛具体在什么位置？")
    if "pain_severity" in missing:
        questions.append("疼痛程度 0-10 分大概几分？")
    if "duration_or_onset" in missing:
        questions.append("疼痛从什么时候开始？是第一次还是以前也有过？")
    if missing:
        questions.append("有没有发热、呕吐、便血、胸闷气短或疼痛越来越重？")
    return {"guided_questions": questions[:4], "trace": trace(state, "GuidedIntakeAgent", f"questions={len(questions[:4])}")}
