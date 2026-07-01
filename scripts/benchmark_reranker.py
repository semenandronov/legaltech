#!/usr/bin/env python3
"""Benchmark case-assistant light/heavy reranker (load vs predict)."""
from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

CASE_ID = "bde0a4a1-7ebd-43e0-bebd-5308b852d910"
DEFAULT_QUESTION = "о чем выписка егрюл"
DEFAULT_POOL_SIZE = 16
DEFAULT_TOP_K = 6


def read_db_url(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    match = re.search(r'^DATABASE_URL\s*=\s*["\']?([^"\'#\n]+)', text, re.M)
    return match.group(1).strip() if match else None


def synthetic_egrul_docs(pool_size: int) -> List["Document"]:
    from langchain_core.documents import Document

    base = (
        "Выписка из Единого государственного реестра юридических лиц. "
        "Полное наименование: Общество с ограниченной ответственностью «Карусель Рус». "
        "ОГРН 1234567890123. ИНН 7701234567. КПП 770101001. "
        "Адрес: г. Москва, ул. Примерная, д. 1. "
        "Основной вид деятельности: 47.11 Торговля розничная в неспециализированных магазинах. "
        "Уставный капитал: 10000 руб. Генеральный директор: Иванов Иван Иванович. "
        "Статус: действующее. Дата регистрации: 15.03.2018. "
    )
    docs: List[Document] = []
    for i in range(pool_size):
        docs.append(
            Document(
                page_content=f"{base} Раздел {i + 1}. " + ("Дополнительные сведения о регистрации. " * 40),
                metadata={
                    "source_file": "Выписка из ЕГРЮЛ от 09.05.25 г. ООО Карусель Рус на 16 л.pdf",
                    "chunk_id": f"synthetic_{i}",
                    "chunk_level": "micro",
                    "combined_score": 0.02 - i * 0.0005,
                },
            )
        )
    return docs


def load_recall_pool_from_db(
    *,
    case_id: str,
    question: str,
    pool_size: int,
    db_url: str,
) -> Tuple[List["Document"], str]:
    import os

    os.environ["DATABASE_URL"] = db_url

    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine

    from app.services.document_processor import DocumentProcessor
    from app.services.rag_service import RAGService

    engine = create_engine(db_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine)
    rag = RAGService(DocumentProcessor())

    with session_factory() as db:
        docs = rag.retrieve_context(
            case_id=case_id,
            query=question,
            k=pool_size,
            retrieval_strategy="hybrid",
            db=db,
            use_hybrid=True,
            pipeline_micro_only=True,
        )
    docs = [d for d in (docs or []) if d is not None and getattr(d, "page_content", None)]
    return docs[:pool_size], "db_hybrid_recall"


def build_proxies(docs: List["Document"], max_chars: int) -> List["Document"]:
    from langchain_core.documents import Document

    from app.services.chat.rag_passage_utils import passage_for_rerank

    proxies: List[Document] = []
    for i, doc in enumerate(docs):
        md = dict(doc.metadata or {})
        md["_rerank_ix"] = i
        proxies.append(
            Document(
                page_content=passage_for_rerank(doc, max_chars),
                metadata=md,
            )
        )
    return proxies


def measure_predict(
    svc: "RerankerService",
    question: str,
    proxies: List["Document"],
    top_k: int,
) -> float:
    started = time.perf_counter()
    svc.rerank(question.strip(), proxies, top_k=max(1, min(top_k, len(proxies))))
    return (time.perf_counter() - started) * 1000


def benchmark_in_process(
    *,
    tier: str,
    question: str,
    docs: List["Document"],
    top_k: int,
    max_chars: int,
    warm_rounds: int,
    reset_singleton: bool = True,
) -> dict:
    import app.services.reranker_service as rerank_mod
    from app.services.reranker_service import get_reranker_for_tier

    if reset_singleton:
        rerank_mod._reranker = None
        rerank_mod._light_reranker = None

    load_started = time.perf_counter()
    svc = get_reranker_for_tier(tier)
    load_ms = (time.perf_counter() - load_started) * 1000

    proxies = build_proxies(docs, max_chars)
    avg_passage = statistics.mean(len(p.page_content or "") for p in proxies)

    predict_times: List[float] = []
    for _ in range(max(1, warm_rounds)):
        predict_times.append(measure_predict(svc, question, proxies, top_k))

    return {
        "tier": tier,
        "model": svc.model_name,
        "pool_size": len(proxies),
        "top_k": top_k,
        "max_chars": max_chars,
        "avg_passage_chars": round(avg_passage, 1),
        "load_ms": round(load_ms, 1),
        "predict_ms_first": round(predict_times[0], 1),
        "predict_ms_median": round(statistics.median(predict_times), 1),
        "predict_ms_all": [round(x, 1) for x in predict_times],
    }


def run_cold_subprocess(args: argparse.Namespace, source: str) -> dict:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--in-process-only",
        "--tier",
        args.tier,
        "--pool-size",
        str(args.pool_size),
        "--top-k",
        str(args.top_k),
        "--warm-rounds",
        "1",
        "--source",
        source,
        "--question",
        args.question,
    ]
    if args.db_url:
        cmd.extend(["--db-url", args.db_url])
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    import json

    return json.loads(proc.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark reranker load/predict latency")
    parser.add_argument("--tier", choices=("light", "heavy"), default="light")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--warm-rounds", type=int, default=5)
    parser.add_argument("--source", choices=("synthetic", "db", "auto"), default="auto")
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--in-process-only", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    from app.config import config

    max_chars = int(
        getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_MAX_CHARS", 900) or 900
        if args.tier == "light"
        else getattr(config, "CASE_ASSISTANT_RERANK_MAX_CHARS", 1200) or 1200
    )

    db_url = args.db_url or read_db_url(ROOT / ".env")
    source = args.source
    docs_source = "synthetic"
    docs = synthetic_egrul_docs(args.pool_size)

    if source in {"db", "auto"} and db_url:
        try:
            docs, docs_source = load_recall_pool_from_db(
                case_id=CASE_ID,
                question=args.question,
                pool_size=args.pool_size,
                db_url=db_url,
            )
        except Exception as exc:
            if source == "db":
                raise
            docs_source = f"synthetic (db failed: {exc})"
            docs = synthetic_egrul_docs(args.pool_size)
    if len(docs) < args.pool_size:
        docs = (docs + synthetic_egrul_docs(args.pool_size))[: args.pool_size]

    if args.in_process_only:
        result = benchmark_in_process(
            tier=args.tier,
            question=args.question,
            docs=docs,
            top_k=args.top_k,
            max_chars=max_chars,
            warm_rounds=args.warm_rounds,
        )
        result["docs_source"] = docs_source
        import json

        print(json.dumps(result, ensure_ascii=False))
        return

    print(f"Reranker benchmark — tier={args.tier}, pool={args.pool_size}, top_k={args.top_k}")
    print(f"Question: {args.question!r}")
    print(f"Docs source: {docs_source}")
    print()

    cold = run_cold_subprocess(args, source=args.source)
    warm = benchmark_in_process(
        tier=args.tier,
        question=args.question,
        docs=docs,
        top_k=args.top_k,
        max_chars=max_chars,
        warm_rounds=args.warm_rounds,
        reset_singleton=False,
    )
    warm["docs_source"] = docs_source

    print(f"Model: {warm['model']}")
    print(f"Avg passage chars: {warm['avg_passage_chars']}")
    print()
    print("COLD (fresh Python process):")
    print(f"  load model:     {cold['load_ms']:>8.1f} ms")
    print(f"  predict (1st):  {cold['predict_ms_first']:>8.1f} ms")
    print(f"  total:          {cold['load_ms'] + cold['predict_ms_first']:>8.1f} ms")
    print()
    print(f"WARM (same process, {args.warm_rounds} runs):")
    print(f"  load model:     {warm['load_ms']:>8.1f} ms  (cached singleton)")
    print(f"  predict median: {warm['predict_ms_median']:>8.1f} ms")
    print(f"  predict all:    {warm['predict_ms_all']}")
    print()
    print("Compare to Langfuse traces:")
    print("  local cold rerank span ~2500 ms, gap before span ~16600 ms")
    print("  local warm rerank span ~16000 ms")


if __name__ == "__main__":
    main()
