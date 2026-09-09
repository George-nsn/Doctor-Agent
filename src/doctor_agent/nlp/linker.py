from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from doctor_agent.common import PROJECT_ROOT

DEFAULT_LTP_MODEL = "LTP/small"
DEFAULT_LTP_CACHE = "models/ltp"

LTP_ENTITY_TYPE_MAP = {
    "Nh": "person",
    "Ni": "organization",
    "Ns": "location",
    "PER": "person",
    "ORG": "organization",
    "LOC": "location",
}

MEDICAL_TERM_TYPES = {
    "右下腹痛": "symptom",
    "腹痛": "symptom",
    "胸痛": "symptom",
    "呼吸困难": "symptom",
    "出汗": "symptom",
    "恶心": "symptom",
    "发热": "symptom",
    "便血": "symptom",
    "呕吐": "symptom",
    "胃肠道出血": "clinical_state",
    "心肌梗死": "disease",
    "肺栓塞": "disease",
    "阑尾炎": "disease",
    "消化道溃疡": "disease",
    "肝损伤": "clinical_state",
    "布洛芬": "drug",
    "对乙酰氨基酚": "drug",
    "阿司匹林": "drug",
    "奥美拉唑": "drug",
    "止痛药": "drug_class",
    "孕妇": "population",
    "儿童": "population",
    "老人": "population",
}


