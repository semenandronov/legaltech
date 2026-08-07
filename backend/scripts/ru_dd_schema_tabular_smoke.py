#!/usr/bin/env python3
"""
Full tabular smoke for RU DD schema packs (phase 6).

Uses production ``run_tabular_cell_extraction`` via ``tabular_eval_runner``.
Requires DB + embeddings (+ LLM for non-schema cells).

  python scripts/ru_dd_schema_tabular_smoke.py --pack lease
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ru_dd_schema_eval import schema_match  # noqa: E402


def load_pack(pack: str) -> Dict[str, Any]:
    path = REPO / "evals" / f"ru_{pack}" / "gold.json"
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_text(doc: Dict[str, Any], pack: str) -> str:
    if doc.get("text_path"):
        return (REPO / doc["text_path"]).read_text(encoding="utf-8")
    pack_dir = REPO / "evals" / f"ru_{pack}" / "raw_text"
    return (pack_dir / doc["filename"]).read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", choices=["lease", "supply", "services"], required=True)
    parser.add_argument("--force-reindex", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    import ru_ss_kob_tabular_smoke as kob

    gold_pack = load_pack(args.pack)
    # Adapt questions for tabular_eval_runner (needs column_type/prompt/label/difficulty)
    for q in gold_pack["questions"]:
        q.setdefault("difficulty", "medium")
        cfg = {
            "field_id": q.get("field_id") or q["id"],
            "column_kind": q.get("column_kind") or "fact",
        }
        q["column_config"] = cfg

    def match_fn(predicted: str, gold: str, *, qid: str) -> bool:
        field_id = qid
        for q in gold_pack["questions"]:
            if q["id"] == qid:
                field_id = q.get("field_id") or qid
                break
        return schema_match(predicted, gold, field_id=str(field_id))

    t0 = time.time()
    from app.services.document_processor import get_document_processor
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).first()
        if not user:
            raise SystemExit("No users in DB")
        title = gold_pack.get("case_title") or f"RU DD {args.pack}"
        case_id = kob.ensure_case(db, user_id=str(user.id), title=title)
        dp = get_document_processor()
        files_by_id: Dict[str, Any] = {}
        for doc in gold_pack["documents"]:
            text = resolve_text(doc, args.pack)
            fname = f"ru_dd_{args.pack}_{doc['id']}.txt"
            fm = kob.ensure_file(
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
            if needs:
                kob.light_index(
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

    # Inject column_config into eval runner columns via match override + local matrix patch
    from app.services.tabular_eval_runner import run_tabular_eval_matrix, summarize_eval_results

    # Patch: gold questions need column_config on SimpleNamespace — extend runner call
    # by temporarily wrapping match and using custom matrix loop if needed.
    # For now, rewrite questions into runner-compatible shape and monkeypatch
    # run_tabular_eval_matrix's column construction via local copy of questions with config
    # stored in prompt side-channel — better: update eval runner to pass column_config.

    async def _run():
        from types import SimpleNamespace

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
        from app.services.tabular_eval_runner import chunks_for_run, gold_in_context
        from app.services.tabular_search_query_rewrite import rewrite_tabular_search_query
        from app.services.yandex_embeddings import get_yandex_embeddings
        from app.utils.database import SessionLocal as SL

        llm = create_llm(temperature=0.0, max_tokens=700)
        rag = RAGService()
        emb = get_yandex_embeddings()
        results = []

        def normalize_fn(d, column, file):
            return finalize_extraction_dict(
                d,
                column_type=str(column.column_type),
                column_config=column.column_config
                if isinstance(getattr(column, "column_config", None), dict)
                else None,
            )

        for doc in gold_pack["documents"]:
            file_model = files_by_id[doc["id"]]
            for q in gold_pack["questions"]:
                qid = q["id"]
                gold_val = gold_pack["gold"][doc["id"]][qid]
                column = SimpleNamespace(
                    id=f"ru-{qid}",
                    prompt=q["prompt"],
                    column_label=q["label"],
                    column_type=q["column_type"],
                    column_config={
                        "field_id": q.get("field_id") or qid,
                        "column_kind": q.get("column_kind") or "fact",
                    },
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
                sdb = SL()
                try:
                    f = sdb.query(File).filter(File.id == file_model.id).one()
                    pipeline = await run_tabular_cell_extraction(
                        llm,
                        rag_service=rag,
                        file=f,
                        column=column,
                        normalize_fn=normalize_fn,
                        column_run=run,
                        db=None,
                    )
                    extraction = pipeline.extraction
                    verification = pipeline.verification
                    prepared = pipeline.prepared
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
                    method = getattr(extraction, "extraction_method", None)
                    print(
                        f"  [{'OK' if ok else 'MISS'}] {doc['id']} | {q['label']}: "
                        f"pred={pred!r} gold={gold_val!r} method={method}",
                        flush=True,
                    )
                    results.append(
                        {
                            "doc_id": doc["id"],
                            "question_id": qid,
                            "question": q["label"],
                            "difficulty": q.get("difficulty") or "medium",
                            "gold": gold_val,
                            "predicted": pred,
                            "match": ok,
                            "na": (not pred.strip()) or pred.strip().upper() in {"N/A", "NA"},
                            "forced_na": bool(verification.forced_na),
                            "schema_hit": method == "contract_facts",
                            "extraction_method": method,
                            "context_chars": len(prepared.context_text or ""),
                            **gold_in_context(
                                gold_val, qid, prepared.included_docs, prepared.context_text or ""
                            ),
                            "chunks": chunks_for_run(prepared.included_docs),
                        }
                    )
                finally:
                    sdb.close()
        return results

    print(f"Running RU DD pack={args.pack}...", flush=True)
    results = asyncio.run(_run())
    summary = summarize_eval_results(results)
    schema_hits = sum(1 for r in results if r.get("schema_hit"))
    summary["schema_hit_rate"] = (
        round(schema_hits / len(results), 4) if results else 0.0
    )
    summary["forced_na_rate"] = (
        round(sum(1 for r in results if r.get("forced_na")) / len(results), 4)
        if results
        else 0.0
    )
    elapsed = round(time.time() - t0, 1)
    out = Path(
        args.out
        or str(REPO / "evals" / f"ru_{args.pack}" / f"ru_{args.pack}_tabular_run.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pack": args.pack,
        "case_id": case_id,
        "elapsed_sec": elapsed,
        **summary,
        "results": results,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"=== {args.pack}: {summary['correct']}/{summary['scored']} = "
        f"{summary['accuracy']:.1%} schema_hit={summary['schema_hit_rate']:.0%} "
        f"forced_na={summary['forced_na_rate']:.0%} -> {out}",
        flush=True,
    )


if __name__ == "__main__":
    main()
