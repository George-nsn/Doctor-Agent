from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from program.nlp_center.entity_linker.linker import MEDICAL_TERM_TYPES, MedicalLTPAnalyzer


CBLUE_TYPES = {"dis", "sym", "dru", "equ", "pro", "bod", "ite", "mic", "dep"}
PROJECT_TO_CBLUE = {
    "disease": "dis",
    "symptom": "sym",
    "drug": "dru",
}
PROJECT_TO_IMCS = {
    "symptom": "Symptom",
    "drug": "Drug",
    "drug_class": "Drug_Category",
}


def load_json(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list):
        raise ValueError(f"Expected a JSON array in {path}")
    return value


def load_json_mapping(path: Path) -> dict[str, dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def score_entity_sets(tp: int, fp: int, fn: int) -> dict[str, int | float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def build_training_lexicon(records: Iterable[dict[str, Any]]) -> dict[str, str]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        for entity in record.get("entities", []):
            mention = entity.get("entity") or entity.get("text")
            entity_type = entity.get("type")
            if mention and entity_type in CBLUE_TYPES:
                counts[str(mention)][str(entity_type)] += 1
    return {mention: type_counts.most_common(1)[0][0] for mention, type_counts in counts.items()}


def gold_entities(record: dict[str, Any]) -> set[tuple[int, int, str]]:
    result = set()
    for entity in record.get("entities", []):
        start = int(entity["start_idx"])
        end = int(entity["end_idx"])
        entity_type = str(entity["type"])
        result.add((start, end, entity_type))
    return result


def predicted_entities(
    analysis: dict[str, Any],
    text: str,
    training_lexicon: dict[str, str],
) -> set[tuple[int, int, str]]:
    result = set()
    for entity in analysis.get("entities", []):
        mention = str(entity.get("text", ""))
        entity_type = training_lexicon.get(mention) or PROJECT_TO_CBLUE.get(str(entity.get("type")))
        if entity_type not in CBLUE_TYPES:
            continue
        start = entity.get("start_char")
        end = entity.get("end_char")
        if start is not None and end is not None:
            result.add((int(start), int(end), entity_type))
            continue
        # General LTP NER exposes word offsets, not medical char spans. Recover exact
        # occurrences only for diagnostics; its PER/ORG/LOC types are intentionally
        # not mapped to medical types.
        search_from = 0
        while mention:
            found = text.find(mention, search_from)
            if found < 0:
                break
            result.add((found, found + len(mention), entity_type))
            search_from = found + len(mention)
    return result


def evaluate_cmeee(
    train_path: Path,
    eval_path: Path,
    limit: int | None,
    model_name: str | None,
) -> dict[str, Any]:
    train_records = load_json(train_path)
    eval_records = load_json(eval_path)
    if limit is not None:
        eval_records = eval_records[:limit]
    lexicon = build_training_lexicon(train_records)
    analyzer = MedicalLTPAnalyzer(model_name=model_name)
    normalization_dictionary = {mention: mention for mention in lexicon}

    tp = fp = fn = 0
    backend_counts: Counter[str] = Counter()
    for record in eval_records:
        text = str(record["text"])
        analysis = analyzer.analyze(text, normalization_dictionary)
        backend_counts[str(analysis["backend"])] += 1
        predicted = predicted_entities(analysis, text, lexicon)
        gold = gold_entities(record)
        tp += len(predicted & gold)
        fp += len(predicted - gold)
        fn += len(gold - predicted)

    return {
        "benchmark": "CMeEE-V2",
        "mode": "ltp4_cws_pos_general_ner_plus_train_split_medical_lexicon",
        "warning": (
            "LTP general NER is not a medical NER model. This score measures the project hybrid "
            "pipeline with a lexicon built only from the training split; it is not an LTP upstream score."
        ),
        "model": analyzer.model_name,
        "records": len(eval_records),
        "training_lexicon_size": len(lexicon),
        "backend_counts": dict(backend_counts),
        "strict_micro": score_entity_sets(tp, fp, fn),
    }


def imcs_bio_entities(text: str, bio_label: str) -> set[tuple[int, int, str]]:
    labels = bio_label.split()
    if len(labels) != len(text):
        raise ValueError(f"IMCS BIO/text length mismatch: {len(labels)} != {len(text)} for {text!r}")
    entities: set[tuple[int, int, str]] = set()
    index = 0
    while index < len(labels):
        label = labels[index]
        if label.startswith("B-"):
            entity_type = label[2:]
            end = index + 1
            while end < len(labels) and labels[end] == f"I-{entity_type}":
                end += 1
            entities.add((index, end, entity_type))
            index = end
            continue
        index += 1
    return entities


def build_imcs_training_lexicon(samples: dict[str, dict[str, Any]]) -> dict[str, str]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for sample in samples.values():
        for utterance in sample.get("dialogue", []):
            text = str(utterance.get("sentence", ""))
            for start, end, entity_type in imcs_bio_entities(text, str(utterance.get("BIO_label", ""))):
                counts[text[start:end]][entity_type] += 1
    return {mention: type_counts.most_common(1)[0][0] for mention, type_counts in counts.items()}


def imcs_predicted_entities(
    analysis: dict[str, Any],
    lexicon: dict[str, str],
) -> set[tuple[int, int, str]]:
    predicted: set[tuple[int, int, str]] = set()
    for entity in analysis.get("entities", []):
        start = entity.get("start_char")
        end = entity.get("end_char")
        if start is None or end is None:
            continue
        mention = str(entity.get("text", ""))
        entity_type = lexicon.get(mention) or PROJECT_TO_IMCS.get(str(entity.get("type", "")))
        if entity_type:
            predicted.add((int(start), int(end), entity_type))
    return predicted


def lexicon_predicted_entities(text: str, lexicon: dict[str, str]) -> set[tuple[int, int, str]]:
    predicted: set[tuple[int, int, str]] = set()
    occupied: list[tuple[int, int]] = []
    for mention in sorted(lexicon, key=len, reverse=True):
        start = 0
        while mention:
            found = text.find(mention, start)
            if found < 0:
                break
            span = (found, found + len(mention))
            if not any(span[0] >= left and span[1] <= right for left, right in occupied):
                predicted.add((span[0], span[1], lexicon[mention]))
                occupied.append(span)
            start = found + len(mention)
    return predicted


def ltp_word_boundary_spans(text: str, words: list[str]) -> set[tuple[int, int]]:
    spans: set[tuple[int, int]] = set()
    cursor = 0
    for word in words:
        found = text.find(word, cursor)
        if found < 0:
            continue
        end = found + len(word)
        spans.add((found, end))
        cursor = end
    return spans


def evaluate_imcs21_ner(
    train_path: Path,
    eval_path: Path,
    limit_dialogues: int | None,
    max_sentences: int | None,
    model_name: str | None,
) -> dict[str, Any]:
    train_samples = load_json_mapping(train_path)
    eval_samples = load_json_mapping(eval_path)
    if limit_dialogues is not None:
        eval_samples = dict(list(eval_samples.items())[:limit_dialogues])

    training_lexicon = build_imcs_training_lexicon(train_samples)
    static_lexicon = {
        mention: PROJECT_TO_IMCS[entity_type]
        for mention, entity_type in MEDICAL_TERM_TYPES.items()
        if entity_type in PROJECT_TO_IMCS
    }
    normalization_dictionary = {mention: mention for mention in training_lexicon}
    analyzer = MedicalLTPAnalyzer(model_name=model_name)
    counts = {
        "static_dictionary": {"tp": 0, "fp": 0, "fn": 0},
        "ltp_plus_train_lexicon": {"tp": 0, "fp": 0, "fn": 0},
        "ltp_boundary_filtered_train_lexicon": {"tp": 0, "fp": 0, "fn": 0},
    }
    backend_counts: Counter[str] = Counter()
    sentence_count = 0
    gold_entity_count = 0

    stop = False
    for sample in eval_samples.values():
        for utterance in sample.get("dialogue", []):
            if max_sentences is not None and sentence_count >= max_sentences:
                stop = True
                break
            text = str(utterance.get("sentence", ""))
            gold = imcs_bio_entities(text, str(utterance.get("BIO_label", "")))
            analysis = analyzer.analyze(text, normalization_dictionary)
            backend_counts[str(analysis["backend"])] += 1
            hybrid_predicted = imcs_predicted_entities(analysis, training_lexicon)
            word_spans = ltp_word_boundary_spans(text, [str(word) for word in analysis.get("words", [])])
            predictions = {
                "static_dictionary": lexicon_predicted_entities(text, static_lexicon),
                "ltp_plus_train_lexicon": hybrid_predicted,
                "ltp_boundary_filtered_train_lexicon": {
                    entity for entity in hybrid_predicted if (entity[0], entity[1]) in word_spans
                },
            }
            for mode, predicted in predictions.items():
                counts[mode]["tp"] += len(predicted & gold)
                counts[mode]["fp"] += len(predicted - gold)
                counts[mode]["fn"] += len(gold - predicted)
            sentence_count += 1
            gold_entity_count += len(gold)
        if stop:
            break

    scores = {
        mode: score_entity_sets(values["tp"], values["fp"], values["fn"])
        for mode, values in counts.items()
    }
    baseline = scores["static_dictionary"]
    hybrid = scores["ltp_plus_train_lexicon"]
    boundary_filtered = scores["ltp_boundary_filtered_train_lexicon"]
    return {
        "benchmark": "IMCS-21 official GitHub corpus / medical dialogue NER",
        "source": "https://github.com/lemuria-wchen/imcs21",
        "mode": "strict_entity_span_and_type_micro_metrics",
        "warning": (
            "The repository has no explicit LICENSE file. Results are for local research evaluation. "
            "The hybrid score mainly measures train-split medical lexicon augmentation; LTP general NER "
            "is not a medical NER model."
        ),
        "model": analyzer.model_name,
        "dialogues_loaded": len(eval_samples),
        "sentences_evaluated": sentence_count,
        "gold_entities": gold_entity_count,
        "training_lexicon_size": len(training_lexicon),
        "static_lexicon_size": len(static_lexicon),
        "backend_counts": dict(backend_counts),
        "scores": scores,
        "absolute_delta": {
            "precision": float(hybrid["precision"]) - float(baseline["precision"]),
            "recall": float(hybrid["recall"]) - float(baseline["recall"]),
            "f1": float(hybrid["f1"]) - float(baseline["f1"]),
        },
        "boundary_filter_delta_vs_unfiltered": {
            "precision": float(boundary_filtered["precision"]) - float(hybrid["precision"]),
            "recall": float(boundary_filtered["recall"]) - float(hybrid["recall"]),
            "f1": float(boundary_filtered["f1"]) - float(hybrid["f1"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate project medical NLP adapters on approved local benchmark files.")
    subparsers = parser.add_subparsers(dest="benchmark", required=True)
    cmeee = subparsers.add_parser("cmeee-v2", help="Strict entity-level Micro-F1 for CMeEE-V2")
    cmeee.add_argument("--train", type=Path, required=True)
    cmeee.add_argument("--eval", type=Path, required=True)
    cmeee.add_argument("--limit", type=int)
    cmeee.add_argument("--model", default=None)
    cmeee.add_argument("--out", type=Path)
    imcs = subparsers.add_parser("imcs21-ner", help="Strict medical dialogue NER metrics on official IMCS-21")
    imcs.add_argument("--train", type=Path, required=True)
    imcs.add_argument("--eval", type=Path, required=True)
    imcs.add_argument("--limit-dialogues", type=int)
    imcs.add_argument("--max-sentences", type=int)
    imcs.add_argument("--model", default=None)
    imcs.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.benchmark == "cmeee-v2":
        result = evaluate_cmeee(args.train.resolve(), args.eval.resolve(), args.limit, args.model)
    else:
        result = evaluate_imcs21_ner(
            args.train.resolve(),
            args.eval.resolve(),
            args.limit_dialogues,
            args.max_sentences,
            args.model,
        )
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    print(serialized)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
