#!/usr/bin/env python3
"""Переиндексация правового корпуса из legal_corpus_files (после фикса chunking).

Читает сохранённые PDF из БД, удаляет старые чанки и индексирует заново.

Пример:
    cd backend && python -m scripts.reindex_legal_corpus_from_db
    cd backend && python -m scripts.reindex_legal_corpus_from_db --instrument fz-127
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Tuple

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, text

from app.config import config
from app.services.legal_corpus_service import delete_corpus_file, index_uploaded_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_corpus_files(*, instrument_id: str | None) -> List[Tuple[str, str, bytes, str | None]]:
    engine = create_engine(config.DATABASE_URL)
    sql = """
        SELECT f.id, f.filename, f.file_content,
               MAX(e.document->'metadata'->>'instrument_id') AS instrument_id
        FROM legal_corpus_files f
        LEFT JOIN langchain_pg_embedding e
          ON e.document->'metadata'->>'corpus_file_id' = f.id::text
         AND e.case_id = 'GLOBAL_LEGAL_CORPUS'
        WHERE f.file_content IS NOT NULL
    """
    params: dict = {}
    if instrument_id:
        sql += """
          AND EXISTS (
            SELECT 1 FROM langchain_pg_embedding e2
            WHERE e2.document->'metadata'->>'corpus_file_id' = f.id::text
              AND e2.case_id = 'GLOBAL_LEGAL_CORPUS'
              AND e2.document->'metadata'->>'instrument_id' = :iid
          )
        """
        params["iid"] = instrument_id
    sql += " GROUP BY f.id, f.filename, f.file_content ORDER BY f.filename"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    out: List[Tuple[str, str, bytes, str | None]] = []
    for fid, fn, content, iid in rows:
        if not content:
            logger.warning("Пустой file_content, пропуск: %s", fn)
            continue
        out.append((str(fid), str(fn or "document.pdf"), bytes(content), iid))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex legal corpus from DB file_content")
    parser.add_argument("--instrument", default="fz-127", help="Фильтр instrument_id (пусто = все файлы)")
    args = parser.parse_args()
    instrument = (args.instrument or "").strip() or None

    rows = _load_corpus_files(instrument_id=instrument)
    if not rows:
        logger.error("Нет файлов для переиндексации (instrument=%s)", instrument)
        return 1

    logger.info("Файлов к переиндексации: %s", len(rows))

    if instrument:
        from app.services.legal_norm_graph import delete_graph_for_instrument

        delete_graph_for_instrument(instrument)
        logger.info("Граф норм удалён для instrument=%s", instrument)

    total_chunks = 0
    for old_id, filename, content, iid in rows:
        inst = (iid or instrument or "fz-127").strip()
        logger.info("Удаление старых чанков: %s (%s)", filename, old_id)
        delete_corpus_file(old_id)
        logger.info("Индексация: %s (%s bytes)", filename, len(content))
        new_id, n = index_uploaded_file(
            content=content,
            filename=filename,
            instrument_id=inst,
        )
        total_chunks += n
        logger.info("  → corpus_file_id=%s chunks=%s", new_id, n)

    logger.info("Готово: %s файлов, %s чанков всего", len(rows), total_chunks)
    return 0


if __name__ == "__main__":
    sys.exit(main())
