from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# pyright: reportMissingImports=false
from pypdf import PdfReader

from program.medical_knowledge.database import (
    connect_database,
    database_status,
    finish_crawl_run,
    insert_relation_candidate,
    link_document_entity,
    replace_chunks,
    start_crawl_run,
    upsert_drug_monograph,
    upsert_document,
    upsert_entity,
    upsert_guideline_profile,
    upsert_source,
)
from program.nlp_center.entity_linker.linker import analyze_medical_text


DEFAULT_RAW_DIR = PROJECT_ROOT / "program" / "data" / "official_sources"
DEFAULT_LEVEL_A = PROJECT_ROOT / "program" / "data" / "level_a_medical_knowledge.json"

SOURCES = {
    "who": {
        "slug": "who",
        "name": "WHO Publications",
        "publisher": "World Health Organization",
        "base_url": "https://www.who.int/publications",
        "source_category": "clinical_guideline",
        "jurisdiction": "international",
        "authority_tier": "A1",
        "ingestion_policy": "full_text_open_license",
        "rights_status": "open_license",
        "specialties": ["emergency_medicine", "pediatrics", "cardiology"],
        "license_name": "CC BY-NC-SA 3.0 IGO",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/igo/",
        "attribution": "Source: World Health Organization (WHO). Non-commercial use; preserve attribution and licence.",
        "terms_url": "https://www.who.int/about/policies/publishing/copyright",
    },
    "medlineplus": {
        "slug": "medlineplus",
        "name": "MedlinePlus Health Topics",
        "publisher": "U.S. National Library of Medicine",
        "base_url": "https://medlineplus.gov/",
        "source_category": "official_reference",
        "jurisdiction": "US",
        "authority_tier": "A2",
        "ingestion_policy": "public_domain_summary_only",
        "rights_status": "public_domain",
        "specialties": ["general_practice"],
        "license_name": "U.S. federal government public domain (health topic summaries)",
        "license_url": "https://medlineplus.gov/about/using/usingcontent/",
        "attribution": "Source: MedlinePlus, National Library of Medicine.",
        "terms_url": "https://medlineplus.gov/about/using/usingcontent/",
    },
    "openfda": {
        "slug": "openfda",
        "name": "openFDA Drug Labeling API",
        "publisher": "U.S. Food and Drug Administration",
        "base_url": "https://open.fda.gov/apis/drug/label/",
        "source_category": "regulatory_drug_label",
        "jurisdiction": "US",
        "authority_tier": "A1",
        "ingestion_policy": "official_api_record_level_rights",
        "rights_status": "public_domain_or_record_specific",
        "specialties": ["pharmacology"],
        "license_name": "CC0 1.0 unless otherwise marked",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": "Data provided by the U.S. Food and Drug Administration (https://open.fda.gov).",
        "terms_url": "https://open.fda.gov/terms/",
    },
    "cn_nhc": {
        "slug": "cn_nhc",
        "name": "国家卫生健康委员会诊疗规范与指南目录",
        "publisher": "中华人民共和国国家卫生健康委员会",
        "base_url": "https://www.nhc.gov.cn/",
        "source_category": "national_clinical_guideline",
        "jurisdiction": "CN",
        "authority_tier": "A1",
        "ingestion_policy": "metadata_first_full_text_only_when_reuse_permitted",
        "rights_status": "record_specific_review_required",
        "specialties": ["internal_medicine", "surgery", "gynecology", "pediatrics", "dermatology", "gastroenterology"],
        "license_name": "按具体政府信息公开页面和附件权利声明审核",
        "license_url": "https://www.nhc.gov.cn/",
        "attribution": "来源：中华人民共和国国家卫生健康委员会。",
        "terms_url": "https://www.nhc.gov.cn/",
    },
    "cn_nmpa": {
        "slug": "cn_nmpa",
        "name": "国家药品监督管理局药品与说明书目录",
        "publisher": "国家药品监督管理局",
        "base_url": "https://www.nmpa.gov.cn/",
        "source_category": "national_regulatory_drug_database",
        "jurisdiction": "CN",
        "authority_tier": "A1",
        "ingestion_policy": "metadata_first_authorized_label_import",
        "rights_status": "record_specific_review_required",
        "specialties": ["pharmacology"],
        "license_name": "按具体药品记录、说明书来源和网站使用条款审核",
        "license_url": "https://www.nmpa.gov.cn/",
        "attribution": "来源：国家药品监督管理局。",
        "terms_url": "https://www.nmpa.gov.cn/",
    },
    "cn_medical_society": {
        "slug": "cn_medical_society",
        "name": "全国医学会临床指南与专家共识目录",
        "publisher": "中华医学会及各专科分会等发布机构",
        "base_url": "https://www.cma.org.cn/",
        "source_category": "medical_society_guideline_consensus",
        "jurisdiction": "CN",
        "authority_tier": "A2",
        "ingestion_policy": "metadata_only_or_licensed_local_import",
        "rights_status": "copyright_or_record_specific",
        "specialties": ["internal_medicine", "surgery", "gynecology", "pediatrics", "dermatology", "gastroenterology"],
        "license_name": "通常受著作权保护；全文需出版方或权利人授权",
        "license_url": "https://www.cma.org.cn/",
        "attribution": "按具体指南、期刊和发布机构要求署名。",
        "terms_url": "https://www.cma.org.cn/",
    },
    "licensed_medical_textbooks": {
        "slug": "licensed_medical_textbooks",
        "name": "授权医学教材与临床工具书",
        "publisher": "用户合法授权的医学出版机构或内容提供方",
        "base_url": "local://licensed-medical-textbooks",
        "source_category": "medical_textbook_reference",
        "jurisdiction": "CN",
        "authority_tier": "C1",
        "ingestion_policy": "licensed_local_import_only",
        "rights_status": "license_proof_required",
        "specialties": ["basic_medicine", "internal_medicine", "surgery", "gynecology", "pediatrics", "pharmacology", "pathophysiology"],
        "license_name": "必须提供可用于本项目处理、索引和展示的授权依据",
        "license_url": "local://license-proof",
        "attribution": "按出版社、作者和授权协议要求署名。",
        "terms_url": "local://license-proof",
    },
}

WHO_PUBLICATIONS = [
    {
        "external_id": "who_bec_9789241513081",
        "title": "WHO-ICRC Basic Emergency Care: approach to the acutely ill and injured",
        "document_type": "manual",
        "published_at": "2018-10-30",
        "department": "emergency_medicine",
        "isbn": "978-92-4-151308-1",
        "source_url": "https://www.who.int/publications/i/item/9789241513081",
        "download_url": "https://iris.who.int/server/api/core/bitstreams/63432b9f-8808-44c5-9692-cea717c0cbda/content",
        "overview": "Open-access training manual for first-contact assessment and management of acute illness and injury.",
    },
    {
        "external_id": "who_pocket_child_9789241548373",
        "title": "Pocket book of hospital care for children: guidelines for the management of common childhood illnesses",
        "document_type": "clinical_manual",
        "published_at": "2013-06-03",
        "department": "pediatrics",
        "isbn": "978-92-4-154837-3",
        "source_url": "https://www.who.int/publications/i/item/9789241548373",
        "download_url": "https://iris.who.int/server/api/core/bitstreams/8f110da0-22e6-4ef1-90e4-c9f1b7daa363/content",
        "overview": "Evidence-based hospital guidance for severe common childhood illnesses at first-referral level.",
    },
    {
        "external_id": "who_hypertension_9789240033986",
        "title": "Guideline for the pharmacological treatment of hypertension in adults",
        "document_type": "clinical_guideline",
        "published_at": "2021-08-24",
        "department": "cardiology",
        "isbn": "978-92-4-003398-6",
        "source_url": "https://www.who.int/publications/i/item/9789240033986",
        "download_url": "https://iris.who.int/server/api/core/bitstreams/f062769d-f075-4a00-87af-0a2106e0bd04/content",
        "overview": "WHO recommendations for pharmacological treatment initiation, targets and follow-up in adults with hypertension.",
    },
]

ENTITY_CATALOG = [
    {"canonical_name": "高血压", "entity_type": "Disease", "aliases": ["hypertension", "high blood pressure", "高血压"]},
    {"canonical_name": "心肌梗死", "entity_type": "Disease", "aliases": ["heart attack", "myocardial infarction", "心肌梗死", "心梗", "AMI"]},
    {"canonical_name": "肺栓塞", "entity_type": "Disease", "aliases": ["pulmonary embolism", "肺栓塞", "PE"]},
    {"canonical_name": "阑尾炎", "entity_type": "Disease", "aliases": ["appendicitis", "阑尾炎"]},
    {"canonical_name": "肺炎", "entity_type": "Disease", "aliases": ["pneumonia", "肺炎"]},
    {"canonical_name": "腹泻", "entity_type": "Disease", "aliases": ["diarrhoea", "diarrhea", "腹泻"]},
    {"canonical_name": "疟疾", "entity_type": "Disease", "aliases": ["malaria", "疟疾"]},
    {"canonical_name": "脑膜炎", "entity_type": "Disease", "aliases": ["meningitis", "脑膜炎"]},
    {"canonical_name": "脓毒症", "entity_type": "Disease", "aliases": ["sepsis", "septicaemia", "septicemia", "脓毒症"]},
    {"canonical_name": "严重急性营养不良", "entity_type": "Disease", "aliases": ["severe acute malnutrition", "严重急性营养不良"]},
    {"canonical_name": "消化道溃疡", "entity_type": "Disease", "aliases": ["peptic ulcer", "stomach ulcer", "消化道溃疡"]},
    {"canonical_name": "胸痛", "entity_type": "Symptom", "aliases": ["chest pain", "chest discomfort", "胸痛"]},
    {"canonical_name": "呼吸困难", "entity_type": "Symptom", "aliases": ["shortness of breath", "difficulty breathing", "breathing difficulty", "呼吸困难", "气短"]},
    {"canonical_name": "腹痛", "entity_type": "Symptom", "aliases": ["abdominal pain", "stomach pain", "腹痛"]},
    {"canonical_name": "右下腹痛", "entity_type": "Symptom", "aliases": ["right lower abdominal pain", "right lower quadrant pain", "RLQ pain", "右下腹痛"]},
    {"canonical_name": "发热", "entity_type": "Symptom", "aliases": ["fever", "febrile", "发热"]},
    {"canonical_name": "呕吐", "entity_type": "Symptom", "aliases": ["vomiting", "vomit", "呕吐"]},
    {"canonical_name": "恶心", "entity_type": "Symptom", "aliases": ["nausea", "恶心"]},
    {"canonical_name": "出血", "entity_type": "Symptom", "aliases": ["bleeding", "haemorrhage", "hemorrhage", "出血"]},
    {"canonical_name": "胃肠道出血", "entity_type": "ClinicalState", "aliases": ["gastrointestinal bleeding", "GI bleeding", "stomach bleeding", "胃肠道出血"]},
    {"canonical_name": "便血", "entity_type": "Symptom", "aliases": ["blood in stool", "bloody stool", "便血"]},
    {"canonical_name": "呕血", "entity_type": "Symptom", "aliases": ["vomiting blood", "haematemesis", "hematemesis", "呕血"]},
    {"canonical_name": "出汗", "entity_type": "Symptom", "aliases": ["sweating", "cold sweat", "出汗"]},
    {"canonical_name": "肝损伤", "entity_type": "ClinicalState", "aliases": ["liver damage", "liver injury", "hepatotoxicity", "肝损伤"]},
    {"canonical_name": "休克", "entity_type": "ClinicalState", "aliases": ["shock", "休克"]},
    {"canonical_name": "意识状态改变", "entity_type": "ClinicalState", "aliases": ["altered mental status", "altered consciousness", "意识状态改变"]},
    {"canonical_name": "创伤", "entity_type": "ClinicalState", "aliases": ["trauma", "injury", "创伤"]},
    {"canonical_name": "布洛芬", "entity_type": "Drug", "aliases": ["ibuprofen", "布洛芬"]},
    {"canonical_name": "对乙酰氨基酚", "entity_type": "Drug", "aliases": ["acetaminophen", "paracetamol", "对乙酰氨基酚"]},
    {"canonical_name": "阿司匹林", "entity_type": "Drug", "aliases": ["aspirin", "阿司匹林"]},
    {"canonical_name": "奥美拉唑", "entity_type": "Drug", "aliases": ["omeprazole", "奥美拉唑"]},
    {"canonical_name": "降压药", "entity_type": "DrugClass", "aliases": ["antihypertensive", "blood pressure-lowering medicine", "降压药"]},
    {"canonical_name": "血压测量", "entity_type": "Test", "aliases": ["blood pressure measurement", "measure blood pressure", "血压测量"]},
    {"canonical_name": "心电图", "entity_type": "Test", "aliases": ["electrocardiogram", "ECG", "心电图"]},
    {"canonical_name": "CT", "entity_type": "Test", "aliases": ["computed tomography", "CT scan", "CT"]},
    {"canonical_name": "超声", "entity_type": "Test", "aliases": ["ultrasound", "sonography", "超声"]},
    {"canonical_name": "内镜", "entity_type": "Test", "aliases": ["endoscopy", "内镜"]},
    {"canonical_name": "儿童", "entity_type": "Population", "aliases": ["children", "child", "paediatric", "pediatric", "儿童"]},
    {"canonical_name": "成人", "entity_type": "Population", "aliases": ["adults", "adult", "成人"]},
    {"canonical_name": "孕妇", "entity_type": "Population", "aliases": ["pregnant women", "pregnancy", "孕妇"]},
]

RELATION_RULES = [
    {
        "subject_types": {"Disease"},
        "object_types": {"Symptom", "ClinicalState"},
        "predicate": "HAS_SYMPTOM",
        "cues": ["symptom", "sign", "present with", "associated with", "症状", "表现"],
        "confidence": 0.58,
    },
    {
        "subject_types": {"Disease"},
        "object_types": {"Test"},
        "predicate": "REQUIRES_TEST",
        "cues": ["diagnos", "assessment", "test", "measure", "screen", "检查", "诊断"],
        "confidence": 0.6,
    },
    {
        "subject_types": {"Drug", "DrugClass"},
        "object_types": {"Disease"},
        "predicate": "TREATS",
        "cues": ["treatment", "treat", "therapy", "manage", "recommended", "治疗", "推荐"],
        "confidence": 0.54,
    },
    {
        "subject_types": {"Drug", "DrugClass"},
        "object_types": {"Symptom", "ClinicalState", "Disease"},
        "predicate": "HAS_ADVERSE_EFFECT",
        "cues": ["adverse", "side effect", "warning", "risk of", "may cause", "不良反应", "警告"],
        "confidence": 0.56,
    },
    {
        "subject_types": {"Disease"},
        "object_types": {"Population"},
        "predicate": "AFFECTS_POPULATION",
        "cues": ["children", "adults", "pregnant", "population", "儿童", "成人", "孕妇"],
        "confidence": 0.5,
    },
]


def main() -> int:
    args = parse_args()
    connection = connect_database(args.database_url, reset=args.reset)
    for source in SOURCES.values():
        upsert_source(connection, source)
    connection.commit()
    source_slugs = []
    if not args.skip_who:
        source_slugs.append("who")
    if not args.skip_level_a:
        source_slugs.extend(["medlineplus", "openfda"])
    crawl_run_id = start_crawl_run(connection, source_slugs)
    counters = {"seen": 0, "documents": 0, "chunks": 0, "relations": 0}
    errors: list[str] = []
    try:
        if not args.skip_who:
            ingest_who_publications(connection, args.raw_dir, args.refresh, args.max_pages, counters, errors)
        if not args.skip_level_a:
            ingest_level_a_json(connection, args.level_a, counters, errors)
        status = "completed" if not errors else "completed_with_errors"
        finish_crawl_run(
            connection,
            crawl_run_id,
            status=status,
            documents_seen=counters["seen"],
            documents_written=counters["documents"],
            chunks_written=counters["chunks"],
            relations_written=counters["relations"],
            errors=errors,
        )
        connection.commit()
        print(json.dumps({"crawl": counters, "database": database_status(connection), "errors": errors}, ensure_ascii=False, indent=2))
        print("Database: MySQL (MYSQL_DATABASE_URL or MYSQL_* environment variables)")
        print(f"Raw official files: {args.raw_dir}")
        return 0 if not errors else 2
    except Exception as error:
        errors.append(f"fatal: {type(error).__name__}: {error}")
        finish_crawl_run(
            connection,
            crawl_run_id,
            status="failed",
            documents_seen=counters["seen"],
            documents_written=counters["documents"],
            chunks_written=counters["chunks"],
            relations_written=counters["relations"],
            errors=errors,
        )
        raise
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest licence-checked official medical sources into MySQL for knowledge graph construction.")
    parser.add_argument("--database-url", help="Optional mysql+pymysql:// URL; defaults to MYSQL_DATABASE_URL or MYSQL_* variables.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--level-a", type=Path, default=DEFAULT_LEVEL_A)
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all project tables in the configured MySQL database. Development only.")
    parser.add_argument("--refresh", action="store_true", help="Download WHO PDFs even when a local copy exists.")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages per PDF for smoke tests; 0 means all pages.")
    parser.add_argument("--skip-who", action="store_true")
    parser.add_argument("--skip-level-a", action="store_true")
    return parser.parse_args()


def ingest_who_publications(
    connection: Any,
    raw_dir: Path,
    refresh: bool,
    max_pages: int,
    counters: dict[str, int],
    errors: list[str],
) -> None:
    source = SOURCES["who"]
    source_id = upsert_source(connection, source)
    who_dir = raw_dir / "who"
    who_dir.mkdir(parents=True, exist_ok=True)
    for publication in WHO_PUBLICATIONS:
        counters["seen"] += 1
        try:
            pdf_path = who_dir / f"{publication['external_id']}.pdf"
            download_file(publication["download_url"], pdf_path, refresh=refresh)
            pages = extract_pdf_pages(pdf_path, max_pages=max_pages)
            raw_text = "\n\n".join(page["text"] for page in pages if page["text"])
            if len(raw_text) < 500:
                raise ValueError("PDF text extraction produced too little text")
            chunks = chunk_pdf_pages(pages)
            document = {
                **publication,
                "language": "en",
                "license_name": source["license_name"],
                "attribution": source["attribution"],
                "evidence_level": "A",
                "evidence_grade": "GRADE_or_guideline_specific",
                "authority_tier": "A1",
                "jurisdiction": "international",
                "version": publication.get("published_at"),
                "effective_from": publication.get("published_at"),
                "rights_status": "open_license",
                "ingestion_mode": "full_text",
                "review_status": "source_verified",
                "content_sha256": sha256_text(raw_text),
                "raw_path": pdf_path.relative_to(PROJECT_ROOT).as_posix(),
                "raw_text": raw_text,
                "metadata": {
                    "isbn": publication["isbn"],
                    "overview": publication["overview"],
                    "page_count_ingested": len(pages),
                    "licence_url": source["license_url"],
                    "terms_url": source["terms_url"],
                },
            }
            document_id = upsert_document(connection, source_id, document)
            upsert_guideline_profile(connection, document_id, guideline_profile_for_who(publication))
            chunk_ids = replace_chunks(connection, document_id, chunks)
            relation_count = index_entities_and_relation_candidates(connection, document_id, chunks, chunk_ids)
            counters["documents"] += 1
            counters["chunks"] += len(chunks)
            counters["relations"] += relation_count
            connection.commit()
        except (HTTPError, URLError, OSError, ValueError) as error:
            errors.append(f"{publication['external_id']}: {type(error).__name__}: {error}")


def ingest_level_a_json(connection: Any, path: Path, counters: dict[str, int], errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"level_a file missing: {path}")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    document_records: list[tuple[int, dict[str, Any], int, list[int], list[dict[str, Any]]]] = []
    for item in payload.get("documents", []):
        counters["seen"] += 1
        source_slug = "openfda" if item.get("source_type") == "drug_label" else "medlineplus"
        source = SOURCES[source_slug]
        source_id = upsert_source(connection, source)
        raw_text = str(item.get("content", "")).strip()
        if not raw_text:
            continue
        chunks = chunk_text(raw_text, max_chars=1800, overlap=180)
        document = {
            "external_id": str(item.get("id")),
            "title": str(item.get("title")),
            "document_type": "drug_label" if source_slug == "openfda" else "health_topic_summary",
            "language": "en",
            "published_at": item.get("published_at"),
            "source_url": item.get("source_url") or source["base_url"],
            "download_url": item.get("source_url"),
            "license_name": source["license_name"],
            "attribution": source["attribution"],
            "evidence_level": item.get("evidence_level", "A"),
            "evidence_grade": "regulatory_label" if source_slug == "openfda" else "ungraded_patient_reference",
            "authority_tier": source["authority_tier"],
            "jurisdiction": source["jurisdiction"],
            "version": item.get("published_at"),
            "effective_from": item.get("published_at"),
            "rights_status": source["rights_status"],
            "ingestion_mode": "full_text" if source_slug == "openfda" else "summary_only",
            "review_status": "source_verified",
            "department": item.get("department"),
            "content_sha256": sha256_text(raw_text),
            "raw_path": None,
            "raw_text": raw_text,
            "metadata": {"source_note": item.get("source_note"), "provided_entities": item.get("entities", [])},
        }
        document_id = upsert_document(connection, source_id, document)
        if source_slug == "openfda":
            upsert_drug_monograph(connection, document_id, drug_profile_from_level_a(item))
        chunk_ids = replace_chunks(connection, document_id, chunks)
        relation_count = index_entities_and_relation_candidates(connection, document_id, chunks, chunk_ids)
        link_provided_entities(connection, document_id, item.get("entities", []))
        document_records.append((document_id, item, relation_count, chunk_ids, chunks))
        counters["documents"] += 1
        counters["chunks"] += len(chunks)
        counters["relations"] += relation_count
    curated = ingest_curated_graph(connection, payload.get("graph", []), document_records)
    counters["relations"] += curated
    connection.commit()


def download_file(url: str, destination: Path, refresh: bool) -> None:
    if destination.exists() and destination.stat().st_size > 10_000 and not refresh:
        return
    request = Request(url, headers={"User-Agent": "agentic-rag-eval-official-ingest/0.1"})
    with urlopen(request, timeout=120) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise ValueError(f"Official download is not a PDF: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def extract_pdf_pages(path: Path, max_pages: int) -> list[dict[str, Any]]:
    reader = PdfReader(str(path))
    page_limit = min(len(reader.pages), max_pages) if max_pages > 0 else len(reader.pages)
    pages = []
    for index in range(page_limit):
        text = normalize_pdf_text(reader.pages[index].extract_text() or "")
        pages.append({"page_number": index + 1, "text": text})
    return pages


def normalize_pdf_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\x00", "")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pdf_pages(pages: list[dict[str, Any]], max_chars: int = 1800, overlap: int = 180) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in pages:
        for local_chunk in chunk_text(page["text"], max_chars=max_chars, overlap=overlap):
            local_chunk["page_number"] = page["page_number"]
            local_chunk["chunk_index"] = len(chunks)
            chunks.append(local_chunk)
    return chunks


def chunk_text(text: str, max_chars: int, overlap: int) -> list[dict[str, Any]]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start : start + max_chars])
                start += max(1, max_chars - overlap)
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            prefix = current[-overlap:] if overlap and current else ""
            current = f"{prefix}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return [
        {
            "chunk_index": index,
            "page_number": None,
            "section_title": infer_section_title(content),
            "chunk_type": infer_chunk_type(content),
            "content": content,
            "content_sha256": sha256_text(content),
        }
        for index, content in enumerate(chunks)
        if content
    ]


