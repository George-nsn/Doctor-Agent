from __future__ import annotations

from .models import EvalQuery, EvaluationResult
from .graph import LangGraphEvaluationWorkflow
from .rag_clients import RagClient


class EvaluationRunner:
    def __init__(self, rag_client: RagClient):
        self.workflow = LangGraphEvaluationWorkflow(rag_client)

    def run(self, queries: list[EvalQuery]) -> list[EvaluationResult]:
        results: list[EvaluationResult] = []
        for query in queries:
            results.append(self.workflow.invoke(query))
        return results
