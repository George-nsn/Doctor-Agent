from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from doctor_agent.common import PROJECT_ROOT
from doctor_agent.knowledge.database import MySQLConnection, connect_database
from doctor_agent.rag.qdrant_store import get_qdrant_store


INDEXABLE_RIGHTS = {
    "public_domain",
    "open_license",
    "licensed",
    "user_provided_authorized",
    "public_domain_or_record_specific",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Index licence-cleared MySQL medical chunks into Qdrant Local.")
    parser.add_argument("--database-url", help="Optional mysql+pymysql:// URL; defaults to MYSQL_DATABASE_URL or MYSQL_* variables.")
    parser.add_argument("--include-pending-source-review", action="store_true")
    args = parser.parse_args()
    connection = connect_database(args.database_url)
    try:
        documents = load_indexable_chunks(connection, args.include_pending_source_review)
    finally:
        connection.close()
    store = get_qdrant_store()
    try:
        indexed = store.index_documents(documents, namespace="mysql_database", replace_all=True)
        print(json.dumps({"indexable_chunks": len(documents), "indexed": indexed, **store.status()}, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()


def load_indexable_chunks(connection: MySQLConnection, include_pending_source_review: bool = False) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            c.chunk_id, c.content, c.page_number, c.section_title, c.chunk_type,
            d.document_id, d.title, d.document_type, d.published_at, d.version,
            d.evidence_level, d.evidence_grade, d.authority_tier, d.jurisdiction,
            d.rights_status, d.ingestion_mode, d.review_status, d.department,
            d.source_url, d.attribution, s.slug AS source_slug, s.name AS source_name,
            s.source_category, s.publisher
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN sources s ON s.source_id = d.source_id
        ORDER BY c.chunk_id
        """
    ).fetchall()
    entity_map = load_document_entities(connection)
    documents = []
    for row in rows:
        if row["ingestion_mode"] == "metadata_only" or row["rights_status"] not in INDEXABLE_RIGHTS:
            continue
        if not include_pending_source_review and row["review_status"] not in {"source_verified", "approved"}:
            continue
        authority_tier = str(row["authority_tier"])
        documents.append(
            {
                "id": f"mysql_chunk_{row['chunk_id']}",
                "title": row["title"],
                "content": row["content"],
                "source_type": normalize_source_type(str(row["source_category"]), str(row["document_type"])),
                "source_category": row["source_category"],
                "source_slug": row["source_slug"],
                "source_name": row["source_name"],
                "publisher": row["publisher"],
                "source_url": row["source_url"],
                "attribution": row["attribution"],
                "evidence_level": row["evidence_level"],
                "evidence_grade": row["evidence_grade"],
                "authority_tier": authority_tier,
                "jurisdiction": row["jurisdiction"],
                "version": row["version"],
                "published_at": row["published_at"],
                "department": row["department"],
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "page_number": row["page_number"],
                "section_title": row["section_title"],
                "chunk_type": row["chunk_type"],
                "rights_status": row["rights_status"],
                "entities": entity_map.get(int(row["document_id"]), []),
                "trust_score": authority_trust_score(authority_tier),
                "freshness_score": 0.8,
            }
        )
    return documents


def load_document_entities(connection: MySQLConnection) -> dict[int, list[str]]:
    entity_map: dict[int, list[str]] = {}
    rows = connection.execute(
        """
        SELECT de.document_id, e.canonical_name
        FROM document_entities de
        JOIN entities e ON e.entity_id = de.entity_id
        ORDER BY de.document_id, e.canonical_name
        """
    ).fetchall()
    for row in rows:
        entity_map.setdefault(int(row["document_id"]), []).append(str(row["canonical_name"]))
    return {document_id: sorted(set(names)) for document_id, names in entity_map.items()}


def normalize_source_type(source_category: str, document_type: str) -> str:
    if "drug" in source_category or document_type == "drug_label":
        return "drug_label"
    if "guideline" in source_category or document_type in {"clinical_guideline", "clinical_manual", "manual"}:
        return "guideline"
    if "textbook" in source_category or "textbook" in document_type:
        return "medical_textbook"
    return "official_reference"


def authority_trust_score(authority_tier: str) -> float:
    return {"A1": 0.98, "A2": 0.92, "B1": 0.82, "C1": 0.72, "D1": 0.5}.get(authority_tier, 0.5)


if __name__ == "__main__":
    raise SystemExit(main())
