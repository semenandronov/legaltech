#!/usr/bin/env python3
"""
RU tabular eval: 5 payment orders (PDF) via production ingest + tabular cell pipeline.

Gold: evals/ru_pp_5/gold.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD_PATH = REPO / "evals" / "ru_pp_5" / "gold.json"
PDF_DIR = REPO / "evals" / "ru_pp_5" / "pdfs"


def _normalize(s: str) -> str:
    t = (s or "").lower().replace("ё", "е")
    t = re.sub(r"[^\w\s./\-]", " ", t, flags=re.UNICODE)
    return " ".join(t.split())


def _digits(s: str) -> str:
    return re.sub(r"[^\d.]", "", (s or "").replace(",", ".").replace(" ", ""))


def pp_match(predicted: str, gold: str, *, qid: str) -> bool:
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
    if qid == "pp_number":
        return _digits(p) == _digits(g)
    if qid == "payment_date":
        gd, pd = re.sub(r"\D", "", g), re.sub(r"\D", "", p)
        return len(gd) >= 8 and len(pd) >= 8 and gd[:8] == pd[:8]
    if qid in {"amount", "payee_inn"}:
        gd, pd = _digits(g), _digits(p)
        if gd and pd:
            # Суммы: сравниваем целую часть (копейки в gold обычно нет)
            if qid == "amount":
                return gd.split(".")[0] == pd.split(".")[0]
            return gd == pd
        return False
    if qid == "contract_ref":
        gn, pn = _normalize(g), _normalize(p)
        return gn in pn or pn in gn or _normalize(g.replace("-", "/")) in pn
    if qid == "payment_kind":
        gn, pn = _normalize(g), _normalize(p)
        kind_map = {
            "транспорт": {"транспорт", "логист", "доставк", "экспедиц"},
            "аренда": {"аренд"},
            "коммунальные": {"коммунал", "коммунальн", "кому"},
        }
        for key, hints in kind_map.items():
            if key in gn or gn in key:
                return any(h in pn for h in hints)
        return gn in pn or pn in gn
    if qid in {"payer", "payee"}:
        gn, pn = _normalize(g), _normalize(p)
        # Фамилия + ключевые токены
        tokens = [t for t in gn.split() if len(t) >= 4]
        return tokens and sum(1 for t in tokens if t in pn) >= min(2, len(tokens))
    if _normalize(p) == _normalize(g):
        return True
    gn, pn = _normalize(g), _normalize(p)
    return len(gn) >= 4 and (gn in pn or pn in gn)


def _wait_files_ready(db, file_ids: List[str], *, timeout_sec: int = 900) -> None:
    from app.models.case import File

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        rows = db.query(File).filter(File.id.in_(file_ids)).all()
        if rows and all(f.processing_status == "ready" for f in rows):
            return
        if rows and any(f.processing_status == "failed" for f in rows):
            failed = [f.filename for f in rows if f.processing_status == "failed"]
            raise RuntimeError(f"ingest failed: {failed}")
        time.sleep(2)
    raise TimeoutError("ingest timeout")


def ingest_pdfs_main_path(
    db,
    *,
    case_id: str,
    gold_pack: Dict[str, Any],
    force: bool,
) -> Dict[str, Any]:
    """Stage PDFs under UPLOAD_DIR and run process_files_background (production path)."""
    from app.config import config
    from app.models.case import File
    from app.services.file_processor_bg import process_files_background

    upload_root = Path(config.UPLOAD_DIR)
    if not upload_root.is_absolute():
        upload_root = (ROOT / upload_root).resolve()
    case_dir = upload_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    files_by_id: Dict[str, Any] = {}
    to_process: List[str] = []

    for doc in gold_pack["documents"]:
        src = PDF_DIR / doc["filename"]
        if not src.is_file():
            raise SystemExit(f"Missing PDF: {src}")
        dest_name = doc["filename"]
        dest = case_dir / dest_name
        existing = (
            db.query(File)
            .filter(File.case_id == case_id, File.filename == dest_name)
            .first()
        )
        if existing and not force and existing.processing_status == "ready":
            files_by_id[doc["id"]] = existing
            print(f"  reuse {dest_name} status=ready", flush=True)
            continue

        shutil.copy2(src, dest)
        rel = f"{case_id}/{dest_name}"
        if existing:
            existing.file_path = rel
            existing.file_type = "pdf"
            existing.processing_status = "pending"
            existing.processing_error = None
            fm = existing
        else:
            fm = File(
                id=str(uuid.uuid4()),
                case_id=case_id,
                filename=dest_name[:255],
                file_type="pdf",
                original_text="",
                file_path=rel,
                processing_status="pending",
            )
            db.add(fm)
        db.flush()
        files_by_id[doc["id"]] = fm
        to_process.append(str(fm.id))
        print(f"  queued {dest_name} id={fm.id}", flush=True)

    db.commit()

    if to_process:
        print(f"process_files_background ({len(to_process)} files)...", flush=True)
        process_files_background(to_process, case_id)
        _wait_files_ready(db, to_process)
        db.expire_all()
        for doc in gold_pack["documents"]:
            fm = (
                db.query(File)
                .filter(File.id == str(files_by_id[doc["id"]].id))
                .one()
            )
            files_by_id[doc["id"]] = fm
            n = len(fm.original_text or "")
            print(f"  ingested {fm.filename}: {n} chars status={fm.processing_status}", flush=True)
            if fm.processing_status != "ready":
                raise RuntimeError(f"not ready: {fm.filename}")

    from app.services.bm25_case_prewarm import finalize_case_bm25_after_ingestion
    from app.services.document_processor import get_document_processor

    finalize_case_bm25_after_ingestion(case_id, get_document_processor())
    return files_by_id


def ensure_case(db, *, user_id: str, title: str) -> str:
    from app.models.case import Case

    case = Case(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        description="RU PP tabular eval (5 payment orders)",
        case_type="dd",
        status="completed",
        full_text="ru_pp_5",
        num_documents=5,
        file_names=[],
    )
    db.add(case)
    db.commit()
    return str(case.id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", default="", help="Reuse existing case (skip ingest if ready)")
    parser.add_argument("--force-reindex", action="store_true", help="Re-run production ingest")
    parser.add_argument(
        "--out",
        default=str(REPO / "evals" / "ru_pp_5" / "ru_pp_tabular_run.json"),
    )
    args = parser.parse_args()

    import ru_ss_kob_tabular_smoke as kob_smoke

    kob_smoke.ru_match = pp_match  # type: ignore[misc]

    gold_pack = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    t0 = time.time()

    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        from app.models.case import File
        from app.models.user import User

        user = db.query(User).first()
        if not user:
            raise SystemExit("No users in DB")
        title = gold_pack.get("case_title") or "RU tabular PP×5"
        if args.case_id.strip():
            case_id = args.case_id.strip()
        else:
            case_id = ensure_case(db, user_id=str(user.id), title=title)
        print(f"case_id={case_id}", flush=True)

        if args.force_reindex or not args.case_id.strip():
            files_by_id = ingest_pdfs_main_path(
                db, case_id=case_id, gold_pack=gold_pack, force=args.force_reindex
            )
        else:
            files_by_id = {}
            for doc in gold_pack["documents"]:
                fm = (
                    db.query(File)
                    .filter(File.case_id == case_id, File.filename == doc["filename"])
                    .first()
                )
                if not fm or fm.processing_status != "ready":
                    files_by_id = ingest_pdfs_main_path(
                        db,
                        case_id=case_id,
                        gold_pack=gold_pack,
                        force=True,
                    )
                    break
                files_by_id[doc["id"]] = fm
    finally:
        db.close()

    n_docs = len(gold_pack["documents"])
    n_q = len(gold_pack["questions"])
    print(f"Running {n_docs}×{n_q} extractions...", flush=True)
    results = asyncio.run(
        kob_smoke.run_matrix(case_id=case_id, files_by_id=files_by_id, gold_pack=gold_pack)
    )
    summary = kob_smoke.summarize(results)
    elapsed = round(time.time() - t0, 1)

    from app.config import config

    payload = {
        "case_id": case_id,
        "gold_path": str(GOLD_PATH),
        "ingest": "process_files_background",
        "elapsed_sec": elapsed,
        "flags": {
            "QUOTE_THEN_ANSWER": str(getattr(config, "TABULAR_QUOTE_THEN_ANSWER", False)),
            "EVIDENCE_REQUIRED": str(getattr(config, "TABULAR_EVIDENCE_REQUIRED", True)),
        },
        **summary,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"=== PP {n_docs}×{n_q}: {summary['correct']}/{summary['scored']} = "
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
