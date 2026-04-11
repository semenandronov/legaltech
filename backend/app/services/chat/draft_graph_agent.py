"""
Draft Graph Agent — LangGraph-based iterative document drafter.

Flow:
  plan → search → evaluate → [coverage OK or max iter] → generate
                      ↑              ↓ (gaps remain)
                      └── refine ────┘

Each node emits SSE progress events via an asyncio.Queue so the caller
can stream them to the client in real-time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, TypedDict

from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.chat.events import SSESerializer

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3
COVERAGE_THRESHOLD = 0.70   # stop looping when LLM scores ≥ this
MAX_CHUNKS_PER_SECTION = 3  # RAG hits per section per iteration
MAX_CONTEXT_CHARS = 18_000  # total chars fed to generate node
MAX_TEMPLATE_IN_PROMPT = 16_000  # фрагмент системного/файлового шаблона в промпте генерации


# ── State ─────────────────────────────────────────────────────────────────────

class DraftState(TypedDict):
    # ── inputs ──
    case_id: str
    query: str
    title: str
    template_context: str   # pre-loaded template text (may be "")

    # ── plan ──
    document_type: str
    sections: List[str]                    # required doc sections
    section_queries: Dict[str, str]        # section → search query

    # ── search/evaluate loop ──
    gathered: Dict[str, List[str]]         # section → list of text snippets
    gaps: List[str]                        # sections/aspects still missing
    coverage_score: float
    iterations: int

    # ── output ──
    final_content: str
    error: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_llm(temperature: float = 0.1):
    from app.services.llm_factory import create_legal_llm
    return create_legal_llm(temperature=temperature)


async def _llm_call(prompt: str, temperature: float = 0.1) -> str:
    """Run a single LLM call asynchronously."""
    llm = _make_llm(temperature)
    try:
        resp = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        logger.error(f"[DraftGraph] LLM error: {e}")
        raise


async def _rag_search(case_id: str, query: str, db: Session, k: int = MAX_CHUNKS_PER_SECTION) -> List[str]:
    """Search case documents and return text snippets."""
    try:
        from app.services.rag_service import RAGService

        def _search():
            rag = RAGService()
            docs = rag.retrieve_context(
                case_id=case_id,
                query=query,
                k=k,
                use_hybrid=True,
                db=db,
            )
            return [d.page_content[:1200] for d in docs if d.page_content.strip()]

        return await asyncio.to_thread(_search)
    except Exception as e:
        logger.warning(f"[DraftGraph] RAG error for query '{query[:60]}': {e}")
        return []


def _headings_from_template(html: str) -> List[str]:
    """Извлечь названия разделов из HTML-шаблона (h1/h2)."""
    if not html or not html.strip():
        return []
    heads = re.findall(r"<h[12][^>]*>([\s\S]*?)</h[12]>", html, re.IGNORECASE)
    out: List[str] = []
    for h in heads:
        t = re.sub(r"<[^>]+>", "", h)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            out.append(t)
    return out if out else ["Документ"]


def _parse_json_block(text: str) -> Any:
    """Extract and parse the first JSON object/array found in text."""
    match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def plan_node(state: DraftState, queue: asyncio.Queue) -> DraftState:
    """
    Step 1: Ask LLM to identify the document type and list the required
    sections, together with a focused search query for each section.
    """
    await queue.put(SSESerializer.reasoning(
        phase="draft_plan", step=1, total_steps=5,
        content="Определяю структуру документа и нужные разделы…"
    ))

    tc = (state.get("template_context") or "").strip()
    if tc:
        sections = _headings_from_template(tc)
        doc_type = state.get("title") or "Процессуальный документ"
        qbase = state["query"][:300] if state.get("query") else ""
        queries = {s: f"{s} {doc_type} {qbase}" for s in sections}
        logger.info(f"[DraftGraph] plan: using template skeleton, sections={sections}")
        return {
            **state,
            "document_type": doc_type,
            "sections": sections,
            "section_queries": queries,
            "gathered": {},
            "gaps": list(sections),
            "coverage_score": 0.0,
            "iterations": 0,
        }

    prompt = f"""Ты помощник юриста. Пользователь хочет составить документ:

ЗАПРОС: {state['query']}
РАБОЧЕЕ НАЗВАНИЕ: {state['title']}

