"""Execute decomposed Draft pipeline from ChatGraphState."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.services.draft_pipeline.case_state_builder import prebuilt_pipeline_input_from_assistant
from app.services.draft_pipeline.graph import create_draft_pipeline_graph

logger = logging.getLogger(__name__)


def execute_draft_pipeline(
    state: Dict[str, Any],
    db: Optional[Session] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run creation pipeline and return ChatGraphState partial update.

    Expects keys from ChatGraphState: case_id, user_id, question, template_*,
    attached_file_ids, template_system_id.

    DB session is bound per invocation via graph factory closure — never placed
    in LangGraph state (not msgpack-serializable).
    """
    new_state = dict(state)
    case_id = state.get("case_id")
    user_id = state.get("user_id")
    question = (state.get("question") or "").strip()

    if not case_id or not user_id or not question:
        new_state["response"] = "❌ Ошибка: недостаточно данных для создания документа"
        new_state["errors"] = (new_state.get("errors") or []) + ["draft_pipeline: missing case_id/user_id/question"]
        return new_state

    if db is None:
        new_state["response"] = "❌ Ошибка создания документа: нет сессии БД"
        new_state["errors"] = (new_state.get("errors") or []) + ["draft_pipeline: missing db session"]
        return new_state

    try:
        graph = create_draft_pipeline_graph(db=db)
        pipeline_input = {
            "case_id": str(case_id),
            "user_id": str(user_id),
            "user_prompt": question,
            "attached_file_ids": state.get("attached_file_ids"),
            "template_system_id": state.get("template_system_id"),
            "template_context": state.get("template_context"),
            "template_label": state.get("template_label"),
            "template_key": state.get("template_key"),
        }
        prebuilt = prebuilt_pipeline_input_from_assistant(state)
        if prebuilt:
            pipeline_input.update(prebuilt)
            logger.info(
                "[draft_pipeline.runner] using internal assistant case state calc_applied=%s",
                (prebuilt.get("financial_calculator_meta") or {}).get("applied"),
            )
        result = graph.invoke(pipeline_input, config=config or {})

        doc_created = result.get("document_created")
        response = result.get("response") or ""
        if doc_created:
            new_state["document_created"] = doc_created
            new_state["response"] = response
            new_state["messages"] = [AIMessage(content=response)]
            new_state["waiting_for_approval"] = False
            new_state["draft_approved"] = True
            # Lightweight plan for UI/history compatibility
            new_state["draft_plan"] = {
                "title": result.get("document_title") or doc_created.get("title"),
                "type": result.get("strategy") or "draft",
                "sections": [
                    {"name": s.get("title"), "description": s.get("section_id")}
                    for s in (result.get("blueprint") or [])
                    if isinstance(s, dict)
                ],
                "document_overview": question[:500],
                "planned_content": "Draft unified via internal assistant RAG + facts passport",
            }
            logger.info("[draft_pipeline.runner] success document_id=%s", doc_created.get("id"))
        else:
            new_state["response"] = "❌ Ошибка создания документа"
            new_state["errors"] = (new_state.get("errors") or []) + ["draft_pipeline: no document_created"]
    except Exception as exc:
        logger.error("[draft_pipeline.runner] failed: %s", exc, exc_info=True)
        new_state["response"] = f"❌ Ошибка создания документа: {exc}"
        new_state["errors"] = (new_state.get("errors") or []) + [f"Draft pipeline error: {exc}"]
        new_state["waiting_for_approval"] = False

    return new_state
