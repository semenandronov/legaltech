"""Общий правовой справочник: чанкинг, индексация в pgvector, выборка для чата."""
from __future__ import annotations

import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from sqlalchemy import text

from app.config import config
from app.services.chat.rag_passage_utils import legal_corpus_max_fragment_chars, passage_for_rerank, truncate_passage_body
from app.services.document_processor import get_document_processor
from app.services.langchain_loaders import DocumentLoaderService
from app.services.pgvector_store import CaseVectorStore, get_case_vector_store
from app.services.yandex_embeddings import YandexEmbeddings

logger = logging.getLogger(__name__)

LEGAL_CORPUS_CASE_ID = "GLOBAL_LEGAL_CORPUS"
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200
# Пакеты чанков: меньше нагрузка на память и проще откат при сбое
INDEX_BATCH_SIZE = 16
_COUNT_CACHE_TTL_SEC = 10.0
_COUNT_CACHE_VALUE: Optional[int] = None
_COUNT_CACHE_TS: float = 0.0


def legal_corpus_uploader_emails() -> set:
    raw = (getattr(config, "LEGAL_CORPUS_UPLOADER_EMAILS", None) or "").strip()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_legal_corpus_uploader(user) -> bool:
    if not user or not getattr(user, "email", None):
        return False
    return user.email.strip().lower() in legal_corpus_uploader_emails()


def _splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _allowed_extension(filename: str) -> bool:
    _, dot, rest = filename.rpartition(".")
    if not dot:
        return False
    ext = f".{rest.lower()}"
    return ext in [x.lower() for x in config.ALLOWED_EXTENSIONS]


def _sanitize_filename(name: str) -> str:
    n = name.replace("..", "").replace("/", "").replace("\\", "")
    return n or "document"


def _file_type_from_name(name: str) -> str:
    _, dot, ext = name.rpartition(".")
    if not dot:
        return "txt"
    return ext.lower()


def _save_original_corpus_file(
    corpus_file_id: str,
    filename: str,
    file_content: bytes,
    created_by_user_id: Optional[str] = None,
) -> None:
    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(LegalCorpusFile).filter(LegalCorpusFile.id == corpus_file_id).first()
        if row:
            row.filename = filename
            row.file_type = _file_type_from_name(filename)
            row.file_content = file_content
            row.created_by_user_id = created_by_user_id
            row.html_content = None
        else:
            db.add(
                LegalCorpusFile(
                    id=corpus_file_id,
                    filename=filename,
                    file_type=_file_type_from_name(filename),
                    file_content=file_content,
                    created_by_user_id=created_by_user_id,
                )
            )
        db.commit()
    finally:
        db.close()


def _delete_original_corpus_file(corpus_file_id: str) -> int:
    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(LegalCorpusFile).filter(LegalCorpusFile.id == corpus_file_id).first()
        if not row:
            return 0
        db.delete(row)
        db.commit()
        return 1
    finally:
        db.close()


def get_corpus_file_record(corpus_file_id: str) -> Optional[Dict[str, Any]]:
    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(LegalCorpusFile).filter(LegalCorpusFile.id == corpus_file_id).first()
        if not row:
            return None
        return {
            "id": row.id,
            "filename": row.filename,
            "file_type": row.file_type,
            "has_content": bool(row.file_content),
            "html_content": row.html_content,
        }
    finally:
        db.close()


def get_corpus_file_bytes(corpus_file_id: str) -> Optional[bytes]:
    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(LegalCorpusFile).filter(LegalCorpusFile.id == corpus_file_id).first()
        return row.file_content if row and row.file_content else None
    finally:
        db.close()


def get_corpus_file_html(corpus_file_id: str) -> Optional[str]:
    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(LegalCorpusFile).filter(LegalCorpusFile.id == corpus_file_id).first()
        return row.html_content if row and row.html_content else None
    finally:
        db.close()


def set_corpus_file_html(corpus_file_id: str, html: str) -> None:
    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(LegalCorpusFile).filter(LegalCorpusFile.id == corpus_file_id).first()
        if row:
            row.html_content = html
            db.commit()
    finally:
        db.close()


def assert_embeddings_available() -> None:
    emb = YandexEmbeddings()
    if not emb.is_available():
        raise RuntimeError(
            "Индексация справочника недоступна: настройте YANDEX_API_KEY и YANDEX_FOLDER_ID "
            "(нужны рабочие эмбеддинги Yandex Cloud)."
        )


