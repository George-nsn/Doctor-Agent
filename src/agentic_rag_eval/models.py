from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalQuery:
    query_id: str
    question: str
    category: str
    difficulty: str
    expected_points: list[str] = field(default_factory=list)
    expected_sources: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalQuery":
        return cls(
            query_id=str(payload["id"]),
            question=str(payload["question"]),
            category=str(payload.get("category", "general")),
            difficulty=str(payload.get("difficulty", "medium")),
            expected_points=[str(item) for item in payload.get("expected_points", [])],
            expected_sources=[str(item) for item in payload.get("expected_sources", [])],
        )


@dataclass(frozen=True)
class RagResponse:
    answer: str
    contexts: list[str]
    latency_ms: int
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationResult:
    query: EvalQuery
    response: RagResponse
    context_relevance: float
    faithfulness: float
    answer_relevance: float
    success: bool
    error_type: str
    improvement_suggestion: str

    @property
    def overall_score(self) -> float:
        return round((self.context_relevance + self.faithfulness + self.answer_relevance) / 3, 4)

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.query.query_id,
            "question": self.query.question,
            "category": self.query.category,
            "difficulty": self.query.difficulty,
            "answer": self.response.answer,
            "contexts": self.response.contexts,
            "latency_ms": self.response.latency_ms,
            "source": self.response.source,
            "context_relevance": self.context_relevance,
            "faithfulness": self.faithfulness,
            "answer_relevance": self.answer_relevance,
            "overall_score": self.overall_score,
            "success": self.success,
            "error_type": self.error_type,
            "improvement_suggestion": self.improvement_suggestion,
        }


def read_queries(path: Path) -> list[EvalQuery]:
    queries: list[EvalQuery] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                queries.append(EvalQuery.from_dict(json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return queries
