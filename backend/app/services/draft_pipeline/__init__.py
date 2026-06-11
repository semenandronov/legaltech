"""
Draft pipeline: facts → template/scratch → unified generation (default) or decomposed sections → persist.

Used by chat_graph.draft_node (creation) and editor refactor runner (section-targeted edits).
"""

__all__ = ["execute_draft_pipeline", "execute_draft_refactor"]


def __getattr__(name: str):
    if name == "execute_draft_pipeline":
        from app.services.draft_pipeline.runner import execute_draft_pipeline

        return execute_draft_pipeline
    if name == "execute_draft_refactor":
        from app.services.draft_pipeline.refactor.runner import execute_draft_refactor

        return execute_draft_refactor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
