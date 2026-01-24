"""
Summary Chain - узел для генерации структурированного резюме дела.

# РОЛЬ
Узел-синтезатор, создающий краткое и информативное резюме дела
на основе извлечённых ключевых фактов.

# ПАТТЕРН: LangChain Chain (не агент)
Согласно рекомендациям LangGraph:
- summary не требует tools
- Это просто генерация текста на основе key_facts
- Chain достаточен, агент избыточен

# КОГДА ИСПОЛЬЗОВАТЬ
- Нужно создать резюме дела для быстрого ознакомления
- Есть извлечённые ключевые факты (key_facts_result)
- Требуется структурированный обзор дела

# КОГДА НЕ ИСПОЛЬЗОВАТЬ
- Нет ключевых фактов → сначала извлеки их
- Нужен глубокий анализ → используй deep_analysis
- Нужен поиск информации → используй rag_search
"""
from typing import Dict, Any, Optional, TypedDict
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage
from app.services.llm_factory import create_llm, create_legal_llm
import logging
import json

logger = logging.getLogger(__name__)


# Определяем AnalysisState локально
class AnalysisState(TypedDict, total=False):
    """Состояние анализа."""
    case_id: str
    user_id: str
    key_facts_result: Optional[Dict[str, Any]]
    summary_result: Optional[Dict[str, Any]]


def create_summary_chain():
    """
    Создать chain для генерации резюме.
    
    Returns:
        LangChain chain для генерации резюме
    """
    llm = create_legal_llm(use_rate_limiting=False)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """# РОЛЬ
Ты — юридический аналитик, создающий профессиональные резюме дел.

# ЦЕЛЬ
Создать краткое, структурированное и информативное резюме дела для быстрого ознакомления.

# ПРИНЦИПЫ
- Объективность: только факты, без домыслов
- Структурированность: чёткие разделы
- Краткость: главное без воды
- Практичность: выделяй важное для принятия решений

# ОГРАНИЧЕНИЯ (GUARDRAILS)
- НЕ добавляй информацию, которой нет в фактах
- НЕ делай выводы о виновности/невиновности
- НЕ давай юридических заключений
- Отмечай неполноту данных, если что-то неясно"""),
        ("human", """# КЛЮЧЕВЫЕ ФАКТЫ ДЕЛА
{key_facts}

# ЗАДАЧА
Создай профессиональное резюме дела по следующей структуре:

## 📋 Краткое описание
[2-3 предложения: суть дела, предмет спора]

## 👥 Участники
[Стороны дела с их ролями]

## 📅 Хронология
[Ключевые даты и события в хронологическом порядке]

## 📄 Ключевые документы
[Список важных документов с краткой характеристикой]

## ⚠️ Важные обстоятельства
[Факты, требующие особого внимания]

## 💡 Выводы
[Краткие выводы на основе фактов, без домыслов]

---
Резюме:""")
    ])
    
    chain = prompt | llm | StrOutputParser()
    return chain


def summary_chain_node(
    state: AnalysisState,
    db=None,
    rag_service=None
) -> AnalysisState:
    """
    Узел для генерации резюме дела.
    
    Args:
        state: Текущее состояние графа
        db: Database session (опционально)
        rag_service: RAG service (опционально)
    
    Returns:
        Обновлённое состояние с summary_result
    """
    case_id = state.get("case_id", "")
    
    try:
        logger.info(f"[SummaryChain] Generating summary for case {case_id}")
        
        # Получаем key_facts из состояния
        key_facts_result = state.get("key_facts_result", {})
        key_facts = key_facts_result.get("facts", [])
        
        if not key_facts:
            logger.warning(f"[SummaryChain] No key facts found for case {case_id}")
            new_state = dict(state)
            new_state["summary_result"] = {
                "summary": "Ключевые факты не найдены. Невозможно создать резюме.",
                "error": "no_key_facts"
            }
            return new_state
        
        # Форматируем ключевые факты
        key_facts_text = ""
        for i, fact in enumerate(key_facts, 1):
            if isinstance(fact, dict):
                fact_text = fact.get("fact", fact.get("text", str(fact)))
                category = fact.get("category", "")
                importance = fact.get("importance", "")
                key_facts_text += f"{i}. [{category}] {fact_text}"
                if importance:
                    key_facts_text += f" (важность: {importance})"
                key_facts_text += "\n"
            else:
                key_facts_text += f"{i}. {fact}\n"
        
        # Создаём chain и генерируем резюме
        chain = create_summary_chain()
        summary = chain.invoke({"key_facts": key_facts_text})
        
        logger.info(f"[SummaryChain] Generated summary for case {case_id}: {len(summary)} chars")
        
        new_state = dict(state)
        new_state["summary_result"] = {
            "summary": summary,
            "key_facts_count": len(key_facts),
            "generated": True
        }
        
        return new_state
        
    except Exception as e:
        logger.error(f"[SummaryChain] Error generating summary for case {case_id}: {e}", exc_info=True)
        new_state = dict(state)
        new_state["summary_result"] = {
            "summary": f"Ошибка генерации резюме: {str(e)}",
            "error": str(e)
        }
        return new_state