Определи:
1. Тип документа (договор аренды / трудовой договор / протокол / etc.)
2. Список разделов, которые ОБЯЗАТЕЛЬНО должны быть в этом документе
3. Для каждого раздела — точный поисковый запрос, по которому можно найти нужные данные в документах дела

Ответь строго JSON (без markdown-обёртки):
{{
  "document_type": "...",
  "sections": [
    {{"name": "Стороны договора", "query": "наименование сторон реквизиты"}},
    {{"name": "Предмет договора", "query": "предмет описание объект"}},
    ...
  ]
}}"""

    raw = await _llm_call(prompt, temperature=0.1)
    parsed = _parse_json_block(raw)

    if parsed and isinstance(parsed, dict):
        sections = [s["name"] for s in parsed.get("sections", []) if isinstance(s, dict)]
        queries = {s["name"]: s.get("query", s["name"]) for s in parsed.get("sections", []) if isinstance(s, dict)}
        doc_type = parsed.get("document_type", state["title"])
    else:
        # Fallback: generic sections
        logger.warning("[DraftGraph] plan_node: could not parse LLM JSON, using fallback sections")
        doc_type = state["title"]
        sections = ["Стороны", "Предмет", "Сроки", "Оплата", "Ответственность", "Реквизиты"]
        queries = {s: f"{s} {state['title']}" for s in sections}

    logger.info(f"[DraftGraph] plan: type={doc_type}, sections={sections}")
    return {
        **state,
        "document_type": doc_type,
        "sections": sections,
        "section_queries": queries,
        "gathered": {},
        "gaps": sections[:],   # initially all sections are gaps
        "coverage_score": 0.0,
        "iterations": 0,
    }


async def search_node(state: DraftState, queue: asyncio.Queue, db: Session) -> DraftState:
    """
    Step 2: RAG search for each gap section in parallel.
    Merges new results into gathered (no duplicates).
    """
    gaps = state.get("gaps") or state.get("sections", [])
    iteration = state.get("iterations", 0)

    await queue.put(SSESerializer.reasoning(
        phase="draft_search", step=2, total_steps=5,
        content=f"Поиск по документам дела (итерация {iteration + 1}/{MAX_ITERATIONS})…"
    ))

    gathered = dict(state.get("gathered", {}))
    queries = state.get("section_queries", {})

    # Run all section searches concurrently
    tasks = {
        section: _rag_search(state["case_id"], queries.get(section, section), db)
        for section in gaps
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    for section, result in zip(tasks.keys(), results):
        if isinstance(result, list) and result:
            existing = gathered.get(section, [])
            # Deduplicate by checking first 100 chars
            seen = {t[:100] for t in existing}
            new_chunks = [t for t in result if t[:100] not in seen]
            gathered[section] = existing + new_chunks
            logger.info(f"[DraftGraph] search: {section} → {len(new_chunks)} new chunks")

    total_chunks = sum(len(v) for v in gathered.values())
    logger.info(f"[DraftGraph] search done: {total_chunks} total chunks across {len(gathered)} sections")

    return {**state, "gathered": gathered, "iterations": state.get("iterations", 0) + 1}


async def evaluate_node(state: DraftState, queue: asyncio.Queue) -> DraftState:
    """
    Step 3: LLM evaluates how well we've covered each required section.
    Returns coverage_score (0-1) and a list of still-missing sections/aspects.
    """
    await queue.put(SSESerializer.reasoning(
        phase="draft_evaluate", step=3, total_steps=5,
        content="Оцениваю полноту найденной информации…"
    ))

    gathered = state.get("gathered", {})
    sections = state.get("sections", [])

    # Build a compact summary of what we have
    summary_lines = []
    for sec in sections:
        chunks = gathered.get(sec, [])
        if chunks:
            preview = " | ".join(c[:120] for c in chunks[:2])
            summary_lines.append(f"✅ {sec}: {preview}")
        else:
            summary_lines.append(f"❌ {sec}: ничего не найдено")
    summary = "\n".join(summary_lines)

    prompt = f"""Документ: {state['document_type']}
Запрос пользователя: {state['query']}

Что нашли по разделам:
{summary}

