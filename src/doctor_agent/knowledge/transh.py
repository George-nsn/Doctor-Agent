from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any
import numpy as np

from doctor_agent.common import PROJECT_ROOT
from doctor_agent.nlp.encoder import MedicalEmbeddingEncoder, get_medical_encoder


class MedicalTransH:
    """Medical Knowledge Graph Embedding using TransH (Translation on Hyperplanes).

    Uses BGE-small-zh (512-dim) dense embedding as warm-start for entity vectors.
    Projects head and tail entities onto relation-specific hyperplanes defined by normal vector w_r,
    and calculates translation energy in the hyperplane using displacement vector d_r:
        h_perp = h - (w_r^T * h) * w_r
        t_perp = t - (w_r^T * t) * w_r
        f_r(h, t) = || h_perp + d_r - t_perp ||_2

    Constraints enforced:
        || w_r ||_2 == 1.0
        w_r^T * d_r == 0 (displacement is orthogonal to hyperplane normal)
    """

    def __init__(
        self,
        dimension: int = 512,
        encoder: MedicalEmbeddingEncoder | None = None,
        weights_path: Path | str | None = None,
        margin: float = 1.5,
    ):
        self.dimension = dimension
        self.encoder = encoder or get_medical_encoder()
        self.margin = margin
        self.weights_path = Path(weights_path) if weights_path else PROJECT_ROOT / ".cache" / "transh_weights.npz"

        # Cache of entity vectors: entity_name -> np.ndarray of shape (512,)
        self.entity_embeddings: dict[str, np.ndarray] = {}
        # Relation parameters:
        # relation_name -> w_r (normal vector, shape (512,))
        self.relation_normals: dict[str, np.ndarray] = {}
        # relation_name -> d_r (translation vector, shape (512,))
        self.relation_translations: dict[str, np.ndarray] = {}

        self._load_or_init()

    def _normalize_vector(self, v: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(v)
        if norm < 1e-12:
            return v
        return v / norm

    def _enforce_orthogonality(self, w: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Enforces ||w||_2 = 1 and w^T * d = 0."""
        w_norm = self._normalize_vector(w)
        # Project d onto plane orthogonal to w
        d_orth = d - np.dot(w_norm, d) * w_norm
        return w_norm, d_orth

    def get_entity_embedding(self, entity: str) -> np.ndarray:
        """Retrieves or calculates BGE warm-started embedding for an entity."""
        entity = str(entity).strip()
        if entity not in self.entity_embeddings:
            # Warm-start from BGE dense vector
            vec = np.array(self.encoder.embed_query(entity), dtype=np.float32)
            # Normalize to unit sphere (standard BGE norm)
            self.entity_embeddings[entity] = self._normalize_vector(vec)
        return self.entity_embeddings[entity]

    def init_relation(self, relation: str, seed: int | None = None) -> None:
        """Initializes relation normal w_r and translation d_r if not present."""
        if relation in self.relation_normals and relation in self.relation_translations:
            return

        # Warm start relation direction from semantic text embedding
        rel_text = f"医学关系：{relation}"
        base_vec = np.array(self.encoder.embed_query(rel_text), dtype=np.float32)
        base_vec = self._normalize_vector(base_vec)

        # Generate a distinct orthogonal direction for normal vector
        rng = np.random.default_rng(seed or (abs(hash(relation)) % 100000))
        rand_noise = rng.standard_normal(self.dimension).astype(np.float32)
        # Gram-Schmidt against base_vec
        w_r = rand_noise - np.dot(base_vec, rand_noise) * base_vec
        w_r = self._normalize_vector(w_r)

        # Translation vector d_r along semantic direction, orthogonalized to w_r
        d_r = base_vec - np.dot(w_r, base_vec) * w_r
        d_r = d_r * 0.5  # moderate magnitude for translation

        w_r, d_r = self._enforce_orthogonality(w_r, d_r)
        self.relation_normals[relation] = w_r
        self.relation_translations[relation] = d_r

    def project_entity(self, entity: str, relation: str) -> np.ndarray:
        """Projects entity onto the hyperplane defined by w_r:
        e_perp = e - (w_r^T * e) * w_r
        """
        e = self.get_entity_embedding(entity)
        self.init_relation(relation)
        w_r = self.relation_normals[relation]
        proj = e - np.dot(w_r, e) * w_r
        return proj

    def energy(self, head: str, relation: str, tail: str) -> float:
        """Calculates TransH energy (distance in the relation hyperplane).
        Lower energy means higher triple validity and closer match:
            f_r(h, t) = || h_perp + d_r - t_perp ||_2
        """
        self.init_relation(relation)
        w_r = self.relation_normals[relation]
        d_r = self.relation_translations[relation]

        h = self.get_entity_embedding(head)
        t = self.get_entity_embedding(tail)

        h_perp = h - np.dot(w_r, h) * w_r
        t_perp = t - np.dot(w_r, t) * w_r

        diff = h_perp + d_r - t_perp
        dist = float(np.linalg.norm(diff))
        return dist

    def confidence(self, head: str, relation: str, tail: str) -> float:
        """Converts TransH energy to a normalized [0.0, 1.0] confidence score."""
        e = self.energy(head, relation, tail)
        # Sigmoid decay centered around margin
        # Closer distance gives higher score (close to 1.0)
        score = 1.0 / (1.0 + math.exp((e - self.margin) * 2.5))
        return round(float(np.clip(score, 0.05, 0.99)), 4)

    def train_triples(
        self,
        triples: list[tuple[str, str, str] | list[str]],
        epochs: int = 50,
        learning_rate: float = 0.02,
        margin: float = 1.5,
    ) -> dict[str, Any]:
        """Lightweight margin-ranking SGD optimization for relation hyperplanes.

        Loss = max(0, f_r(h, t) - f_r(h', t') + margin)
        Entities are warm-started with BGE and regularized, while w_r and d_r are updated.
        """
        if not triples:
            return {"loss": 0.0, "epochs": 0, "status": "no_triples"}

        clean_triples = [(str(t[0]), str(t[1]), str(t[2])) for t in triples if len(t) >= 3]
        entities = list({t[0] for t in clean_triples} | {t[2] for t in clean_triples})
        relations = list({t[1] for t in clean_triples})

        # Pre-warm all entities and relations
        for ent in entities:
            self.get_entity_embedding(ent)
        for rel in relations:
            self.init_relation(rel)

        rng = np.random.default_rng(42)
        total_loss = 0.0

        for epoch in range(epochs):
            epoch_loss = 0.0
            # Shuffle triples
            indices = rng.permutation(len(clean_triples))
            for idx in indices:
                h, r, t = clean_triples[idx]
                w_r = self.relation_normals[r]
                d_r = self.relation_translations[r]

                # Negative sampling: corrupt tail or head with 50% chance
                if rng.random() > 0.5:
                    neg_h, neg_r, neg_t = h, r, rng.choice(entities)
                    if neg_t == t and len(entities) > 1:
                        neg_t = entities[(entities.index(neg_t) + 1) % len(entities)]
                else:
                    neg_h, neg_r, neg_t = rng.choice(entities), r, t
                    if neg_h == h and len(entities) > 1:
                        neg_h = entities[(entities.index(neg_h) + 1) % len(entities)]

                pos_dist = self.energy(h, r, t)
                neg_dist = self.energy(neg_h, neg_r, neg_t)

                loss = max(0.0, pos_dist - neg_dist + margin)
                epoch_loss += loss

                if loss > 0.0:
                    # Gradient step on d_r and w_r
                    h_perp = self.project_entity(h, r)
                    t_perp = self.project_entity(t, r)
                    neg_h_perp = self.project_entity(neg_h, r)
                    neg_t_perp = self.project_entity(neg_t, r)

                    pos_diff = h_perp + d_r - t_perp
                    pos_norm = max(float(np.linalg.norm(pos_diff)), 1e-8)
                    grad_pos = pos_diff / pos_norm

                    neg_diff = neg_h_perp + d_r - neg_t_perp
                    neg_norm = max(float(np.linalg.norm(neg_diff)), 1e-8)
                    grad_neg = neg_diff / neg_norm

                    # Update d_r: minimize pos_dist, maximize neg_dist
                    d_r_grad = grad_pos - grad_neg
                    d_r -= learning_rate * d_r_grad

                    # Update w_r slightly towards stabilizing the projection
                    w_r_grad = -0.1 * (np.dot(pos_diff, grad_pos) * w_r)
                    w_r -= learning_rate * w_r_grad

                    # Re-project orthogonality
                    w_r, d_r = self._enforce_orthogonality(w_r, d_r)
                    self.relation_normals[r] = w_r
                    self.relation_translations[r] = d_r

            total_loss = epoch_loss / max(1, len(clean_triples))

        self.save_weights()
        return {
            "status": "trained",
            "epochs": epochs,
            "final_loss": round(float(total_loss), 6),
            "triples_count": len(clean_triples),
            "relations_count": len(relations),
        }

    def save_weights(self) -> None:
        """Saves relation weights and warm-started entity embeddings to compressed npz."""
        try:
            self.weights_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            for rel, w in self.relation_normals.items():
                data[f"rel_norm_{rel}"] = w
            for rel, d in self.relation_translations.items():
                data[f"rel_trans_{rel}"] = d
            for ent, vec in self.entity_embeddings.items():
                data[f"ent_{ent}"] = vec
            np.savez_compressed(self.weights_path, **data)
        except Exception:
            pass

    def _load_or_init(self) -> None:
        """Loads weights from disk if available."""
        if not self.weights_path.exists():
            return
        try:
            loaded = np.load(self.weights_path)
            for k in loaded.files:
                if k.startswith("rel_norm_"):
                    rel = k[len("rel_norm_") :]
                    self.relation_normals[rel] = loaded[k]
                elif k.startswith("rel_trans_"):
                    rel = k[len("rel_trans_") :]
                    self.relation_translations[rel] = loaded[k]
                elif k.startswith("ent_"):
                    ent = k[len("ent_") :]
                    self.entity_embeddings[ent] = loaded[k]
        except Exception:
            pass


_default_transh: MedicalTransH | None = None


def get_medical_transh() -> MedicalTransH:
    global _default_transh
    if _default_transh is None:
        _default_transh = MedicalTransH()
    return _default_transh
