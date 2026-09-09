from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph

from .judges import (
    classify_error,
    score_answer_relevance,
    score_context_relevance,
    score_faithfulness,
    suggest_improvement,
)
from .models import EvalQuery, EvaluationResult, RagResponse
from .rag_clients import RagClient


class EvaluationState(TypedDict, total=False):
    query: EvalQuery
    response: RagResponse
    context_relevance: float
    faithfulness: float
    answer_relevance: float
    error_type: str
    improvement_suggestion: str
    result: EvaluationResult
    trace: list[str]


def _append_trace(state: EvaluationState, step: str) -> list[str]:
    return [*state.get("trace", []), step]


def build_evaluation_graph(rag_client: RagClient):
    """Build the LangGraph workflow for one RAG evaluation case."""

    def prepare_query(state: EvaluationState) -> EvaluationState:
        query = state["query"]
        return {"query": query, "trace": _append_trace(state, "prepare_query")}

    def call_rag(state: EvaluationState) -> EvaluationState:
        response = rag_client.ask(state["query"])
        return {"response": response, "trace": _append_trace(state, "call_rag")}

    def judge_evidence(state: EvaluationState) -> EvaluationState:
        response = state["response"]
        return {
            "context_relevance": score_context_relevance(state["query"], response),
            "faithfulness": score_faithfulness(response),
            "trace": _append_trace(state, "judge_evidence"),
        }

    def judge_answer(state: EvaluationState) -> EvaluationState:
        return {
            "answer_relevance": score_answer_relevance(state["query"], state["response"]),
            "trace": _append_trace(state, "judge_answer"),
        }

    def optimize_case(state: EvaluationState) -> EvaluationState:
        error_type = classify_error(
            state["response"],
            state["context_relevance"],
            state["faithfulness"],
            state["answer_relevance"],
        )
        return {
            "error_type": error_type,
            "improvement_suggestion": suggest_improvement(error_type),
            "trace": _append_trace(state, "optimize_case"),
        }

    def finalize_result(state: EvaluationState) -> EvaluationState:
        error_type = state["error_type"]
        result = EvaluationResult(
            query=state["query"],
            response=state["response"],
            context_relevance=state["context_relevance"],
            faithfulness=state["faithfulness"],
            answer_relevance=state["answer_relevance"],
            success=error_type == "none",
            error_type=error_type,
            improvement_suggestion=state["improvement_suggestion"],
        )
        return {"result": result, "trace": _append_trace(state, "finalize_result")}

    graph = StateGraph(EvaluationState)
    graph.add_node("prepare_query", RunnableLambda(prepare_query))
    graph.add_node("call_rag", RunnableLambda(call_rag))
    graph.add_node("judge_evidence", RunnableLambda(judge_evidence))
    graph.add_node("judge_answer", RunnableLambda(judge_answer))
    graph.add_node("optimize_case", RunnableLambda(optimize_case))
    graph.add_node("finalize_result", RunnableLambda(finalize_result))

    graph.set_entry_point("prepare_query")
    graph.add_edge("prepare_query", "call_rag")
    graph.add_edge("call_rag", "judge_evidence")
    graph.add_edge("judge_evidence", "judge_answer")
    graph.add_edge("judge_answer", "optimize_case")
    graph.add_edge("optimize_case", "finalize_result")
    graph.add_edge("finalize_result", END)
    return graph.compile()


class LangGraphEvaluationWorkflow:
    def __init__(self, rag_client: RagClient):
        self.app = build_evaluation_graph(rag_client)

    def invoke(self, query: EvalQuery) -> EvaluationResult:
        state: dict[str, Any] = self.app.invoke({"query": query, "trace": []})
        return state["result"]