def index_uploaded_file(
    content: bytes,
    filename: str,
    created_by_user_id: Optional[str] = None,
    instrument_id: Optional[str] = None,
    *,
    progress_cb: Optional[callable] = None,
) -> Tuple[str, int]:
    """
    Извлекает текст, режет на чанки, пишет в pgvector.
    При любой ошибке после частичной вставки удаляет все чанки с данным corpus_file_id.
    """
    assert_embeddings_available()

    safe_name = _sanitize_filename(filename)
    if not _allowed_extension(safe_name):
        raise ValueError(
            f"Неподдерживаемый формат файла. Допустимо: {', '.join(config.ALLOWED_EXTENSIONS)}"
        )

    corpus_max_size = int(getattr(config, "LEGAL_CORPUS_MAX_FILE_SIZE", config.MAX_FILE_SIZE) or config.MAX_FILE_SIZE)
    if len(content) > corpus_max_size:
        raise ValueError(
            f"Файл слишком большой (макс. {corpus_max_size // (1024 * 1024)} МБ)"
        )

    corpus_file_id = str(uuid.uuid4())
    ingest_content = content
    ext = _file_type_from_name(safe_name)
    prepared_pdf_text: Optional[str] = None
    if ext in ("html", "htm"):
        from app.services.consultant_html_preprocess import (
            is_consultant_plus_html,
            prepare_consultant_html_for_ingest,
        )

        if is_consultant_plus_html(content):
            ingest_content = prepare_consultant_html_for_ingest(content)
    elif ext == "pdf" and bool(getattr(config, "LEGAL_CORPUS_PDF_PREPROCESS_ENABLED", True)):
        from app.services.consultant_pdf_preprocess import (
            prepare_consultant_pdf_for_ingest,
            should_preprocess_legal_pdf,
        )
        from app.services.legal_instruments import resolve_instrument as _resolve_inst

        inst_preview = _resolve_inst(instrument_id) if instrument_id else None
        iid_preview = inst_preview.instrument_id if inst_preview else (instrument_id or "other")
        if should_preprocess_legal_pdf(instrument_id=iid_preview, ext=ext):
            prep = prepare_consultant_pdf_for_ingest(content, filename=safe_name)
            if prep and prep.plain_text.strip():
                prepared_pdf_text = prep.plain_text
                logger.info(
                    "Legal corpus PDF preprocessed: %s pages=%s chars=%s stripped=%s",
                    safe_name,
                    prep.page_count,
                    len(prep.plain_text),
                    prep.stripped_chars,
                )
    _save_original_corpus_file(
        corpus_file_id=corpus_file_id,
        filename=safe_name,
        file_content=ingest_content,
        created_by_user_id=created_by_user_id,
    )
    store = get_case_vector_store()
    total = 0

    try:
        from app.services.legal_instruments import resolve_instrument

        inst = resolve_instrument(instrument_id)
        vf, vt = None, None
        if inst:
            vf, vt = inst.valid_from, inst.valid_to
        docs = DocumentLoaderService.load_document(ingest_content, safe_name)
        if not docs:
            raise ValueError("Не удалось извлечь текст из файла")

        # Full parity with case ingestion pipeline:
        # use the same splitter/chunk-contract implementation as file uploads.
        text = "\n\n".join((d.page_content or "").strip() for d in docs if (d.page_content or "").strip())
        if not text.strip():
            raise ValueError("Не удалось извлечь текст из файла")

        document_processor = get_document_processor()
        file_documents = document_processor.split_documents(
            text=text,
            filename=safe_name,
            metadata={
                "case_id": LEGAL_CORPUS_CASE_ID,
                "file_id": corpus_file_id,
                "file_type": _file_type_from_name(safe_name),
                "doc_type": "legal_reference",
                # MVP: stable legal act identity for metadata filtering in retrieval.
                "instrument_id": (inst.instrument_id if inst else None),
                "instrument_short_name": (inst.short_name if inst else None),
                "instrument_version": "latest",
            },
            file_id=corpus_file_id,
            langchain_docs=docs,
            content_bytes=ingest_content,
            prepared_pdf_text=prepared_pdf_text,
        )
        if not file_documents:
            raise ValueError("Не удалось сформировать чанки из документа")

        # Keep legal corpus-specific selectors for retrieval/status pages.
        for i, d in enumerate(file_documents):
            md = dict(d.metadata or {})
            # ensure instrument metadata is present on each chunk even if a chunker overwrote base metadata
            if inst:
                md.setdefault("instrument_id", inst.instrument_id)
                md.setdefault("instrument_short_name", inst.short_name)
                md.setdefault("instrument_version", "latest")
                md.setdefault("norm_class", inst.norm_class)
                if vf:
                    md.setdefault("valid_from", vf.isoformat())
                if vt:
                    md.setdefault("valid_to", vt.isoformat())
            md["corpus_file_id"] = corpus_file_id
            md["source_filename"] = safe_name
            md["corpus_type"] = "legal_reference"
            md["chunk_index"] = int(md.get("chunk_index", i))
            d.metadata = md

        # Same batch write pattern to shared pgvector collection.
        batch: List[Document] = []
        for d in file_documents:
            batch.append(d)
            if len(batch) >= INDEX_BATCH_SIZE:
                store.add_documents(batch, LEGAL_CORPUS_CASE_ID)
                total += len(batch)
                if progress_cb:
                    try:
                        progress_cb({"event": "chunks_indexed", "added": len(batch), "total_indexed": total})
                    except Exception:
                        pass
                batch = []
        if batch:
            store.add_documents(batch, LEGAL_CORPUS_CASE_ID)
            total += len(batch)
            if progress_cb:
                try:
                    progress_cb({"event": "chunks_indexed", "added": len(batch), "total_indexed": total})
                except Exception:
                    pass

        logger.info(
            "Legal corpus indexed: %s → %s chunks (corpus_file_id=%s)",
            safe_name,
            total,
            corpus_file_id,
        )
        try:
            from app.services.legal_instruments import instrument_validity
            from app.services.legal_norm_graph import sync_legal_norm_graph

            iid = inst.instrument_id if inst else "other"
            vf, vt = instrument_validity(iid)
            graph_stats = sync_legal_norm_graph(
                file_documents,
                corpus_file_id=corpus_file_id,
                instrument_id=iid,
                instrument_short_name=inst.short_name if inst else "",
                valid_from=vf,
                valid_to=vt,
            )
            logger.info(
                "Legal norm graph synced: corpus_file_id=%s stats=%s",
                corpus_file_id,
                graph_stats,
            )
        except Exception as graph_exc:
            logger.warning("Legal norm graph sync failed (non-fatal): %s", graph_exc, exc_info=True)

        try:
            from app.services.legal_corpus_index_health import (
                assert_corpus_file_index_health,
                assess_corpus_file_index,
                log_corpus_file_index_health,
            )

            health = assess_corpus_file_index(
                corpus_file_id=corpus_file_id,
                instrument_id=inst.instrument_id if inst else "other",
                chunk_count=total,
            )
            log_corpus_file_index_health(health)
            assert_corpus_file_index_health(health)
        except ValueError:
            raise
        except Exception as health_exc:
            logger.warning("Legal corpus index health check failed: %s", health_exc)

        if inst and bool(getattr(config, "LEGAL_NORM_GRAPH_RECONCILE_ON_UPLOAD", True)):
            try:
                from app.services.legal_norm_graph_reconcile import reconcile_instrument_graph

                reconcile_stats = reconcile_instrument_graph(inst.instrument_id)
                logger.info(
                    "Legal norm graph reconcile after upload instrument=%s stats=%s",
                    inst.instrument_id,
                    reconcile_stats,
                )
            except Exception as reconcile_exc:
                logger.warning(
                    "Legal norm graph reconcile failed (non-fatal): %s",
                    reconcile_exc,
                    exc_info=True,
                )

        try:
            prewarm_legal_corpus_bm25(force_rebuild=True)
        except Exception as bm25_exc:
            logger.warning("BM25 rebuild after corpus upload failed (non-fatal): %s", bm25_exc)
        return corpus_file_id, total
    except Exception:
        deleted = delete_corpus_file(corpus_file_id)
        if deleted:
            logger.warning(
                "Откат индекса справочника: удалено %s чанков (corpus_file_id=%s)",
                deleted,
                corpus_file_id,
            )
        raise