class MedicalLTPAnalyzer:
    """LTP 4 Chinese lexical analysis with medical-dictionary augmentation."""

    def __init__(self, model_name: str | None = None, cache_dir: Path | None = None):
        self.model_name = model_name or os.getenv("MEDICAL_LTP_MODEL", DEFAULT_LTP_MODEL)
        self.cache_dir = cache_dir or PROJECT_ROOT / os.getenv("MEDICAL_LTP_CACHE", DEFAULT_LTP_CACHE)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model: Any | None = None
        self._load_error: str | None = None
        self._registered_words: set[str] = set()

    @property
    def available(self) -> bool:
        self._ensure_model()
        return self._model is not None

    @property
    def load_error(self) -> str | None:
        self._ensure_model()
        return self._load_error

    def analyze(self, text: str, dictionary: dict[str, str] | None = None) -> dict[str, Any]:
        dictionary = dictionary or {}
        medical_terms = self._medical_terms(dictionary)
        self._ensure_model(medical_terms)
        if self._model is None:
            if os.getenv("MEDICAL_LTP_REQUIRED", "0") == "1":
                raise RuntimeError(f"LTP is required but unavailable: {self._load_error}")
            return self._fallback_analysis(text, dictionary)

        self._register_words(medical_terms)
        output = self._model.pipeline([text], tasks=["cws", "pos", "ner"])
        words = list((output.cws or [[]])[0])
        pos_tags = list((output.pos or [[]])[0])
        ltp_entities = self._convert_ltp_entities((output.ner or [[]])[0])
        dictionary_entities = self._dictionary_entities(text, dictionary)
        medical_mentions = {
            str(entity["text"]).casefold() for entity in dictionary_entities
        } | {str(entity["normalized"]).casefold() for entity in dictionary_entities}
        ltp_entities = [
            entity for entity in ltp_entities if str(entity["text"]).casefold() not in medical_mentions
        ]
        entities = self._deduplicate_entities([*dictionary_entities, *ltp_entities])
        normalized_tokens = self._normalize_tokens(words, dictionary)
        return {
            "backend": "ltp4_neural_with_medical_dictionary",
            "model": self.model_name,
            "tokens": normalized_tokens,
            "words": words,
            "pos": pos_tags,
            "entities": entities,
            "fallback": False,
        }

    def _ensure_model(self, medical_terms: list[str] | None = None) -> None:
        if self._model is not None or self._load_error is not None:
            return
        try:
            from ltp import LTP

            self._model = LTP(self.model_name, cache_dir=str(self.cache_dir))
            self._register_words(medical_terms or list(MEDICAL_TERM_TYPES))
        except Exception as error:  # noqa: BLE001
            self._load_error = f"{type(error).__name__}: {error}"

    def _register_words(self, words: list[str]) -> None:
        if self._model is None:
            return
        new_words = [word for word in words if len(word) > 1 and word not in self._registered_words]
        if new_words:
            self._model.add_words(new_words, freq=3)
            self._registered_words.update(new_words)

    def _medical_terms(self, dictionary: dict[str, str]) -> list[str]:
        return sorted({*MEDICAL_TERM_TYPES, *dictionary.keys(), *dictionary.values()}, key=len, reverse=True)

    def _convert_ltp_entities(self, entities: list[Any]) -> list[dict[str, Any]]:
        converted = []
        for entity in entities:
            if not isinstance(entity, (tuple, list)) or len(entity) < 4:
                continue
            label, text, start, end = entity[:4]
            converted.append(
                {
                    "text": str(text),
                    "type": LTP_ENTITY_TYPE_MAP.get(str(label), f"ltp_{str(label).lower()}"),
                    "normalized": str(text),
                    "source": "ltp_ner",
                    "start_word": int(start),
                    "end_word": int(end),
                    "confidence": None,
                }
            )
        return converted

    def _dictionary_entities(self, text: str, dictionary: dict[str, str]) -> list[dict[str, Any]]:
        candidates: dict[str, str] = dict(MEDICAL_TERM_TYPES)
        for alias, canonical in dictionary.items():
            candidates[alias] = MEDICAL_TERM_TYPES.get(canonical, "medical_concept")
            candidates[canonical] = MEDICAL_TERM_TYPES.get(canonical, "medical_concept")
        entities = []
        occupied: list[tuple[int, int]] = []
        for mention in sorted(candidates, key=len, reverse=True):
            for match in re.finditer(re.escape(mention), text, flags=re.IGNORECASE):
                span = match.span()
                if any(span[0] >= start and span[1] <= end for start, end in occupied):
                    continue
                canonical = dictionary.get(mention, mention)
                entities.append(
                    {
                        "text": match.group(0),
                        "type": MEDICAL_TERM_TYPES.get(canonical, candidates[mention]),
                        "normalized": canonical,
                        "source": "medical_dictionary",
                        "start_char": span[0],
                        "end_char": span[1],
                        "confidence": 1.0,
                    }
                )
                occupied.append(span)
        return entities

    def _normalize_tokens(self, words: list[str], dictionary: dict[str, str]) -> list[str]:
        tokens = []
        for word in words:
            normalized = dictionary.get(word, word).strip().lower()
            if normalized:
                tokens.append(normalized)
        return sorted(set(tokens))

    def _fallback_analysis(self, text: str, dictionary: dict[str, str]) -> dict[str, Any]:
        normalized = text
        for alias, canonical in dictionary.items():
            normalized = normalized.replace(alias, canonical)
        chunks = re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]+", normalized)
        tokens: list[str] = []
        for chunk in chunks:
            if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
                tokens.extend([canonical for alias, canonical in dictionary.items() if canonical in chunk or alias in chunk])
                tokens.extend([chunk[index : index + 2] for index in range(max(len(chunk) - 1, 0))])
            else:
                tokens.append(chunk.lower())
        return {
            "backend": "regex_dictionary_fallback",
            "model": None,
            "tokens": sorted(set(token for token in tokens if token)),
            "words": chunks,
            "pos": [],
            "entities": self._dictionary_entities(text, dictionary),
            "fallback": True,
            "load_error": self._load_error,
        }

    @staticmethod
    def _deduplicate_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        seen = set()
        for entity in entities:
            key = (
                entity.get("normalized"),
                entity.get("type"),
                entity.get("source"),
                entity.get("start_char", entity.get("start_word")),
                entity.get("end_char", entity.get("end_word")),
            )
            if key not in seen:
                seen.add(key)
                result.append(entity)
        return result


@lru_cache(maxsize=1)
def get_medical_ltp_analyzer() -> MedicalLTPAnalyzer:
    return MedicalLTPAnalyzer()


def analyze_medical_text(text: str, dictionary: dict[str, str] | None = None) -> dict[str, Any]:
    return get_medical_ltp_analyzer().analyze(text, dictionary)


def medical_tokens(text: str, dictionary: dict[str, str]) -> list[str]:
    return list(analyze_medical_text(text, dictionary)["tokens"])
