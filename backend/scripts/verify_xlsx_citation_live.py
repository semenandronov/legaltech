#!/usr/bin/env python3
"""Live verification: upload Excel → ask assistant → check citation open + row highlight."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = REPO_ROOT / "frontend"
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env")

XLSX = Path("/Users/semyon_andronov04/Downloads/Справка о движении средств.pdf_фильтр_9.xlsx")
OUT = BACKEND_ROOT / "evals" / "xlsx_citation_live_verify.json"

QUESTIONS = [
    "Сколько операций в выписке и какие они по сумме?",
    "Найди операцию кэшбэк за покупки в Городе и назови сумму.",
    "Какие платы за оповещения об операциях есть в файле? Укажи даты и суммы.",
]


def _parse_sse(events: list[str]) -> dict[str, Any]:
    text_parts: list[str] = []
    content_sync = ""
    citations: list = []
    for raw in events:
        if not raw.startswith("data: "):
            continue
        try:
            payload = json.loads(raw.replace("data: ", "", 1).strip())
        except json.JSONDecodeError:
            continue
        t = payload.get("type")
        if t in ("text-delta", "text_delta"):
            text_parts.append(
                str(
                    payload.get("textDelta")
                    or payload.get("text_delta")
                    or payload.get("content")
                    or payload.get("text")
                    or ""
                )
            )
        elif t == "content_sync":
            content_sync = str(payload.get("content") or payload.get("text") or "")
        elif t == "citations":
            citations = list(payload.get("citations") or [])
    streamed = "".join(text_parts).strip()
    return {"response": (content_sync or streamed).strip(), "citations": citations}


class _RowCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[Dict[str, str]] = []
        self._cur: Optional[Dict[str, Any]] = None
        self._buf: List[str] = []

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        attrs_d = dict(attrs)
        if tag == "tr":
            self._cur = {"data_row": attrs_d.get("data-row") or "", "has_td": False}
            self._buf = []
        if tag == "td" and self._cur is not None:
            self._cur["has_td"] = True

    def handle_data(self, data: str) -> None:
        if self._cur is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._cur is not None:
            if self._cur.get("has_td"):
                self.rows.append(
                    {
                        "data_row": str(self._cur.get("data_row") or ""),
                        "text": "".join(self._buf),
                    }
                )
            self._cur = None
            self._buf = []


def _looks_whole_sheet_quote(text: str) -> bool:
    raw = (text or "").strip()
    if len(raw) < 80:
        return False
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    labeled = sum(1 for ln in lines if ":" in ln)
    # Structured row chunks are mostly "Col: value" — not whole-sheet dumps.
    if lines and labeled >= max(3, int(len(lines) * 0.6)):
        return False
    t = re.sub(r"\s+", " ", raw)
    header_hits = sum(
        1
        for h in (
            "Номер карты",
            "Дата списания",
            "Описание операции",
            "Сумма в валюте",
            "Операции №",
        )
        if h.lower() in t.lower()
    )
    return header_hits >= 2


def _uuidish(value: Any) -> bool:
    s = str(value or "").strip()
    if len(s) < 8:
        return False
    if re.fullmatch(r"doc_?\d+", s, flags=re.I):
        return False
    return True


async def _ask(db, user, case_id: str, question: str) -> dict[str, Any]:
    from app.services.chat.case_chat_request_prep import CaseChatPrepParams, prepare_case_chat_request
    from app.services.chat.orchestrator import ChatOrchestrator

    session_id = str(uuid.uuid4())
    prep = prepare_case_chat_request(
        db,
        CaseChatPrepParams(
            case_id=case_id,
            question=question,
            current_user=user,
            session_id=session_id,
            draft_mode=False,
            legal_research=False,
            deep_think=False,
            court_practice=False,
        ),
    )
    req = prep.chat_request
    req.session_id = session_id
    orch = ChatOrchestrator(db=db)
    events: list[str] = []
    async for ev in orch.process_request(req):
        events.append(ev)
    parsed = _parse_sse(events)
    return {
        "question": question,
        "session_id": session_id,
        "response": parsed["response"],
        "citations": parsed["citations"],
    }


def _score_highlights_with_ts(payload: dict[str, Any]) -> List[dict[str, Any]]:
    fixture = Path("/tmp/xlsx_live_cite_score_in.json")
    out = Path("/tmp/xlsx_live_cite_score_out.json")
    fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        ["npx", "--yes", "tsx", "scripts/score_xlsx_live_cites.mts"],
        cwd=str(FRONTEND_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"TS scorer failed: rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return json.loads(out.read_text(encoding="utf-8"))


async def main() -> int:
    if not XLSX.is_file():
        print(f"ERROR: missing {XLSX}")
        return 1

    from app import config as config_module
    from app.models.case import Case, File as FileModel
    from app.models.case_file_transaction import CaseFileTransaction
    from app.models.user import User
    from app.services.case_file_ingest import persist_case_file_bytes
    from app.services.document_converter_service import DocumentConverterService
    from app.services.file_processor_bg import process_files_background
    from app.utils.database import SessionLocal

    config_module.config.CASE_FILE_TRANSACTIONS_ENABLED = True

    db = SessionLocal()
    report: Dict[str, Any] = {"file": str(XLSX), "questions": []}
    try:
        user = db.query(User).first()
        if not user:
            print("ERROR: no users in DB")
            return 1

        case = Case(
            user_id=user.id,
            title=f"xlsx-citation-verify-{uuid.uuid4().hex[:8]}",
            description="live citation open+highlight verification",
            full_text="",
            file_names=[XLSX.name],
            num_documents=1,
        )
        db.add(case)
        db.flush()

        content = XLSX.read_bytes()
        ingested = persist_case_file_bytes(
            db,
            case_id=case.id,
            filename=XLSX.name,
            content=content,
            reconnect_db=lambda _db: None,
        )
        db.commit()
        file_id = ingested.file_id
        print(f"CASE={case.id}")
        print(f"FILE={file_id}")
        print("INGEST: processing…")
        process_files_background([file_id], case.id)

        db.expire_all()
        frow = db.query(FileModel).filter(FileModel.id == file_id).first()
        tx_count = (
            db.query(CaseFileTransaction)
            .filter(CaseFileTransaction.file_id == file_id)
            .count()
        )
        print(
            f"INGEST_DONE status={getattr(frow, 'processing_status', None)} "
            f"tx_rows={tx_count}"
        )
        report["case_id"] = case.id
        report["file_id"] = file_id
        report["ingest"] = {
            "status": getattr(frow, "processing_status", None),
            "tx_rows": tx_count,
        }
        if getattr(frow, "processing_status", None) != "ready":
            report["error"] = "file_not_ready"
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 2

        html = DocumentConverterService().convert_to_html(content, XLSX.name, "xlsx")
        parser = _RowCollector()
        parser.feed(html)
        row_texts = [r["text"] for r in parser.rows]
        data_rows = [r["data_row"] for r in parser.rows]
        report["html_data_rows"] = len(row_texts)

        score_citations: List[dict[str, Any]] = []
        for qi, q in enumerate(QUESTIONS):
            print(f"\nASK[{qi+1}]: {q}")
            ans = await _ask(db, user, case.id, q)
            cites = ans["citations"]
            print(f"  citations={len(cites)} answer_chars={len(ans['response'])}")
            print(f"  preview={ans['response'][:240]!r}")

            checks: List[dict[str, Any]] = []
            for ci, c in enumerate(cites):
                key = f"q{qi}-c{ci}"
                quote = str(c.get("quote") or "")
                anchor = str(c.get("quote_anchor") or "")
                targets = c.get("highlight_targets") or []
                source_id = str(c.get("source_id") or "")
                file_name = str(c.get("file_name") or c.get("filename") or "")
                can_open = _uuidish(source_id) and source_id == file_id
                whole_sheet = _looks_whole_sheet_quote(quote) or _looks_whole_sheet_quote(anchor)
                check = {
                    "key": key,
                    "citation_id": c.get("citation_id"),
                    "source_id": source_id,
                    "file_name": file_name,
                    "quote_preview": (quote or anchor)[:180],
                    "quote_anchor": anchor[:120],
                    "highlight_targets_head": list(targets)[:4] if isinstance(targets, list) else [],
                    "is_whole_sheet_quote": whole_sheet,
                    "can_open_document": can_open,
                    "has_highlight_targets": bool(targets),
                }
                checks.append(check)
                score_citations.append(
                    {
                        "key": key,
                        "quote": quote,
                        "quote_anchor": anchor,
                        "highlight_targets": targets if isinstance(targets, list) else [],
                    }
                )
                print(
                    f"  cite[{ci}] open={can_open} whole_sheet={whole_sheet} "
                    f"targets={len(targets) if isinstance(targets, list) else 0} "
                    f"anchor={anchor[:60]!r}"
                )

            report["questions"].append(
                {
                    "question": q,
                    "response_preview": ans["response"][:600],
                    "citations_count": len(cites),
                    "citation_checks": checks,
                }
            )

        print("\nSCORING row highlights via production TS…")
        scored = _score_highlights_with_ts(
            {
                "row_texts": row_texts,
                "data_rows": data_rows,
                "citations": score_citations,
            }
        )
        by_key = {s["key"]: s for s in scored}
        for qblock in report["questions"]:
            for check in qblock["citation_checks"]:
                s = by_key.get(check["key"]) or {}
                check["highlight_row_found"] = bool(s.get("ok"))
                check["picked_data_row"] = s.get("picked_data_row")
                check["highlight_hits"] = s.get("hits")
                check["highlight_unique_hits"] = s.get("uniqueHits")
                check["pass_open_and_highlight"] = bool(
                    check["can_open_document"]
                    and check["highlight_row_found"]
                    and check["has_highlight_targets"]
                )

        flat = [
            c
            for q in report["questions"]
            for c in q["citation_checks"]
        ]
        report["summary"] = {
            "questions": len(report["questions"]),
            "citations_total": len(flat),
            "can_open_document": sum(1 for c in flat if c["can_open_document"]),
            "highlight_row_found": sum(1 for c in flat if c.get("highlight_row_found")),
            "whole_sheet_quotes": sum(1 for c in flat if c["is_whole_sheet_quote"]),
            "pass_open_and_highlight": sum(1 for c in flat if c.get("pass_open_and_highlight")),
            "fail_open_and_highlight": sum(1 for c in flat if not c.get("pass_open_and_highlight")),
        }

        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n=== SUMMARY ===")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print(f"report: {OUT}")
        return 0 if report["summary"]["fail_open_and_highlight"] == 0 and flat else 3
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
