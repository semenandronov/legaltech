"""Shared retrieval state for one tabular column run (one query embedding per column)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from app.models.tabular_review import TabularColumn
from app.services.tabular_cell_pipeline import build_retrieval_query


_EMBEDDING_DIM = 256


@dataclass(frozen=True)
class TabularColumnRunContext:
    """Precomputed search query + query vector reused for every file in a column run."""

    search_query: str
    query_embedding: Tuple[float, ...]

    @property
    def query_embedding_list(self) -> list[float]:
        return list(self.query_embedding)


def prepare_tabular_column_run_context(column: TabularColumn) -> TabularColumnRunContext:
    """
    Embed the column retrieval question once before parallel cell extraction.

    Raises ValueError when the column has no prompt/label, RuntimeError when embedding fails.
    """
    search_query = build_retrieval_query(column).strip()
    if not search_query:
        raise ValueError("empty_query")

    from app.services.yandex_embeddings import get_yandex_embeddings

    embeddings = get_yandex_embeddings()
    if not embeddings.is_available():
        raise RuntimeError("Yandex embeddings are not configured")

    vector = embeddings.embed_query(search_query)
    if not isinstance(vector, list) or len(vector) != _EMBEDDING_DIM:
        raise RuntimeError(
            f"Tabular column embedding invalid: expected {_EMBEDDING_DIM} dims, "
            f"got {len(vector) if isinstance(vector, list) else type(vector)}"
        )
    return TabularColumnRunContext(
        search_query=search_query,
        query_embedding=tuple(float(x) for x in vector),
    )