def infer_section_title(content: str) -> str | None:
    first_line = content.splitlines()[0].strip() if content else ""
    if 2 <= len(first_line) <= 120 and (first_line.isupper() or re.match(r"^\d+(\.\d+)*\s+", first_line)):
        return first_line
    return None


def infer_chunk_type(content: str) -> str:
    lowered = content.lower()
    if any(cue in lowered for cue in ["recommendation", "we recommend", "should be"]):
        return "recommendation"
    if any(cue in lowered for cue in ["diagnosis", "assessment", "clinical signs"]):
        return "diagnosis"
    if any(cue in lowered for cue in ["treatment", "management", "therapy"]):
        return "treatment"
    if any(cue in lowered for cue in ["warning", "contraindication", "adverse"]):
        return "safety"
    return "body"


def index_entities_and_relation_candidates(
    connection: Any,
    document_id: int,
    chunks: list[dict[str, Any]],
    chunk_ids: list[int],
) -> int:
    relation_count = 0
    entity_ids: dict[tuple[str, str], int] = {}
    for chunk, chunk_id in zip(chunks, chunk_ids):
        matches = find_entities(chunk["content"])
        for match in matches:
            key = (match["canonical_name"], match["entity_type"])
            entity_id = entity_ids.get(key) or upsert_entity(connection, match)
            entity_ids[key] = entity_id
            link_document_entity(connection, document_id, entity_id, match["mention"], 0.86, "dictionary_alias_match")
        relation_count += extract_relation_candidates(connection, document_id, chunk_id, chunk["content"], matches, entity_ids)
    return relation_count


