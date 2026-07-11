#!/usr/bin/env python3
"""Замер времени реранкера BGE для справочника и судебной практики."""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from langchain_core.documents import Document

from app.config import config
from app.services.chat.rag_passage_utils import passage_for_rerank
from app.services.legal_corpus_service import _maybe_rerank_legal_pool, _passage_for_rerank
from app.services.reranker_service import get_reranker_service


LEGAL_QUERY = "оспаривание сделки должника в деле о банкротстве субсидиарная ответственность"
COURT_QUERY = "субсидиарная ответственность контролирующего лица банкротство"

LEGAL_PARAGRAPH = (
    "Статья 61.11. Оспаривание сделок должника. Сделка, совершенная должником, может быть "
    "признана арбитражным судом недействительной по заявлению арбитражного управляющего. "
    "Заявление об оспаривании сделки должника может быть подано в течение срока, "
    "установленного настоящим Федеральным законом. Подозрительная сделка может быть "
    "признана арбитражным судом недействительной, если она была совершена должником "
    "во вред имущественным правам кредиторов. Контролирующее лицо несёт субсидиарную "
    "ответственность по обязательствам должника при наличии оснований, предусмотренных "
    "настоящим Федеральным законом. "
)

COURT_PARAGRAPH = (
    "Судебная коллегия по экономическим спорам Верховного Суда Российской Федерации "
    "рассмотрела в открытом судебном заседании кассационную жалобу на определение "
    "арбитражного суда апелляционной инстанции. Суд установил, что контролирующее лицо "
    "довело должника до банкротства, не обеспечило ведение бухгалтерского учёта и "
    "представление отчётности, что препятствовало проведению процедуры банкротства. "
    "При таких обстоятельствах требования о привлечении к субсидиарной ответственности "
    "подлежат удовлетворению в части, согласованной с разъяснениями Пленума ВС РФ. "
)


def synthetic_legal_docs(pool_size: int) -> list[Document]:
    docs: list[Document] = []
    for i in range(pool_size):
        body = (LEGAL_PARAGRAPH + f" Фрагмент {i + 1}. ") * 8
        docs.append(
            Document(
                page_content=body[:2200],
                metadata={
                    "chunk_id": f"legal_{i}",
                    "section_title": f"Глава 6. Особенности банкротства юридических лиц — §{i + 1}",
                },
            )
        )
    return docs


def synthetic_court_docs(pool_size: int) -> list[Document]:
    docs: list[Document] = []
    for i in range(pool_size):
        body = (COURT_PARAGRAPH + f" Дело А40-{1000 + i}/2024. ") * 6
        tmp = Document(page_content=body[:2200], metadata={"source_file": f"А40-{1000 + i}/2024"})
        max_c = int(getattr(config, "COURT_PRACTICE_RERANK_MAX_CHARS", 2400) or 2400)
        docs.append(
            Document(
                page_content=passage_for_rerank(tmp, max_c),
                metadata={"chunk_id": f"court_{i}"},
            )
        )
    return docs


def bench_legal_corpus(warm_rounds: int = 5) -> dict:
    recall_max = int(getattr(config, "LEGAL_CORPUS_RECALL_MAX", 30) or 30)
    final_k = int(getattr(config, "LEGAL_CORPUS_FINAL_K", 8) or 8)
    docs = synthetic_legal_docs(recall_max)

    # cold: first load + rerank
    import app.services.reranker_service as rs

    rs._reranker = None
    t0 = time.perf_counter()
    _maybe_rerank_legal_pool(LEGAL_QUERY, docs, top_k=final_k, skip_rerank=False)
    cold_ms = (time.perf_counter() - t0) * 1000

    times: list[float] = []
    for _ in range(warm_rounds):
        t1 = time.perf_counter()
        _maybe_rerank_legal_pool(LEGAL_QUERY, docs, top_k=final_k, skip_rerank=False)
        times.append((time.perf_counter() - t1) * 1000)

    svc = get_reranker_service()
    proxies = [_passage_for_rerank(d, int(config.LEGAL_CORPUS_RERANK_MAX_CHARS or 2400)) for d in docs]
    avg_chars = statistics.mean(len(p) for p in proxies)

    return {
        "mode": "справочник (legal_corpus)",
        "model": svc.model_name,
        "pool_size": recall_max,
        "top_k": final_k,
        "max_chars": int(config.LEGAL_CORPUS_RERANK_MAX_CHARS or 2400),
        "avg_passage_chars": round(avg_chars, 0),
        "cold_ms": round(cold_ms, 0),
        "warm_median_ms": round(statistics.median(times), 0),
        "warm_all_ms": [round(x, 0) for x in times],
    }


