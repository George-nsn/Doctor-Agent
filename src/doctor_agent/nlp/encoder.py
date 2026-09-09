from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

# pyright: reportMissingImports=false
from fastembed import TextEmbedding

from doctor_agent.common import PROJECT_ROOT

DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"


class MedicalEmbeddingEncoder:
    """Chinese medical retrieval encoder backed by FastEmbed/ONNX."""

    def __init__(self, model_name: str | None = None, cache_dir: Path | None = None):
        self.model_name = model_name or os.getenv("MEDICAL_EMBEDDING_MODEL", DEFAULT_MODEL)
        self.cache_dir = cache_dir or PROJECT_ROOT / os.getenv("MEDICAL_EMBEDDING_CACHE", "models/fastembed")
        self.model = TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    @property
    def dimension(self) -> int:
        return len(self.embed_query("医学检索维度探测"))


@lru_cache(maxsize=1)
def get_medical_encoder() -> MedicalEmbeddingEncoder:
    return MedicalEmbeddingEncoder()
