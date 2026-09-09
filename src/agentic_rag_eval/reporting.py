from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean

from .models import EvaluationResult


def write_outputs(results: list[EvaluationResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(results, out_dir / "evaluation_results.jsonl")
    _write_csv(results, out_dir / "metrics.csv")
    _write_markdown(results, out_dir / "report.md")


def _write_jsonl(results: list[EvaluationResult], path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result.to_record(), ensure_ascii=False) + "\n")


def _write_csv(results: list[EvaluationResult], path: Path) -> None:
    fieldnames = [
        "id",
        "category",
        "difficulty",
        "latency_ms",
        "context_relevance",
        "faithfulness",
        "answer_relevance",
        "overall_score",
        "success",
        "error_type",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            record = result.to_record()
            writer.writerow({key: record[key] for key in fieldnames})


def _write_markdown(results: list[EvaluationResult], path: Path) -> None:
    success_count = sum(1 for result in results if result.success)
    avg_latency = round(mean([result.response.latency_ms for result in results]), 2) if results else 0
    avg_score = round(mean([result.overall_score for result in results]), 4) if results else 0

    lines = [
        "# Agentic RAG Evaluation Report",
        "",
        "## Summary",
        "",
        f"- Cases: {len(results)}",
        f"- Success: {success_count}/{len(results)}",
        f"- Average overall score: {avg_score}",
        f"- Average latency: {avg_latency} ms",
        "",
        "## Case Table",
        "",
        "| ID | Category | Score | Latency | Error | Suggestion |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for result in results:
        lines.append(
            "| {id} | {category} | {score} | {latency} | {error} | {suggestion} |".format(
                id=result.query.query_id,
                category=result.query.category,
                score=result.overall_score,
                latency=result.response.latency_ms,
                error=result.error_type,
                suggestion=result.improvement_suggestion.replace("|", "/"),
            )
        )
    lines.extend(["", "## Interview Notes", ""])
    lines.append("- Explain one query from input, retrieval contexts, answer generation, judging, to report aggregation.")
    lines.append("- For failed cases, map the error type to a backend action: query rewrite, rerank, timeout, retry, cache, or logging.")
    lines.append("- Do not claim percentage improvements until a real before/after baseline is measured.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
