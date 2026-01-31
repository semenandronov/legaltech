"""
Sub-graph для пошагового мышления (deep_think).

Реализует многоэтапный процесс анализа:
1. Понимание вопроса
2. Анализ контекста
3. Построение аргументации
4. Формулирование выводов

# АРХИТЕКТУРА
```
START
  ↓
understand_question (понимание вопроса)
  ↓
analyze_context (анализ контекста)
  ↓
build_arguments (построение аргументации)
  ↓
formulate_conclusions (формулирование выводов)
  ↓
END
```

# ИСПОЛЬЗОВАНИЕ
```python
subgraph = create_thinking_subgraph()
result = subgraph.invoke({
    "question": "Какие риски в этом договоре?",
    "context": "Текст договора...",
    "deep_think": True
})
```
"""
from typing import TypedDict, Optional, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
import logging
import operator

logger = logging.getLogger(__name__)


# ============== State Definition ==============

class ThinkingStep(TypedDict):
    """Один шаг мышления."""
    phase: str  # "understand", "analyze", "argue", "conclude"
    step_number: int
    total_steps: int
    content: str


class ThinkingState(TypedDict):
    """
    Состояние sub-graph для пошагового мышления.
    """
    # Входные данные
    question: str
    context: str  # RAG + ГАРАНТ контекст
    
    # Настройки
    deep_think: bool
    max_steps: int
    
    # Промежуточные результаты
    understanding: Optional[str]
    analysis: Optional[str]
    arguments: Optional[List[str]]
    
    # Результаты
    thinking_steps: List[ThinkingStep]
    conclusions: str
    confidence: float
    
    # Метаданные
    errors: Optional[List[str]]


def create_initial_thinking_state(
    question: str,
    context: str,
    deep_think: bool = True,
    max_steps: int = 10
) -> ThinkingState:
    """Создать начальное состояние для мышления."""
    return ThinkingState(
        question=question,
        context=context,
        deep_think=deep_think,
        max_steps=max_steps,
        understanding=None,
        analysis=None,
        arguments=None,
        thinking_steps=[],
        conclusions="",
        confidence=0.0,
        errors=None
    )


# ============== Node Functions ==============

def understand_question_node(state: ThinkingState) -> ThinkingState:
    """
    Узел понимания вопроса.
    
    Разбирает вопрос на составляющие, определяет ключевые аспекты.
    """
    question = state["question"]
    
    logger.info(f"[Thinking] Understanding question: {question[:100]}...")
    
    new_state = dict(state)
    
    try:
        from app.services.llm_factory import create_llm
        
        llm = create_llm()
        
        prompt = f"""# ЗАДАЧА
Проанализируй юридический вопрос и выдели его ключевые аспекты.

# ВОПРОС
{question}

# ИНСТРУКЦИИ
1. Определи тип вопроса (фактический, правовой, смешанный)
2. Выдели ключевые правовые понятия
3. Определи, какая информация нужна для ответа
4. Сформулируй подвопросы, если вопрос сложный

# ФОРМАТ ОТВЕТА
Структурированный анализ вопроса в 3-5 предложениях."""

        response = llm.invoke([HumanMessage(content=prompt)])
        understanding = response.content if hasattr(response, 'content') else str(response)
        
        new_state["understanding"] = understanding
        new_state["thinking_steps"] = new_state.get("thinking_steps", []) + [
            ThinkingStep(
                phase="understand",
                step_number=1,
                total_steps=4,
                content=understanding
            )
        ]
        
        logger.info("[Thinking] Question understanding complete")
        
    except Exception as e:
        logger.error(f"[Thinking] Understanding error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Understanding error: {str(e)}"]
        new_state["understanding"] = f"Вопрос: {question}"
    
    return new_state


def analyze_context_node(state: ThinkingState) -> ThinkingState:
    """
    Узел анализа контекста.
    
    Анализирует предоставленный контекст в свете вопроса.
    """
    question = state["question"]
    context = state["context"]
    understanding = state.get("understanding", "")
    
    logger.info("[Thinking] Analyzing context...")
    
    new_state = dict(state)
    
    if not context:
        new_state["analysis"] = "Контекст не предоставлен. Ответ будет основан на общих знаниях."
        new_state["thinking_steps"] = new_state.get("thinking_steps", []) + [
            ThinkingStep(
                phase="analyze",
                step_number=2,
                total_steps=4,
                content=new_state["analysis"]
            )
        ]
        return new_state
    
    try:
        from app.services.llm_factory import create_llm
        
        llm = create_llm()
        
        prompt = f"""# ЗАДАЧА
Проанализируй контекст в свете поставленного вопроса.

# ВОПРОС
{question}

# ПОНИМАНИЕ ВОПРОСА
{understanding}

# КОНТЕКСТ
{context[:8000]}

# ИНСТРУКЦИИ
1. Выдели релевантные факты из контекста
2. Отметь противоречия, если есть
3. Определи пробелы в информации
4. Оцени достаточность контекста для ответа

# ФОРМАТ ОТВЕТА
Структурированный анализ контекста в 4-6 предложениях."""

        response = llm.invoke([HumanMessage(content=prompt)])
        analysis = response.content if hasattr(response, 'content') else str(response)
        
        new_state["analysis"] = analysis
        new_state["thinking_steps"] = new_state.get("thinking_steps", []) + [
            ThinkingStep(
                phase="analyze",
                step_number=2,
                total_steps=4,
                content=analysis
            )
        ]
        
        logger.info("[Thinking] Context analysis complete")
        
    except Exception as e:
        logger.error(f"[Thinking] Analysis error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Analysis error: {str(e)}"]
        new_state["analysis"] = "Анализ контекста не удался."
    
    return new_state


