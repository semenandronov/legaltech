"""
Fixed multi-step risk analysis for tabular cells (phase 4.2).

Graph (not a free agent):
  plan_sections → retrieve_sections → synthesize_risks → END

Limits are hard-capped via config (steps / queries / chars / tokens).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, model_validator

from app.config import config
from app.models.case import File
from app.models.tabular_review import TabularColumn
from app.services.tabular_extraction_schemas import typed_extraction_to_cell_model
from app.services.tabular_review_models import TabularCellExtractionModel

logger = logging.getLogger(__name__)

# Fixed catalog — plan picks a subset; never invents free tool loops.
_SECTION_CATALOG: Dict[str, str] = {
    "liability": "ответственность сторон неустойка ущерб убытки лимит ответственности",
    "termination": "расторжение отказ от договора односторонний выход",
    "penalty": "неустойка пеня штраф просрочка платежа",
    "payment": "оплата порядок расчетов срок оплаты аванс",
    "sla": "срок выполнения SLA качество гарантия недостатки",
    "ip_confidential": "конфиденциальность интеллектуальная собственность NDA",
    "change_control": "изменение условий доп соглашение существенные изменения",
    "dispute": "спор подсудность арбитраж применимое право",
}


class RiskItem(BaseModel):
    title: str = Field(default="Риск", description="Краткий заголовок риска")
    severity: str = Field(default="medium", description="high|medium|low")
    detail: str = Field(default="", description="1–2 предложения по тексту")
    quote: Optional[str] = Field(None, description="Дословная цитата из фрагментов")

    class Config:
        extra = "ignore"

    @model_validator(mode="before")
    @classmethod
    def _coerce_ru_keys(cls, obj: Any) -> Any:
        if not isinstance(obj, dict):
            return obj
        return {
            "title": obj.get("title")
            or obj.get("риск")
            or obj.get("name")
            or obj.get("risk")
            or "Риск",
            "severity": obj.get("severity") or obj.get("уровень") or "medium",
            "detail": obj.get("detail")
            or obj.get("описание")
            or obj.get("detail_text")
            or "",
            "quote": obj.get("quote") or obj.get("цитата") or obj.get("verbatim"),
        }


class RiskSynthesisModel(BaseModel):
    risks: List[RiskItem] = Field(default_factory=list)
    cell_value: str = Field(
        default="N/A",
        description="Итоговый список рисков для ячейки (маркированный), или N/A",
    )
    verbatim_extract: Optional[str] = Field(
        None, description="Главная подтверждающая цитата"
    )
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    reasoning: str = Field(
        default="Risk analysis graph", description="Как сформирован список"
    )

    class Config:
        extra = "ignore"

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload(cls, obj: Any) -> Any:
        if not isinstance(obj, dict):
            return obj
        data = dict(obj)
        if "risks" not in data:
            for key, val in obj.items():
                if isinstance(val, list) and "риск" in str(key).lower():
                    data["risks"] = val
                    break
        if not (data.get("cell_value") or "").strip() and isinstance(data.get("risks"), list):
            lines: List[str] = []
            for item in data["risks"][:12]:
                if isinstance(item, dict):
                    title = (
                        item.get("title")
                        or item.get("риск")
                        or item.get("name")
                        or "Риск"
                    )
                    detail = item.get("detail") or item.get("описание") or ""
                    line = f"- {title}"
                    if detail:
                        line = f"{line}: {detail}"
                    lines.append(line)
                elif item:
                    lines.append(f"- {item}")
            data["cell_value"] = "\n".join(lines) if lines else "N/A"
        data.setdefault("cell_value", "N/A")
        data.setdefault("reasoning", "Risk analysis graph")
        return data


class RiskGraphState(TypedDict, total=False):
    question: str
    column_label: str
    section_ids: List[str]
    section_queries: List[str]
    context_text: str
    doc_count: int
    extraction: Optional[TabularCellExtractionModel]
    status: str
    error: str


def tabular_risk_analysis_enabled() -> bool:
    return bool(getattr(config, "TABULAR_RISK_ANALYSIS_ENABLED", True))


def tabular_risk_max_section_queries() -> int:
    return max(1, min(6, int(getattr(config, "TABULAR_RISK_MAX_SECTION_QUERIES", 4) or 4)))


def tabular_risk_max_context_chars() -> int:
    return max(4000, int(getattr(config, "TABULAR_RISK_MAX_CONTEXT_CHARS", 16000) or 16000))


def tabular_risk_max_tokens() -> int:
    return max(400, int(getattr(config, "TABULAR_RISK_MAX_TOKENS", 1200) or 1200))


def plan_risk_sections(question: str, column_label: str = "") -> List[str]:
    """Heuristic section planner (deterministic; no LLM)."""
    blob = f"{column_label or ''} {question or ''}".lower()
    scored: List[tuple[float, str]] = []
    keyword_map = {
        "liability": ("ответствен", "убытк", "лимит", "indemn", "liability"),
        "termination": ("расторж", "отказ", "terminat", "выход"),
        "penalty": ("неустойк", "пеня", "штраф", "penalty"),
        "payment": ("оплат", "платеж", "аванс", "payment"),
        "sla": ("срок", "sla", "гарант", "качеств"),
        "ip_confidential": ("конфиденц", "nda", "интеллект", "ip "),
        "change_control": ("изменен", "доп соглаш", "amend"),
        "dispute": ("спор", "арбитраж", "подсудност", "governing"),
    }
    for sid, keys in keyword_map.items():
        score = sum(1.0 for k in keys if k in blob)
        if score:
            scored.append((score, sid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = [sid for _, sid in scored[: tabular_risk_max_section_queries()]]
    if not picked:
        # Default risk sweep for open-ended «перечисли риски»
        picked = ["liability", "termination", "penalty", "payment"][
            : tabular_risk_max_section_queries()
        ]
    return picked


def _node_plan(state: RiskGraphState) -> Dict[str, Any]:
    section_ids = plan_risk_sections(
        state.get("question") or "",
        state.get("column_label") or "",
    )
    queries = [_SECTION_CATALOG[sid] for sid in section_ids if sid in _SECTION_CATALOG]
    return {
        "section_ids": section_ids,
        "section_queries": queries,
        "status": "planned",
    }


def _retrieve_for_queries(
    *,
    rag_service,
    file: File,
    column: TabularColumn,
    queries: List[str],
    column_run=None,
    file_context=None,
) -> tuple[str, List[Document]]:
    from app.services.tabular_cell_pipeline import (
        cell_retrieval_params_from_models,
        prepare_cell_retrieval_sync,
    )
    from app.services.tabular_column_run_context import TabularColumnRunContext

    merged_docs: List[Document] = []
    seen = set()
    parts: List[str] = []
    budget = tabular_risk_max_context_chars()

    for q in queries:
        q = (q or "").strip()
        if not q:
            continue
        # Override search query for this section pass.
        run = column_run
        if run is not None:
            run = TabularColumnRunContext(
                search_query=q,
                query_embedding=(),
                source_query=str(getattr(column, "prompt", "") or q),
                rewrite_method="risk_section",
                rewrite_rationale=f"section:{q[:80]}",
                exact_query="",
                lexical_terms=tuple(w for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", q)[:8]),
                exact_literals=(),
                search_queries=(q,),
            )
        else:
            run = TabularColumnRunContext(
                search_query=q,
                query_embedding=(),
                source_query=str(getattr(column, "prompt", "") or q),
                rewrite_method="risk_section",
                rewrite_rationale="section",
                exact_query="",
                lexical_terms=tuple(w for w in re.findall(r"[A-Za-zА-Яа-яЁё]{4,}", q)[:8]),
                exact_literals=(),
                search_queries=(q,),
            )
        params = cell_retrieval_params_from_models(
            file, column, column_run=run, file_context=file_context
        )
        prepared = prepare_cell_retrieval_sync(rag_service, params=params)
        if prepared.error or not prepared.included_docs:
            continue
        parts.append(f"[Секция: {q[:60]}]\n{prepared.context_text}")
        for doc in prepared.included_docs:
            key = (
                str((doc.metadata or {}).get("chunk_id") or ""),
                (doc.page_content or "")[:120],
            )
            if key in seen:
                continue
            seen.add(key)
            merged_docs.append(doc)
        if sum(len(p) for p in parts) >= budget:
            break

    context = "\n\n".join(parts)
    if len(context) > budget:
        context = context[:budget]
    return context, merged_docs


def _format_risk_line(item: RiskItem) -> str:
    title = (item.title or "").strip()
    detail = (item.detail or "").strip()
    quote = (item.quote or "").strip()
    useless = {"", "риск", "risk", "n/a", "н/д", "-", "—"}

    def _usable(text: str) -> str:
        t = (text or "").strip()
        return "" if t.lower() in useless else t

    title = _usable(title)
    detail = _usable(detail)
    if detail and title and detail.lower() == title.lower():
        detail = ""

    body = ""
    if title and detail:
        body = f"{title}: {detail}"
    elif title:
        body = title
    elif detail:
        body = detail
    elif quote:
        numbered = re.match(r"^\d+(?:\.\d+)+\.\s*(.+)$", quote, flags=re.DOTALL)
        if numbered:
            body = numbered.group(1).strip()
        else:
            body = re.split(r"\.\s+", quote, maxsplit=1)[0].strip()
        body = body[:220].strip()
    if not body:
        return ""

    sev = (item.severity or "medium").strip().lower()
    if sev not in {"high", "medium", "low"}:
        sev = "medium"
    return f"- [{sev}] {body}"


def _format_risks_fallback(items: List[RiskItem]) -> str:
    lines = [line for item in items if (line := _format_risk_line(item))]
    return "\n".join(lines) if lines else "N/A"


async def _synthesize(
    llm,
    *,
    column: TabularColumn,
    context_text: str,
    normalize_fn,
    file: File,
) -> TabularCellExtractionModel:
    if not (context_text or "").strip():
        return typed_extraction_to_cell_model(
            {
                "cell_value": "N/A",
                "reasoning": "Нет фрагментов для risk analysis",
                "extraction_method": "risk_analysis_graph",
                "confidence": 0.0,
            },
            column=column,
        )

    system = (
        "Ты юрист due diligence. По фрагментам составь список рисков. "
        "Каждый risk: title — конкретная формулировка (5–12 слов, не слово «Риск»), "
        "detail — 1 предложение по тексту, quote — дословная цитата. "
        "Если рисков нет — risks=[] и cell_value=N/A."
    )
    human = (
        f"Вопрос колонки: {column.prompt}\n"
        f"Документ: {file.filename}\n\n"
        f"Фрагменты:\n{context_text}"
    )
    try:
        structured = llm.with_structured_output(RiskSynthesisModel, method="json_mode")
        raw = await structured.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        if hasattr(raw, "model_dump"):
            payload = raw.model_dump()
            model = RiskSynthesisModel.model_validate(payload)
        elif isinstance(raw, dict):
            model = RiskSynthesisModel.model_validate(raw)
            payload = model.model_dump()
        else:
            model = raw  # type: ignore[assignment]
            payload = model.model_dump()

        # Always assemble cell text from structured risks — never trust blank titles.
        if model.risks:
            cell_value = _format_risks_fallback(model.risks)
        else:
            cell_value = (payload.get("cell_value") or "").strip() or "N/A"
        if not cell_value:
            cell_value = "N/A"

        refs = []
        for risk in model.risks[:8]:
            if risk.quote:
                refs.append({"text": risk.quote[:500]})
        verbatim = payload.get("verbatim_extract")
        if not verbatim and refs:
            verbatim = refs[0]["text"]

        result_dict = {
            "cell_value": cell_value,
            "verbatim_extract": verbatim,
            "source_references": refs,
            "confidence": float(payload.get("confidence") or 0.7),
            "reasoning": payload.get("reasoning") or "Risk analysis graph",
            "extraction_method": "risk_analysis_graph",
        }
        result_dict = normalize_fn(result_dict, column, file)
        return typed_extraction_to_cell_model(result_dict, column=column)
    except Exception as exc:
        logger.warning("Risk synthesize failed: %s", exc, exc_info=True)
        # Lightweight fallback: single-pass text extract over merged context
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                (
                    "human",
                    "Вопрос: {question}\n\nФрагменты:\n{context}\n\n"
                    "Ответь маркированным списком рисков или N/A.",
                ),
            ]
        )
        resp = await (prompt | llm).ainvoke(
            {"question": column.prompt, "context": context_text[:8000]}
        )
        text = resp.content if hasattr(resp, "content") else str(resp)
        return typed_extraction_to_cell_model(
            {
                "cell_value": (text or "N/A").strip()[:4000] or "N/A",
                "reasoning": "Risk analysis fallback (unstructured)",
                "extraction_method": "risk_analysis_graph",
                "confidence": 0.55,
            },
            column=column,
        )


async def run_tabular_risk_analysis(
    llm,
    *,
    rag_service,
    file: File,
    column: TabularColumn,
    normalize_fn,
    column_run=None,
    file_context=None,
) -> tuple[TabularCellExtractionModel, List[Document], Dict[str, Any]]:
    """
    Execute the fixed 3-node risk graph for one cell.

    Returns (extraction, included_docs, meta).
    """
    if not tabular_risk_analysis_enabled():
        extraction = typed_extraction_to_cell_model(
            {
                "cell_value": "N/A",
                "reasoning": "Risk analysis disabled by config",
                "extraction_method": "risk_analysis_disabled",
                "confidence": 0.0,
            },
            column=column,
        )
        return extraction, [], {"status": "disabled"}

    # Cap LLM budget for this path
    try:
        if hasattr(llm, "max_tokens"):
            llm.max_tokens = min(
                int(getattr(llm, "max_tokens", None) or tabular_risk_max_tokens()),
                tabular_risk_max_tokens(),
            )
    except Exception:
        pass

    captured_docs: List[Document] = []

    def retrieve_node(state: RiskGraphState) -> Dict[str, Any]:
        context, docs = _retrieve_for_queries(
            rag_service=rag_service,
            file=file,
            column=column,
            queries=list(state.get("section_queries") or []),
            column_run=column_run,
            file_context=file_context,
        )
        captured_docs.clear()
        captured_docs.extend(docs)
        return {
            "context_text": context,
            "doc_count": len(docs),
            "status": "retrieved",
        }

    async def synthesize_node(state: RiskGraphState) -> Dict[str, Any]:
        extraction = await _synthesize(
            llm,
            column=column,
            context_text=state.get("context_text") or "",
            normalize_fn=normalize_fn,
            file=file,
        )
        return {"extraction": extraction, "status": "done"}

    graph = StateGraph(RiskGraphState)
    graph.add_node("plan_sections", _node_plan)
    graph.add_node("retrieve_sections", retrieve_node)
    graph.add_node("synthesize_risks", synthesize_node)
    graph.add_edge(START, "plan_sections")
    graph.add_edge("plan_sections", "retrieve_sections")
    graph.add_edge("retrieve_sections", "synthesize_risks")
    graph.add_edge("synthesize_risks", END)
    app = graph.compile()

    initial: RiskGraphState = {
        "question": str(getattr(column, "prompt", "") or ""),
        "column_label": str(getattr(column, "column_label", "") or ""),
    }
    final_state = await app.ainvoke(initial)

    docs = list(captured_docs)
    extraction = final_state.get("extraction")
    if extraction is None:
        extraction = typed_extraction_to_cell_model(
            {
                "cell_value": "N/A",
                "reasoning": "Risk graph produced no extraction",
                "extraction_method": "risk_analysis_graph",
                "confidence": 0.0,
            },
            column=column,
        )

    meta = {
        "status": "risk_analysis",
        "section_ids": list(final_state.get("section_ids") or []),
        "section_queries": list(final_state.get("section_queries") or []),
        "doc_count": int(final_state.get("doc_count") or len(docs)),
        "pipeline": "risk_analysis_graph",
        "steps": 3,
    }
    return extraction, docs, meta
