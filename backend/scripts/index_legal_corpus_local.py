"""Индексация одного файла в локальный GLOBAL_LEGAL_CORPUS.

Пример:
  cd backend && python -m scripts.index_legal_corpus_local \\
    --path "/Users/.../127-ФЗ.htm" \\
    --instrument fz-127 \\
    --replace-instrument
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.services.legal_corpus_service import (
    LEGAL_CORPUS_CASE_ID,
    delete_corpus_file,
    index_uploaded_file,
    list_corpus_files,
)
from app.services.pgvector_store import get_case_vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _delete_by_instrument(instrument_id: str) -> int:
    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    removed = 0
    with store.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT DISTINCT document->'metadata'->>'corpus_file_id' AS fid
                FROM {table}
                WHERE case_id = :cid
                  AND document->'metadata'->>'instrument_id' = :iid
                """
            ),
            {"cid": LEGAL_CORPUS_CASE_ID, "iid": instrument_id},
        ).fetchall()
    for (fid,) in rows:
        if fid:
            removed += delete_corpus_file(fid)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Index legal corpus file locally")
    parser.add_argument("--path", required=True, type=Path, help="Путь к PDF/HTML")
    parser.add_argument("--instrument", default="fz-127", help="instrument_id")
    parser.add_argument(
        "--replace-instrument",
        action="store_true",
        help="Удалить старые чанки с тем же instrument_id перед загрузкой",
    )
    args = parser.parse_args()
    path: Path = args.path
    if not path.is_file():
        logger.error("Файл не найден: %s", path)
        return 1

    if args.replace_instrument:
        from app.services.legal_norm_graph import delete_graph_for_instrument

        delete_graph_for_instrument(args.instrument)
        n = _delete_by_instrument(args.instrument)
        logger.info("Удалено чанков (instrument=%s): %s", args.instrument, n)

    content = path.read_bytes()
    corpus_file_id, chunk_count = index_uploaded_file(
        content=content,
        filename=path.name,
        instrument_id=args.instrument,
    )
    logger.info("Готово: corpus_file_id=%s chunks=%s", corpus_file_id, chunk_count)

    arts = set()
    store = get_case_vector_store()
    with store.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT document->'metadata'->>'article_number' AS art
                FROM langchain_pg_embedding
                WHERE case_id = :cid
                  AND document->'metadata'->>'corpus_file_id' = :fid
                  AND document->'metadata'->>'article_number' IS NOT NULL
                ORDER BY 1
                """
            ),
            {"cid": LEGAL_CORPUS_CASE_ID, "fid": corpus_file_id},
        ).fetchall()
        arts = {r[0] for r in rows if r[0]}
    logger.info("Уникальных article_number в файле: %s", len(arts))
    for probe in ("61", "56", "1", "25.1"):
        logger.info("  ст.%s: %s", probe, "да" if probe in arts else "нет")

    logger.info("Файлы в корпусе: %s", list_corpus_files())
    return 0


if __name__ == "__main__":
    sys.exit(main())