def prewarm_legal_corpus_bm25(*, force_rebuild: bool = False) -> bool:
    """Load all GLOBAL_LEGAL_CORPUS chunks from pgvector and build in-memory BM25 index."""
    try:
        dp = get_document_processor()
        if not dp.bm25_retriever.available:
            logger.info("Legal corpus BM25 prewarm: retriever unavailable")
            return False
        if dp.bm25_retriever.has_index(LEGAL_CORPUS_CASE_ID) and not force_rebuild:
            return True
        store = get_case_vector_store()
        table = "langchain_pg_embedding"
        with store.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT document->>'page_content' AS pc,
                           document->'metadata' AS meta
                    FROM {table}
                    WHERE case_id = :cid
                    LIMIT 50000
                    """
                ),
                {"cid": LEGAL_CORPUS_CASE_ID},
            ).fetchall()
        if not rows:
            logger.info("Legal corpus BM25 prewarm: 0 docs in pgvector, skipping")
            return False
        docs: List[Document] = []
        for r in rows:
            pc = r[0] or ""
            if not pc.strip():
                continue
            import json as _json
            meta = _json.loads(r[1]) if isinstance(r[1], str) else (r[1] or {})
            docs.append(Document(page_content=pc, metadata=meta))
        ok = dp.prewarm_bm25_index(LEGAL_CORPUS_CASE_ID, documents=docs, force_rebuild=force_rebuild)
        if ok:
            logger.info("✅ Legal corpus BM25 prewarm complete (%s docs)", len(docs))
        return ok
    except Exception as exc:
        logger.warning("Legal corpus BM25 prewarm failed: %s", exc, exc_info=True)
        return False


def count_corpus_chunks() -> int:
    global _COUNT_CACHE_VALUE, _COUNT_CACHE_TS
    now = time.monotonic()
    if _COUNT_CACHE_VALUE is not None and (now - _COUNT_CACHE_TS) < _COUNT_CACHE_TTL_SEC:
        return _COUNT_CACHE_VALUE
    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    with store.engine.connect() as conn:
        r = conn.execute(
            text(
                f"""
            SELECT COUNT(*) FROM {table}
            WHERE collection_id = :cid AND case_id = :case_id
            """
            ),
            {"cid": store.collection_name, "case_id": LEGAL_CORPUS_CASE_ID},
        )
        row = r.fetchone()
        count = int(row[0]) if row else 0
        _COUNT_CACHE_VALUE = count
        _COUNT_CACHE_TS = now
        return count


def list_corpus_files() -> List[Dict[str, Any]]:
    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    with store.engine.connect() as conn:
        r = conn.execute(
            text(
                f"""
            SELECT
              document->'metadata'->>'corpus_file_id' AS corpus_file_id,
              MAX(document->'metadata'->>'source_filename') AS source_filename,
              COUNT(*) AS chunk_count
            FROM {table}
            WHERE collection_id = :cid AND case_id = :case_id
              AND document->'metadata'->>'corpus_file_id' IS NOT NULL
            GROUP BY 1
            ORDER BY MAX(document->'metadata'->>'source_filename') NULLS LAST
            """
            ),
            {"cid": store.collection_name, "case_id": LEGAL_CORPUS_CASE_ID},
        )
        out: List[Dict[str, Any]] = []
        for row in r.fetchall():
            if not row[0]:
                continue
            record = get_corpus_file_record(row[0])
            filename = (record or {}).get("filename") or row[1] or ""
            file_type = (record or {}).get("file_type") or _file_type_from_name(filename)
            out.append(
                {
                    "corpus_file_id": row[0],
                    "source_filename": filename,
                    "file_type": file_type,
                    "has_original": bool((record or {}).get("has_content")),
                    "chunk_count": int(row[2]),
                }
            )
        return out


def delete_corpus_file(corpus_file_id: str) -> int:
    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    with store.engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
            DELETE FROM {table}
            WHERE collection_id = :cid AND case_id = :case_id
              AND document->'metadata'->>'corpus_file_id' = :fid
            """
            ),
            {"cid": store.collection_name, "case_id": LEGAL_CORPUS_CASE_ID, "fid": corpus_file_id},
        )
        deleted_chunks = int(result.rowcount or 0)
    try:
        from app.services.legal_norm_graph import delete_graph_for_corpus_file

        delete_graph_for_corpus_file(corpus_file_id)
    except Exception as exc:
        logger.warning("Legal norm graph delete failed for %s: %s", corpus_file_id, exc)
    _delete_original_corpus_file(corpus_file_id)
    return deleted_chunks


