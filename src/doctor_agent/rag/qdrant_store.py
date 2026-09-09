from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any

# pyright: reportMissingImports=false
from qdrant_client import QdrantClient, models

from doctor_agent.common import PROJECT_ROOT
from doctor_agent.nlp.encoder import MedicalEmbeddingEncoder, get_medical_encoder


def _point_id(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:15], 16)


def _document_text(document: dict[str, Any]) -> str:
    entities = "、".join(str(item) for item in document.get("entities", []))
    return (
        f"标题：{document.get('title', '')}\n"
        f"来源：{document.get('source_type', '')}\n"
        f"来源类别：{document.get('source_category', '')}\n"
        f"权威等级：{document.get('authority_tier', '')}\n"
        f"证据等级：{document.get('evidence_level', '')}\n"
        f"临床证据强度：{document.get('evidence_grade', '')}\n"
        f"适用地区：{document.get('jurisdiction', '')}\n"
        f"版本：{document.get('version', '')}\n"
        f"科室：{document.get('department', '')}\n"
        f"实体：{entities}\n"
        f"正文：{document.get('content', '')}"
    )


class QdrantMedicalVectorStore:
    """Persistent local Qdrant vector store for medical knowledge."""

    def __init__(
        self,
        path: Path | None = None,
        collection: str | None = None,
        encoder: MedicalEmbeddingEncoder | None = None,
    ):
        raw_env_path = os.getenv("QDRANT_PATH", ".cache/qdrant")
        if raw_env_path == ":memory:" and path is None:
            self.path = None
            self.client = QdrantClient(location=":memory:")
        else:
            self.path = path or PROJECT_ROOT / raw_env_path
            self.path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(self.path))
        self.collection = collection or os.getenv("QDRANT_COLLECTION", "medical_knowledge_v1")
        self.encoder = encoder or get_medical_encoder()
        self._indexed_hashes: dict[str, str] = {}

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(size=self.encoder.dimension, distance=models.Distance.COSINE),
        )

    def index_documents(
        self,
        documents: list[dict[str, Any]],
        *,
        namespace: str = "default",
        replace_namespace: bool = False,
        replace_all: bool = False,
    ) -> int:
        self.ensure_collection()
        if replace_all:
            self.clear_collection()
        if not documents:
            return 0
        texts = [_document_text(document) for document in documents]
        content_hash = hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()
        if self._indexed_hashes.get(namespace) == content_hash:
            return 0
        vectors = self.encoder.embed_documents(texts)
        points = []
        active_point_ids = set()
        for document, text, vector in zip(documents, texts, vectors):
            doc_id = str(document.get("id") or hashlib.sha256(text.encode("utf-8")).hexdigest())
            point_id = _point_id(f"{namespace}:{doc_id}")
            active_point_ids.add(point_id)
            payload = dict(document)
            payload["document_text"] = text
            payload["embedding_model"] = self.encoder.model_name
            payload["content_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            payload["index_namespace"] = namespace
            points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))
        self.client.upsert(collection_name=self.collection, points=points, wait=True)
        if replace_namespace and not replace_all:
            existing_points, _next_page = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=models.Filter(
                    must=[models.FieldCondition(key="index_namespace", match=models.MatchValue(value=namespace))]
                ),
                limit=10_000,
                with_payload=False,
                with_vectors=False,
            )
            stale_ids = [point.id for point in existing_points if point.id not in active_point_ids]
            if stale_ids:
                self.client.delete(
                    collection_name=self.collection,
                    points_selector=models.PointIdsList(points=stale_ids),
                    wait=True,
                )
        self._indexed_hashes[namespace] = content_hash
        return len(points)

    def search(
        self,
        query: str,
        limit: int = 6,
        score_threshold: float | None = None,
        namespaces: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_collection()
        query_vector = self.encoder.embed_query(query)
        query_filter = None
        if namespaces:
            query_filter = models.Filter(
                should=[
                    models.FieldCondition(key="index_namespace", match=models.MatchValue(value=namespace))
                    for namespace in namespaces
                ]
            )
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        results = []
        for point in response.points:
            payload = dict(point.payload or {})
            payload["relevance"] = round(float(point.score), 4)
            payload["retrieval_path"] = ["fastembed_bge_small_zh", "qdrant_cosine"]
            payload["qdrant_point_id"] = point.id
            results.append(payload)
        return results

    def namespace_count(self, namespace: str) -> int:
        self.ensure_collection()
        response = self.client.count(
            collection_name=self.collection,
            count_filter=models.Filter(
                must=[models.FieldCondition(key="index_namespace", match=models.MatchValue(value=namespace))]
            ),
            exact=True,
        )
        return int(response.count)

    def clear_collection(self) -> None:
        self.ensure_collection()
        point_ids = []
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=1000,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            point_ids.extend(point.id for point in points)
            if offset is None:
                break
        if point_ids:
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True,
            )
        self._indexed_hashes.clear()

    def status(self) -> dict[str, Any]:
        self.ensure_collection()
        info = self.client.get_collection(self.collection)
        return {
            "backend": "qdrant_local",
            "path": str(self.path),
            "collection": self.collection,
            "points_count": info.points_count,
            "embedding_model": self.encoder.model_name,
            "dimension": self.encoder.dimension,
        }

    def close(self) -> None:
        self.client.close()


# Alias for compatibility
MedicalQdrantStore = QdrantMedicalVectorStore


def index_knowledge_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    store = get_qdrant_store()
    namespace = "knowledge_file_" + hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    indexed = store.index_documents(
        list(payload.get("documents", [])),
        namespace=namespace,
        replace_namespace=True,
    )
    return {"indexed": indexed, **store.status()}


@lru_cache(maxsize=1)
def get_qdrant_store() -> QdrantMedicalVectorStore:
    return QdrantMedicalVectorStore()
