from __future__ import annotations

from typing import Any

from doctor_agent.knowledge.transh import MedicalTransH, get_medical_transh


def expand_graph(
    message: str,
    symptoms: list[str],
    graph: list[list[str]],
    transh_model: MedicalTransH | None = None,
    min_confidence: float = 0.4,
) -> list[dict[str, Any]]:
    """Expands knowledge graph associations for user query and extracted symptoms using TransH.

    1. Identifies matching candidate triples connected to input message or symptoms.
    2. Uses TransH hyperplane projection (h_perp, t_perp) and translation (d_r) to score geometric energy.
    3. Filters out low-confidence relations and ranks triples by TransH confidence score.
    """
    if not graph:
        return []

    hits = []
    symptom_text = " ".join(symptoms)
    model = transh_model or get_medical_transh()

    for item in graph:
        if len(item) < 3:
            continue
        head, relation, tail = item[0], item[1], item[2]
        # Candidate filter: head or tail mentioned in message or symptoms
        is_relevant = head in message or tail in message or head in symptom_text or tail in symptom_text
        if not is_relevant:
            continue

        # TransH geometric evaluation
        energy_score = model.energy(head, relation, tail)
        conf = model.confidence(head, relation, tail)

        if conf >= min_confidence:
            hits.append(
                {
                    "head": head,
                    "relation": relation,
                    "tail": tail,
                    "source_type": "neo4j_transh",
                    "relevance": round(float(conf), 3),
                    "transh_energy": round(float(energy_score), 4),
                    "transh_confidence": round(float(conf), 4),
                }
            )

    # Sort by TransH confidence descending (lowest energy first)
    hits.sort(key=lambda x: (x.get("transh_confidence", 0.0), -x.get("transh_energy", 99.0)), reverse=True)
    return hits

