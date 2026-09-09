from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "dataset_manifest.json"


def load_manifest() -> list[dict]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return list(payload["datasets"])


def run(command: list[str], cwd: Path | None = None) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def safe_name(dataset: dict) -> str:
    return dataset["id"].replace("/", "_")


def clone_github(dataset: dict, target: Path, update: bool = False) -> None:
    destination = target / safe_name(dataset)
    if destination.exists():
        if update:
            run(["git", "pull", "--ff-only"], cwd=destination)
        else:
            print(f"skip existing: {destination}")
        return
    run(["git", "clone", "--depth", "1", dataset["url"], str(destination)])
    subdir = dataset.get("subdir")
    if subdir:
        (destination / "SELECTED_SUBDIR.txt").write_text(subdir, encoding="utf-8")


def download_hf(dataset: dict, target: Path) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("huggingface_hub is not installed. Run: python -m pip install huggingface_hub")
        raise
    destination = target / safe_name(dataset)
    snapshot_download(repo_id=dataset["repo_id"], repo_type="dataset", local_dir=str(destination), local_dir_use_symlinks=False)


def list_datasets(datasets: list[dict]) -> None:
    for item in datasets:
        tags = ",".join(item.get("recommended_use", []))
        print(f"{item['id']} | {item['language']} | {item['source_type']} | {item['name']} | {tags}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Chinese medical fine-tuning datasets from the manifest.")
    parser.add_argument("--target", type=Path, default=ROOT / "raw")
    parser.add_argument("--source", choices=["github", "hf", "all"], default="github")
    parser.add_argument("--ids", nargs="*", help="Dataset IDs to download. Default: all matching --source.")
    parser.add_argument("--include-large", action="store_true", help="Include datasets marked as large.")
    parser.add_argument("--update", action="store_true", help="git pull existing GitHub repositories.")
    parser.add_argument("--list", action="store_true", help="List datasets and exit.")
    args = parser.parse_args(argv)

    datasets = load_manifest()
    if args.list:
        list_datasets(datasets)
        return 0

    if not shutil.which("git") and args.source in {"github", "all"}:
        print("git is required for GitHub downloads.", file=sys.stderr)
        return 2

    args.target.mkdir(parents=True, exist_ok=True)
    selected = []
    id_filter = set(args.ids or [])
    for item in datasets:
        if id_filter and item["id"] not in id_filter:
            continue
        if item.get("large") and not args.include_large:
            continue
        if item.get("requires_login"):
            continue
        if args.source == "github" and item["source_type"] != "github":
            continue
        if args.source == "hf" and item["source_type"] != "huggingface":
            continue
        if args.source == "all" and item["source_type"] not in {"github", "huggingface"}:
            continue
        selected.append(item)

    if not selected:
        print("No datasets selected. Use --list to inspect manifest.")
        return 0

    for item in selected:
        print(f"\n==> {item['id']} ({item['name']})")
        if item["source_type"] == "github":
            clone_github(item, args.target, update=args.update)
        elif item["source_type"] == "huggingface":
            download_hf(item, args.target)
        else:
            print(f"manual download required: {item['url']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
