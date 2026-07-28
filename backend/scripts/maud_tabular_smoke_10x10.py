#!/usr/bin/env python3
"""
MAUD × tabular smoke: 10 merger agreements × 10 deal-point questions.

Indexes contracts lightly (chunk + vector, no document passport), runs the same
tabular cell pipeline as production, compares to MAUD expert labels.

For context-recall KPIs aligned with production, re-index MAUD files through
`file_processor_bg` / legal_chunking v2.2 (not light txt-only chunks) before
running `scripts/tabular_context_recall_eval.py`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence, Tuple

# backend/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAUD_ROOT = ROOT.parent / "evals" / "maud" / "maud_repo"
MAIN_CSV = MAUD_ROOT / "data" / "raw" / "main.csv"
CONTRACTS_DIR = MAUD_ROOT / "data" / "contracts"

CONTRACT_NAMES = [
    "contract_65.txt",
    "contract_16.txt",
    "contract_18.txt",
    "contract_61.txt",
    "contract_49.txt",
    "contract_80.txt",
    "contract_135.txt",
    "contract_134.txt",
    "contract_90.txt",
    "contract_19.txt",
]

# (short label, MAUD answer column, column_type)
QUESTIONS: List[Tuple[str, str, str]] = [
    ("Type of consideration", "Type of Consideration-Answer", "text"),
    (
        "MAE includes ability to consummate",
        "MAE definition includes adverse impact on Target's ability to consummate (Y/N)",
        "yes_no",
    ),
    ("MAE forward-looking standard", "MAE Forward looking standard (Y/N)", "yes_no"),
    (
        "Political/social conditions carveout",
        "General political and/or social conditions (Y/N)",
        "yes_no",
    ),
    (
        "Economic conditions carveout",
        "General economic and financial conditions (Y/N)",
        "yes_no",
    ),
    ("Change in law carveout", "Change in law (Y/N)", "yes_no"),
    (
        "MAE applies to target and subs",
        "MAE applies to Target and subsidiaries (MAE)-Answer",
        "text",
    ),
    ("FLS MAE standard", "FLS (MAE) Standard-Answer", "text"),
    (
        "Target covenant closing condition",
        "Compliance with Target Covenant Closing Condition-Answer",
        "text",
    ),
    (
        "Stock deal structure",
        "Stock Deal: Fixed Ratio v. Fixed Value-Answer",
        "text",
    ),
]


def _load_maud_rows() -> Dict[str, Dict[str, str]]:
    import csv

    with MAIN_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        anon = (row.get("Filename (anon)") or "").strip()
        if not anon:
            continue
        key = anon.replace(".pdf", ".txt")
        out[key] = row
    return out


def _question_prompt(label: str, answer_col: str) -> str:
    return (
        f"Deal point: {label}. "
        f"Find the contractual wording that answers this deal point "
        f"({answer_col}). Prefer definitions and operative clauses."
    )


def _normalize(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def _yn_token(s: str) -> str:
    n = _normalize(s)
    if n in {"yes", "y", "true", "да"}:
        return "yes"
    if n in {"no", "n", "false", "нет"}:
        return "no"
    return n


def maud_match(predicted: str, gold: str) -> bool:
    g = (gold or "").strip()
    if not g or g in {"(None entered)", ".."}:
        return False
    p = (predicted or "").strip()
    if not p or p.upper() == "N/A":
        return False
    if _normalize(p) == _normalize(g):
        return True
    if _yn_token(p) == _yn_token(g) and _yn_token(g) in {"yes", "no"}:
        return True
    # Loose: gold answer contained in prediction (verbatim-style cells)
    gn, pn = _normalize(g), _normalize(p)
    if len(gn) >= 4 and gn in pn:
        return True
    if len(pn) >= 4 and pn in gn:
        return True
    aliases = {
        "all cash": {"cash", "all cash consideration"},
        "each covenant": {"each covenant", "every covenant"},
    }
    for canon, variants in aliases.items():
        if gn == canon and any(v in pn for v in variants):
            return True
    return False


def light_index_contract(
    db,
    *,
    document_processor,
    case_id: str,
    file_model,
    text: str,
) -> None:
    from langchain_core.documents import Document

    from app.services.file_char_basis import resolve_ingest_original_text

    file_id = str(file_model.id)
    filename = str(file_model.filename or "contract.txt")
    metadata = {
        "case_id": case_id,
        "file_id": file_id,
        "file_type": "txt",
        "doc_type": "contract",
    }
    langchain_docs = [Document(page_content=text, metadata={"source": filename})]
    file_documents = document_processor.split_documents(
        text=text,
        filename=filename,
        metadata=metadata,
        file_id=file_id,
        langchain_docs=langchain_docs,
        content_bytes=text.encode("utf-8"),
    )
    if not file_documents:
        raise RuntimeError(f"no chunks for {filename}")

    file_documents, citation_text, char_basis = resolve_ingest_original_text(
        file_documents,
        loader_text=text,
    )
    file_model.original_text = citation_text
    file_model.processing_status = "ready"
    file_model.processing_error = None
    db.commit()

    document_processor.store_in_vector_db(
        case_id=case_id,
        documents=file_documents,
        db=db,
        bm25_after_store="invalidate_only",
    )


def ensure_maud_case(db, *, user_id: str, title: str) -> str:
    from app.models.case import Case

    existing = (
        db.query(Case)
        .filter(Case.title == title, Case.user_id == user_id)
        .order_by(Case.created_at.desc())
        .first()
    )
    if existing:
        return str(existing.id)
    case = Case(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        description="MAUD tabular smoke benchmark",
        case_type="dd",
        status="completed",
        full_text="maud",
        num_documents=0,
        file_names=[],
    )
    db.add(case)
    db.commit()
    return str(case.id)


def prod_index_contracts(db, *, case_id: str, file_models: Sequence[Any]) -> None:
    """Full ingest: passport, legal chunking, outline — same as production upload."""
    from app.services.file_processor_bg import process_files_background

    file_ids: List[str] = []
    for fm in file_models:
        fm.processing_status = "pending"
        fm.processing_error = None
        fm.processing_progress = None
        db.commit()
        file_ids.append(str(fm.id))
    print(f"Prod ingest for {len(file_ids)} files (blocking)...", flush=True)
    process_files_background(file_ids, case_id)
    db.expire_all()
    for fm in file_models:
        db.refresh(fm)
        st = fm.processing_status
        if st != "ready":
            raise RuntimeError(
                f"{fm.filename} ended with status={st!r} error={fm.processing_error!r}"
            )
        from app.services.file_document_outline import load_outline_payload_from_file

        outline = load_outline_payload_from_file(fm)
        n_chunks = "?"
        print(
            f"  ready {fm.filename} outline={'yes' if outline else 'no'}",
            flush=True,
        )


def ensure_contract_file(
    db,
    *,
    case_id: str,
    contract_name: str,
    text: str,
    force_reindex: bool = False,
) -> Any:
    from app.models.case import File

    existing = (
        db.query(File)
        .filter(File.case_id == case_id, File.filename == contract_name)
        .first()
    )
    if (
        existing
        and (existing.original_text or "").strip()
        and existing.processing_status == "ready"
        and not force_reindex
    ):
        return existing

    if existing:
        fid = str(existing.id)
        existing.file_content = text.encode("utf-8")
        existing.processing_status = "pending"
        db.commit()
        return existing

    file_model = File(
        id=str(uuid.uuid4()),
        case_id=case_id,
        filename=contract_name,
        file_type="txt",
        file_content=text.encode("utf-8"),
        processing_status="pending",
        original_text=" ",
    )
    db.add(file_model)
    db.commit()
    return file_model


async def run_matrix(
    *,
    case_id: str,
    files_by_name: Dict[str, Any],
    gold_by_name: Dict[str, Dict[str, str]],
    contract_names: Sequence[str],
    questions: Sequence[Tuple[str, str, str]],
) -> List[Dict[str, Any]]:
    from app.models.case import File
    from app.services.llm_factory import create_llm
    from app.services.rag_service import RAGService
    from app.services.tabular_cell_pipeline import (
        augment_context_for_column,
        cell_retrieval_params_from_models,
        docs_for_cell_geometry,
        invoke_structured_cell_extraction,
        prepare_cell_retrieval_sync,
    )
    from app.services.tabular_cell_payload import build_tabular_cell_db_payload
    from app.services.tabular_column_run_context import TabularColumnRunContext
    from app.services.tabular_search_query_rewrite import rewrite_tabular_search_query
    from app.services.yandex_embeddings import get_yandex_embeddings
    from app.utils.database import SessionLocal

    def normalize_fn(data, column, file):
        return data

    rag = RAGService()
    llm = create_llm(temperature=0.0, max_tokens=700)
    emb = get_yandex_embeddings()
    results: List[Dict[str, Any]] = []

    # Same DCP prep as tabular_review_service column runs (not a smoke-only path).
    file_context_packages: Dict[str, Any] = {}
    prep_db = SessionLocal()
    try:
        from app.services.tabular_document_context import (
            prepare_file_context_packages,
            tabular_dcp_enabled,
        )

        if tabular_dcp_enabled():
            file_ids = [str(files_by_name[n].id) for n in contract_names if n in files_by_name]
            file_context_packages = prepare_file_context_packages(
                prep_db,
                case_id=case_id,
                file_ids=file_ids,
            )
            print(
                f"DCP packages: {len(file_context_packages)} "
                f"(outline sections: "
                f"{sum(len(p.outline) for p in file_context_packages.values())})",
                flush=True,
            )
    finally:
        prep_db.close()

    for contract_name in contract_names:
        file_row = gold_by_name.get(contract_name)
        file_model = files_by_name.get(contract_name)
        if not file_row or not file_model:
            continue
        for label, answer_col, ctype in questions:
            gold = (file_row.get(answer_col) or "").strip()
            if not gold or gold in {"(None entered)", ".."}:
                results.append(
                    {
                        "contract": contract_name,
                        "question": label,
                        "gold": gold,
                        "skipped": True,
                        "match": None,
                    }
                )
                continue

            column = SimpleNamespace(
                id=f"maud-{answer_col}",
                column_label=label,
                column_type=ctype,
                prompt=_question_prompt(label, answer_col),
                tag_options=None,
                column_config={},
            )
            rewritten = rewrite_tabular_search_query(column, allow_llm=True)
            vec = emb.embed_query(rewritten.search_query)
            run = TabularColumnRunContext(
                search_query=rewritten.search_query,
                query_embedding=tuple(float(x) for x in vec),
                source_query=rewritten.source_query,
                rewrite_method=rewritten.method,
                rewrite_rationale=rewritten.rationale,
                exact_query=rewritten.exact_query,
                lexical_terms=tuple(rewritten.lexical_terms or ()),
                exact_literals=tuple(rewritten.exact_literals or ()),
                search_queries=tuple(rewritten.search_queries or ())
                or (rewritten.search_query,),
            )

            db = SessionLocal()
            try:
                f = db.query(File).filter(File.id == file_model.id).one()
                file_ctx = file_context_packages.get(str(f.id))
                params = cell_retrieval_params_from_models(
                    f, column, column_run=run, file_context=file_ctx
                )
                prepared = prepare_cell_retrieval_sync(rag, params=params)
                ctx = augment_context_for_column(
                    prepared.context_text,
                    column_type=ctype,
                    original_text=str(f.original_text or ""),
                )
                extraction = await invoke_structured_cell_extraction(
                    llm,
                    column=column,
                    context_text=ctx,
                    normalize_fn=normalize_fn,
                    file=f,
                )
                from app.services.tabular_cell_verification import apply_evidence_first_policy

                verification = apply_evidence_first_policy(
                    extraction,
                    column=column,
                    file=f,
                    included_docs=prepared.included_docs,
                )
                extraction = verification.result
                payload = build_tabular_cell_db_payload(
                    file=f,
                    column=column,
                    result=extraction,
                    included_docs=prepared.included_docs,
                    geometry_docs=docs_for_cell_geometry(prepared),
                    db=None,
                    verification_outcome=verification,
                )
                pred = str(payload.get("cell_value") or extraction.cell_value or "")
                ok = maud_match(pred, gold)
                refs = payload.get("source_references") or []
                has_bbox = any(isinstance(r, dict) and r.get("bbox") for r in refs)
                ctx_meta = dict(getattr(prepared, "retrieval_meta", None) or {})
                na = not pred.strip() or pred.strip().upper() == "N/A"
                results.append(
                    {
                        "contract": contract_name,
                        "question": label,
                        "answer_col": answer_col,
                        "gold": gold,
                        "predicted": pred,
                        "match": ok,
                        "skipped": False,
                        "has_bbox": has_bbox,
                        "n_refs": len(refs),
                        "verbatim_extract": (extraction.verbatim_extract or None),
                        "extraction_method": getattr(extraction, "extraction_method", None),
                        "forced_na": bool(verification.forced_na),
                        "rewrite": rewritten.search_query,
                        "search_queries": list(rewritten.search_queries or ()),
                        "lexical_terms": list(rewritten.lexical_terms or ())[:10],
                        "context_outcome": ctx_meta.get("context_outcome"),
                        "escalation_used": ctx_meta.get("escalation_used"),
                        "route_method": ctx_meta.get("route_method"),
                        "na": na,
                    }
                )
                mark = "OK" if ok else "MISS"
                print(
                    f"  [{mark}] {contract_name} | {label}: pred={pred!r} gold={gold!r}",
                    flush=True,
                )
            finally:
                db.close()

    return results


def _ce_flags_snapshot() -> Dict[str, str]:
    from app.config import config

    return {
        "COMPILER": str(getattr(config, "TABULAR_CONTEXT_COMPILER_ENABLED", False)),
        "DCP": str(getattr(config, "TABULAR_DCP_ENABLED", False)),
        "ROUTER": str(getattr(config, "TABULAR_SECTION_ROUTER_ENABLED", False)),
        "ESCALATION": str(getattr(config, "TABULAR_RETRIEVAL_ESCALATION_ENABLED", False)),
        "CROSS_REF": str(getattr(config, "TABULAR_CROSS_REF_FOLLOW_ENABLED", False)),
        "QUOTE_THEN_ANSWER": str(getattr(config, "TABULAR_QUOTE_THEN_ANSWER", True)),
        "EVIDENCE_REQUIRED": str(getattr(config, "TABULAR_EVIDENCE_REQUIRED", True)),
    }


def _load_compare_baseline(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument(
        "--prod-ingest",
        action="store_true",
        help="Index via file_processor_bg (production) instead of light chunking",
    )
    parser.add_argument(
        "--force-reindex",
        action="store_true",
        help="Re-index even when files are already ready",
    )
    parser.add_argument("--case-id", default="", help="Reuse existing MAUD case UUID")
    parser.add_argument(
        "--contracts",
        default="",
        help="Comma-separated contract filenames (default: all 10)",
    )
    parser.add_argument(
        "--question-limit",
        type=int,
        default=0,
        help="Use first N deal-point questions only (e.g. 8 for 5×8)",
    )
    parser.add_argument(
        "--compare-with",
        default="",
        help="Baseline eval JSON for delta summary (accuracy, na_count)",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Only ingest files; skip extraction matrix",
    )
    parser.add_argument("--out", default=str(ROOT / "evals" / "maud_tabular_smoke_10x10.json"))
    args = parser.parse_args()

    if args.prod_ingest and args.skip_index:
        raise SystemExit("--prod-ingest and --skip-index are mutually exclusive")

    contract_names = (
        [c.strip() for c in args.contracts.split(",") if c.strip()]
        if args.contracts.strip()
        else list(CONTRACT_NAMES)
    )
    questions = list(QUESTIONS)
    if args.question_limit > 0:
        questions = questions[: args.question_limit]

    grid = f"{len(contract_names)}×{len(questions)}"

    if not MAIN_CSV.is_file():
        raise SystemExit(f"MAUD data missing: {MAIN_CSV} (clone + unzip data.zip)")

    t0 = time.time()
    gold_by_name = _load_maud_rows()

    from app.services.document_processor import get_document_processor
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).first()
        if not user:
            raise SystemExit("No users in DB")
        user_id = str(user.id)
        if args.case_id.strip():
            case_id = args.case_id.strip()
        else:
            case_id = ensure_maud_case(db, user_id=user_id, title="MAUD tabular smoke 10x10")
        print(f"case_id={case_id}", flush=True)

        dp = get_document_processor()
        files_by_name: Dict[str, Any] = {}
        force = args.force_reindex or args.prod_ingest

        if not args.skip_index:
            from app.services.bm25_case_prewarm import finalize_case_bm25_after_ingestion

            pending_prod: List[Any] = []
            for name in contract_names:
                path = CONTRACTS_DIR / name
                if not path.is_file():
                    raise SystemExit(f"Missing contract file: {path}")
                text = path.read_text(encoding="utf-8", errors="replace")
                print(f"Prepare {name} ({len(text)} chars)...", flush=True)
                fm = ensure_contract_file(
                    db,
                    case_id=case_id,
                    contract_name=name,
                    text=text,
                    force_reindex=force,
                )
                needs_index = (
                    force
                    or not (fm.original_text or "").strip()
                    or fm.processing_status != "ready"
                )
                if needs_index:
                    if args.prod_ingest:
                        pending_prod.append(fm)
                    else:
                        light_index_contract(
                            db,
                            document_processor=dp,
                            case_id=case_id,
                            file_model=fm,
                            text=text,
                        )
                files_by_name[name] = fm
            if pending_prod:
                prod_index_contracts(db, case_id=case_id, file_models=pending_prod)
            finalize_case_bm25_after_ingestion(case_id, dp)
        else:
            from app.models.case import File

            for name in contract_names:
                fm = db.query(File).filter_by(case_id=case_id, filename=name).first()
                if not fm:
                    raise SystemExit(f"Missing indexed file {name}; run without --skip-index")
                if fm.processing_status != "ready":
                    raise SystemExit(
                        f"{name} status={fm.processing_status!r}; finish ingest before --skip-index"
                    )
                files_by_name[name] = fm

        print(f"\nRunning {grid} extractions...", flush=True)
        if args.index_only:
            print("(--index-only: skipping extractions)", flush=True)
            matrix = []
        else:
            matrix = asyncio.run(
                run_matrix(
                    case_id=case_id,
                    files_by_name=files_by_name,
                    gold_by_name=gold_by_name,
                    contract_names=contract_names,
                    questions=questions,
                )
            )
    finally:
        db.close()

    scored = [r for r in matrix if not r.get("skipped")]
    hits = sum(1 for r in scored if r.get("match"))
    bbox_n = sum(1 for r in scored if r.get("has_bbox"))
    na_count = sum(1 for r in scored if r.get("na"))
    esc_count = sum(1 for r in scored if r.get("escalation_used"))
    flags = _ce_flags_snapshot()
    out: Dict[str, Any] = {
        "case_id": case_id,
        "contracts": contract_names,
        "questions": [q[0] for q in questions],
        "ingest_mode": "prod" if args.prod_ingest else ("skip" if args.skip_index else "light"),
        "flags": flags,
        "elapsed_sec": round(time.time() - t0, 1),
        "cells": len(matrix),
        "scored": len(scored),
        "correct": hits,
        "accuracy": round(hits / max(1, len(scored)), 4),
        "na_count": na_count,
        "escalation_count": esc_count,
        "with_bbox": bbox_n,
        "results": matrix,
    }
    baseline_path = Path(args.compare_with) if args.compare_with.strip() else None
    if baseline_path:
        base = _load_compare_baseline(baseline_path)
        if base:
            out["compare_with"] = str(baseline_path)
            out["baseline"] = {
                "accuracy": base.get("accuracy"),
                "correct": base.get("correct"),
                "scored": base.get("scored"),
                "na_count": base.get("na_count"),
                "ingest_mode": base.get("ingest_mode", "light"),
            }
            out["delta"] = {
                "accuracy": round(out["accuracy"] - float(base.get("accuracy") or 0), 4),
                "correct": hits - int(base.get("correct") or 0),
                "na_count": na_count - int(base.get("na_count") or 0),
            }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    delta_s = ""
    if out.get("delta"):
        d = out["delta"]
        delta_s = f" Δacc={d['accuracy']:+.1%} ΔNA={d['na_count']:+d}"
    print(
        f"\n=== MAUD {grid}: {hits}/{len(scored)} = {100*out['accuracy']:.1f}% "
        f"N/A={na_count} ingest={out['ingest_mode']} "
        f"(bbox {bbox_n}/{len(scored)}) elapsed {out['elapsed_sec']}s{delta_s} -> {out_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
