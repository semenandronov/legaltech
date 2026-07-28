"""Shared retrieval state for one tabular column run (one query embedding per column)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from app.models.tabular_review import TabularColumn
from app.services.tabular_search_query_rewrite import rewrite_tabular_search_query


_EMBEDDING_DIM = 256


@dataclass(frozen=True)
class TabularColumnRunContext:
    """Precomputed multi-channel retrieval plan + query vector for a column run."""

    search_query: str
    query_embedding: Tuple[float, ...]
    source_query: str = ""
    rewrite_method: str = "passthrough"
    rewrite_rationale: str = ""
    exact_query: Optional[str] = None
    lexical_terms: Tuple[str, ...] = ()
    exact_literals: Tuple[str, ...] = ()
    search_queries: Tuple[str, ...] = ()

    @property
    def semantic_query(self) -> str:
        return self.search_query

    @property
    def query_embedding_list(self) -> list[float]:
        return list(self.query_embedding)


def prepare_tabular_column_run_context(column: TabularColumn) -> TabularColumnRunContext:
    """
    Rewrite the column prompt into semantic + lexical + exact plan, embed semantic once.

    Raises ValueError when the column has no prompt/label, RuntimeError when embedding fails.
    """
    rewritten = rewrite_tabular_search_query(column, allow_llm=True)
    search_query = (rewritten.search_query or "").strip()
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
    search_queries = tuple(rewritten.search_queries or ()) or (search_query,)
    return TabularColumnRunContext(
        search_query=search_query,
        query_embedding=tuple(float(x) for x in vector),
        source_query=rewritten.source_query,
        rewrite_method=rewritten.method,
        rewrite_rationale=rewritten.rationale,
        exact_query=(rewritten.exact_query or None),
        lexical_terms=tuple(rewritten.lexical_terms or ()),
        exact_literals=tuple(rewritten.exact_literals or ()),
        search_queries=search_queries,
    )
