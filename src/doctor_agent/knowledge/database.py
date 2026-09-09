from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

# pyright: reportMissingImports=false
import pymysql
from pymysql.cursors import DictCursor


MYSQL_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS sources (
        source_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        slug VARCHAR(128) NOT NULL,
        name VARCHAR(512) NOT NULL,
        publisher VARCHAR(512) NOT NULL,
        base_url TEXT NOT NULL,
        source_category VARCHAR(128) NOT NULL DEFAULT 'official_reference',
        jurisdiction VARCHAR(64) NOT NULL DEFAULT 'international',
        authority_tier VARCHAR(16) NOT NULL DEFAULT 'B',
        ingestion_policy VARCHAR(128) NOT NULL DEFAULT 'metadata_only',
        rights_status VARCHAR(128) NOT NULL DEFAULT 'unknown',
        specialties_json JSON NOT NULL,
        license_name VARCHAR(512) NOT NULL,
        license_url TEXT NOT NULL,
        attribution TEXT NOT NULL,
        terms_url TEXT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (source_id),
        UNIQUE KEY uq_sources_slug (slug),
        KEY idx_sources_authority (authority_tier, source_category)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        document_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        source_id BIGINT UNSIGNED NOT NULL,
        external_id VARCHAR(255) NOT NULL,
        title VARCHAR(1024) NOT NULL,
        document_type VARCHAR(128) NOT NULL,
        language VARCHAR(32) NOT NULL,
        published_at VARCHAR(32) NULL,
        updated_at_source VARCHAR(64) NULL,
        source_url TEXT NOT NULL,
        download_url TEXT NULL,
        license_name VARCHAR(512) NOT NULL,
        attribution TEXT NOT NULL,
        evidence_level VARCHAR(64) NOT NULL,
        evidence_grade VARCHAR(64) NOT NULL DEFAULT 'ungraded',
        authority_tier VARCHAR(16) NOT NULL DEFAULT 'B',
        jurisdiction VARCHAR(64) NOT NULL DEFAULT 'international',
        version VARCHAR(128) NULL,
        effective_from VARCHAR(32) NULL,
        valid_until VARCHAR(32) NULL,
        rights_status VARCHAR(128) NOT NULL DEFAULT 'unknown',
        ingestion_mode VARCHAR(32) NOT NULL DEFAULT 'full_text',
        review_status VARCHAR(64) NOT NULL DEFAULT 'pending',
        department VARCHAR(128) NULL,
        content_sha256 CHAR(64) NOT NULL,
        raw_path TEXT NULL,
        raw_text LONGTEXT NOT NULL,
        metadata_json JSON NOT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (document_id),
        UNIQUE KEY uq_documents_source_external (source_id, external_id),
        KEY idx_documents_source (source_id),
        KEY idx_documents_authority (authority_tier, evidence_grade),
        KEY idx_documents_rights (rights_status, ingestion_mode),
        CONSTRAINT fk_documents_source FOREIGN KEY (source_id) REFERENCES sources(source_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        document_id BIGINT UNSIGNED NOT NULL,
        chunk_index INT UNSIGNED NOT NULL,
        page_number INT NULL,
        section_title VARCHAR(1024) NULL,
        chunk_type VARCHAR(64) NOT NULL,
        content LONGTEXT NOT NULL,
        char_count INT UNSIGNED NOT NULL,
        token_estimate INT UNSIGNED NOT NULL,
        content_sha256 CHAR(64) NOT NULL,
        PRIMARY KEY (chunk_id),
        UNIQUE KEY uq_chunks_document_index (document_id, chunk_index),
        KEY idx_chunks_document (document_id),
        CONSTRAINT fk_chunks_document FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS entities (
        entity_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        canonical_name VARCHAR(512) NOT NULL,
        entity_type VARCHAR(128) NOT NULL,
        language VARCHAR(32) NOT NULL,
        aliases_json JSON NOT NULL,
        PRIMARY KEY (entity_id),
        UNIQUE KEY uq_entities_name_type (canonical_name, entity_type)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS document_entities (
        document_id BIGINT UNSIGNED NOT NULL,
        entity_id BIGINT UNSIGNED NOT NULL,
        mention VARCHAR(512) NOT NULL,
        confidence DOUBLE NOT NULL,
        extraction_method VARCHAR(128) NOT NULL,
        PRIMARY KEY (document_id, entity_id, mention),
        KEY idx_document_entities_entity (entity_id),
        CONSTRAINT fk_document_entities_document FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
        CONSTRAINT fk_document_entities_entity FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS relation_candidates (
        relation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        relation_key CHAR(64) NOT NULL,
        subject_entity_id BIGINT UNSIGNED NOT NULL,
        predicate VARCHAR(128) NOT NULL,
        object_entity_id BIGINT UNSIGNED NOT NULL,
        document_id BIGINT UNSIGNED NOT NULL,
        chunk_id BIGINT UNSIGNED NULL,
        confidence DOUBLE NOT NULL,
        evidence_quote TEXT NOT NULL,
        extraction_method VARCHAR(128) NOT NULL,
        review_status ENUM('pending', 'approved', 'rejected') NOT NULL,
        created_at DATETIME(6) NOT NULL,
        PRIMARY KEY (relation_id),
        UNIQUE KEY uq_relation_key (relation_key),
        KEY idx_relations_subject (subject_entity_id, predicate),
        KEY idx_relations_object (object_entity_id, predicate),
        KEY idx_relations_review (review_status),
        CONSTRAINT fk_relations_subject FOREIGN KEY (subject_entity_id) REFERENCES entities(entity_id),
        CONSTRAINT fk_relations_object FOREIGN KEY (object_entity_id) REFERENCES entities(entity_id),
        CONSTRAINT fk_relations_document FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE,
        CONSTRAINT fk_relations_chunk FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_runs (
        crawl_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        started_at DATETIME(6) NOT NULL,
        finished_at DATETIME(6) NULL,
        status VARCHAR(64) NOT NULL,
        source_slugs_json JSON NOT NULL,
        documents_seen INT UNSIGNED NOT NULL DEFAULT 0,
        documents_written INT UNSIGNED NOT NULL DEFAULT 0,
        chunks_written INT UNSIGNED NOT NULL DEFAULT 0,
        relations_written INT UNSIGNED NOT NULL DEFAULT 0,
        error_json JSON NOT NULL,
        PRIMARY KEY (crawl_run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS guideline_profiles (
        document_id BIGINT UNSIGNED NOT NULL,
        specialty VARCHAR(128) NOT NULL,
        target_population TEXT NULL,
        disease_scope_json JSON NOT NULL,
        classification_criteria LONGTEXT NULL,
        diagnostic_criteria LONGTEXT NULL,
        risk_stratification LONGTEXT NULL,
        treatment_recommendations LONGTEXT NULL,
        follow_up_requirements LONGTEXT NULL,
        referral_indications LONGTEXT NULL,
        red_flags LONGTEXT NULL,
        extraction_status VARCHAR(64) NOT NULL DEFAULT 'pending',
        PRIMARY KEY (document_id),
        CONSTRAINT fk_guideline_document FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS drug_monographs (
        document_id BIGINT UNSIGNED NOT NULL,
        approval_number VARCHAR(255) NULL,
        generic_name VARCHAR(512) NOT NULL,
        brand_names_json JSON NOT NULL,
        ingredients LONGTEXT NULL,
        dosage_form TEXT NULL,
        indications LONGTEXT NULL,
        dosage_and_administration LONGTEXT NULL,
        contraindications LONGTEXT NULL,
        adverse_reactions LONGTEXT NULL,
        drug_interactions LONGTEXT NULL,
        pregnancy_and_lactation LONGTEXT NULL,
        pediatric_use LONGTEXT NULL,
        geriatric_use LONGTEXT NULL,
        hepatic_renal_impairment LONGTEXT NULL,
        storage LONGTEXT NULL,
        manufacturer TEXT NULL,
        approval_status TEXT NULL,
        extraction_status VARCHAR(64) NOT NULL DEFAULT 'pending',
        PRIMARY KEY (document_id),
        CONSTRAINT fk_drug_document FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS textbook_profiles (
        document_id BIGINT UNSIGNED NOT NULL,
        book_title VARCHAR(1024) NOT NULL,
        edition VARCHAR(128) NULL,
        volume VARCHAR(128) NULL,
        isbn VARCHAR(64) NULL,
        publisher VARCHAR(512) NULL,
        authors_json JSON NOT NULL,
        subject VARCHAR(255) NULL,
        chapter_title VARCHAR(1024) NULL,
        rights_basis TEXT NOT NULL,
        allowed_scope VARCHAR(128) NOT NULL,
        mechanism_summary LONGTEXT NULL,
        extraction_status VARCHAR(64) NOT NULL DEFAULT 'metadata_only',
        PRIMARY KEY (document_id),
        CONSTRAINT fk_textbook_document FOREIGN KEY (document_id) REFERENCES documents(document_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]

MYSQL_TABLES_IN_DROP_ORDER = [
    "relation_candidates",
    "document_entities",
    "guideline_profiles",
    "drug_monographs",
    "textbook_profiles",
    "chunks",
    "crawl_runs",
    "entities",
    "documents",
    "sources",
]


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"

    @classmethod
    def from_env(cls, database_url: str | None = None) -> "MySQLConfig":
        url = database_url or os.getenv("MYSQL_DATABASE_URL")
        if url:
            parsed = urlparse(url)
            if parsed.scheme not in {"mysql", "mysql+pymysql"}:
                raise ValueError("MYSQL_DATABASE_URL must use mysql:// or mysql+pymysql://")
            return cls(
                host=parsed.hostname or "127.0.0.1",
                port=parsed.port or 3306,
                user=unquote(parsed.username or "root"),
                password=unquote(parsed.password or ""),
                database=(parsed.path or "/agentic_rag_medical").lstrip("/"),
            )
        return cls(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "agentic_rag"),
            password=os.getenv("MYSQL_PASSWORD", "agentic_rag_dev"),
            database=os.getenv("MYSQL_DATABASE", "agentic_rag_medical"),
        )


class MySQLConnection:
    def __init__(self, raw: pymysql.Connection):
        self.raw = raw

    def execute(self, query: str, params: Iterable[Any] | None = None) -> DictCursor:
        cursor = self.raw.cursor()
        cursor.execute(query, tuple(params or ()))
        return cursor

    def commit(self) -> None:
        self.raw.commit()

    def rollback(self) -> None:
        self.raw.rollback()

    def close(self) -> None:
        self.raw.close()


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def connect_database(database_url: str | None = None, reset: bool = False) -> MySQLConnection:
    config = MySQLConfig.from_env(database_url)
    _validate_identifier(config.database)
    try:
        raw = _open_database(config)
    except pymysql.err.OperationalError as error:
        if error.args[0] != 1049:
            raise
        _create_database(config)
        raw = _open_database(config)
    connection = MySQLConnection(raw)
    if reset:
        connection.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in MYSQL_TABLES_IN_DROP_ORDER:
            connection.execute(f"DROP TABLE IF EXISTS `{table}`")
        connection.execute("SET FOREIGN_KEY_CHECKS = 1")
        connection.commit()
    for statement in MYSQL_SCHEMA_STATEMENTS:
        connection.execute(statement)
    connection.commit()
    return connection


def _open_database(config: MySQLConfig) -> pymysql.Connection:
    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset=config.charset,
        autocommit=False,
        cursorclass=DictCursor,
    )


def _create_database(config: MySQLConfig) -> None:
    bootstrap = pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        charset=config.charset,
        autocommit=True,
        cursorclass=DictCursor,
    )
    try:
        with bootstrap.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE `{config.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        bootstrap.close()


def _validate_identifier(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError(f"Unsafe MySQL database identifier: {value!r}")


def upsert_source(connection: MySQLConnection, source: dict[str, Any]) -> int:
    now = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO sources (
            slug, name, publisher, base_url, source_category, jurisdiction,
            authority_tier, ingestion_policy, rights_status, specialties_json,
            license_name, license_url, attribution, terms_url, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            source_id=LAST_INSERT_ID(source_id), name=VALUES(name), publisher=VALUES(publisher),
            base_url=VALUES(base_url), source_category=VALUES(source_category),
            jurisdiction=VALUES(jurisdiction), authority_tier=VALUES(authority_tier),
            ingestion_policy=VALUES(ingestion_policy), rights_status=VALUES(rights_status),
            specialties_json=VALUES(specialties_json), license_name=VALUES(license_name),
            license_url=VALUES(license_url), attribution=VALUES(attribution),
            terms_url=VALUES(terms_url), updated_at=VALUES(updated_at)
        """,
        (
            source["slug"], source["name"], source["publisher"], source["base_url"],
            source.get("source_category", "official_reference"), source.get("jurisdiction", "international"),
            source.get("authority_tier", "B"), source.get("ingestion_policy", "metadata_only"),
            source.get("rights_status", "unknown"), json.dumps(source.get("specialties", []), ensure_ascii=False),
            source["license_name"], source["license_url"], source["attribution"], source.get("terms_url"), now, now,
        ),
    )
    return int(cursor.lastrowid)


def upsert_document(connection: MySQLConnection, source_id: int, document: dict[str, Any]) -> int:
    now = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO documents (
            source_id, external_id, title, document_type, language, published_at,
            updated_at_source, source_url, download_url, license_name, attribution,
            evidence_level, evidence_grade, authority_tier, jurisdiction, version,
            effective_from, valid_until, rights_status, ingestion_mode, review_status,
            department, content_sha256, raw_path, raw_text, metadata_json, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            document_id=LAST_INSERT_ID(document_id), title=VALUES(title), document_type=VALUES(document_type),
            language=VALUES(language), published_at=VALUES(published_at), updated_at_source=VALUES(updated_at_source),
            source_url=VALUES(source_url), download_url=VALUES(download_url), license_name=VALUES(license_name),
            attribution=VALUES(attribution), evidence_level=VALUES(evidence_level), evidence_grade=VALUES(evidence_grade),
            authority_tier=VALUES(authority_tier), jurisdiction=VALUES(jurisdiction), version=VALUES(version),
            effective_from=VALUES(effective_from), valid_until=VALUES(valid_until), rights_status=VALUES(rights_status),
            ingestion_mode=VALUES(ingestion_mode), review_status=VALUES(review_status), department=VALUES(department),
            content_sha256=VALUES(content_sha256), raw_path=VALUES(raw_path), raw_text=VALUES(raw_text),
            metadata_json=VALUES(metadata_json), updated_at=VALUES(updated_at)
        """,
        (
            source_id, document["external_id"], document["title"], document["document_type"],
            document.get("language", "en"), document.get("published_at"), document.get("updated_at_source"),
            document["source_url"], document.get("download_url"), document["license_name"], document["attribution"],
            document.get("evidence_level", "A"), document.get("evidence_grade", "ungraded"),
            document.get("authority_tier", "B"), document.get("jurisdiction", "international"),
            document.get("version"), document.get("effective_from"), document.get("valid_until"),
            document.get("rights_status", "unknown"), document.get("ingestion_mode", "full_text"),
            document.get("review_status", "pending"), document.get("department"), document["content_sha256"],
            document.get("raw_path"), document["raw_text"],
            json.dumps(document.get("metadata", {}), ensure_ascii=False, sort_keys=True), now, now,
        ),
    )
    return int(cursor.lastrowid)


def replace_chunks(connection: MySQLConnection, document_id: int, chunks: Iterable[dict[str, Any]]) -> list[int]:
    connection.execute("DELETE FROM relation_candidates WHERE document_id = %s", (document_id,))
    connection.execute("DELETE FROM document_entities WHERE document_id = %s", (document_id,))
    connection.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
    chunk_ids: list[int] = []
    for chunk in chunks:
        cursor = connection.execute(
            """
            INSERT INTO chunks (
                document_id, chunk_index, page_number, section_title, chunk_type,
                content, char_count, token_estimate, content_sha256
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                document_id, chunk["chunk_index"], chunk.get("page_number"), chunk.get("section_title"),
                chunk.get("chunk_type", "body"), chunk["content"], len(chunk["content"]),
                max(1, len(chunk["content"]) // 4), chunk["content_sha256"],
            ),
        )
        chunk_ids.append(int(cursor.lastrowid))
    return chunk_ids


def upsert_entity(connection: MySQLConnection, entity: dict[str, Any]) -> int:
    aliases = sorted(set(str(alias) for alias in entity.get("aliases", []) if alias))
    cursor = connection.execute(
        """
        INSERT INTO entities (canonical_name, entity_type, language, aliases_json)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE entity_id=LAST_INSERT_ID(entity_id), language=VALUES(language), aliases_json=VALUES(aliases_json)
        """,
        (entity["canonical_name"], entity["entity_type"], entity.get("language", "zh-en"), json.dumps(aliases, ensure_ascii=False)),
    )
    return int(cursor.lastrowid)


def link_document_entity(
    connection: MySQLConnection,
    document_id: int,
    entity_id: int,
    mention: str,
    confidence: float,
    extraction_method: str,
) -> None:
    connection.execute(
        """
        INSERT INTO document_entities (document_id, entity_id, mention, confidence, extraction_method)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE confidence=VALUES(confidence), extraction_method=VALUES(extraction_method)
        """,
        (document_id, entity_id, mention, confidence, extraction_method),
    )


def insert_relation_candidate(
    connection: MySQLConnection,
    *,
    subject_entity_id: int,
    predicate: str,
    object_entity_id: int,
    document_id: int,
    chunk_id: int | None,
    confidence: float,
    evidence_quote: str,
    extraction_method: str,
    review_status: str,
) -> bool:
    relation_key = hashlib.sha256(
        f"{subject_entity_id}|{predicate}|{object_entity_id}|{document_id}|{chunk_id or 0}".encode("utf-8")
    ).hexdigest()
    cursor = connection.execute(
        """
        INSERT INTO relation_candidates (
            relation_key, subject_entity_id, predicate, object_entity_id, document_id, chunk_id,
            confidence, evidence_quote, extraction_method, review_status, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            confidence=GREATEST(confidence, VALUES(confidence)),
            evidence_quote=IF(VALUES(review_status)='approved', VALUES(evidence_quote), evidence_quote),
            extraction_method=IF(VALUES(review_status)='approved', VALUES(extraction_method), extraction_method),
            review_status=CASE
                WHEN review_status='approved' OR VALUES(review_status)='approved' THEN 'approved'
                WHEN review_status='rejected' THEN 'rejected'
                ELSE VALUES(review_status)
            END
        """,
        (
            relation_key, subject_entity_id, predicate, object_entity_id, document_id, chunk_id,
            confidence, evidence_quote[:1000], extraction_method, review_status, utc_now(),
        ),
    )
    return cursor.rowcount > 0


def start_crawl_run(connection: MySQLConnection, source_slugs: list[str]) -> int:
    cursor = connection.execute(
        "INSERT INTO crawl_runs (started_at, status, source_slugs_json, error_json) VALUES (%s, 'running', %s, '[]')",
        (utc_now(), json.dumps(source_slugs, ensure_ascii=False)),
    )
    connection.commit()
    return int(cursor.lastrowid)


def finish_crawl_run(
    connection: MySQLConnection,
    crawl_run_id: int,
    *,
    status: str,
    documents_seen: int,
    documents_written: int,
    chunks_written: int,
    relations_written: int,
    errors: list[str],
) -> None:
    connection.execute(
        """
        UPDATE crawl_runs SET finished_at=%s, status=%s, documents_seen=%s, documents_written=%s,
            chunks_written=%s, relations_written=%s, error_json=%s WHERE crawl_run_id=%s
        """,
        (
            utc_now(), status, documents_seen, documents_written, chunks_written,
            relations_written, json.dumps(errors, ensure_ascii=False), crawl_run_id,
        ),
    )
    connection.commit()


def database_status(connection: MySQLConnection) -> dict[str, int]:
    tables = [
        "sources", "documents", "chunks", "entities", "document_entities", "relation_candidates",
        "guideline_profiles", "drug_monographs", "textbook_profiles", "crawl_runs",
    ]
    result: dict[str, int] = {}
    for table in tables:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM `{table}`").fetchone()
        result[table] = int(row["count"] if row else 0)
    return result


def upsert_guideline_profile(connection: MySQLConnection, document_id: int, profile: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO guideline_profiles (
            document_id, specialty, target_population, disease_scope_json, classification_criteria,
            diagnostic_criteria, risk_stratification, treatment_recommendations, follow_up_requirements,
            referral_indications, red_flags, extraction_status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            specialty=VALUES(specialty), target_population=VALUES(target_population),
            disease_scope_json=VALUES(disease_scope_json), classification_criteria=VALUES(classification_criteria),
            diagnostic_criteria=VALUES(diagnostic_criteria), risk_stratification=VALUES(risk_stratification),
            treatment_recommendations=VALUES(treatment_recommendations), follow_up_requirements=VALUES(follow_up_requirements),
            referral_indications=VALUES(referral_indications), red_flags=VALUES(red_flags), extraction_status=VALUES(extraction_status)
        """,
        (
            document_id, profile["specialty"], profile.get("target_population"),
            json.dumps(profile.get("disease_scope", []), ensure_ascii=False), profile.get("classification_criteria"),
            profile.get("diagnostic_criteria"), profile.get("risk_stratification"), profile.get("treatment_recommendations"),
            profile.get("follow_up_requirements"), profile.get("referral_indications"), profile.get("red_flags"),
            profile.get("extraction_status", "pending"),
        ),
    )


def upsert_drug_monograph(connection: MySQLConnection, document_id: int, profile: dict[str, Any]) -> None:
    fields = [
        "approval_number", "generic_name", "brand_names_json", "ingredients", "dosage_form", "indications",
        "dosage_and_administration", "contraindications", "adverse_reactions", "drug_interactions",
        "pregnancy_and_lactation", "pediatric_use", "geriatric_use", "hepatic_renal_impairment", "storage",
        "manufacturer", "approval_status", "extraction_status",
    ]
    values = [
        profile.get("approval_number"), profile["generic_name"], json.dumps(profile.get("brand_names", []), ensure_ascii=False),
        profile.get("ingredients"), profile.get("dosage_form"), profile.get("indications"),
        profile.get("dosage_and_administration"), profile.get("contraindications"), profile.get("adverse_reactions"),
        profile.get("drug_interactions"), profile.get("pregnancy_and_lactation"), profile.get("pediatric_use"),
        profile.get("geriatric_use"), profile.get("hepatic_renal_impairment"), profile.get("storage"),
        profile.get("manufacturer"), profile.get("approval_status"), profile.get("extraction_status", "pending"),
    ]
    assignments = ", ".join(f"{field}=VALUES({field})" for field in fields)
    placeholders = ", ".join(["%s"] * (len(fields) + 1))
    connection.execute(
        f"INSERT INTO drug_monographs (document_id, {', '.join(fields)}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {assignments}",
        (document_id, *values),
    )


def upsert_textbook_profile(connection: MySQLConnection, document_id: int, profile: dict[str, Any]) -> None:
    fields = [
        "book_title", "edition", "volume", "isbn", "publisher", "authors_json", "subject", "chapter_title",
        "rights_basis", "allowed_scope", "mechanism_summary", "extraction_status",
    ]
    values = [
        profile["book_title"], profile.get("edition"), profile.get("volume"), profile.get("isbn"),
        profile.get("publisher"), json.dumps(profile.get("authors", []), ensure_ascii=False), profile.get("subject"),
        profile.get("chapter_title"), profile["rights_basis"], profile["allowed_scope"],
        profile.get("mechanism_summary"), profile.get("extraction_status", "metadata_only"),
    ]
    assignments = ", ".join(f"{field}=VALUES({field})" for field in fields)
    placeholders = ", ".join(["%s"] * (len(fields) + 1))
    connection.execute(
        f"INSERT INTO textbook_profiles (document_id, {', '.join(fields)}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {assignments}",
        (document_id, *values),
    )