def build_arguments_node(state: ThinkingState) -> ThinkingState:
    """
    Узел построения аргументации.
    
    Формирует аргументы на основе анализа.
    """
    question = state["question"]
    understanding = state.get("understanding", "")
    analysis = state.get("analysis", "")
    context = state["context"]
    
    logger.info("[Thinking] Building arguments...")
    
    new_state = dict(state)
    
    try:
        from app.services.llm_factory import create_llm
        import json
        
        llm = create_llm()
        
        prompt = f"""# ЗАДАЧА
Построй аргументацию для ответа на юридический вопрос.

# ВОПРОС
{question}

# ПОНИМАНИЕ ВОПРОСА
{understanding}

# АНАЛИЗ КОНТЕКСТА
{analysis}

# КОНТЕКСТ (для ссылок)
{context[:4000]}

# ИНСТРУКЦИИ
1. Сформулируй 3-5 ключевых аргументов
2. Каждый аргумент должен опираться на факты или нормы
3. Укажи источник для каждого аргумента
4. Отметь сильные и слабые стороны позиции

# ФОРМАТ ОТВЕТА (JSON)
{{
    "arguments": [
        {{
            "claim": "Основное утверждение",
            "evidence": "Доказательство/источник",
            "strength": "strong/medium/weak"
        }}
    ],
    "counter_arguments": ["Возможный контраргумент 1"],
    "overall_strength": "strong/medium/weak"
}}"""

        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Парсим JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            result = json.loads(json_match.group())
            arguments = result.get("arguments", [])
        else:
            arguments = [{"claim": response_text, "evidence": "Из контекста", "strength": "medium"}]
        
        # Форматируем аргументы для шагов мышления
        args_text = "\n".join([
            f"• {arg.get('claim')} [{arg.get('strength')}]\n  Источник: {arg.get('evidence')}"
            for arg in arguments
        ])
        
        new_state["arguments"] = [arg.get("claim") for arg in arguments]
        new_state["thinking_steps"] = new_state.get("thinking_steps", []) + [
            ThinkingStep(
                phase="argue",
                step_number=3,
                total_steps=4,
                content=args_text
            )
        ]
        
        logger.info(f"[Thinking] Built {len(arguments)} arguments")
        
    except Exception as e:
        logger.error(f"[Thinking] Arguments error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Arguments error: {str(e)}"]
        new_state["arguments"] = []
    
    return new_state


def formulate_conclusions_node(state: ThinkingState) -> ThinkingState:
    """
    Узел формулирования выводов.
    
    Синтезирует финальные выводы на основе всего анализа.
    """
    question = state["question"]
    understanding = state.get("understanding", "")
    analysis = state.get("analysis", "")
    arguments = state.get("arguments", [])
    
    logger.info("[Thinking] Formulating conclusions...")
    
    new_state = dict(state)
    
    try:
        from app.services.llm_factory import create_llm
        
        llm = create_llm()
        
        args_str = "\n".join([f"• {arg}" for arg in arguments]) if arguments else "Аргументы не сформулированы"
        
        prompt = f"""# ЗАДАЧА
Сформулируй итоговые выводы по юридическому вопросу.

# ВОПРОС
{question}

# ПОНИМАНИЕ ВОПРОСА
{understanding}

# АНАЛИЗ КОНТЕКСТА
{analysis}

# АРГУМЕНТЫ
{args_str}

# ИНСТРУКЦИИ
1. Синтезируй главный вывод
2. Укажи степень уверенности (высокая/средняя/низкая)
3. Дай практические рекомендации
4. Отметь ограничения анализа

# ФОРМАТ ОТВЕТА
Структурированные выводы в 3-5 пунктах."""

        response = llm.invoke([HumanMessage(content=prompt)])
        conclusions = response.content if hasattr(response, 'content') else str(response)
        
        # Определяем confidence
        conclusions_lower = conclusions.lower()
        if "высокая уверенность" in conclusions_lower or "уверен" in conclusions_lower:
            confidence = 0.9
        elif "низкая уверенность" in conclusions_lower or "не уверен" in conclusions_lower:
            confidence = 0.5
        else:
            confidence = 0.7
        
        new_state["conclusions"] = conclusions
        new_state["confidence"] = confidence
        new_state["thinking_steps"] = new_state.get("thinking_steps", []) + [
            ThinkingStep(
                phase="conclude",
                step_number=4,
                total_steps=4,
                content=conclusions
            )
        ]
        
        logger.info(f"[Thinking] Conclusions formulated, confidence: {confidence}")
        
    except Exception as e:
        logger.error(f"[Thinking] Conclusions error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Conclusions error: {str(e)}"]
        new_state["conclusions"] = "Не удалось сформулировать выводы."
        new_state["confidence"] = 0.3
    
    return new_state


# ============== Graph Builder ==============

def create_thinking_subgraph():
    """
    Создать sub-graph для пошагового мышления.
    
    Returns:
        Compiled sub-graph
    """
    logger.info("[Thinking] Creating thinking subgraph")
    
    graph = StateGraph(ThinkingState)
    
    # Добавляем узлы
    graph.add_node("understand_question", understand_question_node)
    graph.add_node("analyze_context", analyze_context_node)
    graph.add_node("build_arguments", build_arguments_node)
    graph.add_node("formulate_conclusions", formulate_conclusions_node)
    
    # Добавляем рёбра
    graph.add_edge(START, "understand_question")
    graph.add_edge("understand_question", "analyze_context")
    graph.add_edge("analyze_context", "build_arguments")
    graph.add_edge("build_arguments", "formulate_conclusions")
    graph.add_edge("formulate_conclusions", END)
    
    # Компилируем
    compiled = graph.compile()
    
    logger.info("[Thinking] Subgraph created successfully")
    return compiled

