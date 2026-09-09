from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from urllib import request

from .models import EvalQuery, RagResponse


class RagClient(Protocol):
    def ask(self, query: EvalQuery) -> RagResponse:
        """Return an answer and evidence contexts for one query."""


class MockRagClient:
    def __init__(self, mock_path: Path):
        with mock_path.open("r", encoding="utf-8") as file:
            self._responses: dict[str, Any] = json.load(file)

    def ask(self, query: EvalQuery) -> RagResponse:
        started = time.perf_counter()
        payload = self._responses.get(query.query_id) or self._responses.get("default", {})
        latency_ms = int((time.perf_counter() - started) * 1000) + int(payload.get("latency_ms", 12))
        return RagResponse(
            answer=str(payload.get("answer", "No mock answer configured.")),
            contexts=[str(item) for item in payload.get("contexts", [])],
            latency_ms=latency_ms,
            source="mock",
            metadata={"query_id": query.query_id},
        )


class HttpRagClient:
    def __init__(self, endpoint: str, timeout_seconds: float = 30.0):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def ask(self, query: EvalQuery) -> RagResponse:
        started = time.perf_counter()
        body = json.dumps({"question": query.question}).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - keep CLI error records instead of crashing batches.
            latency_ms = int((time.perf_counter() - started) * 1000)
            return RagResponse(
                answer="",
                contexts=[],
                latency_ms=latency_ms,
                source="http",
                metadata={"error": type(exc).__name__, "message": str(exc)},
            )

        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        contexts = data.get("contexts") or data.get("evidence") or data.get("documents") or []
        if isinstance(contexts, str):
            contexts = [contexts]
        latency_ms = int((time.perf_counter() - started) * 1000)
        return RagResponse(
            answer=str(data.get("answer", data.get("response", ""))),
            contexts=[str(item) for item in contexts],
            latency_ms=latency_ms,
            source="http",
            metadata={"status": "ok", "raw_keys": sorted(data.keys())},
        )
