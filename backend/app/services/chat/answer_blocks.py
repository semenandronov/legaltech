"""
Phase 2: structured answer blocks with stable citation_id grounding.

Second pass after main response: LLM splits markdown into blocks with citation_ids,
then deterministic validation filters unknown ids and weak token overlap.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AnswerBlockDraft(BaseModel):
    block_id: str = Field(..., description="Stable id for the block")
    markdown_text: str = Field(..., description="Markdown for this block only")
    citation_ids: List[str] = Field(default_factory=list)


class AnswerBlocksLLMResponse(BaseModel):
    blocks: List[AnswerBlockDraft] = Field(default_factory=list)


def _tokens(text: str) -> Set[str]:
    if not text:
        return set()
    raw = re.findall(r"[A-Za-zА-Яа-яЁё0-9]{3,}", (text or "").lower())
    stop = {
        "это",
        "как",
        "так",
        "или",
        "что",
        "для",
        "при",
        "без",
        "его",
        "ее",
        "их",
        "они",
        "также",
        "если",
        "когда",
        "где",
        "который",
        "которая",
        "которые",
        "данный",
        "данная",
        "данные",
        "документ",
        "источник",
    }
    return {t for t in raw if t not in stop}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return float(inter) / float(union) if union else 0.0


def _citation_text_for_overlap(c: Dict[str, Any]) -> str:
    parts = [
        str(c.get("quote_anchor") or ""),
        str(c.get("quote") or ""),
        str(c.get("context_before") or "")[-200:],
        str(c.get("context_after") or "")[:200],
    ]
    return " ".join(parts)


def _catalog_citation_order(citations: List[Dict[str, Any]]) -> Dict[str, int]:
    """Индекс citation_id в каталоге retrieval (стабильный порядок чипов слева направо)."""
    order: Dict[str, int] = {}
    for i, c in enumerate(citations or []):
        cid = c.get("citation_id")
        if not cid:
            continue
        s = str(cid)
        if s not in order:
            order[s] = i
    return order


_BACKFILL_SKIP_RE = re.compile(
    r"(недостаточно\s+(данных|сведений|информации)|"
    r"не\s+хватает|для\s+полн(ой)?\s+квалификации|"
    r"требу(ется|ются)\s+уточнен|уточните|рекомендую\s+уточн|"
    r"не\s+представлен(о|ы)\s+(в\s+)?материал(ах)?)",
    re.IGNORECASE,
)


def _should_skip_citation_backfill(markdown_text: str) -> bool:
    """Блоки-дисклеймеры («не хватает данных») не добиваем цитатами из дела."""
    t = (markdown_text or "").strip()
    return bool(_BACKFILL_SKIP_RE.search(t))


def validate_answer_blocks_grounding(
    blocks: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    *,
    min_jaccard: float = 0.05,
    backfill_min_jaccard: float = 0.032,
    backfill_min_block_tokens: int = 5,
) -> List[Dict[str, Any]]:
    """
    - Drop citation_ids not present in citations.
    - Drop ids whose Jaccard(block_tokens, citation_tokens) < min_jaccard when block has text.
    - Strip [N] и [D:C] из markdown_text.
    - Упорядочивает citation_ids по позиции в каталоге цитат (убирает «7 перед 6» в UI).
    - Если модель не проставила ссылки, но блок содержательный — одна цитата с лучшим Jaccard
      (>= backfill_min_jaccard), кроме дисклеймеров про нехватку данных.
    """
    allowed: Dict[str, Dict[str, Any]] = {}
    for c in citations or []:
        cid = c.get("citation_id")
        if cid:
            allowed[str(cid)] = c

    cid_catalog_pos = _catalog_citation_order(citations)
    cite_tokens_cache: Dict[str, Set[str]] = {}

    out: List[Dict[str, Any]] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        bid = str(b.get("block_id") or "").strip() or str(uuid.uuid4())
        md = str(b.get("markdown_text") or "")
        md = re.sub(r"\[\d+\]", "", md)
        md = re.sub(r"\[\s*D\d+\s*:\s*C\d+\s*\]", "", md, flags=re.IGNORECASE)
        md = re.sub(r"[ \t]+\n", "\n", md).strip()

        block_tokens = _tokens(md)
        raw_ids = b.get("citation_ids") or []
        if not isinstance(raw_ids, list):
            raw_ids = []

        kept: List[str] = []
        for rid in raw_ids:
            sid = str(rid).strip()
            if sid not in allowed:
                continue
            if not block_tokens:
                kept.append(sid)
                continue
            if sid not in cite_tokens_cache:
                cite_tokens_cache[sid] = _tokens(_citation_text_for_overlap(allowed[sid]))
            if _jaccard(block_tokens, cite_tokens_cache[sid]) >= min_jaccard:
                kept.append(sid)

        unique_kept = list(dict.fromkeys(kept))
        kept_sorted = sorted(
            unique_kept,
            key=lambda x: (cid_catalog_pos.get(x, 10**9), x),
        )

        if (
            not kept_sorted
            and block_tokens
            and len(block_tokens) >= backfill_min_block_tokens
            and allowed
            and not _should_skip_citation_backfill(md)
        ):
            best_id: Optional[str] = None
            best_score = 0.0
            for sid, c in allowed.items():
                if sid not in cite_tokens_cache:
                    cite_tokens_cache[sid] = _tokens(_citation_text_for_overlap(c))
                ct = cite_tokens_cache[sid]
                if not ct:
                    continue
                sc = _jaccard(block_tokens, ct)
                if sc > best_score:
                    best_score, best_id = sc, sid
            if best_id and best_score >= backfill_min_jaccard:
                kept_sorted = [best_id]

        out.append({"block_id": bid, "markdown_text": md, "citation_ids": kept_sorted})
    return out


def _catalog_lines(citations: List[Dict[str, Any]], max_lines: int = 80) -> str:
    lines: List[str] = []
    for i, c in enumerate(citations or []):
        if i >= max_lines:
            lines.append("... (truncated)")
            break
        cid = c.get("citation_id") or ""
        fn = c.get("file_name") or ""
        excerpt = (c.get("quote_anchor") or c.get("quote") or "")[:400]
        excerpt = excerpt.replace("\n", " ")
        lines.append(f"- citation_id={cid!r} file={fn!r} excerpt={excerpt!r}")
    return "\n".join(lines)


def llm_generate_answer_blocks_structured(
    question: str,
    response_markdown: str,
    citations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Structured LLM call: returns blocks with citation_ids only from catalog.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.services.llm_factory import create_legal_llm

    if not (response_markdown or "").strip() or not citations:
        return []

    catalog = _catalog_lines(citations)
    sys = SystemMessage(
        content=(
            "Ты разбиваешь готовый ответ ассистента на логические блоки по смыслу.\n"
            "Один блок = одна законченная мысль: один абзац, один пункт списка или несколько предложений, если это одна тезисная линия с одними источниками.\n"
            "Если в абзаце несколько разных утверждений (разные факты, разные выводы) — разбей на несколько блоков: у каждого блока свои citation_ids только для утверждений ЭТОГО блока.\n"
            "ВАЖНО: любой блок, где пересказываются факты из материалов дела (тип документа, стороны, доводы, подписант, процедура, даты/номера если они в тексте ответа), "
            "ОБЯЗАН содержать хотя бы один citation_id из каталога, который эти факты подтверждает (по смыслу совпадает с excerpt в каталоге).\n"
            "Исключение — только блоки, где чисто перечисляется, чего не хватает для анализа без новых фактов из документа, или общие методические фразы без содержания из дела.\n"
            "Не прикрепляй цитату, если excerpt явно про другое; не сваливай все источники в один блок без необходимости.\n"
            "В citation_ids перечисляй id в порядке, в каком факты читаются в блоке (сверху вниз), иначе — как в каталоге сверху вниз.\n"
            "Для каждого блока верни markdown_text БЕЗ маркеров [1], [2], [D1:C3] — только чистый markdown.\n"
            "В citation_ids включай ТОЛЬКО значения citation_id из каталога ниже. Не выдумывай id.\n"
            "block_id: короткий латинский slug или uuid.\n"
            "Любые пояснения в рассуждениях (если модель их генерирует) — только на русском.\n"
            "В markdown_text не должно быть JSON, ```json, символов {\"blocks\" — только чистый markdown для пользователя."
        )
    )
    human = HumanMessage(
        content=(
            f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}\n\n"
            f"КАТАЛОГ ЦИТАТ (только эти citation_id разрешены):\n{catalog}\n\n"
            f"ОТВЕТ ДЛЯ РАЗБИВКИ НА БЛОКИ:\n{response_markdown}\n"
        )
    )
    try:
        llm = create_legal_llm(use_rate_limiting=False, streaming=False)
        json_hint = HumanMessage(
            content=(
                "Ответ верни СТРОГО в JSON без текста вокруг.\n"
                "Формат: {\"blocks\": [{\"block_id\": \"...\", \"markdown_text\": \"...\", \"citation_ids\": [\"...\"]}]}\n"
                "markdown_text: чистый markdown без маркеров [1]/[D:C] и без JSON/```.\n"
                "citation_ids: только из каталога."
            )
        )
        resp = llm.invoke([sys, human, json_hint])
        raw = resp.content if hasattr(resp, "content") else str(resp)
        try:
            parsed = AnswerBlocksLLMResponse.model_validate_json(raw)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", raw)
            if not m:
                raise
            parsed = AnswerBlocksLLMResponse.model_validate_json(m.group(0))
    except Exception as e:
        logger.warning("[answer_blocks] structured invoke failed: %s", e, exc_info=True)
        return []

    return [b.model_dump() for b in (parsed.blocks or [])]


def build_answer_blocks_pipeline(
    question: str,
    response_markdown: str,
    citations: List[Dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Generate blocks via LLM, then validate. Returns None if nothing usable."""
    drafts = llm_generate_answer_blocks_structured(question, response_markdown, citations)
    if not drafts:
        return None
    return validate_answer_blocks_grounding(drafts, citations)
