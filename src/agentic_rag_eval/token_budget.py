from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SOURCE_PRIORITY = {
    "guideline": 100,
    "drug_label": 90,
    "regulatory": 88,
    "consensus": 80,
    "paper": 70,
    "hospital": 65,
    "local_record": 60,
    "web": 20,
}

EVIDENCE_PRIORITY = {
    "A": 30,
    "B": 20,
    "C": 10,
    "drug_label": 25,
    "unknown": 0,
}


@dataclass(frozen=True)
class TokenBudget:
    total: int = 2000
    knowledge_ratio: float = 0.55
    history_ratio: float = 0.35
    reserved_ratio: float = 0.10

    @property
    def knowledge(self) -> int:
        return int(self.total * self.knowledge_ratio)

    @property
    def history(self) -> int:
        return int(self.total * self.history_ratio)

    @property
    def reserved(self) -> int:
        return max(self.total - self.knowledge - self.history, 0)


class TokenCache:
    """Two-level cache for token packing.

    L1 is an in-process dictionary. L2 is an optional directory of JSON files.
    The cache stores deterministic intermediate outputs only: compressed
    knowledge items and final packed contexts.
    """

    _memory: dict[str, Any] = {}

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, namespace: str, key: str) -> tuple[Any | None, str | None]:
        cache_key = f"{namespace}:{key}"
        if cache_key in self._memory:
            return self._memory[cache_key], "l1_memory"
        if not self.cache_dir:
            return None, None
        path = self.cache_dir / namespace / f"{key}.json"
        if not path.exists():
            return None, None
        value = json.loads(path.read_text(encoding="utf-8"))
        self._memory[cache_key] = value
        return value, "l2_disk"

    def set(self, namespace: str, key: str, value: Any) -> None:
        cache_key = f"{namespace}:{key}"
        self._memory[cache_key] = value
        if not self.cache_dir:
            return
        namespace_dir = self.cache_dir / namespace
        namespace_dir.mkdir(parents=True, exist_ok=True)
        (namespace_dir / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def estimate_tokens(text: str) -> int:
    """Small local token estimator for budget decisions.

    It deliberately overestimates mixed Chinese/English text a little so the
    packed context stays under the target when used with real tokenizers later.
    """

    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    ascii_words = re.findall(r"[A-Za-z0-9_./%+-]+", text)
    punctuation = sum(1 for char in text if char in "，。；：、！？,.!?;:()[]{}")
    return max(int(cjk_chars * 0.75) + len(ascii_words) + int(punctuation * 0.25), 1)


def _compact_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _truncate_by_tokens(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    chars = []
    for char in text:
        chars.append(char)
        if estimate_tokens("".join(chars)) >= max_tokens:
            break
    return "".join(chars).rstrip() + "..."


def _knowledge_score(item: dict[str, Any]) -> float:
    source_type = str(item.get("source_type", "unknown"))
    evidence_level = str(item.get("evidence_level", "unknown"))
    relevance = float(item.get("relevance", item.get("score", 0.0)))
    trust = float(item.get("trust_score", item.get("trust", 0.0)))
    freshness = float(item.get("freshness_score", 0.0))
    return (
        SOURCE_PRIORITY.get(source_type, 0)
        + EVIDENCE_PRIORITY.get(evidence_level, 0)
        + relevance * 100
        + trust * 40
        + freshness * 20
    )


def _compress_knowledge(item: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    """Formats evidence item as a clean, complete clinical chunk without destructive single-line clipping."""
    chunk_id = str(item.get("id", item.get("chunk_id", "chunk_unknown")))
    title = str(item.get("title", ""))
    source_type = str(item.get("source_type", "unknown"))
    evidence_level = str(item.get("evidence_level", "unknown"))
    content = str(item.get("content", ""))

    raw_text = content
    if estimate_tokens(raw_text) > max_tokens:
        raw_text = _truncate_by_tokens(raw_text, max_tokens)

    chunk_repr = {
        "chunk_id": chunk_id,
        "title": title,
        "source_type": source_type,
        "evidence_level": evidence_level,
        "content": raw_text,
    }
    return chunk_repr


def _compress_knowledge_cached(item: dict[str, Any], max_tokens: int, cache: TokenCache | None) -> tuple[dict[str, Any], str]:
    key = _stable_hash({"item": item, "max_tokens": max_tokens})
    if cache:
        cached, level = cache.get("compressed_knowledge_chunk", key)
        if isinstance(cached, dict) and "chunk" in cached:
            return cached["chunk"], str(level)
    chunk = _compress_knowledge(item, max_tokens)
    if cache:
        cache.set("compressed_knowledge_chunk", key, {"chunk": chunk})
    return chunk, "miss"


def _build_profile_card(profile: dict[str, Any]) -> str:
    keep_keys = [
        "age_group",
        "age",
        "sex",
        "allergies",
        "chronic_conditions",
        "long_term_medications",
        "pregnancy_status",
    ]
    compact = {key: profile[key] for key in keep_keys if key in profile and profile[key] not in (None, [], "")}
    return _compact_json(compact) if compact else "{}"


def _extract_dialogue_state_nlp(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Uses medical NLP entity extraction and negation detection to distill dialogue state."""
    full_text = " ".join(str(turn.get("content", "")) for turn in history)

    try:
        from doctor_agent.nlp.linker import analyze_medical_text
        analysis = analyze_medical_text(full_text)
        entities = analysis.get("entities", [])
    except Exception:
        # Fallback keyword scanning
        candidates = ["右下腹痛", "腹痛", "胸痛", "发热", "便血", "恶心", "呕吐", "布洛芬", "头孢", "阿司匹林"]
        entities = [{"normalized": c, "type": "symptom" if "痛" in c or "热" in c or "血" in c else "drug"} for c in candidates if c in full_text]

    # Preserve high-value medication mentions even when the local linker emits only
    # a generic class such as "止痛药".
    known_entities = {str(ent.get("normalized", ent.get("text", ""))) for ent in entities}
    for candidate in ["布洛芬", "头孢", "阿司匹林"]:
        if candidate in full_text and candidate not in known_entities:
            entities.append({"normalized": candidate, "type": "drug"})

    from doctor_agent.common import is_negated

    clinical_slots: list[str] = []
    ruled_out_negatives: list[str] = []
    medication_milestones: list[str] = []

    seen = set()
    for ent in entities:
        norm = str(ent.get("normalized", ent.get("text", ""))).strip()
        etype = ent.get("type", "")
        if not norm or norm in seen:
            continue
        seen.add(norm)

        if is_negated(full_text, norm):
            ruled_out_negatives.append(f"否认/无{norm}")
        else:
            if etype in ("symptom", "disease", "clinical_state"):
                clinical_slots.append(norm)
            elif etype in ("drug", "drug_class"):
                medication_milestones.append(norm)
            else:
                clinical_slots.append(norm)

    for medication in ["布洛芬", "头孢", "阿司匹林"]:
        if medication in full_text and medication not in medication_milestones:
            medication_milestones.append(medication)

    # Timeline milestones
    timeline: list[str] = []
    time_keywords = ["昨晚", "今晨", "两天", "三天", "开始", "好转", "加重", "未见缓解", "无效"]
    for kw in time_keywords:
        if kw in full_text:
            timeline.append(kw)

    return {
        "active_symptoms": clinical_slots[:6],
        "ruled_out_negatives": ruled_out_negatives[:4],
        "medication_trials": medication_milestones[:4],
        "timeline_clues": timeline[:5],
    }


def _pack_history(
    history: list[dict[str, Any]],
    profile: dict[str, Any],
    budget: int,
    recalled_cold_history: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], str, dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    profile_card = _build_profile_card(profile)
    session_state_card: dict[str, Any] = {}
    dropped: list[dict[str, Any]] = []
    protected_recent = [dict(turn) for turn in history[-3:]]
    cold_history = [dict(turn) for turn in history[:-3]]
    total_history_cost = sum(estimate_tokens(str(turn.get("content", ""))) for turn in history)
    compression_triggered = bool(cold_history and total_history_cost >= budget * 0.70)

    if compression_triggered:
        cold_state = _extract_dialogue_state_nlp(cold_history)
        session_state_card = {
            **cold_state,
            "_compression": {
                "triggered": True,
                "threshold_ratio": 0.70,
                "source": "cold_history",
                "cold_turn_count": len(cold_history),
                "protected_turn_count": len(protected_recent),
            },
        }
        dropped.append(
            {
                "type": "history_compression",
                "reason": "history_reached_70pct_budget",
                "triggered_nlp": True,
                "protected_turn_count": len(protected_recent),
                "cold_turn_count": len(cold_history),
            }
        )

    summary_cost = estimate_tokens(_compact_json(session_state_card)) if session_state_card else 0
    protected_cost = sum(estimate_tokens(str(turn.get("content", ""))) for turn in protected_recent)
    recalled = list(recalled_cold_history or [])
    recall_budget = max(int(budget * 0.15), 1)
    recalled_packed: list[dict[str, str]] = []
    recalled_cost = 0
    for turn in recalled:
        candidate = {
            "role": str(turn.get("role", "user")),
            "content": str(turn.get("content", "")),
        }
        cost = estimate_tokens(candidate["content"])
        remaining_recall = recall_budget - recalled_cost
        if remaining_recall <= 0:
            continue
        if cost > remaining_recall:
            candidate["content"] = _truncate_by_tokens(candidate["content"], remaining_recall)
            cost = estimate_tokens(candidate["content"])
        if cost <= 0:
            continue
        recalled_packed.append(candidate)
        recalled_cost += cost

    # Preserve the hot suffix first. Cold raw turns are not returned after compression.
    packed: list[dict[str, str]] = []
    if compression_triggered:
        packed = [
            {"role": str(turn.get("role", "user")), "content": str(turn.get("content", ""))}
            for turn in protected_recent
        ]
    else:
        remaining = max(budget - estimate_tokens(profile_card) - protected_cost, 0)
        cold_packed: list[dict[str, str]] = []
        for turn in reversed(cold_history):
            candidate = {
                "role": str(turn.get("role", "user")),
                "content": str(turn.get("content", "")),
            }
            cost = estimate_tokens(candidate["content"])
            if cost <= remaining:
                cold_packed.append(candidate)
                remaining -= cost
            else:
                dropped.append({"type": "history", "reason": "history_budget_exceeded", "role": candidate["role"]})
        packed = list(reversed(cold_packed)) + [
            {"role": str(turn.get("role", "user")), "content": str(turn.get("content", ""))}
            for turn in protected_recent
        ]

    post_compression_tokens = summary_cost + protected_cost + recalled_cost
    metadata = {
        "compression_triggered": compression_triggered,
        "protected_turn_count": len(protected_recent),
        "cold_turn_count": len(cold_history),
        "post_compression_tokens": post_compression_tokens,
        "vector_store_required": bool(cold_history and post_compression_tokens > budget * 0.85),
        "recalled_cold_history": recalled_packed,
    }
    cold_for_storage = cold_history if metadata["vector_store_required"] else []
    return packed, profile_card, session_state_card, dropped, metadata, cold_for_storage


def pack_context(payload: dict[str, Any], budget: TokenBudget | None = None, cache: TokenCache | None = None) -> dict[str, Any]:
    budget = budget or TokenBudget()
    pack_key = _stable_hash(
        {
            "payload": payload,
            "budget": {
                "total": budget.total,
                "knowledge_ratio": budget.knowledge_ratio,
                "history_ratio": budget.history_ratio,
                "reserved_ratio": budget.reserved_ratio,
                "packing_version": "cold-hot-v1",
            },
        }
    )
    if cache:
        cached, level = cache.get("packed_context", pack_key)
        if isinstance(cached, dict):
            cached["cache"] = {"hit": True, "level": level, "key": pack_key}
            return cached

    similarity_threshold = float(payload.get("similarity_threshold", 0.0))
    max_knowledge_items = int(payload.get("max_knowledge_items", 3))
    question = str(payload.get("question", ""))
    profile = dict(payload.get("profile", {}))
    history = list(payload.get("history", []))
    recalled_cold_history = list(payload.get("recalled_cold_history", []))
    knowledge = list(payload.get("knowledge", []))

    eligible = []
    dropped: list[dict[str, Any]] = []
    for item in knowledge:
        relevance = float(item.get("relevance", item.get("score", 0.0)))
        if relevance < similarity_threshold:
            dropped.append({"type": "knowledge", "id": item.get("id"), "reason": "below_similarity_threshold", "relevance": relevance})
            continue
        eligible.append(item)

    eligible.sort(key=_knowledge_score, reverse=True)
    selected = eligible[:max_knowledge_items]
    for item in eligible[max_knowledge_items:]:
        dropped.append({"type": "knowledge", "id": item.get("id"), "reason": "top_k_limit"})

    per_item_budget = max(int(budget.knowledge / max(len(selected), 1)), 1)
    packed_knowledge = []
    cache_events = []
    for item in selected:
        chunk_data, cache_level = _compress_knowledge_cached(item, per_item_budget, cache)
        cache_events.append({"type": "compressed_knowledge_chunk", "id": item.get("id"), "level": cache_level})
        packed_knowledge.append(
            {
                "id": chunk_data["chunk_id"],
                "title": chunk_data["title"],
                "source_type": chunk_data["source_type"],
                "evidence_level": chunk_data["evidence_level"],
                "tokens": estimate_tokens(chunk_data["content"]),
                "content": chunk_data["content"],
                "chunk": chunk_data,
            }
        )

    (
        packed_history,
        profile_card,
        session_state_card,
        history_dropped,
        history_metadata,
        cold_for_storage,
    ) = _pack_history(history, profile, budget.history, recalled_cold_history)
    dropped.extend(history_dropped)

    packed_context = {
        "question": question,
        "profile_card": profile_card,
        "session_state_card": session_state_card,
        "history": packed_history,
        "recalled_cold_history": history_metadata["recalled_cold_history"],
        "knowledge_chunks": packed_knowledge,
        "knowledge": packed_knowledge,
        "safety_note": "Medical advice must be evidence-backed; do not diagnose or adjust prescription medication.",
    }
    token_estimate = estimate_tokens(_compact_json(packed_context))
    result = {
        "budget": {
            "total": budget.total,
            "knowledge": budget.knowledge,
            "history": budget.history,
            "reserved": budget.reserved,
        },
        "token_estimate": token_estimate,
        "within_budget": token_estimate <= budget.total,
        "packed_context": packed_context,
        "dropped_items": dropped,
        "history_metadata": history_metadata,
        "cold_history_for_vector_store": cold_for_storage,
        "cache": {"hit": False, "level": "miss", "key": pack_key, "events": cache_events},
    }

    if cache:
        cache.set("packed_context", pack_key, result)
    return result


def pack_context_file(input_path: Path, output_path: Path, total_budget: int = 2000, cache_dir: Path | None = None) -> dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    cache = TokenCache(cache_dir) if cache_dir else None
    result = pack_context(payload, TokenBudget(total=total_budget), cache=cache)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
