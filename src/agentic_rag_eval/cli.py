from __future__ import annotations

import argparse
import os
from pathlib import Path

from .models import read_queries
from .rag_clients import HttpRagClient, MockRagClient
from .reporting import write_outputs
from .runner import EvaluationRunner
from .token_budget import pack_context_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an Agentic RAG evaluation harness.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a query set against a mock or HTTP RAG client.")
    run_parser.add_argument("--queries", type=Path, required=True, help="JSONL query set path.")
    run_parser.add_argument("--out", type=Path, required=True, help="Output report directory.")
    run_parser.add_argument("--mock", type=Path, help="Mock response JSON path.")
    run_parser.add_argument("--endpoint", default=os.getenv("RAG_ENDPOINT"), help="HTTP RAG endpoint.")
    run_parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")

    pack_parser = subparsers.add_parser("pack-context", help="Pack medical context under a token budget.")
    pack_parser.add_argument("--input", type=Path, required=True, help="Input JSON context path.")
    pack_parser.add_argument("--out", type=Path, required=True, help="Output packed context JSON path.")
    pack_parser.add_argument("--budget", type=int, default=2000, help="Total token budget.")
    pack_parser.add_argument("--cache-dir", type=Path, help="Optional L2 disk cache directory for packed context and compressed knowledge.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        queries = read_queries(args.queries)
        if args.mock:
            client = MockRagClient(args.mock)
        elif args.endpoint:
            client = HttpRagClient(args.endpoint, timeout_seconds=args.timeout)
        else:
            parser.error("Provide --mock or --endpoint/RAG_ENDPOINT.")
        results = EvaluationRunner(client).run(queries)
        write_outputs(results, args.out)
        print(f"Wrote {len(results)} evaluation results to {args.out}")
        return 0
    if args.command == "pack-context":
        result = pack_context_file(args.input, args.out, total_budget=args.budget, cache_dir=args.cache_dir)
        cache = result.get("cache", {})
        cache_info = f", cache={cache.get('level', 'none')}" if cache else ""
        print(f"Packed context to {args.out} ({result['token_estimate']}/{result['budget']['total']} estimated tokens{cache_info})")
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2
