from __future__ import annotations

from collections import Counter
import re

from .models import EvalQuery, EvaluationResult, RagResponse


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for char in text.lower():
        codepoint = ord(char)
        is_cjk = 0x4E00 <= codepoint <= 0x9FFF
        if char.isalnum() and not is_cjk:
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
        if is_cjk:
            tokens.append(char)
    if current:
        tokens.append("".join(current))
    return [token for token in tokens if len(token.strip()) > 0]


def _overlap_score(left: str, right: str) -> float:
    left_tokens = Counter(_tokenize(left))
    right_tokens = Counter(_tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = sum((left_tokens & right_tokens).values())
    return round(min(overlap / max(sum(left_tokens.values()), 1), 1.0), 4)


def _expected_point_score(answer: str, expected_points: list[str]) -> float:
    if not expected_points:
        return 0.0
    hits = 0
    for point in expected_points:
        point_tokens = set(_tokenize(point))
        answer_tokens = set(_tokenize(answer))
        if point_tokens and len(point_tokens & answer_tokens) / len(point_tokens) >= 0.35:
            hits += 1
    return round(hits / len(expected_points), 4)


def score_context_relevance(query: EvalQuery, response: RagResponse) -> float:
    context_text = "\n".join(response.contexts)
    return _overlap_score(query.question, context_text)


def score_faithfulness(response: RagResponse) -> float:
    context_text = "\n".join(response.contexts)
    return _overlap_score(response.answer, context_text)


def score_answer_relevance(query: EvalQuery, response: RagResponse) -> float:
    answer_overlap = _overlap_score(query.question, response.answer)
    expected_overlap = _expected_point_score(response.answer, query.expected_points)
    answer_relevance = round(max(answer_overlap, expected_overlap), 4)
    if re.search(r"sorry|cannot|no mock answer", response.answer, flags=re.IGNORECASE):
        answer_relevance = min(answer_relevance, 0.2)
    return answer_relevance


def classify_error(response: RagResponse, context_relevance: float, faithfulness: float, answer_relevance: float) -> str:
    if response.metadata.get("error"):
        return "rag_api_error"
    if not response.answer.strip():
        return "empty_answer"
    if not response.contexts:
        return "missing_context"
    if context_relevance < 0.25:
        return "low_context_relevance"
    if faithfulness < 0.25:
        return "low_faithfulness"
    if answer_relevance < 0.25:
        return "low_answer_relevance"
    return "none"


def suggest_improvement(error_type: str) -> str:
    suggestions = {
        "rag_api_error": "Add retry, timeout, and structured error logging around the RAG API client.",
        "empty_answer": "Check generation prompt, model provider config, and answer parsing fields.",
        "missing_context": "Expose retrieved chunks from the RAG service and validate top_k retrieval output.",
        "low_context_relevance": "Improve query rewriting, metadata filtering, hybrid search, or reranking.",
        "low_faithfulness": "Tighten generation prompt to cite evidence and reject unsupported claims.",
        "low_answer_relevance": "Add answer relevance judge cases and route vague queries to query rewriting first.",
        "none": "Keep this case as a passing baseline example; use it for regression checks.",
    }
    return suggestions[error_type]


def judge(query: EvalQuery, response: RagResponse) -> EvaluationResult:
    context_relevance = score_context_relevance(query, response)
    faithfulness = score_faithfulness(response)
    answer_relevance = score_answer_relevance(query, response)
    error_type = classify_error(response, context_relevance, faithfulness, answer_relevance)
    return EvaluationResult(
        query=query,
        response=response,
        context_relevance=context_relevance,
        faithfulness=faithfulness,
        answer_relevance=answer_relevance,
        success=error_type == "none",
        error_type=error_type,
        improvement_suggestion=suggest_improvement(error_type),
    )
