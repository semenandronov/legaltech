#!/usr/bin/env python3
"""
RU tabular mini-eval: SS↔KOB case docs × mixed-difficulty questions.

Uses the same tabular cell pipeline as production (light ingest + ``run_tabular_cell_extraction``).
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
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD_PATH = REPO / "evals" / "ru_ss_kob" / "gold.json"
TEXT_DIR = REPO / "evals" / "ru_ss_kob" / "raw_text"


def _normalize(s: str) -> str:
    from app.services.tabular_eval_runner import normalize_eval_text

    return normalize_eval_text(s)


def _digits(s: str) -> str:
    from app.services.tabular_eval_runner import eval_digits

    return eval_digits(s)


def _yn_token(s: str) -> str:
    n = _normalize(s)
    if n in {"yes", "y", "true", "да"}:
        return "yes"
    if n in {"no", "n", "false", "нет"}:
        return "no"
    return n


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
    try:
        from app.services.dd_document_classifier import (
            classify_dd_document,
            save_dd_classification_on_file,
        )

        save_dd_classification_on_file(
            file_model,
            classify_dd_document(text=citation_text, filename=filename),
        )
    except Exception:
        pass
    try:
        from app.services.contract_facts_service import (
            build_contract_facts_payload,
            contract_facts_enabled,
            save_contract_facts_on_file,
        )
        from app.services.dd_document_classifier import get_file_dd_doc_type

        if contract_facts_enabled():
            save_contract_facts_on_file(
                file_model,
                build_contract_facts_payload(
                    text=citation_text,
                    filename=filename,
                    dd_doc_type=get_file_dd_doc_type(file_model) or "unknown",
                    allow_llm=False,
                ),
            )
    except Exception:
        pass
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
    from app.services.tabular_eval_runner import run_tabular_eval_matrix

    match_fn = ru_match
    if getattr(run_matrix, "_match_override", None):
        match_fn = run_matrix._match_override  # type: ignore[attr-defined]
    return await run_tabular_eval_matrix(
        case_id=case_id,
        files_by_id=files_by_id,
        gold_pack=gold_pack,
        match_fn=match_fn,
    )


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    from app.services.tabular_eval_runner import summarize_eval_results

    return summarize_eval_results(results)


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
