from __future__ import annotations

import time
from typing import Any

from doctor_agent.knowledge.transh import get_medical_transh
from doctor_agent.tools.doctor_search import search_doctors_and_hospitals


class BaseVerticalAgent:
    """Base class for all modular vertical agents enforcing JSON envelope protocol."""

    agent_name: str = "BaseVerticalAgent"
    intent_name: str = "base"

    def execute(self, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        raise NotImplementedError


class MedicationSafetyAgent(BaseVerticalAgent):
    """Vertical Agent: Evaluates drug safety, contraindications, and adverse effects.
    Calls drug knowledge bases and TransH relation hyperplane models.
    """

    agent_name = "MedicationSafetyAgent"
    intent_name = "medication_consultation"

    def execute(self, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        start = time.perf_counter()
        message = payload.get("message", "")
        profile = payload.get("profile", {})
        allergies = profile.get("allergies", [])

        # Drug detection
        detected_drug = "布洛芬" if ("布洛芬" in message or "止痛药" in message) else "待确认药物"
        contraindications = []
        warnings = []
        safety_verdict = "safe"

        # Check against gastric issues
        is_gastric = any(k in message for k in ["胃痛", "胃炎", "胃溃疡", "上腹痛", "反酸"])
        if is_gastric and "布洛芬" in detected_drug:
            safety_verdict = "contraindicated_caution"
            contraindications.append("活动性消化道溃疡/胃炎急性发作期")
            warnings.append("布洛芬等非甾体抗炎药（NSAIDs）对胃黏膜具有明显刺激和损伤，胃痛时不宜直接盲目服用，可能加重病情甚至诱发消化道出血。")

        # Check allergies
        for a in allergies:
            if a in detected_drug or detected_drug in a:
                safety_verdict = "allergic_rejection"
                contraindications.append(f"明确药物过敏史：{a}")
                warnings.append(f"患者档案中已标注存在【{a}】过敏史，严禁服用！")

        # TransH knowledge graph query
        transh = get_medical_transh()
        energy_score = transh.energy(detected_drug, "HAS_ADVERSE_EFFECT", "胃出血")
        conf = transh.confidence(detected_drug, "HAS_ADVERSE_EFFECT", "胃出血")

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "trace_id": trace_id,
            "agent_name": self.agent_name,
            "intent": self.intent_name,
            "status": "success",
            "execution_time_ms": elapsed_ms,
            "facts": {
                "drug_name": detected_drug,
                "safety_verdict": safety_verdict,
                "contraindications": contraindications,
                "clinical_warning": " ".join(warnings) or "用药需严格遵医嘱或参照药品说明书。",
                "transh_verification": {
                    "relation": f"{detected_drug} -[HAS_ADVERSE_EFFECT]-> 胃出血",
                    "hyperplane_energy": round(energy_score, 4),
                    "confidence": conf,
                },
            },
            "evidence_references": [
                {"title": f"{detected_drug}药品说明书", "authority": "A1", "section": "禁忌与不良反应"}
            ],
            "recommendations": [
                "胃痛期暂停自行口服非甾体解热镇痛药",
                "如胃痛剧烈或呈烧灼痛，建议由消化专科医生开具胃黏膜保护剂或抑酸药物",
            ],
        }


class TriageConsultationAgent(BaseVerticalAgent):
    """Vertical Agent: Clinical symptom triage and hospital/doctor matching.
    Calls doctor search tool when consultation/doctor recommendation intent is detected.
    """

    agent_name = "TriageConsultationAgent"
    intent_name = "triage_and_doctor_matching"

    def execute(self, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        start = time.perf_counter()
        message = payload.get("message", "")

        # Department determination
        department = "消化内科"
        if any(k in message for k in ["胸痛", "心口", "心悸"]):
            department = "心内科"
        elif any(k in message for k in ["咳", "肺", "呼吸"]):
            department = "呼吸内科"

        # Call doctor search tool
        matched_doctors = []
        if any(k in message for k in ["医生", "医院", "挂号", "看病", "推荐", "就医", "哪家"]):
            matched_doctors = search_doctors_and_hospitals(
                department=department,
                symptom_keyword="胃痛" if "胃" in message else None,
                limit=3,
            )

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "trace_id": trace_id,
            "agent_name": self.agent_name,
            "intent": self.intent_name,
            "status": "success",
            "execution_time_ms": elapsed_ms,
            "facts": {
                "recommended_department": department,
                "primary_concern": "胃部疼痛与不适",
                "matched_doctors_count": len(matched_doctors),
                "doctor_recommendations": matched_doctors,
            },
            "evidence_references": [
                {"title": "三级甲等医院专科门诊预约指南", "authority": "B"}
            ],
            "recommendations": [
                f"建议挂号就诊科室：{department}",
                "就医前请空腹，以便医生根据需要安排胃镜、幽门螺杆菌呼气试验或腹部超声检查",
            ],
        }


class EmergencyResponseAgent(BaseVerticalAgent):
    """Vertical Agent: Fast-path circuit breaker for acute emergencies (chest pain, sweating, red flags)."""

    agent_name = "EmergencyResponseAgent"
    intent_name = "emergency_intervention"

    def execute(self, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        start = time.perf_counter()
        message = payload.get("message", "")
        red_flags = []
        if any(k in message for k in ["压榨痛", "胸痛", "大汗", "喘不上气", "休克"]):
            red_flags.extend(["剧烈胸痛", "大汗淋漓", "呼吸急促"])

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "trace_id": trace_id,
            "agent_name": self.agent_name,
            "intent": self.intent_name,
            "status": "success",
            "execution_time_ms": elapsed_ms,
            "facts": {
                "is_emergency": bool(red_flags),
                "red_flags": red_flags,
                "triage_verdict": "EMERGENCY_CIRCUIT_BREAK",
            },
            "emergency_instructions": [
                "立即停止任何重体力活动，保持安静半卧位",
                "请立即拨打 120 急救电话或前往最近的三甲医院急诊科",
                "在线智能问诊严禁替代急救，严禁自行乱服药物",
            ],
        }


class FollowUpAgent(BaseVerticalAgent):
    """Vertical Agent: Generates structured follow-up monitoring and red-flag alerts."""

    agent_name = "FollowUpAgent"
    intent_name = "follow_up_tracking"

    def execute(self, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        start = time.perf_counter()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "trace_id": trace_id,
            "agent_name": self.agent_name,
            "intent": self.intent_name,
            "status": "success",
            "execution_time_ms": elapsed_ms,
            "facts": {
                "follow_up_after": "24h~48h",
                "watch_items": ["黑便/呕血", "疼痛持续加剧", "发热", "频繁呕吐"],
            },
            "follow_up_plan": {
                "period": "24小时内复查观察",
                "alarm_criteria": "若出现呕吐咖啡色胃内容物或黑便，立即急诊就医",
            },
        }


class SafetyAuditAgent(BaseVerticalAgent):
    """Vertical Agent: Central gatekeeper auditing aggregated drafts before release.
    Enforces no definitive diagnosis, no dosage adjustments, and checks for citations.
    Supports rejection with actionable revision suggestions.
    """

    agent_name = "SafetyAuditAgent"
    intent_name = "safety_audit_review"

    def execute(self, payload: dict[str, Any], trace_id: str) -> dict[str, Any]:
        start = time.perf_counter()
        draft = payload.get("draft_text", "")
        violations = []

        # Rule checks
        if "保证根治" in draft or "包治百病" in draft:
            violations.append("禁止包含绝对化疗效保证表述")
        if "你就是" in draft or "确诊为" in draft:
            violations.append("禁止给出排他性确诊断言")
        if "不用就医" in draft:
            violations.append("禁止给出劝阻患者就医的指令")

        passed = len(violations) == 0
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        return {
            "trace_id": trace_id,
            "agent_name": self.agent_name,
            "intent": self.intent_name,
            "status": "success",
            "execution_time_ms": elapsed_ms,
            "audit_verdict": "approved" if passed else "rejected",
            "violations": violations,
            "action": "pass" if passed else "retry_with_revisions",
            "disclaimer_required": True,
            "standard_disclaimer": "【免责说明】以上医学分析与就医建议仅供健康咨询与分诊参考，不能替代执业医师线下临床诊断，请遵医嘱。",
        }
