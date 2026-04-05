"""Общий правовой справочник: чанкинг, индексация в pgvector, выборка для чата."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Tuple

from langchain_core.documents import Document
from sqlalchemy import text

from app.config import config
from app.services.langchain_loaders import DocumentLoaderService
from app.services.pgvector_store import CaseVectorStore
from app.services.yandex_embeddings import YandexEmbeddings

logger = logging.getLogger(__name__)

LEGAL_CORPUS_CASE_ID = "GLOBAL_LEGAL_CORPUS"
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200
# Пакеты чанков: меньше нагрузка на память и проще откат при сбое
INDEX_BATCH_SIZE = 16


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


def assert_embeddings_available() -> None:
    emb = YandexEmbeddings()
    if not emb.is_available():
        raise RuntimeError(
            "Индексация справочника недоступна: настройте YANDEX_API_KEY и YANDEX_FOLDER_ID "
            "(нужны рабочие эмбеддинги Yandex Cloud)."
        )


def index_uploaded_file(content: bytes, filename: str) -> Tuple[str, int]:
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
    store = CaseVectorStore()
    total = 0

    try:
        docs = DocumentLoaderService.load_document(content, safe_name)
        full_text = "\n\n".join(
            d.page_content for d in docs if d.page_content and d.page_content.strip()
        )
        if not full_text.strip():
            raise ValueError("Не удалось извлечь текст из файла")

        if len(full_text) > config.MAX_TOTAL_TEXT_CHARS:
            full_text = (
                full_text[: config.MAX_TOTAL_TEXT_CHARS]
                + "\n\n[…текст обрезан по лимиту платформы…]"
            )

        splitter = _splitter()
        chunks = [c.strip() for c in splitter.split_text(full_text) if c.strip()]
        if not chunks:
            raise ValueError("Пустой документ после разбиения")

        batch: List[Document] = []
        for i, chunk in enumerate(chunks):
            batch.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "corpus_file_id": corpus_file_id,
                        "source_filename": safe_name,
                        "chunk_index": i,
                        "corpus_type": "legal_reference",
                    },
                )
            )
            if len(batch) >= INDEX_BATCH_SIZE:
                store.add_documents(batch, LEGAL_CORPUS_CASE_ID)
                total += len(batch)
                batch = []
        if batch:
            store.add_documents(batch, LEGAL_CORPUS_CASE_ID)
            total += len(batch)

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
        return int(row[0]) if row else 0


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
            out.append(
                {
                    "corpus_file_id": row[0],
                    "source_filename": row[1] or "",
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
        return int(result.rowcount or 0)


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


def retrieve_legal_corpus_context(query: str, k: int = 8, max_chars: int = 14000) -> str:
    if should_skip_retrieval_for_message(query):
        return ""
    if count_corpus_chunks() == 0:
        return ""
    emb = YandexEmbeddings()
    if not emb.is_available():
        logger.warning("Legal corpus retrieve skipped: Yandex embeddings unavailable")
        return ""

    store = CaseVectorStore()
    try:
        docs = store.similarity_search(query.strip(), LEGAL_CORPUS_CASE_ID, k=k)
    except Exception as e:
        logger.warning("Legal corpus retrieve failed: %s", e, exc_info=True)
        return ""
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