def find_entities(text: str) -> list[dict[str, Any]]:
    matches: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in ENTITY_CATALOG:
        for alias in entity["aliases"]:
            if alias_occurs(text, alias):
                key = (entity["canonical_name"], entity["entity_type"])
                matches[key] = {**entity, "mention": alias}
                break
    if re.search(r"[\u4e00-\u9fff]", text):
        analysis = analyze_medical_text(text, {})
        for entity in analysis.get("entities", []):
            if entity.get("source") != "ltp_ner":
                continue
            canonical_name = str(entity.get("normalized") or entity.get("text") or "").strip()
            if not canonical_name:
                continue
            entity_type = str(entity.get("type") or "ltp_entity")
            matches[(canonical_name, entity_type)] = {
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "aliases": [canonical_name],
                "language": "zh-CN",
                "mention": str(entity.get("text") or canonical_name),
            }
    return list(matches.values())


def extract_relation_candidates(
    connection: Any,
    document_id: int,
    chunk_id: int,
    content: str,
    matches: list[dict[str, Any]],
    entity_ids: dict[tuple[str, str], int],
) -> int:
    inserted = 0
    for rule in RELATION_RULES:
        subjects = [entity for entity in matches if entity["entity_type"] in rule["subject_types"]]
        objects = [entity for entity in matches if entity["entity_type"] in rule["object_types"]]
        for subject in subjects[:4]:
            for obj in objects[:6]:
                if subject["canonical_name"] == obj["canonical_name"]:
                    continue
                evidence = relation_evidence_window(content, subject["mention"], obj["mention"], rule["cues"])
                if not evidence:
                    continue
                subject_id = entity_ids[(subject["canonical_name"], subject["entity_type"])]
                object_id = entity_ids[(obj["canonical_name"], obj["entity_type"])]
                if insert_relation_candidate(
                    connection,
                    subject_entity_id=subject_id,
                    predicate=rule["predicate"],
                    object_entity_id=object_id,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    confidence=rule["confidence"],
                    evidence_quote=evidence,
                    extraction_method="rule_candidate_v1",
                    review_status="pending",
                ):
                    inserted += 1
    return inserted


