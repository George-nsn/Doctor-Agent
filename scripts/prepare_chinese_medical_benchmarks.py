from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from doctor_agent.common import PROJECT_ROOT

REGISTRY_PATH = PROJECT_ROOT / "data" / "chinese_medical_benchmark_registry.json"
DEFAULT_DATA_ROOT = PROJECT_ROOT / "data" / "benchmarks"
CMB_LOCAL_REPOSITORY = PROJECT_ROOT / "data" / "medical_finetune" / "raw" / "cmb_github"
PUBLIC_ARCHIVES = {
    "cmb": "https://github.com/FreedomIntelligence/CMB/archive/refs/heads/main.zip",
    "cmedqa2": "https://github.com/zhangsheng93/cMedQA2/archive/refs/heads/master.zip",
    "cmexam": "https://github.com/williamliujl/CMExam/archive/refs/heads/main.zip",
    "imcs21": "https://github.com/lemuria-wchen/imcs21/archive/refs/heads/main.zip",
    "promptcblue_code": "https://github.com/michael-wzhu/PromptCBLUE/archive/refs/heads/main.zip",
}


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def print_registry(registry: dict[str, Any]) -> None:
    print("ID\tPRIORITY\tACCESS\tTASKS\tNAME")
    for item in registry["benchmarks"]:
        print(
            f"{item['id']}\t{item['priority']}\t{item['download_method']}\t"
            f"{','.join(item['tasks'])}\t{item['name']}"
        )


def candidate_directories(data_root: Path, item: dict[str, Any]) -> list[Path]:
    benchmark_id = item["id"]
    candidates = [data_root / benchmark_id]
    if item.get("local_path"):
        candidates.insert(0, data_root / str(item["local_path"]))
    if benchmark_id.startswith("cblue_"):
        task_name = item["name"]
        candidates.extend([data_root / "cblue" / task_name, data_root / task_name])
    if benchmark_id == "cmb":
        candidates.append(CMB_LOCAL_REPOSITORY)
    return candidates


def find_expected_files(directory: Path, expected_files: list[str]) -> dict[str, str | None]:
    results: dict[str, str | None] = {}
    if not directory.exists():
        return {name: None for name in expected_files}
    for name in expected_files:
        direct = directory / name
        if direct.exists():
            results[name] = str(direct)
            continue
        matches = list(directory.rglob(name))
        results[name] = str(matches[0]) if matches else None
    return results


def inspect_benchmark(data_root: Path, item: dict[str, Any]) -> dict[str, Any]:
    expected = item.get("expected_files", [])
    candidates = candidate_directories(data_root, item)
    existing = [path for path in candidates if path.exists()]
    selected = existing[0] if existing else candidates[0]
    files = find_expected_files(selected, expected)
    if item["id"] == "cmb":
        extracted_root = selected / "CMB"
        exam = extracted_root / "CMB-Exam"
        clin = extracted_root / "CMB-Clin"
        if exam.is_dir() and clin.is_dir():
            files = {"CMB/CMB-Exam": str(exam), "CMB/CMB-Clin": str(clin)}
        else:
            cmb_zip = selected / "data" / "CMB.zip"
            answer = selected / "data" / "CMB-test-choice-answer.json"
            files = {
                "data/CMB.zip": str(cmb_zip) if cmb_zip.exists() else None,
                "data/CMB-test-choice-answer.json": str(answer) if answer.exists() else None,
            }
    present = sum(value is not None for value in files.values())
    return {
        "id": item["id"],
        "path": str(selected),
        "exists": selected.exists(),
        "present_files": present,
        "expected_files": len(files),
        "ready": bool(files) and present == len(files),
        "files": files,
    }


def print_status(data_root: Path, registry: dict[str, Any], benchmark_id: str | None) -> int:
    selected = [item for item in registry["benchmarks"] if benchmark_id in (None, item["id"])]
    if benchmark_id and not selected:
        raise SystemExit(f"Unknown benchmark id: {benchmark_id}")
    all_ready = True
    for item in selected:
        status = inspect_benchmark(data_root, item)
        marker = "READY" if status["ready"] else "MISSING"
        print(f"[{marker}] {status['id']} -> {status['path']}")
        for name, path in status["files"].items():
            print(f"  {'OK' if path else '--'} {name}")
        if item["download_method"].startswith("manual") or "tianchi" in item["download_method"]:
            print(f"  Apply/download under the official terms: {item['homepage']}")
        all_ready = all_ready and status["ready"]
    return 0 if all_ready else 2


def download_public_archive(name: str, data_root: Path, force: bool) -> Path:
    if name not in PUBLIC_ARCHIVES:
        raise SystemExit(f"No public archive configured for {name}. CBLUE data requires Tianchi approval.")
    destination = data_root / "downloads" / f"{name}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        print(f"Using existing archive: {destination}")
        return destination
    print(f"Downloading {PUBLIC_ARCHIVES[name]}")
    with urllib.request.urlopen(PUBLIC_ARCHIVES[name], timeout=120) as response, destination.open("wb") as target:
        shutil.copyfileobj(response, target)
    print(f"Saved: {destination}")
    return destination


def extract_archive(archive: Path, destination: Path, force: bool) -> Path:
    if destination.exists():
        if not force:
            print(f"Using existing directory: {destination}")
            return destination
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)
    print(f"Extracted: {destination}")
    return destination


def prepare_cmb(data_root: Path, force: bool) -> Path:
    source_zip = CMB_LOCAL_REPOSITORY / "data" / "CMB.zip"
    if not source_zip.exists():
        source_zip = download_public_archive("cmb", data_root, force)
        repository = extract_archive(source_zip, data_root / "sources" / "cmb_repository", force)
        matches = list(repository.rglob("CMB.zip"))
        if not matches:
            raise SystemExit("Downloaded CMB repository does not contain data/CMB.zip")
        source_zip = matches[0]
    return extract_archive(source_zip, data_root / "cmb", force)


def prepare_public(name: str, data_root: Path, force: bool) -> Path:
    archive = download_public_archive(name, data_root, force)
    return extract_archive(archive, data_root / "sources" / name, force)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List, verify and prepare Chinese medical benchmark datasets without bypassing access controls."
    )
    parser.add_argument("action", choices=["list", "status", "prepare"])
    parser.add_argument("--id", help="Registry benchmark id for status")
    parser.add_argument(
        "--dataset",
        choices=["cmb", "cmedqa2", "cmexam", "imcs21", "promptcblue_code"],
        help="Public dataset/code archive",
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    registry = load_registry()
    data_root = args.data_root.resolve()
    if args.action == "list":
        print_registry(registry)
        return 0
    if args.action == "status":
        return print_status(data_root, registry, args.id)
    if not args.dataset:
        parser.error("prepare requires --dataset")
    if args.dataset == "cmb":
        prepare_cmb(data_root, args.force)
    else:
        prepare_public(args.dataset, data_root, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
