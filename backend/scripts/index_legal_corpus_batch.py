"""Пакетная индексация нескольких PDF в GLOBAL_LEGAL_CORPUS."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.services.legal_corpus_service import (
    LEGAL_CORPUS_CASE_ID,
    count_corpus_chunks,
    index_uploaded_file,
    list_corpus_files,
)
from app.services.pgvector_store import get_case_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _articles_for_file(corpus_file_id: str) -> int:
    store = get_case_vector_store()
    with store.engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT COUNT(DISTINCT document->'metadata'->>'article_number')
                FROM langchain_pg_embedding
                WHERE case_id = :cid
                  AND document->'metadata'->>'corpus_file_id' = :fid
                  AND COALESCE(document->'metadata'->>'article_number', '') <> ''
                """
            ),
            {"cid": LEGAL_CORPUS_CASE_ID, "fid": corpus_file_id},
        ).scalar() or 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch index legal corpus PDFs")
    parser.add_argument("--instrument", default="fz-127")
    parser.add_argument("paths", nargs="+", type=Path, help="PDF paths")
    args = parser.parse_args()

    results = []
    for idx, path in enumerate(args.paths, start=1):
        if not path.is_file():
            logger.error("[%s/%s] Файл не найден: %s", idx, len(args.paths), path)
            results.append({"path": str(path), "error": "not_found"})
            continue
        t0 = time.monotonic()
        logger.info("[%s/%s] Индексация: %s", idx, len(args.paths), path.name)
        try:
            content = path.read_bytes()
            corpus_file_id, chunk_count = index_uploaded_file(
                content=content,
                filename=path.name,
                instrument_id=args.instrument,
            )
            arts = _articles_for_file(corpus_file_id)
            elapsed = int((time.monotonic() - t0) * 1000)
            row = {
                "path": str(path),
                "corpus_file_id": corpus_file_id,
                "chunks": chunk_count,
                "articles": arts,
                "ms": elapsed,
            }
            results.append(row)
            logger.info(
                "[%s/%s] OK chunks=%s articles=%s ms=%s id=%s",
                idx,
                len(args.paths),
                chunk_count,
                arts,
                elapsed,
                corpus_file_id,
            )
        except Exception as exc:
            logger.exception("[%s/%s] FAILED %s: %s", idx, len(args.paths), path.name, exc)
            results.append({"path": str(path), "error": str(exc)})

    logger.info("Итого чанков в корпусе: %s", count_corpus_chunks())
    logger.info("Файлы: %s", list_corpus_files())

    failed = [r for r in results if r.get("error")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