def link_provided_entities(connection: Any, document_id: int, names: list[str]) -> None:
    for name in names:
        entity = catalog_entity(str(name)) or {
            "canonical_name": str(name),
            "entity_type": "MedicalConcept",
            "language": "zh-en",
            "aliases": [str(name)],
        }
        entity_id = upsert_entity(connection, entity)
        link_document_entity(connection, document_id, entity_id, str(name), 0.98, "provided_source_entity")


def ingest_curated_graph(connection: Any, graph: list[list[str]], records: list[tuple[int, dict[str, Any], int, list[int], list[dict[str, Any]]]]) -> int:
    inserted = 0
    for triple in graph:
        if len(triple) != 3 or not records:
            continue
        head, predicate, tail = (str(value) for value in triple)
        document_id, item, _relation_count, chunk_ids, chunks = select_provenance_record(head, tail, records)
        subject = catalog_entity(head) or {"canonical_name": head, "entity_type": "MedicalConcept", "aliases": [head], "language": "zh-en"}
        obj = catalog_entity(tail) or {"canonical_name": tail, "entity_type": "MedicalConcept", "aliases": [tail], "language": "zh-en"}
        subject_id = upsert_entity(connection, subject)
        object_id = upsert_entity(connection, obj)
        link_document_entity(connection, document_id, subject_id, head, 0.99, "curated_level_a_graph")
        link_document_entity(connection, document_id, object_id, tail, 0.99, "curated_level_a_graph")
        matching_chunk = best_matching_chunk(chunks, entity_search_terms(subject), entity_search_terms(obj))
        matching_index = matching_chunk[0] if matching_chunk else 0
        chunk_id = chunk_ids[matching_index] if chunk_ids and matching_index < len(chunk_ids) else None
        evidence = matching_chunk[1] if matching_chunk else f"Curated relation imported from {item.get('title', 'Level A knowledge file')}"
        if insert_relation_candidate(
            connection,
            subject_entity_id=subject_id,
            predicate=predicate,
            object_entity_id=object_id,
            document_id=document_id,
            chunk_id=chunk_id,
            confidence=0.95,
            evidence_quote=evidence,
            extraction_method="curated_level_a_graph",
            review_status="approved",
        ):
            inserted += 1
    return inserted


