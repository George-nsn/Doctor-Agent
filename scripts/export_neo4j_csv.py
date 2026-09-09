from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from doctor_agent.common import PROJECT_ROOT
from doctor_agent.knowledge.database import MySQLConnection, connect_database

DEFAULT_OUT = PROJECT_ROOT / "data" / "neo4j_import"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export reviewed MySQL knowledge graph entities and relationships to Neo4j CSV files.")
    parser.add_argument("--database-url", help="Optional mysql+pymysql:// URL; defaults to MYSQL_DATABASE_URL or MYSQL_* variables.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--status", default="approved", help="Comma-separated statuses: approved,pending,rejected.")
    args = parser.parse_args()
    statuses = [status.strip() for status in args.status.split(",") if status.strip()]
    invalid = sorted(set(statuses) - {"approved", "pending", "rejected"})
    if not statuses or invalid:
        raise SystemExit(f"Invalid --status value(s): {', '.join(invalid) or 'empty'}")

    args.out.mkdir(parents=True, exist_ok=True)
    connection = connect_database(args.database_url)
    try:
        relation_rows = load_relations(connection, statuses)
        entity_ids = {int(row["subject_entity_id"]) for row in relation_rows} | {int(row["object_entity_id"]) for row in relation_rows}
        entity_rows = load_entities(connection, entity_ids)
        write_nodes(args.out / "entities.csv", entity_rows)
        write_relationships(args.out / "relationships.csv", relation_rows)
        print(f"Exported {len(entity_rows)} entities and {len(relation_rows)} relationships")
        print(f"Nodes: {args.out / 'entities.csv'}")
        print(f"Relationships: {args.out / 'relationships.csv'}")
        return 0
    finally:
        connection.close()


def load_relations(connection: MySQLConnection, statuses: list[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("%s" for _ in statuses)
    return list(
        connection.execute(
            f"""
            SELECT
                r.subject_entity_id, r.object_entity_id, r.predicate, r.confidence,
                r.review_status, r.evidence_quote, r.extraction_method, d.document_id,
                d.title AS document_title, d.source_url, c.page_number, c.section_title
            FROM relation_candidates r
            JOIN documents d ON d.document_id = r.document_id
            LEFT JOIN chunks c ON c.chunk_id = r.chunk_id
            WHERE r.review_status IN ({placeholders})
            ORDER BY r.review_status, r.predicate, r.subject_entity_id, r.object_entity_id
            """,
            statuses,
        ).fetchall()
    )


def load_entities(connection: MySQLConnection, entity_ids: set[int]) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    ordered_ids = sorted(entity_ids)
    placeholders = ",".join("%s" for _ in ordered_ids)
    return list(
        connection.execute(
            f"SELECT entity_id, canonical_name, entity_type, language, aliases_json "
            f"FROM entities WHERE entity_id IN ({placeholders}) ORDER BY entity_id",
            ordered_ids,
        ).fetchall()
    )


def write_nodes(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["entity_id:ID(Entity)", "name", "entity_type", "language", "aliases", ":LABEL"])
        for row in rows:
            writer.writerow([row["entity_id"], row["canonical_name"], row["entity_type"], row["language"], row["aliases_json"], sanitize_label(str(row["entity_type"]))])


def write_relationships(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            ":START_ID(Entity)", ":END_ID(Entity)", ":TYPE", "confidence:float", "review_status",
            "evidence_quote", "extraction_method", "document_id:int", "document_title", "source_url",
            "page_number:int", "section_title",
        ])
        for row in rows:
            writer.writerow([
                row["subject_entity_id"], row["object_entity_id"], sanitize_label(str(row["predicate"])),
                row["confidence"], row["review_status"], row["evidence_quote"], row["extraction_method"],
                row["document_id"], row["document_title"], row["source_url"],
                row["page_number"] if row["page_number"] is not None else "", row["section_title"] or "",
            ])


def sanitize_label(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "RELATED_TO"


if __name__ == "__main__":
    raise SystemExit(main())