Оцени насколько информации достаточно для составления документа.
Учти: если раздел пустой, но данные можно подставить стандартные ([ЗАПОЛНИТЬ]) — это нормально.

Ответь строго JSON:
{{
  "coverage_score": 0.85,
  "gaps": ["Реквизиты сторон", "Размер штрафа"],
  "comment": "Не хватает банковских реквизитов и условий расторжения"
}}

coverage_score: от 0.0 до 1.0 (0.7+ = достаточно для генерации)
gaps: список разделов/аспектов которых всё ещё не хватает (пустой массив если всё ок)"""

    raw = await _llm_call(prompt, temperature=0.0)
    parsed = _parse_json_block(raw)

    if parsed and isinstance(parsed, dict):
        score = float(parsed.get("coverage_score", 0.5))
        gaps = [g for g in parsed.get("gaps", []) if isinstance(g, str)]
        comment = parsed.get("comment", "")
    else:
        logger.warning("[DraftGraph] evaluate_node: could not parse JSON")
        score = 0.5
        gaps = [s for s in sections if not gathered.get(s)]
        comment = ""

    logger.info(f"[DraftGraph] evaluate: score={score:.2f}, gaps={gaps}, comment={comment}")

    if (state.get("template_context") or "").strip():
        # С фиксированным шаблоном не крутим лишние итерации RAG — хватает данных из дела + [ЗАПОЛНИТЬ]
        score = max(float(score), 0.78)
        gaps = []

    return {**state, "coverage_score": score, "gaps": gaps}


async def refine_node(state: DraftState, queue: asyncio.Queue) -> DraftState:
    """
    Step 3b: When gaps remain, ask LLM to produce better search queries
    for the missing sections, then loop back to search_node.
    """
    await queue.put(SSESerializer.reasoning(
        phase="draft_refine", step=3, total_steps=5,
        content=f"Уточняю поисковые запросы для: {', '.join(state.get('gaps', [])[:3])}…"
    ))

    gaps = state.get("gaps", [])
    if not gaps:
        return state

    prompt = f"""Нужно найти в документах дела информацию для следующих разделов документа «{state['document_type']}»:

{chr(10).join(f'- {g}' for g in gaps)}

Придумай для каждого раздела ДРУГОЙ поисковый запрос — более широкий или с синонимами.

Ответь строго JSON:
{{
  "queries": {{
    "Стороны договора": "участники соглашения наименование организации",
    ...
  }}
}}"""

    raw = await _llm_call(prompt, temperature=0.2)
    parsed = _parse_json_block(raw)

    new_queries = state.get("section_queries", {}).copy()
    if parsed and isinstance(parsed.get("queries"), dict):
        new_queries.update(parsed["queries"])
        logger.info(f"[DraftGraph] refine: updated queries for {list(parsed['queries'].keys())}")

    return {**state, "section_queries": new_queries}


async def generate_node(state: DraftState, queue: asyncio.Queue) -> DraftState:
    """
    Final step: assemble all gathered context and generate the HTML document.
    """
    await queue.put(SSESerializer.reasoning(
        phase="draft_generate", step=5, total_steps=5,
        content="Генерирую документ…"
    ))

    gathered = state.get("gathered", {})

    # Build context block, sorted by section order, capped at MAX_CONTEXT_CHARS
    context_parts: List[str] = []
    total = 0
    for section in state.get("sections", []):
        chunks = gathered.get(section, [])
        if not chunks:
            continue
        block = f"### {section}\n" + "\n".join(chunks[:MAX_CHUNKS_PER_SECTION])
        if total + len(block) > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total
            if remaining > 200:
                context_parts.append(block[:remaining])
            break
        context_parts.append(block)
        total += len(block)

    context_text = "\n\n".join(context_parts) if context_parts else "(данные из документов не найдены)"

    template_part = ""
    tpl = (state.get("template_context") or "").strip()
    has_template = bool(tpl)
    if has_template:
        template_part = (
            f"\n\nОБЯЗАТЕЛЬНЫЙ ШАБЛОН (сохрани порядок разделов и заголовки; "
            f"замени плейсхолдеры в квадратных скобках на факты из дела или [ЗАПОЛНИТЬ]):\n"
            f"{tpl[:MAX_TEMPLATE_IN_PROMPT]}"
        )

    instr_template = ""
    if has_template:
        instr_template = (
            "- Не выдумывай новую структуру: следуй шаблону выше (заголовки разделов как в шаблоне).\n"
            "- Подставляй данные из «ДАННЫЕ ИЗ ДОКУМЕНТОВ ДЕЛА»; недостающее — [ЗАПОЛНИТЬ].\n"
        )
    else:
        instr_template = (
            "- Структура: все стандартные разделы для данного типа документа.\n"
        )

    prompt = f"""Составь профессиональный юридический документ.

