"""
Пары (D, C) для retrieval-чанков: D — порядковый номер документа в деле (по первому появлению file_id),
C — chunk_index из метаданных индекса либо порядковый номер фрагмента этого файла в батче, если индекса нет.

Должны совпадать между format_sources_for_prompt_with_docs и build_retrieval_citations.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from langchain_core.documents import Document

from app.services.chat.citation_file_identity import is_synthetic_doc_label


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compute_retrieval_dc_labels(docs: List[Document]) -> List[Tuple[int, int]]:
    """
    Для каждого документа в том же порядке, что и в retrieval / промпте:
    возвращает (retrieval_d, retrieval_c), которые модель указывает как [D{d}:C{c}].
    """
    file_to_ord: Dict[str, int] = {}
    next_ord = 1
    per_file_fallback: Dict[str, int] = {}
    out: List[Tuple[int, int]] = []

    for idx, doc in enumerate(docs):
        meta = dict(doc.metadata or {})
        fid_raw = meta.get("file_id")
        if fid_raw is not None and str(fid_raw).strip() and not is_synthetic_doc_label(fid_raw):
            key = str(fid_raw).strip()
        else:
            doc_raw = meta.get("doc_id")
            if doc_raw is not None and str(doc_raw).strip() and not is_synthetic_doc_label(doc_raw):
                key = str(doc_raw).strip()
            else:
                key = f"__anon_{idx}"
        if key not in file_to_ord:
            file_to_ord[key] = next_ord
            next_ord += 1
            per_file_fallback[key] = 0
        doc_ord = file_to_ord[key]
        ci = _int_or_none(meta.get("chunk_index"))
        if ci is not None:
            c = ci
        else:
            per_file_fallback[key] += 1
            c = per_file_fallback[key]
        out.append((doc_ord, c))
    return out
