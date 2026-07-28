#!/usr/bin/env python3
"""
RU tabular mini-eval: SS↔KOB case docs × mixed-difficulty questions.

Uses the same tabular cell pipeline as production (light ingest + extract).
Gold: evals/ru_ss_kob/gold.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD_PATH = REPO / "evals" / "ru_ss_kob" / "gold.json"
TEXT_DIR = REPO / "evals" / "ru_ss_kob" / "raw_text"


def _normalize(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s./\-]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def _yn_token(s: str) -> str:
    n = _normalize(s)
    if n in {"yes", "y", "true", "да"}:
        return "yes"
    if n in {"no", "n", "false", "нет"}:
        return "no"
    return n


def _digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", (s or "").replace(",", ".").replace(" ", ""))


def _chunks_for_run(included_docs: List[Any], *, max_chars: int = 2500) -> List[Dict[str, Any]]:
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


def _gold_signal_in_text(gold: str, qid: str, text: str) -> bool:
    g = (gold or "").strip()
    if not g or g.upper() in {"N/A", "NA", "Н/Д"}:
        return False
    t_norm = _normalize(text)
    if qid == "inn_smart_city":
        return _digits(g) in re.sub(r"\D", "", text)
    if qid in {"rent_or_buyout_amount", "case_number", "contract_number", "amount", "payee_inn", "pp_number"}:
        gd = _digits(g)
        if gd and gd in re.sub(r"\D", "", text):
            return True
        return _normalize(g) in t_norm or gd in t_norm.replace(" ", "")
    if _normalize(g) in t_norm:
        return True
    gn = _normalize(g)
    return len(gn) >= 4 and gn in t_norm


def _gold_in_context(gold: str, qid: str, included_docs: List[Any], context_text: str) -> Dict[str, Any]:
    g_na = (gold or "").strip().upper() in {"N/A", "NA", "Н/Д"}
    corpus = context_text or ""
    if not corpus and included_docs:
        corpus = "\n\n".join(str(getattr(d, "page_content", "") or "") for d in included_docs)
    chunk_hits: List[int] = []
    for row in _chunks_for_run(included_docs, max_chars=999999):
        if _gold_signal_in_text(gold, qid, row["text"]):
            chunk_hits.append(int(row["index"]))
    in_full = _gold_signal_in_text(gold, qid, corpus) if not g_na else False
    return {
        "gold_in_any_chunk": bool(chunk_hits),
        "gold_chunk_indices": chunk_hits,
        "gold_in_merged_context": in_full,
    }


def ru_match(predicted: str, gold: str, *, qid: str) -> bool:
    g = (gold or "").strip()
    p = (predicted or "").strip()
    if not g:
        return False
    g_na = g.upper() in {"N/A", "NA", "Н/Д"}
    p_na = (not p) or p.upper() in {"N/A", "NA", "Н/Д", "—", "-"}
    if g_na:
        return p_na
    if p_na:
        # For penalty_01 gold «Нет», empty/N/A is acceptable (topic absent).
        if qid == "penalty_01" and _yn_token(g) == "no":
            return True
        return False
    if _normalize(p) == _normalize(g):
        return True
    if _yn_token(p) == _yn_token(g) and _yn_token(g) in {"yes", "no"}:
        return True
    gn, pn = _normalize(g), _normalize(p)
    if len(gn) >= 4 and (gn in pn or pn in gn):
        return True
    # INN / amounts / case numbers: digit-core match
    if qid in {"inn_smart_city", "rent_or_buyout_amount", "case_number", "contract_number"}:
        gd, pd = _digits(g), _digits(p)
        if gd and pd and (gd in pd or pd in gd):
            return True
    # Dates: compare digit cores YYYYMMDD-ish
    if qid == "doc_date":
        gd, pd = re.sub(r"\D", "", g), re.sub(r"\D", "", p)
        if len(gd) >= 8 and len(pd) >= 8 and gd[:8] == pd[:8]:
            return True
    # Doc type aliases
    if qid == "doc_type":
        aliases = [
            {"дополнительное соглашение", "дс", "доп соглашение", "доп. соглашение"},
            {"письмо", "уведомление", "письмо уведомление", "письмо-уведомление"},
            {"претензия"},
            {"встречное исковое заявление", "встречный иск", "исковое заявление"},
            {"таблица расчетов", "таблица расчётов", "расчет", "расчёт"},
        ]
        for group in aliases:
            if any(a in gn for a in group) and any(a in pn for a in group):
                return True
    return False


def light_index(db, *, document_processor, case_id: str, file_model, text: str) -> None:
    from langchain_core.documents import Document

    from app.services.file_char_basis import resolve_ingest_original_text

    file_id = str(file_model.id)
    filename = str(file_model.filename or "doc.txt")
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
    file_documents, citation_text, _ = resolve_ingest_original_text(
        file_documents, loader_text=text
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


def ensure_case(db, *, user_id: str, title: str) -> str:
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
        description="RU SS-KOB tabular mini-eval",
        case_type="dd",
        status="completed",
        full_text="ru_ss_kob",
        num_documents=0,
        file_names=[],
    )
    db.add(case)
    db.commit()
    return str(case.id)


def ensure_file(db, *, case_id: str, filename: str, text: str, force: bool) -> Any:
    from app.models.case import File

    existing = (
        db.query(File).filter(File.case_id == case_id, File.filename == filename).first()
    )
    if (
        existing
        and (existing.original_text or "").strip()
        and existing.processing_status == "ready"
        and not force
    ):
        return existing
    if existing:
        existing.file_content = text.encode("utf-8")
        existing.processing_status = "pending"
        db.commit()
        return existing
    fm = File(
        id=str(uuid.uuid4()),
        case_id=case_id,
        filename=filename,
        file_type="txt",
        file_content=text.encode("utf-8"),
        processing_status="pending",
        original_text=" ",
    )
    db.add(fm)
    db.commit()
    return fm


async def run_matrix(
    *,
    case_id: str,
    files_by_id: Dict[str, Any],
    gold_pack: Dict[str, Any],
) -> List[Dict[str, Any]]:
    from app.models.case import File
    from app.services.llm_factory import create_llm
    from app.services.rag_service import RAGService
    from app.services.tabular_cell_payload import build_tabular_cell_db_payload
    from app.services.tabular_cell_pipeline import (
        augment_context_for_column,
        cell_retrieval_params_from_models,
        docs_for_cell_geometry,
        invoke_structured_cell_extraction,
        prepare_cell_retrieval_sync,
    )
    from app.services.tabular_cell_verification import apply_evidence_first_policy
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
                file_ctx = file_context_packages.get(str(f.id))
                params = cell_retrieval_params_from_models(
                    f, column, column_run=run, file_context=file_ctx
                )
                prepared = prepare_cell_retrieval_sync(rag, params=params)
                ctx = augment_context_for_column(
                    prepared.context_text,
                    column_type=q["column_type"],
                    original_text=str(f.original_text or ""),
                )
                extraction = await invoke_structured_cell_extraction(
                    llm,
                    column=column,
                    context_text=ctx,
                    normalize_fn=normalize_fn,
                    file=f,
                )
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
                ok = ru_match(pred, gold_val, qid=qid)
                na = (not pred.strip()) or pred.strip().upper() in {"N/A", "NA"}
                gold_ctx = _gold_in_context(
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
                        "chunks": _chunks_for_run(prepared.included_docs),
                    }
                )
            finally:
                db.close()
    return results


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--case-id", default="")
    parser.add_argument(
        "--out",
        default=str(REPO / "evals" / "ru_ss_kob" / "ru_ss_kob_tabular_run.json"),
    )
    args = parser.parse_args()

    gold_pack = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    t0 = time.time()

    from app.services.document_processor import get_document_processor
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).first()
        if not user:
            raise SystemExit("No users in DB")
        user_id = str(user.id)
        title = gold_pack.get("case_title") or "RU tabular SS-KOB May 2024"
        case_id = args.case_id.strip() or ensure_case(db, user_id=user_id, title=title)
        print(f"case_id={case_id}", flush=True)

        dp = get_document_processor()
        files_by_id: Dict[str, Any] = {}
        for doc in gold_pack["documents"]:
            txt_path = TEXT_DIR / doc["filename"]
            if not txt_path.is_file():
                raise SystemExit(f"Missing text: {txt_path}")
            text = txt_path.read_text(encoding="utf-8")
            fname = f"ru_{doc['id']}.txt"
            print(f"Prepare {fname} ({len(text)} chars)...", flush=True)
            fm = ensure_file(
                db,
                case_id=case_id,
                filename=fname,
                text=text,
                force=args.force_reindex,
            )
            needs = (
                args.force_reindex
                or not (fm.original_text or "").strip()
                or fm.processing_status != "ready"
            )
            if needs and not args.skip_index:
                light_index(
                    db,
                    document_processor=dp,
                    case_id=case_id,
                    file_model=fm,
                    text=text,
                )
            files_by_id[doc["id"]] = fm

        from app.services.bm25_case_prewarm import finalize_case_bm25_after_ingestion

        finalize_case_bm25_after_ingestion(case_id, dp)
    finally:
        db.close()

    n_docs = len(gold_pack["documents"])
    n_q = len(gold_pack["questions"])
    print(f"Running {n_docs}×{n_q} extractions...", flush=True)
    results = asyncio.run(
        run_matrix(case_id=case_id, files_by_id=files_by_id, gold_pack=gold_pack)
    )
    summary = summarize(results)
    elapsed = round(time.time() - t0, 1)

    from app.config import config

    payload = {
        "case_id": case_id,
        "gold_path": str(GOLD_PATH),
        "elapsed_sec": elapsed,
        "flags": {
            "COMPILER": str(getattr(config, "TABULAR_CONTEXT_COMPILER_ENABLED", False)),
            "DCP": str(getattr(config, "TABULAR_DCP_ENABLED", False)),
            "ROUTER": str(getattr(config, "TABULAR_SECTION_ROUTER_ENABLED", False)),
            "QUOTE_THEN_ANSWER": str(getattr(config, "TABULAR_QUOTE_THEN_ANSWER", True)),
            "EVIDENCE_REQUIRED": str(getattr(config, "TABULAR_EVIDENCE_REQUIRED", True)),
        },
        **summary,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"=== RU {n_docs}×{n_q}: {summary['correct']}/{summary['scored']} = "
        f"{summary['accuracy']:.1%} N/A={summary['na_count']} elapsed {elapsed}s -> {out}",
        flush=True,
    )
    print("By difficulty:", flush=True)
    for d, st in summary["by_difficulty"].items():
        acc = st["ok"] / st["n"] if st["n"] else 0
        print(f"  {d}: {st['ok']}/{st['n']} = {acc:.0%} (NA {st['na']})", flush=True)
    print("By question:", flush=True)
    for q, st in summary["by_question"].items():
        acc = st["ok"] / st["n"] if st["n"] else 0
        print(f"  {q}: {st['ok']}/{st['n']} = {acc:.0%} (NA {st['na']})", flush=True)


if __name__ == "__main__":
    main()
