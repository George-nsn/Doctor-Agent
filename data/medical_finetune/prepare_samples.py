from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent


def read_csv_from_zip(zip_path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if not names:
            return []
        with archive.open(names[0]) as file:
            raw = file.read()
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(text.splitlines()))


def fix_mojibake(text: str) -> str:
    """Repair common UTF-8-as-GBK mojibake seen in some mirrored CSV files."""

    markers = ("鐥", "鎴", "鍖", "璇", "绛", "浣", "涓", "澶", "妫")
    if not any(marker in text for marker in markers):
        return text
    # Some mirrored cMedQA2 rows contain the Euro sign where the mojibake
    # sequence for "怎/总/性" lost one byte. Restoring to the common prefix
    # keeps the repaired text mostly readable instead of leaving all text garbled.
    normalized = text.replace("€", "鎬")
    try:
        repaired = normalized.encode("gb18030", errors="replace").decode("utf-8", errors="replace")
    except UnicodeError:
        return text
    return repaired.replace("�", "")


def build_cmedqa2_sample(raw_dir: Path, output: Path, limit: int) -> int:
    questions = read_csv_from_zip(raw_dir / "question.zip")
    answers = read_csv_from_zip(raw_dir / "answer.zip")
    answer_by_question: dict[str, list[str]] = {}
    for answer in answers:
        answer_by_question.setdefault(answer["question_id"], []).append(answer["content"])

    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as file:
        for question in questions:
            matched_answers = answer_by_question.get(question["question_id"])
            if not matched_answers:
                continue
            record = {
                "id": f"cmedqa2_{question['question_id']}",
                "source": "cMedQA2",
                "instruction": fix_mojibake(question["content"]),
                "input": "",
                "output": fix_mojibake(matched_answers[0]),
                "history": [],
                "metadata": {
                    "question_id": question["question_id"],
                    "answer_count": len(matched_answers),
                    "task_type": "medical_qa",
                    "language": "zh",
                },
            }
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if count >= limit:
                break
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare small medical fine-tuning samples from downloaded raw datasets.")
    parser.add_argument("--dataset", choices=["cmedqa2"], default="cmedqa2")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "raw" / "cmedqa2_github")
    parser.add_argument("--out", type=Path, default=ROOT / "samples" / "cmedqa2_sample.jsonl")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    if args.dataset == "cmedqa2":
        count = build_cmedqa2_sample(args.raw_dir, args.out, args.limit)
        print(f"Wrote {count} records to {args.out}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