def select_provenance_record(head: str, tail: str, records: list[tuple[int, dict[str, Any], int, list[int], list[dict[str, Any]]]]) -> tuple[int, dict[str, Any], int, list[int], list[dict[str, Any]]]:
    head_entity = catalog_entity(head)
    best_record = records[0]
    best_score = -1
    for record in records:
        item = record[1]
        text = " ".join([str(item.get("content", "")), " ".join(item.get("entities", []))])
        score = (3 if head in text else 0) + (2 if tail in text else 0)
        title = str(item.get("title", ""))
        if any(alias_occurs(title, term) for term in entity_search_terms(head_entity) if term):
            score += 8
        if head in item.get("entities", []):
            score += 5
        if head_entity and head_entity["entity_type"] in {"Drug", "DrugClass"} and item.get("source_type") == "drug_label":
            score += 4
        if score > best_score:
            best_record = record
            best_score = score
    return best_record


def catalog_entity(name: str) -> dict[str, Any] | None:
    lowered = name.lower()
    for entity in ENTITY_CATALOG:
        if lowered == entity["canonical_name"].lower() or any(lowered == alias.lower() for alias in entity["aliases"]):
            return entity
    return None


def best_evidence_quote(content: str, first: str, second: str) -> str:
    sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", content)
    for sentence in sentences:
        lowered = sentence.lower()
        if first.lower() in lowered and second.lower() in lowered:
            return sentence.strip()[:1000]
    return content[:1000]


