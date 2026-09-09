from __future__ import annotations

import json
import re
from typing import Any

from doctor_agent.common import contains_any, is_negated
from doctor_agent.llm_api_client import call_llm_from_env


EXTRACTION_SYSTEM_PROMPT = """你是一个严谨的医疗对话记忆结构化提炼引擎。你的任务是从用户的对话历史中提炼出关键的患者医疗事实，并按类别输出为合规的 JSON。
严禁凭空猜测，只能提取用户在对话中明确提到的事实。

输出必须严格为以下 JSON 格式：
{
  "profile_patch": {
    "age": "例如：35岁，若未提及则为null",
    "sex": "male 或 female，若未提及则为null",
    "name": "例如：张三，若未提及则为null"
  },
  "clinical_contraindications": [
    {
      "item": "例如：青霉素、磺胺、头孢",
      "type": "allergy 或 adverse_reaction",
      "reaction": "皮疹、过敏性休克等具体描述",
      "action": "add"
    }
  ],
  "chronic_and_medications": {
    "chronic_add": ["新提及的确诊慢性病，如：高血压、糖尿病"],
    "chronic_remove": ["用户明确表示痊愈或排除的慢病"],
    "medications_add": ["长期服用的药物，如：氨氯地平"],
    "medications_remove": ["已停用的药物"]
  },
  "episode_evolution": {
    "symptoms": ["本次讨论的核心症状，如：右下腹痛、恶心"],
    "trend": "improving 或 worsening 或 persistent 或 resolved",
    "treatment_effect": "服药或处置后的效果，如：布洛芬无效果",
    "summary": "本次就诊对话简要综述（不超过60字）"
  },
  "pending_followup": {
    "needed": true/false,
    "suggested_time": "例如：24h、3天、1周",
    "watch_items": ["发热", "便血", "腹痛加剧"]
  }
}
只输出 JSON 内容，不要包含任何 markdown 解释或多余字符。
"""


def extract_structured_memory_from_dialogue(
    messages: list[dict[str, str]] | str,
    existing_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Uses LLM to extract structured medical memory from dialogue messages.

    If LLM is unavailable or fails, falls back to deterministic rule-based extraction.
    """
    if isinstance(messages, str):
        dialogue_text = messages
    else:
        dialogue_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )

    # 1. Try LLM extraction
    prompt = (
        f"已知患者现有画像: {json.dumps(existing_profile or {}, ensure_ascii=False)}\n\n"
        f"待分析对话记录:\n{dialogue_text}\n\n"
        "请从中提炼出更新的医疗记忆 JSON。"
    )

    extracted_data = None
    llm_meta = {"used": False}

    llm_text, meta = call_llm_from_env(prompt, system=EXTRACTION_SYSTEM_PROMPT, temperature=0.1)
    if llm_text:
        try:
            # Clean possible markdown wrapping like ```json ... ```
            cleaned = llm_text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "profile_patch" in parsed:
                extracted_data = parsed
                llm_meta = meta
                llm_meta["used"] = True
        except Exception:
            extracted_data = None

    # 2. Deterministic Rule-based Fallback if LLM failed or not configured
    if not extracted_data:
        extracted_data = _heuristic_memory_extraction(dialogue_text, existing_profile)
        llm_meta["fallback"] = "heuristic_rule_extractor"

    return {
        "extracted": extracted_data,
        "meta": llm_meta,
    }


def _heuristic_memory_extraction(text: str, existing_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic medical entity and fact extraction as a robust fallback."""
    existing = existing_profile or {}

    # Extract Age
    age = None
    age_match = re.search(r"(\d{1,3})\s*(岁|周岁)", text)
    if age_match:
        age = f"{age_match.group(1)}岁"

    # Extract Sex
    sex = None
    if "女" in text or "女性" in text or "女士" in text:
        sex = "female"
    elif "男" in text or "男性" in text or "先生" in text:
        sex = "male"

    # Allergies
    allergies_add = []
    allergy_candidates = ["青霉素", "头孢", "阿司匹林", "磺胺", "红霉素", "链霉素", "阿莫西林"]
    for a in allergy_candidates:
        if a in text:
            # check if mentioned in an allergic context
            if contains_any(text, ["过敏", "起皮疹", "荨麻疹", "皮疹", "不良反应"]):
                if not is_negated(text, a, window=8) and not is_negated(text, "过敏", window=6):
                    allergies_add.append({"item": a, "type": "allergy", "reaction": "提及过敏", "action": "add"})

    # Chronic conditions
    chronic_add = []
    chronic_candidates = ["高血压", "糖尿病", "高血脂", "冠心病", "慢性胃炎", "哮喘", "脂肪肝", "痛风"]
    for c in chronic_candidates:
        if c in text and not is_negated(text, c, window=8):
            chronic_add.append(c)

    # Long term meds
    meds_add = []
    med_candidates = ["阿司匹林", "二甲双胍", "硝苯地平", "氨氯地平", "缬沙坦", "奥美拉唑", "布洛芬"]
    for m in med_candidates:
        if m in text and contains_any(text, ["长期吃", "每天吃", "一直在吃", "服药", "吃了"]):
            if not is_negated(text, m, window=8):
                meds_add.append(m)

    # Symptoms and evolution
    symptoms = []
    symptom_candidates = ["右下腹痛", "腹痛", "胸痛", "头痛", "发热", "恶心", "便血", "呕吐", "咳嗽"]
    for s in symptom_candidates:
        if s in text and not is_negated(text, s, window=8):
            symptoms.append(s)

    trend = "persistent"
    if "加重" in text or "越来越疼" in text:
        trend = "worsening"
    elif "好转" in text or "减轻" in text or "缓解" in text:
        trend = "improving"

    treatment_effect = None
    if "止痛药无效" in text or "没什么效果" in text or "没有缓解" in text:
        treatment_effect = "服药后未缓解"
    elif "吃药后好多了" in text or "缓解了" in text:
        treatment_effect = "服药后缓解"

    summary = f"就诊对话分析：主诉涉及{', '.join(symptoms[:3]) if symptoms else '一般身体不适'}，病势呈现{trend}。"

    return {
        "profile_patch": {
            "age": age,
            "sex": sex,
            "name": None,
        },
        "clinical_contraindications": allergies_add,
        "chronic_and_medications": {
            "chronic_add": chronic_add,
            "chronic_remove": [],
            "medications_add": meds_add,
            "medications_remove": [],
        },
        "episode_evolution": {
            "symptoms": symptoms,
            "trend": trend,
            "treatment_effect": treatment_effect,
            "summary": summary,
        },
        "pending_followup": {
            "needed": "加重" in text or "红旗" in text or "发热" in text,
            "suggested_time": "24h" if ("发热" in text or "痛" in text) else "48h",
            "watch_items": [s for s in ["发热", "剧痛", "呕吐", "便血"] if s in text],
        },
    }