ТИП ДОКУМЕНТА: {state['document_type']}
ЗАПРОС: {state['query']}
НАЗВАНИЕ: {state['title']}
{template_part}

ДАННЫЕ ИЗ ДОКУМЕНТОВ ДЕЛА:
{context_text}

ИНСТРУКЦИИ:
- Создай полноценный документ в формате HTML
- Используй реальные данные из раздела «ДАННЫЕ ИЗ ДОКУМЕНТОВ ДЕЛА» (имена, реквизиты, суммы, сроки)
- Если конкретного значения нет — пиши [ЗАПОЛНИТЬ]
{instr_template}
- Форматирование: h1, h2, p, ul, li, table где нужно
- Отвечай ТОЛЬКО HTML-кодом, без markdown-обёрток и комментариев"""

    try:
        raw = await _llm_call(prompt, temperature=0.2)
        content = raw.strip()
        # Strip markdown fences if LLM added them
        content = re.sub(r'^```html?\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*```$', '', content).strip()
        # Extract <body> if full HTML page
        body = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL | re.IGNORECASE)
        if body:
            content = body.group(1).strip()

        logger.info(f"[DraftGraph] generate: {len(content)} chars output")
        return {**state, "final_content": content}
    except Exception as e:
        logger.error(f"[DraftGraph] generate error: {e}", exc_info=True)
        return {**state, "error": str(e)}


# ── Main runner ───────────────────────────────────────────────────────────────

async def run_draft_graph(
    case_id: str,
    query: str,
    title: str,
    db: Session,
    template_context: str = "",
) -> AsyncGenerator[str, None]:
    """
    Run the full draft graph and yield SSE events.
    Final SSE event is a special marker containing the generated content.
    """
    queue: asyncio.Queue = asyncio.Queue()

    state: DraftState = {
        "case_id": case_id,
        "query": query,
        "title": title,
        "template_context": template_context,
        "document_type": "",
        "sections": [],
        "section_queries": {},
        "gathered": {},
        "gaps": [],
        "coverage_score": 0.0,
        "iterations": 0,
        "final_content": "",
        "error": "",
    }

    async def _run():
        nonlocal state
        try:
            # 1. Plan
            state = await plan_node(state, queue)

            # 2. Search → Evaluate loop
            while True:
                state = await search_node(state, queue, db)
                state = await evaluate_node(state, queue)

                enough = state["coverage_score"] >= COVERAGE_THRESHOLD
                max_iter = state["iterations"] >= MAX_ITERATIONS

                if enough or max_iter:
                    reason = "достаточно данных" if enough else f"достигнут лимит итераций ({MAX_ITERATIONS})"
                    logger.info(f"[DraftGraph] stopping loop: {reason}, score={state['coverage_score']:.2f}")
                    break

                # Still have gaps — refine queries and search again
                state = await refine_node(state, queue)

            # 3. Generate
            state = await generate_node(state, queue)

        except Exception as e:
            logger.error(f"[DraftGraph] fatal error: {e}", exc_info=True)
            state = {**state, "error": str(e)}
        finally:
            await queue.put(None)  # sentinel

    task = asyncio.create_task(_run())

    # Yield SSE events as they appear in the queue
    while True:
        item = await queue.get()
        if item is None:
            break
        yield item

    await task

    if state.get("error"):
        yield SSESerializer.error(f"Ошибка при генерации документа: {state['error']}")
    elif state.get("final_content"):
        # Internal marker intercepted by DraftHandler — not forwarded to client
        import json as _json
        payload = _json.dumps({
            "type": "_draft_content",
            "content": state["final_content"],
            "title": state["title"],
        }, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    else:
        yield SSESerializer.error("Документ не был сгенерирован")