def relation_evidence_window(content: str, first: str, second: str, cues: list[str]) -> str | None:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|\n+", content) if part.strip()]
    for index, sentence in enumerate(sentences):
        windows = [sentence]
        if index + 1 < len(sentences):
            windows.append(f"{sentence} {sentences[index + 1]}")
        for window in windows:
            lowered = window.lower()
            if alias_occurs(window, first) and alias_occurs(window, second) and any(cue.lower() in lowered for cue in cues):
                return window[:1000]
    return None


def best_matching_chunk(chunks: list[dict[str, Any]], first_terms: list[str], second_terms: list[str]) -> tuple[int, str] | None:
    for index, chunk in enumerate(chunks):
        content = chunk["content"]
        if any(alias_occurs(content, term) for term in first_terms) and any(alias_occurs(content, term) for term in second_terms):
            return index, content[:1000]
    for index, chunk in enumerate(chunks):
        content = chunk["content"]
        if any(alias_occurs(content, term) for term in first_terms + second_terms):
            return index, content[:1000]
    return None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def guideline_profile_for_who(publication: dict[str, Any]) -> dict[str, Any]:
    if publication["external_id"] == "who_hypertension_9789240033986":
        return {
            "specialty": "cardiology",
            "target_population": "adult non-pregnant patients with appropriately diagnosed hypertension",
            "disease_scope": ["高血压"],
            "treatment_recommendations": "待从 recommendation chunks 人工审核提取",
            "follow_up_requirements": "待从 follow-up chunks 人工审核提取",
            "referral_indications": "待人工审核提取",
            "red_flags": "待人工审核提取",
            "extraction_status": "pending_human_review",
        }
    if publication["external_id"] == "who_pocket_child_9789241548373":
        return {
            "specialty": "pediatrics",
            "target_population": "children requiring first-referral inpatient care",
            "disease_scope": ["肺炎", "腹泻", "发热", "疟疾", "脑膜炎", "脓毒症", "严重急性营养不良"],
            "referral_indications": "待按章节和病种审核提取",
            "red_flags": "待按疾病章节审核提取",
            "extraction_status": "pending_human_review",
        }
    return {
        "specialty": "emergency_medicine",
        "target_population": "acutely ill and injured patients at first-contact care",
        "disease_scope": ["急症", "创伤", "呼吸困难", "休克", "意识状态改变"],
        "risk_stratification": "ABCDE and SAMPLE based initial assessment; structured extraction pending review",
        "referral_indications": "待从 transfer and handover sections 审核提取",
        "red_flags": "待从 emergency assessment sections 审核提取",
        "extraction_status": "pending_human_review",
    }


