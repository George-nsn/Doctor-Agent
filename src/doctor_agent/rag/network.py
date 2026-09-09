from __future__ import annotations

from typing import Any

from doctor_agent.common import MedicalAgentState, trace
from doctor_agent.mcp.client import call_medical_tool_sync
from doctor_agent.mcp.network_medical import extract_drug_name


def network_medical_search_agent(state: MedicalAgentState) -> MedicalAgentState:
    query = str(state.get("sanitized_message", state.get("raw_message", "")))
    evidence: list[dict[str, Any]] = []
    events = []

    try:
        pubmed = call_medical_tool_sync("search_pubmed", {"query": query, "max_results": 3})
        evidence.extend(pubmed)
        events.append({"tool": "search_pubmed", "status": "success", "result_count": len(pubmed), "transport": "mcp_stdio"})
    except Exception as exc:  # noqa: BLE001 - preserve fallback behavior in the graph.
        events.append({"tool": "search_pubmed", "status": "failed", "error": type(exc).__name__, "message": str(exc)})

    drug_name = extract_drug_name(query)
    if drug_name:
        try:
            drug_results = call_medical_tool_sync("search_openfda_drug", {"drug_name": drug_name, "max_results": 2})
            evidence.extend(drug_results)
            events.append({"tool": "search_openfda_drug", "status": "success", "result_count": len(drug_results), "transport": "mcp_stdio"})
        except Exception as exc:  # noqa: BLE001
            events.append({"tool": "search_openfda_drug", "status": "failed", "error": type(exc).__name__, "message": str(exc)})

    return {
        "web_evidence": evidence,
        "tool_events": events,
        "trace": trace(state, "MCPMedicalWebSearch", f"results={len(evidence)}, events={len(events)}"),
    }
