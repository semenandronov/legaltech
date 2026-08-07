"""
Shared RU/EN tabular eval matrix — uses the same entrypoint as production UI.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

import re

MatchFn = Callable[..., bool]


def normalize_eval_text(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s./\-]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def eval_digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", (s or "").replace(",", ".").replace(" ", ""))


def chunks_for_run(included_docs: List[Any], *, max_chars: int = 2500) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, doc in enumerate(included_docs or []):
        text = str(getattr(doc, "page_content", None) or "")
        meta = getattr(doc, "metadata", None) or {}
        rows.append(
            {
                "index": i,
                "chars": len(text),
                "source_page": meta.get("source_page"),
                "source_section": meta.get("source_section"),
                "text": text[:max_chars] + ("…" if len(text) > max_chars else ""),
            }
        )
    return rows


def gold_signal_in_text(gold: str, qid: str, text: str) -> bool:
    g = (gold or "").strip()
    if not g or g.upper() in {"N/A", "NA", "Н/Д"}:
        return False
    t_norm = normalize_eval_text(text)
    if qid == "inn_smart_city":
        return eval_digits(g) in re.sub(r"\D", "", text)
    if qid in {
        "rent_or_buyout_amount",
        "case_number",
        "contract_number",
        "amount",
        "payee_inn",
        "pp_number",
    }:
        gd = eval_digits(g)
        if gd and gd in re.sub(r"\D", "", text):
            return True
        return normalize_eval_text(g) in t_norm or gd in t_norm.replace(" ", "")
    if normalize_eval_text(g) in t_norm:
        return True
    gn = normalize_eval_text(g)
    return len(gn) >= 4 and gn in t_norm


def gold_in_context(
    gold: str,
    qid: str,
    included_docs: List[Any],
    context_text: str,
) -> Dict[str, Any]:
    g_na = (gold or "").strip().upper() in {"N/A", "NA", "Н/Д"}
    corpus = context_text or ""
    if not corpus and included_docs:
        corpus = "\n\n".join(str(getattr(d, "page_content", "") or "") for d in included_docs)
    chunk_hits: List[int] = []
    for row in chunks_for_run(included_docs, max_chars=999999):
        if gold_signal_in_text(gold, qid, row["text"]):
            chunk_hits.append(int(row["index"]))
    in_full = gold_signal_in_text(gold, qid, corpus) if not g_na else False
    return {
        "gold_in_any_chunk": bool(chunk_hits),
        "gold_chunk_indices": chunk_hits,
        "gold_in_merged_context": in_full,
    }


def summarize_eval_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [r for r in results if r.get("gold") is not None]
    correct = sum(1 for r in scored if r["match"])
    by_diff: Dict[str, Dict[str, int]] = defaultdict(lambda: {"n": 0, "ok": 0, "na": 0})
    by_q: Dict[str, Dict[str, int]] = defaultdict(lambda: {"n": 0, "ok": 0, "na": 0})
    for r in scored:
        d = r["difficulty"]
        by_diff[d]["n"] += 1
        by_diff[d]["ok"] += int(r["match"])
        by_diff[d]["na"] += int(r["na"])
        by_q[r["question"]]["n"] += 1
        by_q[r["question"]]["ok"] += int(r["match"])
        by_q[r["question"]]["na"] += int(r["na"])
    return {
        "scored": len(scored),
        "correct": correct,
        "accuracy": round(correct / len(scored), 4) if scored else 0.0,
        "na_count": sum(1 for r in scored if r["na"]),
        "by_difficulty": dict(by_diff),
        "by_question": dict(by_q),
    }


async def run_tabular_eval_matrix(
    *,
    case_id: str,
    files_by_id: Dict[str, Any],
    gold_pack: Dict[str, Any],
    match_fn: MatchFn,
) -> List[Dict[str, Any]]:
    """
    Run gold_pack documents × questions through ``run_tabular_cell_extraction``.
    """
    from app.models.case import File
    from app.services.llm_factory import create_llm
    from app.services.rag_service import RAGService
    from app.services.tabular_cell_payload import build_tabular_cell_db_payload
    from app.services.tabular_cell_pipeline import (
        docs_for_cell_geometry,
        run_tabular_cell_extraction,
    )
    from app.services.tabular_column_run_context import TabularColumnRunContext
    from app.services.tabular_column_type_contract import finalize_extraction_dict
    from app.services.tabular_search_query_rewrite import rewrite_tabular_search_query
    from app.services.yandex_embeddings import get_yandex_embeddings
    from app.utils.database import SessionLocal

    llm = create_llm(temperature=0.0, max_tokens=700)
    rag = RAGService()
    emb = get_yandex_embeddings()
    questions = gold_pack["questions"]
    gold = gold_pack["gold"]
    results: List[Dict[str, Any]] = []

    file_context_packages: Dict[str, Any] = {}
    prep_db = SessionLocal()
    try:
        from app.services.tabular_document_context import (
            prepare_file_context_packages,
            tabular_dcp_enabled,
        )

        if tabular_dcp_enabled():
            file_ids = [str(files_by_id[d["id"]].id) for d in gold_pack["documents"]]
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

    def normalize_fn(d, column, file):
        return finalize_extraction_dict(
            d,
            column_type=str(column.column_type),
            column_config=column.column_config
            if isinstance(getattr(column, "column_config", None), dict)
            else None,
        )

    for doc in gold_pack["documents"]:
        doc_id = doc["id"]
        file_model = files_by_id[doc_id]
        for q in questions:
            qid = q["id"]
            gold_val = gold[doc_id][qid]
            column = SimpleNamespace(
                id=f"ru-{qid}",
                prompt=q["prompt"],
                column_label=q["label"],
                column_type=q["column_type"],
                column_config={},
                tag_options=None,
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
                pipeline = await run_tabular_cell_extraction(
                    llm,
                    rag_service=rag,
                    file=f,
                    column=column,
                    normalize_fn=normalize_fn,
                    column_run=run,
                    db=None,
                    file_context_packages=file_context_packages,
                )
                extraction = pipeline.extraction
                verification = pipeline.verification
                prepared = pipeline.prepared
                ctx = prepared.context_text or ""
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
                ok = match_fn(pred, gold_val, qid=qid)
                na = (not pred.strip()) or pred.strip().upper() in {"N/A", "NA"}
                gold_ctx = gold_in_context(
                    gold_val, qid, prepared.included_docs, ctx
                )
                mark = "OK" if ok else "MISS"
                print(
                    f"  [{mark}] {doc_id} | {q['label']} ({q['difficulty']}): "
                    f"pred={pred!r} gold={gold_val!r}",
                    flush=True,
                )
                results.append(
                    {
                        "doc_id": doc_id,
                        "doc_label": doc["label"],
                        "question_id": qid,
                        "question": q["label"],
                        "difficulty": q["difficulty"],
                        "column_type": q["column_type"],
                        "gold": gold_val,
                        "predicted": pred,
                        "match": ok,
                        "na": na,
                        "forced_na": bool(verification.forced_na),
                        "n_refs": len(payload.get("source_references") or []),
                        "extraction_method": getattr(extraction, "extraction_method", None),
                        "verbatim_extract": (extraction.verbatim_extract or None),
                        "search_query": run.search_query,
                        "n_chunks": len(prepared.included_docs or []),
                        "context_chars": len(ctx or ""),
                        **gold_ctx,
                        "chunks": chunks_for_run(prepared.included_docs),
                    }
                )
            finally:
                db.close()
    return results
