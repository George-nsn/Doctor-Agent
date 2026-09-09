from __future__ import annotations

import json

from doctor_agent.common import MedicalAgentState, trace
from doctor_agent.knowledge.graph_store import expand_graph
from doctor_agent.rag.qdrant_store import get_qdrant_store


def medical_hybrid_retriever(state: MedicalAgentState) -> MedicalAgentState:
    kb = state.get("knowledge_base", {})
    message = str(state.get("sanitized_message", state.get("raw_message", "")))
    store = get_qdrant_store()
    formal_count = store.namespace_count("mysql_database")
    if formal_count:
        indexed = 0
        active_namespaces = ["mysql_database"]
    else:
        indexed = store.index_documents(
            list(kb.get("documents", [])),
            namespace="runtime_knowledge",
            replace_namespace=True,
        )
        active_namespaces = ["runtime_knowledge"]
    results = store.search(message, limit=6, namespaces=active_namespaces)

    existing_ids = {str(item.get("id")) for item in results}
    for item in state.get("web_evidence", []):
        if str(item.get("id")) not in existing_ids:
            network_item = dict(item)
            network_item.setdefault("relevance", 0.72)
            network_item["retrieval_path"] = ["mcp_stdio", network_item.get("source_name", "network_api")]
            results.append(network_item)

    graph_hits = expand_graph(message, state.get("structured_case", {}).get("symptoms", []), kb.get("graph", []))
    if graph_hits:
        top_conf = max(float(hit.get("transh_confidence", 0.88)) for hit in graph_hits)
        results.append(
            {
                "id": "neo4j_transh_expansion",
                "title": "Neo4j + TransH 图谱扩展",
                "source_type": "knowledge_graph",
                "evidence_level": "B",
                "trust_score": 0.85,
                "freshness_score": 0.80,
                "relevance": round(float(top_conf), 3),
                "content": "TransH 超平面图谱推理关系：" + json.dumps(graph_hits, ensure_ascii=False),
                "entities": [hit["tail"] for hit in graph_hits],
                "transh_hits_count": len(graph_hits),
            }
        )
    results.sort(key=lambda item: (item.get("relevance", 0), item.get("trust_score", 0)), reverse=True)
    status = {
        "indexed_this_run": indexed,
        "active_namespaces": active_namespaces,
        "formal_knowledge_points": formal_count,
        **store.status(),
    }
    return {
        "retrieved_evidence": results[:8],
        "vector_store_status": status,
        "trace": trace(state, "MedicalHybridRetriever", f"qdrant={len(results[:8])}, transh_hits={len(graph_hits)}, indexed={indexed}"),
    }


def search_router_agent(state: MedicalAgentState) -> MedicalAgentState:
    tools = ["medical_guideline_search", "local_rag_search"]
    if "PharmacistAgent" in state.get("selected_experts", []):
        tools.append("drug_search")
    tools.append("web_search")
    return {"tool_plan": {"tools_to_call": tools, "max_results_per_tool": 3}, "trace": trace(state, "SearchRouterAgent", ",".join(tools))}