def delete_all_corpus_files() -> Dict[str, int]:
    """Удаляет весь правовой корпус: чанки + оригинальные файлы."""
    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    with store.engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
            DELETE FROM {table}
            WHERE collection_id = :cid AND case_id = :case_id
            """
            ),
            {"cid": store.collection_name, "case_id": LEGAL_CORPUS_CASE_ID},
        )
        deleted_chunks = int(result.rowcount or 0)

    from app.models.case import LegalCorpusFile
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        deleted_files = (
            db.query(LegalCorpusFile)
            .delete(synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()

    return {"deleted_chunks": deleted_chunks, "deleted_files": int(deleted_files or 0)}


def should_skip_retrieval_for_message(text: str) -> bool:
    """Не тратить эмбеддинг-запрос на явные короткие приветствия."""
    t = (text or "").strip().lower()
    if len(t) < 4:
        return True
    if len(t) <= 24:
        greetings = (
            "привет",
            "здравствуйте",
            "здравствуй",
            "добрый день",
            "добрый вечер",
            "доброе утро",
            "hi",
            "hello",
            "hey",
        )
        for g in greetings:
            if t == g or t.startswith(g + "!") or t.startswith(g + ".") or t.startswith(g + ","):
                return True
    return False


def _extract_article_query_parts(query: str) -> Dict[str, Optional[str]]:
    q = (query or "").lower()
    article = None
    code = None
    m = re.search(r"(?:ст\.?|статья)\s*([0-9]{1,5}(?:\.[0-9]{1,3})?)", q)
    if m:
        article = m.group(1)
    elif re.fullmatch(r"\s*[0-9]{1,5}(?:\.[0-9]{1,3})?\s*", q):
        article = q.strip()

    if "гк" in q:
        code = "гк"
    elif "гпк" in q:
        code = "гпк"
    elif "апк" in q:
        code = "апк"
    elif "ук" in q:
        code = "ук"
    elif "упк" in q:
        code = "упк"
    elif "коап" in q:
        code = "коап"
    return {"article": article, "code": code}


def _documents_from_json_rows(rows: List[Any]) -> List[Document]:
    docs: List[Document] = []
    for r in rows:
        doc_json = r[0] or {}
        page_content = doc_json.get("page_content") if isinstance(doc_json, dict) else None
        metadata = doc_json.get("metadata") if isinstance(doc_json, dict) else None
        if not page_content:
            continue
        docs.append(Document(page_content=page_content, metadata=metadata or {}))
    return docs


def _legal_chunk_dedup_key(d: Document) -> tuple:
    m = d.metadata or {}
    cid = m.get("chunk_id")
    if cid:
        return ("chunk_id", str(cid))
    return (
        "legacy",
        m.get("corpus_file_id"),
        m.get("chunk_index"),
        (d.page_content or "")[:120],
    )


def batch_articles_fts_lookup(
    articles: List[str],
    question: str,
    instrument_ids: List[str],
    *,
    k_per_article: int = 8,
) -> List[Document]:
    """
    Один connection pool / одна SQL-сессия на все статьи плана (article fast path).
    """
    arts = [str(a).strip() for a in (articles or []) if str(a).strip()][:6]
    if not arts or not instrument_ids:
        return []

    store = get_case_vector_store()
    fts_limit = max(int(k_per_article) * 3, 24)
    merged: List[Document] = []
    seen = {_legal_chunk_dedup_key(d) for d in merged}

    with store.engine.connect() as conn:
        for art in arts:
            fts_q = f"статья {art} {(question or '').strip()}".strip()
            part = _run_fts_bm25_search(
                fts_q,
                limit=fts_limit,
                instrument_ids=instrument_ids,
                conn=conn,
                store=store,
            )
            if len(part) < 2:
                part = _run_lexical_search(
                    fts_q,
                    limit=fts_limit,
                    instrument_ids=instrument_ids,
                    conn=conn,
                    store=store,
                ) or part
            for d in part:
                key = _legal_chunk_dedup_key(d)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(d)

    cap = max(int(k_per_article) * len(arts), 8)
    return merged[:cap]


def _run_lexical_search(
    query: str,
    limit: int = 20,
    *,
    instrument_ids: Optional[List[str]] = None,
    conn: Any = None,
    store: Optional[CaseVectorStore] = None,
) -> List[Document]:
    store = store or get_case_vector_store()
    table = "langchain_pg_embedding"
    q = (query or "").strip().lower()
    if not q:
        return []

    parts = _extract_article_query_parts(q)
    article = parts.get("article")
    code = parts.get("code")

    like_query = f"%{q}%"
    like_article = f"%{article}%" if article else None
    like_code = f"%{code}%" if code else None

    extra_where = ""
    params_extra: Dict[str, Any] = {}
    if instrument_ids:
        norm = [
            str(x).strip().lower()
            for x in instrument_ids
            if str(x).strip() and str(x).strip().lower() != "unknown"
        ]
        if norm:
            placeholders = []
            for idx, iid in enumerate(norm):
                key = f"iid_{idx}"
                placeholders.append(f":{key}")
                params_extra[key] = iid
            extra_where = f" AND lower(document->'metadata'->>'instrument_id') IN ({', '.join(placeholders)})"

    sql = text(
        f"""
        SELECT
          document
        FROM {table}
        WHERE collection_id = :cid
          AND case_id = :case_id
          {extra_where}
          AND (
            lower(document->>'page_content') LIKE :like_query
            OR lower(document->'metadata'->>'source_filename') LIKE :like_query
            OR (:like_article IS NOT NULL AND lower(document->>'page_content') LIKE :like_article)
          )
        ORDER BY
          CASE
            WHEN :like_article IS NOT NULL AND lower(document->>'page_content') LIKE :like_article THEN 0
            ELSE 1
          END,
          CASE
            WHEN :like_code IS NOT NULL AND lower(document->'metadata'->>'source_filename') LIKE :like_code THEN 0
            ELSE 1
          END,
          (document->'metadata'->>'chunk_index')::int
        LIMIT :lim
        """
    )

    params = {
        "cid": store.collection_name,
        "case_id": LEGAL_CORPUS_CASE_ID,
        "like_query": like_query,
        "like_article": like_article,
        "like_code": like_code,
        "lim": int(max(1, limit)),
        **params_extra,
    }
    if conn is not None:
        rows = conn.execute(sql, params).fetchall()
    else:
        with store.engine.connect() as c:
            rows = c.execute(sql, params).fetchall()
    return _documents_from_json_rows(rows)


def _run_fts_bm25_search(
    query: str,
    limit: int = 24,
    *,
    instrument_ids: Optional[List[str]] = None,
    conn: Any = None,
    store: Optional[CaseVectorStore] = None,
) -> List[Document]:
    """
    PostgreSQL FTS ranking (BM25-like via ts_rank_cd) for large corpora.
    Includes weighted ranking for article/code matches.
    """
    store = store or get_case_vector_store()
    table = "langchain_pg_embedding"
    q = (query or "").strip().lower()
    if not q:
        return []

    parts = _extract_article_query_parts(q)
    article = parts.get("article")
    code = parts.get("code")
    article_regex = rf"(ст\.?|статья)\s*{re.escape(article)}\b" if article else None
    like_code = f"%{code}%" if code else None

    extra_where = ""
    params_extra: Dict[str, Any] = {}
    if instrument_ids:
        norm = [
            str(x).strip().lower()
            for x in instrument_ids
            if str(x).strip() and str(x).strip().lower() != "unknown"
        ]
        if norm:
            placeholders = []
            for idx, iid in enumerate(norm):
                key = f"iid_{idx}"
                placeholders.append(f":{key}")
                params_extra[key] = iid
            extra_where = f" AND lower(document->'metadata'->>'instrument_id') IN ({', '.join(placeholders)})"

    sql = text(
        f"""
        WITH ranked AS (
          SELECT
            document,
            ts_rank_cd(
              to_tsvector('russian', coalesce(document->>'page_content', '') || ' ' || coalesce(document->'metadata'->>'source_filename', '')),
              websearch_to_tsquery('russian', :fts_query)
            ) AS rank_ru,
            ts_rank_cd(
              to_tsvector('simple', coalesce(document->>'page_content', '') || ' ' || coalesce(document->'metadata'->>'source_filename', '')),
              websearch_to_tsquery('simple', :fts_query)
            ) AS rank_simple
          FROM {table}
          WHERE collection_id = :cid
            AND case_id = :case_id
            {extra_where}
            AND (
              to_tsvector('russian', coalesce(document->>'page_content', '') || ' ' || coalesce(document->'metadata'->>'source_filename', ''))
                @@ websearch_to_tsquery('russian', :fts_query)
              OR
              to_tsvector('simple', coalesce(document->>'page_content', '') || ' ' || coalesce(document->'metadata'->>'source_filename', ''))
                @@ websearch_to_tsquery('simple', :fts_query)
            )
        )
        SELECT document
        FROM ranked
        ORDER BY
          (GREATEST(rank_ru, rank_simple)
            + CASE
                WHEN :article_regex IS NOT NULL
                  AND lower(document->>'page_content') ~ :article_regex
                THEN 0.75
                ELSE 0
              END
            + CASE
                WHEN :like_code IS NOT NULL
                  AND lower(document->'metadata'->>'source_filename') LIKE :like_code
                THEN 0.35
                ELSE 0
              END
          ) DESC,
          (document->'metadata'->>'chunk_index')::int
        LIMIT :lim
        """
    )

    params = {
        "cid": store.collection_name,
        "case_id": LEGAL_CORPUS_CASE_ID,
        "fts_query": q,
        "article_regex": article_regex,
        "like_code": like_code,
        "lim": int(max(1, limit)),
        **params_extra,
    }
    if conn is not None:
        rows = conn.execute(sql, params).fetchall()
    else:
        with store.engine.connect() as c:
            rows = c.execute(sql, params).fetchall()
    return _documents_from_json_rows(rows)


def _instrument_metadata_filter(
    instrument_ids: Optional[List[str]],
) -> Optional[Dict[str, Any]]:
    """Ограничение hybrid RAG по instrument_id (как similarity_search filter для справочника)."""
    if not instrument_ids:
        return None
    norm = [
        str(x).strip().lower()
        for x in instrument_ids
        if str(x).strip() and str(x).strip().lower() != "unknown"
    ]
    if not norm:
        return None
    return {"instrument_id": norm}


def _embed_legal_search_query(query: str) -> List[float]:
    """Один embed_query на поисковую фразу (text-search-query)."""
    from app.services.yandex_embeddings import get_yandex_embeddings

    emb = get_yandex_embeddings()
    if not emb.is_available():
        raise RuntimeError("Yandex embeddings unavailable for legal corpus search")
    return emb.embed_query(query)


def _legal_corpus_hybrid_alpha() -> float:
    raw = float(getattr(config, "LEGAL_CORPUS_HYBRID_ALPHA", 0.7) or 0.7)
    return max(0.0, min(raw, 1.0))


def _run_norm_hybrid_search(
    query: str,
    k: int,
    *,
    instrument_ids: Optional[List[str]] = None,
    query_embedding: Optional[List[float]] = None,
) -> List[Document]:
    """
    Hybrid retrieval для GLOBAL_LEGAL_CORPUS: norm-чанки (статьи/пункты), dense + FTS.

    Один embedding на фразу (переиспользуется в dense-ноге hybrid_search).
    Не использует macro/micro воронку ассистента по делу — в корпусе chunk_level=norm.
    """
    q = (query or "").strip()
    if not q:
        return []
    try:
        processor = get_document_processor()
        md_filter = _instrument_metadata_filter(instrument_ids)
        vec = query_embedding
        if vec is None:
            vec = _embed_legal_search_query(q)
        docs = processor.hybrid_search(
            case_id=LEGAL_CORPUS_CASE_ID,
            query=q,
            k=max(k, 8),
            alpha=_legal_corpus_hybrid_alpha(),
            chunk_levels=["norm"],
            metadata_filter=md_filter,
            bm25_sync=False,
            query_embedding=vec,
        )
        return [d for d in (docs or []) if d is not None and getattr(d, "page_content", None)]
    except Exception as exc:
        logger.warning("Legal corpus norm-hybrid retrieve failed: %s", exc, exc_info=True)
        return []


def _dedup_extend_in_order(pool: List[Document], incoming: List[Document], max_total: int) -> None:
    seen = {_legal_chunk_dedup_key(x) for x in pool}
    for d in incoming:
        if len(pool) >= max_total:
            break
        key = _legal_chunk_dedup_key(d)
        if key in seen:
            continue
        seen.add(key)
        pool.append(d)


def _trim_to_recall_cap(pool: List[Document], recall_cap: int) -> List[Document]:
    seen: set = set()
    out: List[Document] = []
    for d in pool:
        if len(out) >= recall_cap:
            break
        key = _legal_chunk_dedup_key(d)
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _hybrid_search_for_query(
    sq: str,
    *,
    k_eff: int,
    instrument_ids: Optional[List[str]],
) -> List[Document]:
    return _run_norm_hybrid_search(sq, k=k_eff, instrument_ids=instrument_ids) or []


def _per_query_rerank_top_k(effective_final: int, n_queries: int) -> int:
    """Сколько чанков оставлять после rerank на каждый planned search_query."""
    n = max(1, int(n_queries))
    final_k = max(1, int(effective_final))
    # Минимум 3: иначе теряется 2–3-й hit hybrid до rerank (типично для пороговых статей).
    base = max(3, (final_k + n - 1) // n)
    return min(5, base)


def _planned_search_queries_provided(search_queries: Optional[List[str]]) -> bool:
    return bool([s for s in (search_queries or []) if (s or "").strip()])


def _finalize_merged_legal_docs(docs: List[Document], top_k: int) -> List[Document]:
    """
    Финальный top-k после per-query merge: дедуп чанков, приоритет разнообразия по article_number.
    """
    if not docs:
        return []
    cap = max(1, int(top_k))
    seen_chunk: set = set()
    seen_article: set = set()
    out: List[Document] = []

    def _try_add(d: Document, *, allow_article_dup: bool) -> bool:
        key = _legal_chunk_dedup_key(d)
        if key in seen_chunk:
            return False
        art = str((d.metadata or {}).get("article_number") or "").strip()
        if art and not allow_article_dup and art in seen_article:
            return False
        seen_chunk.add(key)
        if art:
            seen_article.add(art)
        out.append(d)
        return True

    for d in docs:
        if len(out) >= cap:
            break
        _try_add(d, allow_article_dup=False)

    if len(out) < cap:
        for d in docs:
            if len(out) >= cap:
                break
            _try_add(d, allow_article_dup=True)

    return out


def _process_one_hybrid_rerank(
    sq: str,
    *,
    k_eff: int,
    per_query_top_k: int,
    instrument_ids: Optional[List[str]],
    skip_rerank: bool,
) -> List[Document]:
    part = _hybrid_search_for_query(sq, k_eff=k_eff, instrument_ids=instrument_ids)
    if not part:
        return []
    pool_cap = max(per_query_top_k * 2, 12, k_eff)
    trimmed = _trim_to_recall_cap(part, min(len(part), pool_cap))
    return _maybe_rerank_legal_pool(sq.strip(), trimmed, top_k=per_query_top_k, skip_rerank=skip_rerank)


def _collect_hybrid_per_query_reranked(
    unique_queries: List[str],
    *,
    k_eff: int,
    per_query_top_k: int,
    instrument_ids: Optional[List[str]],
    wide_cap: int,
    skip_rerank: bool,
) -> List[Document]:
    """
    Hybrid + rerank для каждой planned-фразы отдельно; merge в порядке планировщика.
    """
    if not unique_queries:
        return []

    merged: List[Document] = []
    parallel = bool(getattr(config, "LEGAL_CORPUS_HYBRID_PARALLEL", True))
    max_workers_cfg = max(1, int(getattr(config, "LEGAL_CORPUS_HYBRID_MAX_WORKERS", 5) or 5))

    if parallel and len(unique_queries) > 1:
        workers = min(max_workers_cfg, len(unique_queries))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _process_one_hybrid_rerank,
                    sq,
                    k_eff=k_eff,
                    per_query_top_k=per_query_top_k,
                    instrument_ids=instrument_ids,
                    skip_rerank=skip_rerank,
                ): sq
                for sq in unique_queries
            }
            by_sq: Dict[str, List[Document]] = {}
            for fut in as_completed(futures):
                sq = futures[fut]
                try:
                    by_sq[sq] = fut.result()
                except Exception as exc:
                    logger.warning(
                        "Legal corpus per-query hybrid/rerank failed (%s): %s",
                        (sq or "")[:80],
                        exc,
                    )
                    by_sq[sq] = []
            for sq in unique_queries:
                _dedup_extend_in_order(merged, by_sq.get(sq) or [], wide_cap)
    else:
        for sq in unique_queries:
            part = _process_one_hybrid_rerank(
                sq,
                k_eff=k_eff,
                per_query_top_k=per_query_top_k,
                instrument_ids=instrument_ids,
                skip_rerank=skip_rerank,
            )
            _dedup_extend_in_order(merged, part, wide_cap)

    return merged


def _collect_hybrid_primary_docs(
    unique_queries: List[str],
    *,
    k_eff: int,
    instrument_ids: Optional[List[str]],
    wide_cap: int,
) -> List[Document]:
    """Hybrid по каждой фразе; при LEGAL_CORPUS_HYBRID_PARALLEL — параллельно."""
    if not unique_queries:
        return []

    primary_docs: List[Document] = []
    parallel = bool(getattr(config, "LEGAL_CORPUS_HYBRID_PARALLEL", True))
    max_workers_cfg = max(1, int(getattr(config, "LEGAL_CORPUS_HYBRID_MAX_WORKERS", 5) or 5))

    if parallel and len(unique_queries) > 1:
        workers = min(max_workers_cfg, len(unique_queries))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _hybrid_search_for_query,
                    sq,
                    k_eff=k_eff,
                    instrument_ids=instrument_ids,
                ): sq
                for sq in unique_queries
            }
            for fut in as_completed(futures):
                sq = futures[fut]
                try:
                    part = fut.result()
                    _dedup_extend_in_order(primary_docs, part, wide_cap)
                except Exception as exc:
                    logger.warning(
                        "Legal corpus parallel hybrid failed (%s): %s",
                        (sq or "")[:80],
                        exc,
                    )
    else:
        for sq in unique_queries:
            part = _hybrid_search_for_query(sq, k_eff=k_eff, instrument_ids=instrument_ids)
            _dedup_extend_in_order(primary_docs, part, wide_cap)

    return primary_docs


def _legal_rerank_max_chars() -> int:
    tier = str(getattr(config, "LEGAL_CORPUS_RERANK_TIER", "light") or "light").strip().lower()
    if tier == "light":
        return int(getattr(config, "CASE_ASSISTANT_RERANK_LIGHT_MAX_CHARS", 900) or 900)
    return int(getattr(config, "LEGAL_CORPUS_RERANK_MAX_CHARS", 2400) or 2400)


def _legal_rerank_tier() -> str:
    return str(getattr(config, "LEGAL_CORPUS_RERANK_TIER", "light") or "light").strip().lower()


def _passage_for_rerank(doc: Document, max_chars: int) -> str:
    return passage_for_rerank(doc, max_chars)


def _maybe_rerank_legal_pool(
    original_query: str,
    docs: List[Document],
    *,
    top_k: int,
    skip_rerank: bool = False,
) -> List[Document]:
    """Cross-encoder rerank; при успехе проставляет metadata[\"rerank_score\"] на исходных Document."""
    if not docs:
        return []
    if skip_rerank or not bool(getattr(config, "LEGAL_CORPUS_USE_RERANKER", False)):
        return docs[: max(1, top_k)]

    max_c = _legal_rerank_max_chars()
    tier = _legal_rerank_tier()
    try:
        from app.services.reranker_service import get_reranker_for_tier

        svc = get_reranker_for_tier(tier)
    except Exception as exc:
        logger.warning("Legal corpus reranker init failed (tier=%s): %s", tier, exc)
        return docs[: max(1, top_k)]

    proxies: List[Document] = []
    for i, d in enumerate(docs):
        md = dict(d.metadata or {})
        md["_lc_rerank_ix"] = i
        proxies.append(Document(page_content=_passage_for_rerank(d, max_c), metadata=md))
    try:
        ranked = svc.rerank(original_query.strip(), proxies, top_k=max(1, min(top_k, len(proxies))))
    except Exception as exc:
        logger.warning("Legal corpus rerank failed: %s", exc, exc_info=True)
        return docs[: max(1, top_k)]

    out: List[Document] = []
    for pdoc, score in ranked:
        ix = (pdoc.metadata or {}).get("_lc_rerank_ix")
        if not isinstance(ix, int) or ix < 0 or ix >= len(docs):
            continue
        orig = docs[ix]
        md2 = dict(orig.metadata or {})
        md2["rerank_score"] = float(score)
        md2.pop("_lc_rerank_ix", None)
        orig.metadata = md2
        out.append(orig)
    return out if out else docs[: max(1, top_k)]


def retrieve_legal_corpus_documents(
    query: str,
    k: int = 8,
    *,
    instrument_ids: Optional[List[str]] = None,
    search_queries: Optional[List[str]] = None,
    recall_max: Optional[int] = None,
    final_k: Optional[int] = None,
    max_search_queries: Optional[int] = None,
    skip_rerank: bool = False,
    include_original_query: bool = True,
) -> List[Document]:
    """
    Вернуть сырые документы из правового корпуса для citation/preview.

    Пайплайн:
      1) Для каждой строки из search_queries — norm-hybrid (1 embed + dense/FTS по chunk_level=norm).
         При наличии planned search_queries: hybrid + cross-encoder rerank **по каждой фразе отдельно**.
      2) Один supplement FTS+lexical по исходному user query (статья / пустой primary).
      3) Без planned queries: дедуп до LEGAL_CORPUS_RECALL_MAX → global rerank по user query.
         С planned queries: merge per-query winners → finalize top final_k (разнообразие по статьям).

    include_original_query=False: не добавлять полный user query в пул hybrid-запросов
    (только search_queries); FTS supplement по user query сохраняется.
    """
    if should_skip_retrieval_for_message(query):
        return []
    if count_corpus_chunks() == 0:
        return []

    recall_cap = max(
        1,
        int(
            recall_max
            if recall_max is not None
            else (getattr(config, "LEGAL_CORPUS_RECALL_MAX", 12) or 12)
        ),
    )
    effective_final = max(1, int(final_k if final_k is not None else k))
    k_eff = max(effective_final, 8)
    wide_cap = max(recall_cap * 4, 64, k_eff * 4)

    raw_qs: List[str] = []
    if include_original_query or not search_queries:
        raw_qs.append(query)
    if search_queries:
        raw_qs.extend([s for s in search_queries if (s or "").strip()])
    unique_queries: List[str] = []
    seen_ql = set()
    for sq in raw_qs:
        t = (sq or "").strip()
        if not t:
            continue
        low = t.lower()
        if low in seen_ql:
            continue
        seen_ql.add(low)
        unique_queries.append(t)
    if not unique_queries:
        unique_queries = [(query or "").strip() or ""]

    if max_search_queries is not None:
        cap = max(1, int(max_search_queries))
        unique_queries = unique_queries[:cap]

    use_per_query_rerank = _planned_search_queries_provided(search_queries)

    if use_per_query_rerank:
        per_k = _per_query_rerank_top_k(effective_final, len(unique_queries))
        primary_docs = _collect_hybrid_per_query_reranked(
            unique_queries,
            k_eff=k_eff,
            per_query_top_k=per_k,
            instrument_ids=instrument_ids,
            wide_cap=wide_cap,
            skip_rerank=skip_rerank,
        )
    else:
        primary_docs = _collect_hybrid_primary_docs(
            unique_queries,
            k_eff=k_eff,
            instrument_ids=instrument_ids,
            wide_cap=wide_cap,
        )

    parts = _extract_article_query_parts(query)
    has_article_intent = bool(parts.get("article") or parts.get("code"))

    bm25_docs: List[Document] = []
    lexical_docs: List[Document] = []

    need_supplement = has_article_intent or not primary_docs
    if need_supplement:
        try:
            bm25_docs = _run_fts_bm25_search(query, limit=max(effective_final * 3, 24), instrument_ids=instrument_ids)
        except Exception as e:
            logger.warning("Legal corpus BM25 FTS retrieve failed: %s", e, exc_info=True)
        try:
            lexical_docs = _run_lexical_search(query, limit=max(effective_final * 3, 24), instrument_ids=instrument_ids)
        except Exception as e:
            logger.warning("Legal corpus lexical retrieve failed: %s", e, exc_info=True)

        if (not primary_docs or not bm25_docs) and parts.get("article"):
            try:
                article_query = f"статья {parts['article']} {parts.get('code') or ''}".strip()
                bm25_docs = (
                    _run_fts_bm25_search(article_query, limit=max(effective_final * 4, 32), instrument_ids=instrument_ids)
                    or bm25_docs
                )
                lexical_docs = (
                    _run_lexical_search(article_query, limit=max(effective_final * 4, 32), instrument_ids=instrument_ids)
                    or lexical_docs
                )
            except Exception as e:
                logger.warning("Legal corpus article fallback failed: %s", e, exc_info=True)

    combined: List[Document] = list(primary_docs)
    _dedup_extend_in_order(combined, bm25_docs, wide_cap)
    _dedup_extend_in_order(combined, lexical_docs, wide_cap)

    if not combined:
        return []

    if use_per_query_rerank:
        return _finalize_merged_legal_docs(combined, effective_final)

    trimmed = _trim_to_recall_cap(combined, recall_cap)
    return _maybe_rerank_legal_pool(query, trimmed, top_k=effective_final, skip_rerank=skip_rerank)


def retrieve_legal_corpus_context(
    query: str,
    k: Optional[int] = None,
    max_chars: Optional[int] = None,
    *,
    instrument_ids: Optional[List[str]] = None,
    search_queries: Optional[List[str]] = None,
    recall_max: Optional[int] = None,
    final_k: Optional[int] = None,
) -> str:
    k_val = int(
        k
        if k is not None
        else (getattr(config, "LEGAL_CORPUS_CONTEXT_K", 8) or 8)
    )
    max_c = int(
        max_chars
        if max_chars is not None
        else (getattr(config, "LEGAL_CORPUS_MAX_CONTEXT_CHARS", 14000) or 14000)
    )
    docs = retrieve_legal_corpus_documents(
        query,
        k=k_val,
        instrument_ids=instrument_ids,
        search_queries=search_queries,
        recall_max=recall_max,
        final_k=final_k,
    )
    if not docs:
        return ""

    parts: List[str] = []
    used = 0
    max_frag = legal_corpus_max_fragment_chars()
    for i, d in enumerate(docs, start=1):
        fn = d.metadata.get("source_filename", "файл")
        body = truncate_passage_body((d.page_content or "").strip(), max_frag)
        block = f"[Справочник — фрагмент {i}, источник: {fn}]\n{body}"
        if used + len(block) > max_c:
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)


