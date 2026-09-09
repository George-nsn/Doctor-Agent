from __future__ import annotations

# pyright: reportMissingImports=false
from mcp.server.fastmcp import FastMCP

from doctor_agent.mcp.network_medical import openfda_drug_search, pubmed_search

mcp = FastMCP("medical-network-knowledge")


@mcp.tool()
def search_pubmed(query: str, max_results: int = 3) -> list[dict]:
    """Search PubMed/NCBI for medical research evidence."""
    return pubmed_search(query, max_results=max_results)


@mcp.tool()
def search_openfda_drug(drug_name: str, max_results: int = 2) -> list[dict]:
    """Search official openFDA drug label warnings and adverse reactions."""
    return openfda_drug_search(drug_name, max_results=max_results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