def bench_court_practice(warm_rounds: int = 5) -> dict:
    pool_k = int(getattr(config, "COURT_PRACTICE_RERANK_POOL_K", 12) or 12)
    final_k = int(getattr(config, "COURT_PRACTICE_FINAL_K", 7) or 7)
    max_chars = int(getattr(config, "COURT_PRACTICE_RERANK_MAX_CHARS", 2400) or 2400)
    docs = synthetic_court_docs(pool_k)

    import app.services.reranker_service as rs

    rs._reranker = None
    t0 = time.perf_counter()
    svc = get_reranker_service()
    svc.rerank(COURT_QUERY, docs, top_k=final_k)
    cold_ms = (time.perf_counter() - t0) * 1000

    times: list[float] = []
    for _ in range(warm_rounds):
        t1 = time.perf_counter()
        svc.rerank(COURT_QUERY, docs, top_k=final_k)
        times.append((time.perf_counter() - t1) * 1000)

    avg_chars = statistics.mean(len(d.page_content or "") for d in docs)

    return {
        "mode": "судебная практика (court_practice)",
        "model": svc.model_name,
        "pool_size": pool_k,
        "top_k": final_k,
        "max_chars": max_chars,
        "avg_passage_chars": round(avg_chars, 0),
        "cold_ms": round(cold_ms, 0),
        "warm_median_ms": round(statistics.median(times), 0),
        "warm_all_ms": [round(x, 0) for x in times],
    }


def try_live_rerank() -> list[dict]:
    """Полный retrieve с БД, если доступна."""
    results: list[dict] = []
    try:
        from app.services.court_practice_store import count_chunks as cp_count
        from app.services.legal_corpus_service import count_corpus_chunks
        from app.services.court_practice_service import retrieve_court_practice
        from app.services.legal_corpus_service import retrieve_legal_corpus_documents
    except Exception as exc:
        return [{"live": "import_failed", "error": str(exc)}]

    if cp_count() > 0:
        t0 = time.perf_counter()
        retrieve_court_practice(COURT_QUERY)
        results.append(
            {
                "mode": "судебная практика (live e2e, rerank внутри)",
                "total_ms": round((time.perf_counter() - t0) * 1000, 0),
                "chunks_in_index": cp_count(),
            }
        )

    if count_corpus_chunks() > 0:
        t0 = time.perf_counter()
        retrieve_legal_corpus_documents(LEGAL_QUERY)
        results.append(
            {
                "mode": "справочник (live e2e, rerank внутри)",
                "total_ms": round((time.perf_counter() - t0) * 1000, 0),
                "chunks_in_index": count_corpus_chunks(),
            }
        )

    return results


def main() -> None:
    print("=== Замер реранкера BGE (production-like synthetic pool) ===\n")
    for bench in (bench_legal_corpus, bench_court_practice):
        r = bench()
        print(f"Режим: {r['mode']}")
        print(f"  Модель: {r['model']}")
        print(f"  Пул / top_k: {r['pool_size']} / {r['top_k']}")
        print(f"  Средняя длина passage: {r['avg_passage_chars']:.0f} символов")
        print(f"  Холодный старт (загрузка модели + rerank): {r['cold_ms']:.0f} ms")
        print(f"  Прогретый rerank (медиана {len(r['warm_all_ms'])} прогонов): {r['warm_median_ms']:.0f} ms")
        print(f"  Прогретые прогоны: {r['warm_all_ms']}")
        print()

    live = try_live_rerank()
    if live:
        print("=== Live (полный retrieval + rerank, если есть индекс) ===\n")
        for row in live:
            print(row)
    else:
        print("Live-индекс недоступен или пуст — только synthetic замер.")


if __name__ == "__main__":
    main()
