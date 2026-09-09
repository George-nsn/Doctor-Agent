from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "program" / "data" / "level_a_medical_knowledge.json"

MEDLINEPLUS_TARGETS = [
    "abdominal pain",
    "chest pain",
    "heart attack",
    "appendicitis",
    "pulmonary embolism",
    "shortness of breath",
    "fever",
    "nausea and vomiting",
    "gastrointestinal bleeding",
]

OPENFDA_DRUGS = ["IBUPROFEN", "ACETAMINOPHEN", "OMEPRAZOLE", "ASPIRIN"]

BILINGUAL_DICTIONARY = {
    "abdominal pain": "腹痛",
    "Abdominal Pain": "腹痛",
    "bellyache": "腹痛",
    "stomach pain": "腹痛",
    "chest pain": "胸痛",
    "Chest Pain": "胸痛",
    "heart attack": "心肌梗死",
    "Heart Attack": "心肌梗死",
    "myocardial infarction": "心肌梗死",
    "shortness of breath": "呼吸困难",
    "Shortness of Breath": "呼吸困难",
    "pulmonary embolism": "肺栓塞",
    "Pulmonary Embolism": "肺栓塞",
    "appendicitis": "阑尾炎",
    "Appendicitis": "阑尾炎",
    "fever": "发热",
    "Fever": "发热",
    "nausea": "恶心",
    "vomiting": "呕吐",
    "gastrointestinal bleeding": "消化道出血",
    "blood in your stool": "便血",
    "Ibuprofen": "布洛芬",
    "ibuprofen": "布洛芬",
    "Acetaminophen": "对乙酰氨基酚",
    "acetaminophen": "对乙酰氨基酚",
    "Omeprazole": "奥美拉唑",
    "omeprazole": "奥美拉唑",
    "Aspirin": "阿司匹林",
    "aspirin": "阿司匹林",
}

ENTITY_HINTS = {
    "abdominal pain": ["腹痛", "急腹症", "呕吐", "便血"],
    "chest pain": ["胸痛", "出汗", "呼吸困难", "心肌梗死"],
    "heart attack": ["心肌梗死", "胸痛", "出汗", "呼吸困难"],
    "appendicitis": ["阑尾炎", "右下腹痛", "腹痛", "发热", "呕吐"],
    "pulmonary embolism": ["肺栓塞", "胸痛", "呼吸困难"],
    "shortness of breath": ["呼吸困难", "喘不上气", "气短"],
    "fever": ["发热", "持续高热"],
    "nausea and vomiting": ["恶心", "呕吐"],
    "gastrointestinal bleeding": ["消化道出血", "便血", "黑便", "呕血"],
}


