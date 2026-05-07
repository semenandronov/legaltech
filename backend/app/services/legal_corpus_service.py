"""Общий правовой справочник: чанкинг, индексация в pgvector, выборка для чата."""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from sqlalchemy import text

from app.config import config
from app.services.document_processor import get_document_processor
from app.services.langchain_loaders import DocumentLoaderService
from app.services.pgvector_store import CaseVectorStore
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

    if len(content) > config.MAX_FILE_SIZE:
        raise ValueError(
            f"Файл слишком большой (макс. {config.MAX_FILE_SIZE // (1024 * 1024)} МБ)"
        )

    corpus_file_id = str(uuid.uuid4())
    _save_original_corpus_file(
        corpus_file_id=corpus_file_id,
        filename=safe_name,
        file_content=content,
        created_by_user_id=created_by_user_id,
    )
    store = CaseVectorStore()
    total = 0

    try:
        docs = DocumentLoaderService.load_document(content, safe_name)
        if not docs:
            raise ValueError("Не удалось извлечь текст из файла")

        # Full parity with case ingestion pipeline:
        # use the same splitter/chunk-contract implementation as file uploads.
        text = "\n\n".join((d.page_content or "").strip() for d in docs if (d.page_content or "").strip())
        if not text.strip():
            raise ValueError("Не удалось извлечь текст из файла")
        if len(text) > config.MAX_TOTAL_TEXT_CHARS:
            text = text[: config.MAX_TOTAL_TEXT_CHARS]

        document_processor = get_document_processor()
        file_documents = document_processor.split_documents(
            text=text,
            filename=safe_name,
            metadata={
                "case_id": LEGAL_CORPUS_CASE_ID,
                "file_id": corpus_file_id,
                "file_type": _file_type_from_name(safe_name),
                "doc_type": "legal_reference",
            },
            file_id=corpus_file_id,
            langchain_docs=docs,
        )
        if not file_documents:
            raise ValueError("Не удалось сформировать чанки из документа")

        # Keep legal corpus-specific selectors for retrieval/status pages.
        for i, d in enumerate(file_documents):
            md = dict(d.metadata or {})
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


def count_corpus_chunks() -> int:
    global _COUNT_CACHE_VALUE, _COUNT_CACHE_TS
    now = time.monotonic()
    if _COUNT_CACHE_VALUE is not None and (now - _COUNT_CACHE_TS) < _COUNT_CACHE_TTL_SEC:
        return _COUNT_CACHE_VALUE
    store = CaseVectorStore()
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
    store = CaseVectorStore()
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
    store = CaseVectorStore()
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
    _delete_original_corpus_file(corpus_file_id)
    return deleted_chunks


def delete_all_corpus_files() -> Dict[str, int]:
    """Удаляет весь правовой корпус: чанки + оригинальные файлы."""
    store = CaseVectorStore()
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