def drug_profile_from_level_a(item: dict[str, Any]) -> dict[str, Any]:
    content = str(item.get("content", ""))
    title = str(item.get("title", ""))
    generic_name = title.split(":", 1)[-1].strip() or title
    sections = split_label_sections(content)
    return {
        "generic_name": generic_name,
        "brand_names": [],
        "indications": sections.get("indications and usage"),
        "contraindications": sections.get("contraindications"),
        "adverse_reactions": sections.get("adverse reactions"),
        "drug_interactions": sections.get("drug interactions"),
        "dosage_and_administration": sections.get("dosage and administration"),
        "pregnancy_and_lactation": sections.get("pregnancy"),
        "storage": sections.get("storage and handling"),
        "approval_status": "official label record; product-specific approval status requires source review",
        "extraction_status": "partially_structured",
    }


def split_label_sections(content: str) -> dict[str, str]:
    headings = [
        "Indications and usage",
        "Dosage and administration",
        "Warnings",
        "Boxed warning",
        "Contraindications",
        "Adverse reactions",
        "Drug interactions",
        "Pregnancy",
        "Storage and handling",
    ]
    pattern = "(" + "|".join(re.escape(heading) for heading in headings) + r"):"
    parts = re.split(pattern, content, flags=re.IGNORECASE)
    sections: dict[str, str] = {}
    for index in range(1, len(parts) - 1, 2):
        sections[parts[index].strip().lower()] = parts[index + 1].strip()
    return sections


def alias_occurs(text: str, alias: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", alias):
        return alias in text
    pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def entity_search_terms(entity: dict[str, Any] | None) -> list[str]:
    if not entity:
        return []
    return [str(entity.get("canonical_name", "")), *(str(alias) for alias in entity.get("aliases", []))]


if __name__ == "__main__":
    raise SystemExit(main())