def main() -> int:
    args = parse_args()
    medline_documents = download_medlineplus_documents(args.medlineplus_limit)
    drug_documents = download_openfda_drug_labels(args.openfda_limit)
    documents = medline_documents + drug_documents
    knowledge = {
        "source_metadata": build_source_metadata(documents),
        "documents": documents,
        "graph": build_graph(),
        "dictionary": build_dictionary(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Downloaded Level A sources: {len(documents)} documents")
    print(f"MedlinePlus official references: {len(medline_documents)}")
    print(f"openFDA drug labels: {len(drug_documents)}")
    print(f"Output: {args.out}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download official Level A medical evidence sources for the program MVP.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--medlineplus-limit", type=int, default=12)
    parser.add_argument("--openfda-limit", type=int, default=4)
    return parser.parse_args()


def download_medlineplus_documents(limit: int) -> list[dict[str, Any]]:
    xml_bytes = download_medlineplus_xml()
    root = ElementTree.fromstring(xml_bytes)
    docs = []
    for topic in root.findall("health-topic"):
        title = topic.attrib.get("title", "").strip()
        url = topic.attrib.get("url", "").strip()
        if is_non_english_topic(topic, url):
            continue
        summary = strip_markup(topic.findtext("full-summary", default=""))
        target_key = match_medlineplus_target(title, url, summary)
        if not target_key:
            continue
        doc_id = "medlineplus_" + slugify(title)
        docs.append(
            {
                "id": doc_id,
                "title": f"MedlinePlus: {title}",
                "source_type": "official_reference",
                "evidence_level": "A",
                "department": infer_department(target_key),
                "published_at": normalize_date(topic.attrib.get("date-created") or current_date()),
                "trust_score": 0.96,
                "freshness_score": 0.88,
                "content": summary,
                "entities": infer_entities(target_key, title, summary),
                "source_name": "MedlinePlus / National Library of Medicine",
                "source_url": url,
                "source_note": "Official NIH/NLM health topic XML. For patient education and triage support, not a substitute for professional care.",
            }
        )
        if len(docs) >= limit:
            break
    return docs


def download_openfda_drug_labels(limit: int) -> list[dict[str, Any]]:
    docs = []
    for drug in OPENFDA_DRUGS[:limit]:
        result = fetch_openfda_label(drug)
        if not result:
            continue
        openfda = result.get("openfda", {})
        generic_name = first_value(openfda.get("generic_name")) or drug.title()
        brand_name = first_value(openfda.get("brand_name")) or generic_name
        content = build_drug_label_content(result)
        docs.append(
            {
                "id": "openfda_label_" + slugify(generic_name),
                "title": f"openFDA drug label: {generic_name}",
                "source_type": "drug_label",
                "evidence_level": "A",
                "department": "pharmacology",
                "published_at": current_date(),
                "trust_score": 0.93,
                "freshness_score": 0.9,
                "content": content,
                "entities": infer_drug_entities(generic_name, brand_name, content),
                "source_name": "openFDA Drug Labeling API / FDA SPL",
                "source_url": build_openfda_url(drug),
                "source_note": "FDA SPL drug labeling converted by openFDA. Check current approved labeling and consult clinicians for care decisions.",
            }
        )
    return docs


def download_medlineplus_xml() -> bytes:
    for url in medlineplus_candidate_urls():
        try:
            data = download_bytes(url)
            if url.endswith(".zip"):
                with zipfile.ZipFile(BytesIO(data)) as archive:
                    xml_name = next(name for name in archive.namelist() if name.endswith(".xml"))
                    return archive.read(xml_name)
            return data
        except (HTTPError, URLError, zipfile.BadZipFile, StopIteration):
            continue
    raise SystemExit("Unable to download MedlinePlus XML from recent official URLs.")


def medlineplus_candidate_urls() -> list[str]:
    today = dt.date.today()
    urls = []
    for offset in range(8):
        date = today - dt.timedelta(days=offset)
        stamp = date.isoformat()
        urls.append(f"https://medlineplus.gov/xml/mplus_topics_compressed_{stamp}.zip")
        urls.append(f"https://medlineplus.gov/xml/mplus_topics_{stamp}.xml")
    return urls


def fetch_openfda_label(drug: str) -> dict[str, Any] | None:
    url = build_openfda_url(drug)
    try:
        payload = json.loads(download_bytes(url).decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError):
        return None
    results = payload.get("results", [])
    return results[0] if results else None


def build_openfda_url(drug: str) -> str:
    query = urlencode({"search": f'openfda.generic_name:"{drug}"', "limit": "1"})
    return f"https://api.fda.gov/drug/label.json?{query}"


def download_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "agentic-rag-eval-level-a-downloader/0.1"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def match_medlineplus_target(title: str, url: str, summary: str) -> str | None:
    title_key = normalize_topic_key(title)
    url_key = normalize_topic_key(Path(url).stem if url else "")
    for target in MEDLINEPLUS_TARGETS:
        target_key = normalize_topic_key(target)
        if title_key == target_key or url_key == target_key:
            return target
    return None


def is_non_english_topic(topic: ElementTree.Element, url: str) -> bool:
    language = topic.attrib.get("language", "").lower()
    return "spanish" in url.lower() or language in {"spanish", "es"}


def build_drug_label_content(label: dict[str, Any]) -> str:
    sections = [
        ("Indications and usage", label.get("indications_and_usage")),
        ("Warnings", label.get("warnings")),
        ("Boxed warning", label.get("boxed_warning")),
        ("Contraindications", label.get("contraindications")),
        ("Adverse reactions", label.get("adverse_reactions")),
        ("Drug interactions", label.get("drug_interactions")),
    ]
    text_parts = []
    for title, value in sections:
        section_text = first_value(value)
        if section_text:
            text_parts.append(f"{title}: {normalize_space(section_text)}")
    return "\n".join(text_parts)[:6000]


def build_source_metadata(documents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "evidence_policy": "Level A means official public source in this MVP dataset: NIH/NLM MedlinePlus or FDA SPL labels via openFDA.",
        "document_count": len(documents),
        "sources": [
            {
                "name": "MedlinePlus Health Topic XML",
                "publisher": "National Library of Medicine / National Institutes of Health",
                "url": "https://medlineplus.gov/xml.html",
            },
            {
                "name": "openFDA Drug Labeling API",
                "publisher": "U.S. Food and Drug Administration",
                "url": "https://open.fda.gov/apis/drug/label/",
            },
        ],
    }


def build_graph() -> list[list[str]]:
    return [
        ["胸痛", "HAS_RED_FLAG", "呼吸困难"],
        ["胸痛", "HAS_RED_FLAG", "出汗"],
        ["胸痛", "MAY_INDICATE", "心肌梗死"],
        ["胸痛", "MAY_INDICATE", "肺栓塞"],
        ["腹痛", "HAS_RED_FLAG", "便血"],
        ["腹痛", "HAS_RED_FLAG", "呕血"],
        ["右下腹痛", "MAY_INDICATE", "阑尾炎"],
        ["布洛芬", "HAS_ADVERSE_EFFECT", "胃肠道出血"],
        ["布洛芬", "REQUIRES_CAUTION", "消化道溃疡"],
        ["阿司匹林", "HAS_ADVERSE_EFFECT", "胃肠道出血"],
        ["对乙酰氨基酚", "REQUIRES_CAUTION", "肝损伤"],
    ]


def build_dictionary() -> dict[str, str]:
    dictionary = {
        "肚子疼": "腹痛",
        "右下腹疼": "右下腹痛",
        "止疼药": "止痛药",
        "AMI": "急性心肌梗死",
        "心梗": "心肌梗死",
        "喘不上气": "呼吸困难",
        "气短": "呼吸困难",
        "黑便": "便血",
    }
    dictionary.update(BILINGUAL_DICTIONARY)
    return dictionary


def infer_department(target_key: str) -> str:
    if target_key in {"chest pain", "heart attack"}:
        return "cardiology"
    if target_key == "pulmonary embolism":
        return "respiratory"
    if target_key in {"abdominal pain", "appendicitis", "nausea and vomiting", "gastrointestinal bleeding"}:
        return "gastroenterology"
    return "general_practice"


def infer_entities(target_key: str, title: str, summary: str) -> list[str]:
    entities = list(ENTITY_HINTS.get(target_key, []))
    for alias, canonical in BILINGUAL_DICTIONARY.items():
        if alias.lower() in summary.lower() or alias.lower() in title.lower():
            entities.append(canonical)
    return sorted(set(entities))


def infer_drug_entities(generic_name: str, brand_name: str, content: str) -> list[str]:
    entities = []
    for text in [generic_name, brand_name, content]:
        for alias, canonical in BILINGUAL_DICTIONARY.items():
            if alias.lower() in str(text).lower():
                entities.append(canonical)
    for marker, canonical in [("bleeding", "出血"), ("ulcer", "消化道溃疡"), ("liver", "肝损伤"), ("adverse", "不良反应")]:
        if marker in content.lower():
            entities.append(canonical)
    return sorted(set(entities))


def strip_markup(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return normalize_space(html.unescape(without_tags))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def first_value(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "unknown"


def normalize_topic_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def current_date() -> str:
    return dt.date.today().isoformat()


def normalize_date(value: str) -> str:
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value


if __name__ == "__main__":
    raise SystemExit(main())