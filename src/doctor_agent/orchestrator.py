from __future__ import annotations

import asyncio
import time
from typing import Any
import uuid

from doctor_agent.agents.vertical_agents import (
    BaseVerticalAgent,
    EmergencyResponseAgent,
    FollowUpAgent,
    MedicationSafetyAgent,
    SafetyAuditAgent,
    TriageConsultationAgent,
)
from doctor_agent.memory.store import MedicalMemoryStore


class CentralOrchestrator:
    """Centralized Dispatcher & Modular Agent Orchestrator.

    Core Architecture:
    1. Single Gateway: Ingests requests with unique trace_id, performs tenant isolation.
    2. Central Routing: Decomposes multi-intent requests into parallel/serial execution DAGs.
    3. Modular Vertical Agents: Agents never talk directly to each other; all flow through central orchestrator.
    4. Pure JSON Contract: Enforces structured JSON envelopes with `trace_id` as the leading field.
    5. SLA & Timeout Isolation: Each vertical agent has an independent 3.0s timeout with graceful safety fallback.
    6. Safety Gatekeeper: Aggregated drafts pass through SafetyAuditAgent with single-shot corrective revision loop.
    7. Full Observability: Every step is recorded to SQLite `agent_trace_logs` and JSONL audit files.
    """

    def __init__(self, agent_timeout: float = 3.0):
        self.agent_timeout = agent_timeout
        self.store = MedicalMemoryStore.get_default_store()

        # Pluggable Agent Registry
        self.registry: dict[str, BaseVerticalAgent] = {
            "medication_safety": MedicationSafetyAgent(),
            "triage_consultation": TriageConsultationAgent(),
            "emergency_response": EmergencyResponseAgent(),
            "follow_up": FollowUpAgent(),
            "safety_audit": SafetyAuditAgent(),
        }

    def register_agent(self, key: str, agent: BaseVerticalAgent) -> None:
        self.registry[key] = agent

    def analyze_intents(self, message: str) -> dict[str, Any]:
        """Dual-track Intent Analyzer:

        1. Fast Emergency check.
        2. Multi-intent decomposition (e.g. medication consultation + hospital/doctor search).
        """
        intents = []
        is_emergency = any(k in message for k in ["压榨痛", "胸痛", "大汗", "喘不上气", "休克", "晕厥"])
        if is_emergency:
            intents.append("emergency_response")
            return {
                "intents": intents,
                "is_emergency": True,
                "execution_mode": "emergency_short_circuit",
                "parallel_groups": [["emergency_response"]],
            }

        # Check medication safety intent
        if any(k in message for k in ["药", "吃", "服", "剂量", "布洛芬", "阿司匹林", "抗生素", "止痛"]):
            intents.append("medication_safety")

        # Check triage and doctor recommendation intent
        if any(k in message for k in ["医生", "医院", "挂号", "科室", "胃痛", "肚子疼", "腹痛", "咳嗽", "头痛", "就医", "推荐", "看病", "哪家"]):
            intents.append("triage_consultation")

        # Follow-up intent (if asking about timeline or recovery)
        if any(k in message for k in ["复查", "多长时间", "几天", "随访", "观察", "恶化"]):
            intents.append("follow_up")

        if not intents:
            intents.append("triage_consultation")

        # By default, independent intents can run in parallel
        return {
            "intents": intents,
            "is_emergency": False,
            "execution_mode": "parallel",
            "parallel_groups": [intents],
        }

    async def _execute_agent_with_timeout(
        self,
        agent_key: str,
        payload: dict[str, Any],
        trace_id: str,
        session_id: str,
        user_id: str,
        patient_id: str,
    ) -> dict[str, Any]:
        agent = self.registry.get(agent_key)
        if not agent:
            return {
                "trace_id": trace_id,
                "agent_name": agent_key,
                "status": "not_found",
                "facts": {},
            }

        start_time = time.perf_counter()
        try:
            # Execute in thread with 3.0s timeout isolation
            res = await asyncio.wait_for(
                asyncio.to_thread(agent.execute, payload, trace_id),
                timeout=self.agent_timeout,
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            self.store.log_agent_trace(
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                patient_id=patient_id,
                agent_name=agent.agent_name,
                intent=agent.intent_name,
                status=res.get("status", "success"),
                duration_ms=duration_ms,
                input_data={"message": payload.get("message")},
                output_data=res,
            )
            return res
        except asyncio.TimeoutError:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            fallback = {
                "trace_id": trace_id,
                "agent_name": agent.agent_name,
                "intent": agent.intent_name,
                "status": "timeout_fallback",
                "execution_time_ms": duration_ms,
                "facts": {
                    "fallback_warning": f"{agent.agent_name} 执行超时 ({self.agent_timeout}s)，已启用通用安全兜底建议。"
                },
                "recommendations": ["建议及时前往正规医院专科门诊进行线下体检或咨询。"],
            }
            self.store.log_agent_trace(
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                patient_id=patient_id,
                agent_name=agent.agent_name,
                intent=agent.intent_name,
                status="timeout_fallback",
                duration_ms=duration_ms,
                input_data={"message": payload.get("message")},
                output_data=fallback,
            )
            return fallback

    def aggregate_responses(
        self,
        intent_plan: dict[str, Any],
        agent_results: dict[str, dict[str, Any]],
        message: str,
        profile: dict[str, Any],
    ) -> str:
        """Central Aggregator: Logically joins pure JSON facts into a coherent, cited medical response."""
        # 1. Emergency takes absolute priority
        if "emergency_response" in agent_results:
            em = agent_results["emergency_response"]
            if em.get("facts", {}).get("is_emergency"):
                flags = "、".join(em["facts"].get("red_flags", []))
                lines = [
                    f"【急危重症红色预警】监测到您描述中存在【{flags}】等极高风险信号！",
                    "请立即停止任何活动，保持安静并即刻拨打 120 急救电话或前往最近三甲医院急诊科！",
                    "在线智能系统严禁替代急诊诊断，请勿自行盲目服药。",
                ]
                return "\n".join(lines)

        sections = []

        # 2. Medication safety findings
        if "medication_safety" in agent_results:
            med = agent_results["medication_safety"]
            facts = med.get("facts", {})
            drug = facts.get("drug_name", "该药物")
            verdict = facts.get("safety_verdict")

            lines = ["【一、用药安全评估】"]
            if verdict == "allergic_rejection":
                lines.append(f"• 严重过敏告警：您存在明确过敏史，严禁使用【{drug}】！")
            elif verdict == "contraindicated_caution":
                lines.append(f"• 禁忌与警示：{facts.get('clinical_warning')}")
            else:
                lines.append(f"• 用药建议：{facts.get('clinical_warning')}")

            recs = med.get("recommendations", [])
            for r in recs:
                lines.append(f"• {r}")
            sections.append("\n".join(lines))

        # 3. Triage & Hospital / Doctor recommendation findings
        if "triage_consultation" in agent_results:
            tri = agent_results["triage_consultation"]
            facts = tri.get("facts", {})
            dept = facts.get("recommended_department", "消化内科")
            docs = facts.get("doctor_recommendations", [])

            lines = ["【二、就诊与医生推荐】", f"• 建议挂号科室：{dept}"]
            if docs:
                lines.append("• 权威专科医生推荐：")
                for d in docs:
                    lines.append(
                        f"  - [{d['hospital']} · {d['hospital_tier']}] {d['doctor_name']} ({d['title']})"
                        f"\n    擅长领域：{'、'.join(d['specialties'][:3])} | 出诊排班：{d['schedule']}"
                    )
            recs = tri.get("recommendations", [])
            for r in recs:
                lines.append(f"• {r}")
            sections.append("\n".join(lines))

        # 4. Follow-up plan
        if "follow_up" in agent_results:
            fol = agent_results["follow_up"]
            facts = fol.get("facts", {})
            lines = [
                "【三、随访观察指征】",
                f"• 重点关注红旗体征：{'、'.join(facts.get('watch_items', []))}",
                f"• 建议复查周期：{facts.get('follow_up_after', '24~48小时')}",
            ]
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    async def dispatch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Main entry point orchestrating request intake, intent decomposition, parallel execution,
        safety gatekeeper review with single-shot retry, and memory persistence.
        """
        start_overall = time.perf_counter()
        trace_id = f"trace-{uuid.uuid4().hex[:12]}"
        message = str(payload.get("message", "")).strip()
        user_id = str(payload.get("user_id", "web-user")).strip()
        patient_id = str(payload.get("patient_id", "patient_self")).strip()
        session_id = str(payload.get("session_id", f"sess-{uuid.uuid4().hex[:8]}")).strip()

        # 1. Tenant Verification & Profile Load
        self.store.bind_and_validate_session(session_id, user_id, patient_id)
        verified_profile = self.store.get_or_create_profile(user_id, patient_id, payload.get("profile", {}))
        payload_with_profile = dict(payload)
        payload_with_profile["profile"] = verified_profile

        # 2. Central Intent Planning
        intent_plan = self.analyze_intents(message)
        active_intents = intent_plan["intents"]

        # 3. Parallel Execution of Independent Vertical Agents
        agent_tasks = [
            self._execute_agent_with_timeout(
                agent_key=intent_key,
                payload=payload_with_profile,
                trace_id=trace_id,
                session_id=session_id,
                user_id=user_id,
                patient_id=patient_id,
            )
            for intent_key in active_intents
        ]
        results_list = await asyncio.gather(*agent_tasks)
        agent_results = {intent_key: res for intent_key, res in zip(active_intents, results_list)}

        # 4. Central Aggregation
        draft_answer = self.aggregate_responses(intent_plan, agent_results, message, verified_profile)

        # 5. Safety Audit Review with Single-Shot Rejection Loop
        audit_agent = self.registry["safety_audit"]
        audit_payload = {"draft_text": draft_answer, "original_message": message}
        audit_res = await self._execute_agent_with_timeout(
            agent_key="safety_audit",
            payload=audit_payload,
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            patient_id=patient_id,
        )

        final_answer = draft_answer
        retry_count = 0
        if audit_res.get("audit_verdict") != "approved":
            # Single-shot corrective retry loop
            retry_count = 1
            violations = "；".join(audit_res.get("violations", []))
            # Append corrective disclaimer and sanitize forbidden terms
            final_answer = (
                draft_answer.replace("保证根治", "可能改善")
                .replace("确诊为", "初步疑似")
                .replace("不用就医", "需线下进一步确诊")
            )
            final_answer += f"\n\n【安全审核修正提示：原草案包含合规警示（{violations}），已自动纠正为保守指导】"

        # Always append standard medical disclaimer
        final_answer += f"\n\n{audit_res.get('standard_disclaimer', '')}"

        # 6. Memory Persistence (Fail-safe update)
        summary_text = f"主诉：{message[:40]}；触发意图：{','.join(active_intents)}"
        episode = self.store.record_episode(
            user_id=user_id,
            patient_id=patient_id,
            session_id=session_id,
            summary=summary_text,
            risk_level="emergency" if intent_plan["is_emergency"] else "standard",
            red_flags=[],
            follow_up={"active_intents": active_intents},
        )

        total_elapsed_ms = round((time.perf_counter() - start_overall) * 1000, 2)
        return {
            "trace_id": trace_id,
            "session_id": session_id,
            "user_id": user_id,
            "patient_id": patient_id,
            "answer": final_answer,
            "intents": active_intents,
            "intent_plan": intent_plan,
            "agent_envelopes": agent_results,
            "safety_audit": audit_res,
            "retry_count": retry_count,
            "execution_time_ms": total_elapsed_ms,
            "memory_episode_id": episode.get("episode_id"),
            "profile": verified_profile,
        }


_default_orchestrator: CentralOrchestrator | None = None


def get_central_orchestrator() -> CentralOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        _default_orchestrator = CentralOrchestrator()
    return _default_orchestrator
