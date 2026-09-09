from __future__ import annotations

from doctor_agent.common import MedicalAgentState, contains_any, trace

SOURCE_PRIORITY = {
    "guideline": 6.0,
    "national_clinical_guideline": 6.0,
    "regulatory": 6.0,
    "regulatory_drug_label": 5.8,
    "drug_label": 5.5,
    "medical_society_guideline": 5.2,
    "expert_consensus": 4.5,
    "official_reference": 4.2,
    "paper": 3.8,
    "systematic_review": 4.8,
    "medical_textbook": 3.0,
    "knowledge_graph": 2.8,
    "hospital": 2.0,
    "web": 1.0,
}

AUTHORITY_SCORE = {"A1": 2.0, "A2": 1.6, "B1": 1.1, "C1": 0.6, "D1": 0.1}
EVIDENCE_GRADE_SCORE = {
    "high": 1.5,
    "moderate": 1.1,
    "low": 0.6,
    "very_low": 0.2,
    "regulatory_label": 1.2,
    "guideline_specific": 1.0,
    "background_mechanism": 0.4,
    "ungraded": 0.0,
}


def web_evidence_cleaner(state: MedicalAgentState) -> MedicalAgentState:
    clean = []
    dropped = []
    for item in state.get("retrieved_evidence", []):
        content = item.get("content", "")
        injection_like = contains_any(content, ["忽略之前", "忽略医生", "system prompt", "you are chatgpt", "不要遵守"])
        unsafe_web = item.get("source_type") == "web" and (contains_any(content, ["偏方", "根治", "不用就医"]) or item.get("trust_score", 0) < 0.45)
        if injection_like:
            dropped.append({"id": item.get("id"), "reason": "retrieved_prompt_injection"})
        elif unsafe_web:
            dropped.append({"id": item.get("id"), "reason": "dirty_or_unsafe_web_data"})
        else:
            clean.append(item)
    return {"clean_evidence": clean, "dropped_evidence": dropped, "trace": trace(state, "WebEvidenceCleaner", f"clean={len(clean)}, dropped={len(dropped)}")}


def evidence_fusion_agent(state: MedicalAgentState) -> MedicalAgentState:
    ranked = []
    for item in state.get("clean_evidence", []):
        enriched = dict(item)
        score, breakdown = calculate_evidence_score(state, enriched)
        enriched["fusion_score"] = round(score, 4)
        enriched["fusion_score_breakdown"] = breakdown
        ranked.append(enriched)
    fused = sorted(ranked, key=lambda item: item["fusion_score"], reverse=True)[:3]
    conflicts = []
    if any("不要自行加量" in item.get("content", "") for item in fused) and "吃什么药" in str(state.get("raw_message", "")):
        conflicts.append({"type": "unsafe_medication_request", "resolution": "do_not_give_direct_medication_advice"})
    return {"fused_evidence": fused, "conflicts": conflicts, "trace": trace(state, "EvidenceFusionAgent", f"fused={len(fused)}, conflicts={len(conflicts)}")}


def calculate_evidence_score(state: MedicalAgentState, item: dict) -> tuple[float, dict[str, float]]:
    source_type = str(item.get("source_type", "web"))
    source_category = str(item.get("source_category", source_type))
    authority_tier = str(item.get("authority_tier", infer_authority_tier(source_type)))
    evidence_grade = str(item.get("evidence_grade", infer_evidence_grade(item))).lower()
    source = SOURCE_PRIORITY.get(source_category, SOURCE_PRIORITY.get(source_type, 1.0))
    authority = AUTHORITY_SCORE.get(authority_tier, 0.0)
    evidence = EVIDENCE_GRADE_SCORE.get(evidence_grade, 0.0)
    relevance = float(item.get("relevance", 0.0)) * 2.0
    trust = float(item.get("trust_score", 0.0))
    freshness = float(item.get("freshness_score", 0.0)) * 0.8
    task = task_specific_boost(state, source_type, source_category)
    breakdown = {
        "source": round(source, 4),
        "authority": round(authority, 4),
        "evidence_grade": round(evidence, 4),
        "relevance": round(relevance, 4),
        "trust": round(trust, 4),
        "freshness": round(freshness, 4),
        "task_specific": round(task, 4),
    }
    return sum(breakdown.values()), breakdown


def task_specific_boost(state: MedicalAgentState, source_type: str, source_category: str) -> float:
    text = str(state.get("sanitized_message", state.get("raw_message", "")))
    medication_query = "PharmacistAgent" in state.get("selected_experts", []) or contains_any(
        text, ["药", "剂量", "禁忌", "不良反应", "相互作用", "孕妇", "老人", "肝功能", "肾功能"]
    )
    diagnosis_query = contains_any(text, ["诊断", "什么病", "标准", "分型", "转诊", "随访", "高危", "红旗"])
    mechanism_query = contains_any(text, ["为什么", "机制", "病理", "生理", "原理"])
    if medication_query and source_type in {"drug_label", "regulatory"}:
        return 2.0
    if medication_query and source_category in {"regulatory_drug_label", "national_regulatory_drug_database"}:
        return 2.0
    if diagnosis_query and source_category in {"national_clinical_guideline", "clinical_guideline"}:
        return 1.5
    if mechanism_query and source_category in {"medical_textbook", "medical_textbook_reference"}:
        return 0.8
    return 0.0


def infer_authority_tier(source_type: str) -> str:
    if source_type in {"guideline", "regulatory", "drug_label"}:
        return "A1"
    if source_type == "official_reference":
        return "A2"
    if source_type in {"paper", "hospital"}:
        return "B1"
    if source_type == "medical_textbook":
        return "C1"
    return "D1"


def infer_evidence_grade(item: dict) -> str:
    if item.get("source_type") == "drug_label":
        return "regulatory_label"
    level = str(item.get("evidence_level", "")).upper()
    return {"A": "high", "B": "moderate", "C": "low"}.get(level, "ungraded")
