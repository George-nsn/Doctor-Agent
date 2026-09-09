from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import Any

# pyright: reportMissingImports=false
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from doctor_agent.common import PROJECT_ROOT


def _parse_result(result: Any) -> list[dict[str, Any]]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        value = structured.get("result", structured)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    for content in getattr(result, "content", []):
        text = getattr(content, "text", None)
        if not text:
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        if isinstance(value, dict) and isinstance(value.get("result"), list):
            return [dict(item) for item in value["result"] if isinstance(item, dict)]
    return []


async def call_medical_tool(tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "doctor_agent.mcp.server"],
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                raise RuntimeError(f"MCP tool failed: {tool_name}")
            return _parse_result(result)


def call_medical_tool_sync(tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return asyncio.run(call_medical_tool(tool_name, arguments))
