from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from program.nlp_center.medical_embedding.encoder import MedicalEmbeddingEncoder


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and validate the Chinese medical retrieval embedding model.")
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--cache-dir", type=Path, default=Path("models/fastembed"))
    parser.add_argument("--generation-model", help="Optional HuggingFace generation model repo to download explicitly.")
    parser.add_argument("--generation-dir", type=Path, default=Path("models/generation"))
    args = parser.parse_args()

    encoder = MedicalEmbeddingEncoder(args.model, args.cache_dir)
    vector = encoder.embed_query("布洛芬可能导致胃肠道不良反应")
    print(f"Downloaded/loaded model: {encoder.model_name}")
    print(f"Cache: {args.cache_dir}")
    print(f"Dimension: {len(vector)}")
    if args.generation_model:
        from huggingface_hub import snapshot_download

        destination = args.generation_dir / args.generation_model.replace("/", "__")
        destination.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=args.generation_model, local_dir=str(destination))
        print(json.dumps({"generation_model": args.generation_model, "path": str(destination)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())