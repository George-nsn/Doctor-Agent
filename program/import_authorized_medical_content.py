from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from program.ingest_official_medical_sources import (
    chunk_pdf_pages,
    chunk_text,
    extract_pdf_pages,
    index_entities_and_relation_candidates,
    sha256_text,
)
from program.medical_knowledge.database import (
    connect_database,
    database_status,
    replace_chunks,
    upsert_document,
    upsert_drug_monograph,
    upsert_guideline_profile,
    upsert_source,
    upsert_textbook_profile,
)


DEFAULT_REGISTRY = PROJECT_ROOT / "program" / "data" / "knowledge_source_registry.json"
ALLOWED_FULL_TEXT_RIGHTS = {"public_domain", "open_license", "licensed", "user_provided_authorized"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import licence-checked Chinese guidelines, drug labels and medical textbooks from local files or metadata manifests.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--database-url", help="Optional mysql+pymysql:// URL; defaults to MYSQL_DATABASE_URL or MYSQL_* variables.")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    sources = {source["slug"]: source for source in registry.get("sources", [])}
    connection = connect_database(args.database_url)
    imported = {"sources": 0, "documents": 0, "chunks": 0, "relations": 0}
    try:
        source_ids = {}
        for source in sources.values():
            source_ids[source["slug"]] = upsert_source(connection, source)
            imported["sources"] += 1
        for item in manifest.get("documents", []):
            source_slug = str(item["source_slug"])
            if source_slug not in sources:
                raise ValueError(f"Unknown source_slug: {source_slug}")
            validate_import_item(item, sources[source_slug], args.manifest.parent)
            raw_text, chunks, raw_path = load_document_content(item, args.manifest.parent)
            document = build_document(item, sources[source_slug], raw_text, raw_path)
            document_id = upsert_document(connection, source_ids[source_slug], document)
            chunk_ids = replace_chunks(connection, document_id, chunks)
            relations = index_entities_and_relation_candidates(connection, document_id, chunks, chunk_ids) if chunks else 0
            upsert_profile(connection, document_id, item)
            imported["documents"] += 1
            imported["chunks"] += len(chunks)
            imported["relations"] += relations
        connection.commit()
        print(json.dumps({"imported": imported, "database": database_status(connection)}, ensure_ascii=False, indent=2))
        print("Database: MySQL (MYSQL_DATABASE_URL or MYSQL_* environment variables)")
        return 0
    finally:
        connection.close()


def validate_import_item(item: dict[str, Any], source: dict[str, Any], manifest_dir: Path) -> None:
    mode = str(item.get("ingestion_mode", "metadata_only"))
    rights = str(item.get("rights_status", source.get("rights_status", "unknown")))
    if mode == "metadata_only":
        return
    if mode != "full_text":
        raise ValueError(f"Unsupported ingestion_mode for {item.get('external_id')}: {mode}")
    if rights not in ALLOWED_FULL_TEXT_RIGHTS:
        raise ValueError(
            f"Full-text import blocked for {item.get('external_id')}: rights_status={rights}. "
            f"Use metadata_only or provide an allowed rights status and licence proof."
        )
    content_path = item.get("content_path")
    if not content_path or not (manifest_dir / str(content_path)).exists():
        raise ValueError(f"Full-text import requires an existing content_path: {item.get('external_id')}")
    if source.get("ingestion_policy") == "licensed_local_import_only":
        proof = item.get("license_proof_path")
        if not proof or not (manifest_dir / str(proof)).exists():
            raise ValueError(f"Licensed textbook import requires license_proof_path: {item.get('external_id')}")


def load_document_content(item: dict[str, Any], manifest_dir: Path) -> tuple[str, list[dict[str, Any]], str | None]:
    if item.get("ingestion_mode", "metadata_only") == "metadata_only":
        return "", [], None
    path = (manifest_dir / str(item["content_path"])).resolve()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pages = extract_pdf_pages(path, max_pages=0)
        raw_text = "\n\n".join(page["text"] for page in pages if page["text"])
        chunks = chunk_pdf_pages(pages)
    elif suffix in {".md", ".txt"}:
        raw_text = path.read_text(encoding="utf-8-sig")
        chunks = chunk_text(raw_text, max_chars=1800, overlap=180)
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_text = str(payload.get("content") or payload.get("raw_text") or "")
        chunks = chunk_text(raw_text, max_chars=1800, overlap=180)
    else:
        raise ValueError(f"Unsupported content file type: {path.suffix}")
    if not raw_text.strip():
        raise ValueError(f"No extractable text in content_path: {path}")
    try:
        raw_path = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        raw_path = str(path)
    return raw_text, chunks, raw_path


def build_document(item: dict[str, Any], source: dict[str, Any], raw_text: str, raw_path: str | None) -> dict[str, Any]:
    return {
        "external_id": item["external_id"],
        "title": item["title"],
        "document_type": item["document_type"],
        "language": item.get("language", "zh-CN"),
        "published_at": item.get("published_at"),
        "updated_at_source": item.get("updated_at_source"),
        "source_url": item.get("source_url", source["base_url"]),
        "download_url": item.get("download_url"),
        "license_name": item.get("license_name", source["license_name"]),
        "attribution": item.get("attribution", source["attribution"]),
        "evidence_level": item.get("evidence_level", item.get("authority_tier", source["authority_tier"])),
        "evidence_grade": item.get("evidence_grade", "ungraded"),
        "authority_tier": item.get("authority_tier", source["authority_tier"]),
        "jurisdiction": item.get("jurisdiction", source["jurisdiction"]),
        "version": item.get("version"),
        "effective_from": item.get("effective_from"),
        "valid_until": item.get("valid_until"),
        "rights_status": item.get("rights_status", source["rights_status"]),
        "ingestion_mode": item.get("ingestion_mode", "metadata_only"),
        "review_status": item.get("review_status", "pending_source_review"),
        "department": item.get("department"),
        "content_sha256": sha256_text(raw_text),
        "raw_path": raw_path,
        "raw_text": raw_text,
        "metadata": item.get("metadata", {}),
    }


def upsert_profile(connection: Any, document_id: int, item: dict[str, Any]) -> None:
    profile_type = item.get("profile_type")
    profile = dict(item.get("profile", {}))
    if profile_type == "guideline":
        upsert_guideline_profile(connection, document_id, profile)
    elif profile_type == "drug":
        upsert_drug_monograph(connection, document_id, profile)
    elif profile_type == "textbook":
        upsert_textbook_profile(connection, document_id, profile)
    elif profile_type:
        raise ValueError(f"Unsupported profile_type: {profile_type}")


if __name__ == "__main__":
    raise SystemExit(main())