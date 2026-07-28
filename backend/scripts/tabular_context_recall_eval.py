#!/usr/bin/env python3
"""Retrieval-only eval: gold terms in recall pool / assembled context."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT.parent / ".env")
load_dotenv(BACKEND_ROOT / ".env")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tabular context recall eval")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--spec", required=True, help="JSON list of cell specs")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    specs = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(specs, list):
        raise SystemExit("spec must be a JSON array")

    from app.utils.database import SessionLocal
    from app.models.case import File
    from app.models.tabular_review import TabularColumn
    from app.services.rag_service import get_rag_service
    from app.services.tabular_cell_pipeline import (
        cell_retrieval_params_from_models,
        retrieve_case_assistant_context_for_cell,
    )
    from app.services.tabular_document_context import prepare_file_context_packages, tabular_dcp_enabled

    db = SessionLocal()
    rag = get_rag_service()
    results = []
    try:
        for item in specs:
            file_id = str(item.get("file_id") or "")
            column_id = str(item.get("column_id") or "")
            gold_terms = [str(t) for t in (item.get("gold_terms") or []) if str(t).strip()]
            file_row = db.query(File).filter(File.id == file_id).first()
            column = db.query(TabularColumn).filter(TabularColumn.id == column_id).first()
            if not file_row or not column:
                results.append({**item, "error": "missing_file_or_column"})
                continue
            packages = None
            if tabular_dcp_enabled():
                packages = prepare_file_context_packages(
                    db,
                    case_id=str(file_row.case_id),
                    file_ids=[file_id],
                )
            params = cell_retrieval_params_from_models(
                file_row,
                column,
                file_context=(packages or {}).get(file_id),
            )
            ctx, _inc, pool, meta = retrieve_case_assistant_context_for_cell(
                rag, params=params, db=db
            )
            pool_blob = "\n".join(getattr(d, "page_content", "") or "" for d in pool).lower()
            ctx_l = (ctx or "").lower()

            def _hit(blob: str) -> bool:
                if not gold_terms:
                    return bool(blob.strip())
                return any(t.lower() in blob for t in gold_terms)

            row = {
                **item,
                "recall_pool_hit": _hit(pool_blob),
                "prompt_hit": _hit(ctx_l),
                "escalation_used": bool(meta.get("escalation_used")),
                "context_outcome": meta.get("context_outcome"),
            }
            results.append(row)
    finally:
        db.close()

    out_path = Path(args.out) if args.out else BACKEND_ROOT / "evals" / "tabular_context_recall_eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(results)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
