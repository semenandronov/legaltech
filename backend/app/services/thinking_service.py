"""
Thinking Service - Сервис пошагового мышления ИИ

Реализует Chain-of-Thought reasoning для юридических задач.
Каждый ответ проходит через этапы анализа перед генерацией.
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import logging
import json
import time

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


class ThinkingPhase(Enum):
    """Фазы мышления ИИ"""
    UNDERSTANDING = "understanding"      # Понимание вопроса
    CONTEXT_ANALYSIS = "context"         # Анализ контекста
    REASONING = "reasoning"              # Рассуждение
    SYNTHESIS = "synthesis"              # Синтез ответа


@dataclass
class ThinkingStep:
    """Шаг мышления"""
    phase: ThinkingPhase
    step_number: int
    total_steps: int
    content: str
    duration_ms: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase.value,
            "step": self.step_number,
            "totalSteps": self.total_steps,
            "content": self.content,
            "duration_ms": self.duration_ms
        }


class ThinkingService:
    """
    Сервис пошагового мышления для юридического ИИ.
    
    Реализует подход, аналогичный Harvey AI и CoCounsel:
    1. Понимание вопроса - что именно спрашивает пользователь
    2. Анализ контекста - какие документы/факты релевантны
    3. Рассуждение - логические выводы
    4. Синтез - формирование ответа
    """
    
    PHASE_PROMPTS = {
        ThinkingPhase.UNDERSTANDING: """Проанализируй вопрос пользователя и определи:
1. Что именно спрашивает пользователь?
2. Какой тип вопроса (фактический, аналитический, сравнительный)?
3. Какие ключевые аспекты нужно рассмотреть?

Вопрос: {question}

Ответь кратко (2-3 предложения), начни с "Пользователь спрашивает о...".""",

        ThinkingPhase.CONTEXT_ANALYSIS: """На основе вопроса и доступного контекста определи:
1. Какие документы/источники релевантны?
2. Какие факты из контекста важны для ответа?
3. Есть ли пробелы в информации?

Вопрос: {question}
Контекст: {context}

Ответь кратко (2-3 предложения), начни с "Для ответа релевантны...".""",

        ThinkingPhase.REASONING: """Проведи логический анализ:
1. Какие выводы можно сделать из фактов?
2. Есть ли противоречия или неясности?
3. Какие юридические нормы применимы?

Вопрос: {question}
Контекст: {context}
Понимание: {understanding}

Ответь кратко (2-3 предложения), начни с "Анализируя факты...".""",

        ThinkingPhase.SYNTHESIS: """Сформулируй план ответа:
1. Какие ключевые пункты включить?
2. В каком порядке изложить?
3. Какие источники процитировать?

Вопрос: {question}
Рассуждение: {reasoning}

Ответь кратко (2-3 предложения), начни с "Ответ должен включать..."."""
    }
    
    def __init__(self, temperature: float = 0.1):
        """
        Инициализация сервиса мышления
        
        Args:
            temperature: Температура для LLM (низкая для точности)
        """
        self.llm = create_legal_llm(temperature=temperature)
        self.total_steps = len(ThinkingPhase)
        
    async def think(
        self,
        question: str,
        context: str = "",
        stream_steps: bool = True
    ) -> AsyncGenerator[ThinkingStep, None]:
        """
        Выполнить пошаговое мышление
        
        Args:
            question: Вопрос пользователя
            context: Контекст из документов (RAG)
            stream_steps: Стримить шаги по мере выполнения
            
        Yields:
            ThinkingStep для каждой фазы
        """
        logger.info(f"[ThinkingService] Starting thinking process for: {question[:100]}...")
        
        results = {}
        step_number = 0
        
        for phase in ThinkingPhase:
            step_number += 1
            start_time = time.time()
            
            try:
                # Формируем промпт для фазы
                prompt_template = self.PHASE_PROMPTS[phase]
                prompt = prompt_template.format(
                    question=question,
                    context=context[:2000] if context else "Контекст не предоставлен",
                    understanding=results.get(ThinkingPhase.UNDERSTANDING, ""),
                    reasoning=results.get(ThinkingPhase.REASONING, "")
                )
                
                # Вызываем LLM
                response = await self._call_llm(prompt)
                results[phase] = response
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                step = ThinkingStep(
                    phase=phase,
                    step_number=step_number,
                    total_steps=self.total_steps,
                    content=response,
                    duration_ms=duration_ms
                )
                
                logger.info(f"[ThinkingService] Phase {phase.value} completed in {duration_ms}ms")
                
                if stream_steps:
                    yield step
                    
            except Exception as e:
                logger.error(f"[ThinkingService] Error in phase {phase.value}: {e}")
                # Продолжаем с fallback
                step = ThinkingStep(
                    phase=phase,
                    step_number=step_number,
                    total_steps=self.total_steps,
                    content=f"Анализ {phase.value}...",
                    duration_ms=0
                )
                if stream_steps:
                    yield step
    
    async def _call_llm(self, prompt: str) -> str:
        """Вызов LLM с промптом"""
        try:
            system_message = SystemMessage(content="""Ты - юридический AI-ассистент, выполняющий пошаговый анализ.
Отвечай кратко и по существу. Используй русский язык.
Не добавляй лишних пояснений - только суть анализа.""")
            
            human_message = HumanMessage(content=prompt)
            
            response = self.llm.invoke([system_message, human_message])
            
            if isinstance(response, AIMessage):
                return response.content or ""
            elif hasattr(response, 'content'):
                return response.content or ""
            return str(response)
            
        except Exception as e:
            logger.error(f"[ThinkingService] LLM call failed: {e}")
            return ""
    
    def get_thinking_summary(self, steps: List[ThinkingStep]) -> str:
        """
        Получить краткое резюме процесса мышления
        
        Args:
            steps: Список выполненных шагов
            
        Returns:
            Форматированное резюме
        """
        summary_parts = []
        for step in steps:
            phase_name = {
                ThinkingPhase.UNDERSTANDING: "📋 Понимание",
                ThinkingPhase.CONTEXT_ANALYSIS: "🔍 Контекст", 
                ThinkingPhase.REASONING: "💭 Рассуждение",
                ThinkingPhase.SYNTHESIS: "✅ Синтез"
            }.get(step.phase, step.phase.value)
            
            summary_parts.append(f"{phase_name}: {step.content}")
        
        return "\n\n".join(summary_parts)


# Глобальный экземпляр сервиса
_thinking_service: Optional[ThinkingService] = None


def get_thinking_service() -> ThinkingService:
    """Получить глобальный экземпляр ThinkingService"""
    global _thinking_service
    if _thinking_service is None:
        _thinking_service = ThinkingService()
    return _thinking_service