def retrieve_legal_corpus_context_with_docs(
    query: str,
    k: Optional[int] = None,
    max_chars: Optional[int] = None,
    *,
    instrument_ids: Optional[List[str]] = None,
    search_queries: Optional[List[str]] = None,
    recall_max: Optional[int] = None,
    final_k: Optional[int] = None,
    max_search_queries: Optional[int] = None,
) -> Tuple[str, List[Document]]:
    """Like retrieve_legal_corpus_context but also returns the raw Document objects
    that were included in the formatted context (respecting max_chars truncation)."""
    k_val = int(
        k
        if k is not None
        else (getattr(config, "LEGAL_CORPUS_CONTEXT_K", 8) or 8)
    )
    max_c = int(
        max_chars
        if max_chars is not None
        else (getattr(config, "LEGAL_CORPUS_MAX_CONTEXT_CHARS", 14000) or 14000)
    )
    docs = retrieve_legal_corpus_documents(
        query,
        k=k_val,
        instrument_ids=instrument_ids,
        search_queries=search_queries,
        recall_max=recall_max,
        final_k=final_k,
        max_search_queries=max_search_queries,
    )
    if not docs:
        return "", []

    parts: List[str] = []
    included: List[Document] = []
    used = 0
    max_frag = legal_corpus_max_fragment_chars()
    for i, d in enumerate(docs, start=1):
        fn = d.metadata.get("source_filename", "файл")
        body = truncate_passage_body((d.page_content or "").strip(), max_frag)
        block = f"[Справочник — фрагмент {i}, источник: {fn}]\n{body}"
        if used + len(block) > max_c:
            break
        parts.append(block)
        included.append(d)
        used += len(block)
    return "\n\n---\n\n".join(parts), included


def get_corpus_document_text(corpus_file_id: str) -> str:
    """Собрать полный текст corpus-файла из чанков в порядке chunk_index."""
    if not corpus_file_id:
        return ""

    store = get_case_vector_store()
    table = "langchain_pg_embedding"
    with store.engine.connect() as conn:
        r = conn.execute(
            text(
                f"""
            SELECT
              document->>'page_content' AS page_content,
              (document->'metadata'->>'chunk_index')::int AS chunk_index
            FROM {table}
            WHERE collection_id = :cid
              AND case_id = :case_id
              AND document->'metadata'->>'corpus_file_id' = :fid
            ORDER BY chunk_index ASC
            """
            ),
            {"cid": store.collection_name, "case_id": LEGAL_CORPUS_CASE_ID, "fid": corpus_file_id},
        )
        chunks: List[str] = []
        for row in r.fetchall():
            txt = row[0] or ""
            if txt:
                chunks.append(txt)
        return "\n\n".join(chunks)
