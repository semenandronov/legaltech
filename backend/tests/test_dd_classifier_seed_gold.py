"""CI seed: DD document classifier accuracy on the anonymised gold set."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.dd_document_classifier import classify_dd_document

GOLD_DIR = Path(__file__).resolve().parent / "fixtures" / "dd_doc_type"
GOLD_PATH = GOLD_DIR / "gold.json"


def test_dd_classifier_seed_gold_accuracy():
    pack = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    docs = pack["documents"]
    ok = 0
    misses = []
    for doc in docs:
        if doc.get("path"):
            text = (GOLD_DIR / doc["path"]).read_text(encoding="utf-8")
        else:
            text = str(doc.get("text") or "")
        result = classify_dd_document(
            text=text,
            filename=str(doc.get("filename") or ""),
        )
        expected = doc["expected"]
        if result.doc_type == expected:
            ok += 1
        else:
            misses.append(
                {
                    "id": doc["id"],
                    "expected": expected,
                    "got": result.doc_type,
                    "confidence": result.confidence,
                    "rationale": result.rationale,
                }
            )
    accuracy = ok / len(docs) if docs else 0.0
    assert accuracy >= 0.9, (
        f"DD classifier seed accuracy {accuracy:.0%} < 90%; misses={misses}"
    )
