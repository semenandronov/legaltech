"""
Offline RU DD schema eval (phase 6) — no LLM/RAG.

Runs contract_facts rules against CI fixtures under
``backend/tests/fixtures/ru_dd_schema/{lease,supply,services}/``
and reports accuracy + schema_hit_rate.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from app.services.contract_facts_service import (
    build_contract_facts_payload,
    try_extraction_from_contract_facts,
)

PACK_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ru_dd_schema"
PACKS = ("lease", "supply", "services")


def _digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", (s or "").replace(",", ".").replace(" ", ""))


def _normalize(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s./%\-]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def schema_match(predicted: str, gold: str, *, field_id: str) -> bool:
    g = (gold or "").strip()
    p = (predicted or "").strip()
    if not g:
        return False
    g_na = g.upper() in {"N/A", "NA", "Н/Д"}
    p_na = (not p) or p.upper() in {"N/A", "NA", "Н/Д", "—", "-"}
    if g_na:
        return p_na
    if p_na:
        return False
    if field_id in {"doc_date"}:
        gd, pd = re.sub(r"\D", "", g), re.sub(r"\D", "", p)
        return len(gd) >= 8 and len(pd) >= 8 and gd[:8] == pd[:8]
    if field_id in {"rent_amount", "price_total", "doc_number"}:
        gd, pd = _digits(g), _digits(p)
        if gd and pd and (gd in pd or pd in gd):
            return True
        return _normalize(g) in _normalize(p) or _normalize(p) in _normalize(g)
    if field_id == "buyout_right":
        return _normalize(p)[:3] == _normalize(g)[:3]
    if field_id == "penalty":
        gd, pd = _digits(g), _digits(p)
        if gd and pd and gd in pd:
            return True
        return _normalize(g) in _normalize(p) or _normalize(p) in _normalize(g)
    return _normalize(p) == _normalize(g) or _normalize(g) in _normalize(p)


def _resolve_text(doc: Dict[str, Any], pack_dir: Path) -> str:
    if doc.get("text_path"):
        # Paths are relative to the pack directory (or its parent fixtures root).
        path = pack_dir / str(doc["text_path"])
        if not path.is_file():
            path = PACK_ROOT / str(doc["text_path"])
        return path.read_text(encoding="utf-8")
    filename = doc.get("filename")
    if filename:
        path = pack_dir / "raw_text" / filename
        return path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"No text for doc {doc.get('id')}")


def run_pack(pack: str) -> Dict[str, Any]:
    pack_dir = PACK_ROOT / pack
    gold_pack = json.loads((pack_dir / "gold.json").read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []

    for doc in gold_pack["documents"]:
        doc_id = doc["id"]
        text = _resolve_text(doc, pack_dir)
        dd_type = str(doc.get("dd_doc_type") or "unknown")
        payload = build_contract_facts_payload(
            text=text,
            filename=str(doc.get("filename") or doc_id),
            dd_doc_type=dd_type,
            allow_llm=False,
        )
        file_model = SimpleNamespace(
            id=doc_id,
            filename=str(doc.get("filename") or doc_id),
            original_text=text,
            contract_facts=payload,
            dd_doc_type=dd_type,
            processing_progress=None,
        )
        for q in gold_pack["questions"]:
            qid = q["id"]
            gold_val = gold_pack["gold"][doc_id][qid]
            column = SimpleNamespace(
                column_type=q.get("column_type") or "text",
                column_label=q.get("label") or qid,
                prompt=q.get("prompt") or "",
                column_config={
                    "field_id": q.get("field_id") or qid,
                    "column_kind": q.get("column_kind") or "fact",
                },
            )
            hit = try_extraction_from_contract_facts(
                file_model, column, allow_lazy=False
            )
            if hit is None:
                pred = ""
                method = None
                schema_hit = False
            else:
                extraction, _docs, _meta = hit
                pred = str(extraction.cell_value or "")
                method = getattr(extraction, "extraction_method", None)
                schema_hit = method == "contract_facts"
            ok = schema_match(pred, gold_val, field_id=str(q.get("field_id") or qid))
            results.append(
                {
                    "doc_id": doc_id,
                    "question_id": qid,
                    "field_id": q.get("field_id") or qid,
                    "gold": gold_val,
                    "predicted": pred,
                    "match": ok,
                    "schema_hit": schema_hit,
                    "extraction_method": method,
                }
            )

    scored = len(results)
    correct = sum(1 for r in results if r["match"])
    schema_hits = sum(1 for r in results if r["schema_hit"])
    return {
        "pack": pack,
        "scored": scored,
        "correct": correct,
        "accuracy": round(correct / scored, 4) if scored else 0.0,
        "schema_hit_rate": round(schema_hits / scored, 4) if scored else 0.0,
        "results": results,
    }


def run_all_packs() -> Dict[str, Any]:
    by_pack = {p: run_pack(p) for p in PACKS}
    scored = sum(v["scored"] for v in by_pack.values())
    correct = sum(v["correct"] for v in by_pack.values())
    schema_hits = sum(
        sum(1 for r in v["results"] if r["schema_hit"]) for v in by_pack.values()
    )
    return {
        "scored": scored,
        "correct": correct,
        "accuracy": round(correct / scored, 4) if scored else 0.0,
        "schema_hit_rate": round(schema_hits / scored, 4) if scored else 0.0,
        "by_pack": {
            k: {kk: vv for kk, vv in v.items() if kk != "results"}
            for k, v in by_pack.items()
        },
        "packs": by_pack,
    }