def _run_lexical_search(query: str, limit: int = 20) -> List[Document]:
    store = CaseVectorStore()
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

    sql = text(
        f"""
        SELECT
          document
        FROM {table}
        WHERE collection_id = :cid
          AND case_id = :case_id
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

    with store.engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "cid": store.collection_name,
                "case_id": LEGAL_CORPUS_CASE_ID,
                "like_query": like_query,
                "like_article": like_article,
                "like_code": like_code,
                "lim": int(max(1, limit)),
            },
        ).fetchall()

    docs: List[Document] = []
    for r in rows:
        doc_json = r[0] or {}
        page_content = doc_json.get("page_content") if isinstance(doc_json, dict) else None
        metadata = doc_json.get("metadata") if isinstance(doc_json, dict) else None
        if not page_content:
            continue
        docs.append(Document(page_content=page_content, metadata=metadata or {}))
    return docs


def _run_fts_bm25_search(query: str, limit: int = 24) -> List[Document]:
    """
    PostgreSQL FTS ranking (BM25-like via ts_rank_cd) for large corpora.
    Includes weighted ranking for article/code matches.
    """
    store = CaseVectorStore()
    table = "langchain_pg_embedding"
    q = (query or "").strip().lower()
    if not q:
        return []

    parts = _extract_article_query_parts(q)
    article = parts.get("article")
    code = parts.get("code")
    article_regex = rf"(ст\.?|статья)\s*{re.escape(article)}\b" if article else None
    like_code = f"%{code}%" if code else None

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

    with store.engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "cid": store.collection_name,
                "case_id": LEGAL_CORPUS_CASE_ID,
                "fts_query": q,
                "article_regex": article_regex,
                "like_code": like_code,
                "lim": int(max(1, limit)),
            },
        ).fetchall()

    docs: List[Document] = []
    for r in rows:
        doc_json = r[0] or {}
        page_content = doc_json.get("page_content") if isinstance(doc_json, dict) else None
        metadata = doc_json.get("metadata") if isinstance(doc_json, dict) else None
        if not page_content:
            continue
        docs.append(Document(page_content=page_content, metadata=metadata or {}))
    return docs


def retrieve_legal_corpus_documents(query: str, k: int = 8) -> List[Document]:
    """Вернуть сырые документы из правового корпуса для citation/preview."""
    if should_skip_retrieval_for_message(query):
        return []
    if count_corpus_chunks() == 0:
        return []
    semantic_docs: List[Document] = []
    emb = YandexEmbeddings()
    if emb.is_available():
        store = CaseVectorStore()
        try:
            # Primary semantic retrieval (kept for broad legal questions).
            semantic_docs = store.similarity_search(query.strip(), LEGAL_CORPUS_CASE_ID, k=max(k, 8)) or []
        except Exception as e:
            logger.warning("Legal corpus semantic retrieve failed: %s", e, exc_info=True)
            semantic_docs = []
    else:
        logger.warning("Legal corpus semantic retrieve skipped: Yandex embeddings unavailable")

    bm25_docs: List[Document] = []
    try:
        bm25_docs = _run_fts_bm25_search(query, limit=max(k * 3, 24))
    except Exception as e:
        logger.warning("Legal corpus BM25 FTS retrieve failed: %s", e, exc_info=True)

    # Hybrid addition: lexical retrieval by article/code/filename patterns.
    lexical_docs: List[Document] = []
    try:
        lexical_docs = _run_lexical_search(query, limit=max(k * 3, 24))
    except Exception as e:
        logger.warning("Legal corpus lexical retrieve failed: %s", e, exc_info=True)

    # Article-aware fallback when semantic misses.
    parts = _extract_article_query_parts(query)
    if not semantic_docs and parts.get("article"):
        try:
            article_query = f"статья {parts['article']} {parts.get('code') or ''}".strip()
            bm25_docs = _run_fts_bm25_search(article_query, limit=max(k * 4, 32)) or bm25_docs
            lexical_docs = _run_lexical_search(article_query, limit=max(k * 4, 32)) or lexical_docs
        except Exception as e:
            logger.warning("Legal corpus article fallback failed: %s", e, exc_info=True)

    combined = semantic_docs + bm25_docs + lexical_docs
    if not combined:
        return []

    # De-dup by corpus file and chunk index.
    seen = set()
    unique_docs: List[Document] = []
    for d in combined:
        m = d.metadata or {}
        key = (m.get("corpus_file_id"), m.get("chunk_index"), (d.page_content or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        unique_docs.append(d)
        if len(unique_docs) >= max(k * 2, 12):
            break

    return unique_docs


def retrieve_legal_corpus_context(query: str, k: int = 8, max_chars: int = 14000) -> str:
    docs = retrieve_legal_corpus_documents(query, k=k)
    if not docs:
        return ""

    parts: List[str] = []
    used = 0
    for i, d in enumerate(docs, start=1):
        fn = d.metadata.get("source_filename", "файл")
        block = f"[Справочник — фрагмент {i}, источник: {fn}]\n{d.page_content.strip()}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)


def get_corpus_document_text(corpus_file_id: str) -> str:
    """Собрать полный текст corpus-файла из чанков в порядке chunk_index."""
    if not corpus_file_id:
        return ""

    store = CaseVectorStore()
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
