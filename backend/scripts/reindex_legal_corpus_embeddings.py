"""Re-embed all GLOBAL_LEGAL_CORPUS chunks with current embedding_text settings.

Usage:
    cd backend && python -m scripts.reindex_legal_corpus_embeddings

This script:
  1. Loads all corpus chunks from pgvector (page_content + metadata).
  2. Re-applies _apply_hidden_embedding_context (breadcrumbs + synonym hints).
  3. Re-computes embeddings via YandexEmbeddings using embedding_text (or page_content).
  4. Updates the embedding column in-place (batch UPDATE).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import List

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from langchain_core.documents import Document

from app.config import config
from app.services.pgvector_store import CaseVectorStore
from app.services.yandex_embeddings import YandexEmbeddings
from app.services.legal_chunker import _apply_hidden_embedding_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CASE_ID = "GLOBAL_LEGAL_CORPUS"
BATCH_SIZE = 32


def main():
    store = CaseVectorStore()
    table = "langchain_pg_embedding"

    logger.info("Loading chunks from pgvector for %s ...", CASE_ID)
    with store.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT id, document->>'page_content' AS pc,
                       document->'metadata' AS meta
                FROM {table}
                WHERE (cmetadata->>'case_id') = :cid
                ORDER BY (cmetadata->>'chunk_index')::int NULLS LAST
                """
            ),
            {"cid": CASE_ID},
        ).fetchall()

    if not rows:
        logger.warning("No chunks found for %s — nothing to reindex.", CASE_ID)
        sys.exit(0)

    logger.info("Loaded %d chunks. Re-applying embedding context ...", len(rows))

    docs: List[Document] = []
    row_ids: List[str] = []
    for r in rows:
        rid, pc, meta_raw = r[0], r[1] or "", r[2]
        meta = json.loads(meta_raw) if isinstance(meta_raw, str) else (meta_raw or {})
        docs.append(Document(page_content=pc, metadata=meta))
        row_ids.append(rid)

    embed_prefix_enabled = bool(getattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True))
    _apply_hidden_embedding_context(docs, enabled=embed_prefix_enabled)

    hints_on = bool(getattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", False))
    logger.info(
        "EMBED_PREFIX=%s  SYNONYM_HINTS=%s", embed_prefix_enabled, hints_on,
    )

    texts: List[str] = []
    for d in docs:
        et = (d.metadata or {}).get("embedding_text")
        texts.append(et.strip() if isinstance(et, str) and et.strip() else (d.page_content or ""))

    embedder = YandexEmbeddings()
    total = len(texts)
    updated = 0
    t0 = time.time()

    for start in range(0, total, BATCH_SIZE):
        batch_texts = texts[start: start + BATCH_SIZE]
        batch_ids = row_ids[start: start + BATCH_SIZE]
        batch_docs = docs[start: start + BATCH_SIZE]

        try:
            vectors = embedder.embed_documents(batch_texts)
        except Exception as exc:
            logger.error("Embedding batch %d-%d failed: %s", start, start + len(batch_texts), exc)
            continue

        with store.engine.begin() as conn:
            for rid, vec, doc in zip(batch_ids, vectors, batch_docs):
                meta = doc.metadata or {}
                conn.execute(
                    text(
                        f"""
                        UPDATE {table}
                        SET embedding = :vec,
                            cmetadata = cmetadata || :meta_patch
                        WHERE id = :rid
                        """
                    ),
                    {
                        "rid": rid,
                        "vec": str(vec),
                        "meta_patch": json.dumps({
                            "embedding_text": meta.get("embedding_text", ""),
                        }),
                    },
                )
                updated += 1

        elapsed = time.time() - t0
        logger.info(
            "Progress: %d/%d (%.1f%%) — %.1fs elapsed",
            min(start + BATCH_SIZE, total), total,
            min(start + BATCH_SIZE, total) / total * 100,
            elapsed,
        )

    logger.info("Done: %d/%d chunks re-embedded in %.1fs", updated, total, time.time() - t0)


if __name__ == "__main__":
    main()
