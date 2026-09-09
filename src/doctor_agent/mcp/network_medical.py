from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


USER_AGENT = "agentic-rag-eval/0.1 (medical research demo)"

ZH_MEDICAL_TERMS = {
    "右下腹痛": "right lower abdominal pain",
    "腹痛": "abdominal pain",
    "胸痛": "chest pain",
    "呼吸困难": "dyspnea",
    "喘不上气": "dyspnea",
    "发热": "fever",
    "恶心": "nausea",
    "呕吐": "vomiting",
    "便血": "gastrointestinal bleeding",
    "布洛芬": "ibuprofen",
    "止痛药": "analgesics",
    "心肌梗死": "myocardial infarction",
}

DRUG_ALIASES = {
    "布洛芬": "ibuprofen",
    "阿司匹林": "aspirin",
    "奥美拉唑": "omeprazole",
    "对乙酰氨基酚": "acetaminophen",
}


def _get_json(url: str, timeout: int = 15) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_bytes(url: str, timeout: int = 20) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def translate_medical_query(query: str) -> str:
    terms = [
        english
        for chinese, english in ZH_MEDICAL_TERMS.items()
        if chinese in query and chinese not in DRUG_ALIASES and chinese != "止痛药"
    ]
    if terms:
        return " AND ".join(list(dict.fromkeys(terms))[:2])
    return query


def pubmed_search(query: str, max_results: int = 3) -> list[dict[str, Any]]:
    """Search PubMed and return titles/abstract snippets from NCBI E-utilities."""
    translated = translate_medical_query(query)
    params = {
        "db": "pubmed",
        "term": translated,
        "retmode": "json",
        "retmax": max(1, min(max_results, 5)),
        "sort": "relevance",
    }
    email = os.getenv("NCBI_EMAIL")
    api_key = os.getenv("NCBI_API_KEY")
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urlencode(params)
    ids = _get_json(search_url).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    fetch_params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    xml_data = _get_bytes("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode(fetch_params))
    root = ET.fromstring(xml_data)
    results = []
    for article in root.findall(".//PubmedArticle"):
        pmid = article.findtext(".//PMID") or ""
        title_node = article.find(".//ArticleTitle")
        title = "".join(title_node.itertext()) if title_node is not None else "Untitled PubMed article"
        abstracts = ["".join(node.itertext()) for node in article.findall(".//AbstractText")]
        abstract = " ".join(abstracts).strip()
        journal = article.findtext(".//Journal/Title") or "PubMed"
        results.append(
            {
                "id": f"pubmed_{pmid}",
                "title": title,
                "content": abstract[:1800] or title,
                "source_type": "paper",
                "source_name": "PubMed / NCBI",
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "evidence_level": "B",
                "department": "medical_research",
                "trust_score": 0.82,
                "freshness_score": 0.75,
                "entities": [],
                "source_metadata": {"pmid": pmid, "journal": journal, "translated_query": translated},
            }
        )
    return results[:max_results]


def extract_drug_name(query: str) -> str | None:
    for chinese, english in DRUG_ALIASES.items():
        if chinese in query:
            return english
    return None


def openfda_drug_search(drug_name: str, max_results: int = 2) -> list[dict[str, Any]]:
    """Search official FDA drug labeling records."""
    normalized = DRUG_ALIASES.get(drug_name, drug_name).strip()
    if not normalized:
        return []
    search = f'openfda.generic_name:"{normalized}"'
    url = "https://api.fda.gov/drug/label.json?" + urlencode({"search": search, "limit": max(1, min(max_results, 3))})
    payload = _get_json(url)
    results = []
    for index, item in enumerate(payload.get("results", [])):
        openfda = item.get("openfda", {})
        names = openfda.get("generic_name") or openfda.get("brand_name") or [normalized]
        warnings = item.get("warnings") or item.get("warnings_and_cautions") or []
        adverse = item.get("adverse_reactions") or []
        contraindications = item.get("contraindications") or []
        interactions = item.get("drug_interactions") or []
        sections = []
        for label, values in [
            ("Warnings", warnings),
            ("Contraindications", contraindications),
            ("Adverse reactions", adverse),
            ("Drug interactions", interactions),
        ]:
            if values:
                sections.append(f"{label}: {' '.join(str(value) for value in values)[:900]}")
        set_id = str(item.get("set_id") or item.get("id") or index)
        results.append(
            {
                "id": f"openfda_{set_id}",
                "title": f"FDA Drug Label: {', '.join(str(name) for name in names)}",
                "content": "\n".join(sections) or "Official FDA drug label record.",
                "source_type": "drug_label",
                "source_name": "openFDA / FDA SPL",
                "source_url": f"https://api.fda.gov/drug/label.json?search=set_id:{quote(set_id)}",
                "evidence_level": "drug_label",
                "department": "pharmacology",
                "trust_score": 0.94,
                "freshness_score": 0.8,
                "entities": [str(name) for name in names],
                "source_metadata": {"set_id": set_id, "query": normalized},
            }
        )
    return results
