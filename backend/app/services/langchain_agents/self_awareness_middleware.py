"""Self-Awareness Middleware for enhancing agent prompts"""
from typing import Any, List
from langchain_core.messages import SystemMessage
from app.services.agent_self_awareness import SelfAwarenessService
import logging

logger = logging.getLogger(__name__)


class SelfAwarenessMiddleware:
    """
    Middleware для добавления самосознания в промпты агентов
    
    Вызывается перед вызовом LLM, добавляет системное сообщение
    с результатами анализа пробелов и предложенной стратегией поиска
    """
    
    def __init__(self):
        self.self_awareness = SelfAwarenessService()
        logger.info("✅ SelfAwarenessMiddleware initialized")
    
    def enhance_prompt(
        self,
        messages: List[Any],
        case_documents: str,
        agent_output: str = "",
        task_type: str = "analysis"
    ) -> List[Any]:
        """
        Улучшает промпт информацией о пробелах в знаниях
        
        Args:
            messages: Существующие сообщения
            case_documents: Текст документов дела
            agent_output: Промежуточный вывод агента
            task_type: Тип задачи
        
        Returns:
            Обновленные сообщения с системным сообщением о пробелах
        """
        # Анализируем пробелы
        gaps = self.self_awareness.identify_knowledge_gaps(
            case_documents=case_documents,
            agent_output=agent_output,
            task_type=task_type
        )
        
        if not gaps:
            return messages
        
        # Генерируем стратегию поиска
        strategy = self.self_awareness.generate_search_strategy(gaps)
        
        # Формируем системное сообщение
        gap_descriptions = {
            "MISSING_NORM": "не хватает нормы права",
            "MISSING_PRECEDENT": "не хватает прецедента",
            "MISSING_COURT_POSITION": "не хватает позиции Верховного Суда",
            "UNCLEAR_INTERPRETATION": "неясное толкование"
        }
        
        gap_text = ", ".join([gap_descriptions.get(g.value, g.value) for g in gaps])
        strategy_text = "\n".join([
            f"- {s['tool']} (приоритет {s['priority']})" for s in strategy
        ])
        
        awareness_message = f"""Обнаружены пробелы в знаниях: {gap_text}

Рекомендуемая стратегия поиска:
{strategy_text}

Используй соответствующие инструменты для поиска недостающей информации."""
        
        # Добавляем системное сообщение в начало
        enhanced_messages = [SystemMessage(content=awareness_message)] + messages
        
        logger.info(f"[Self-Awareness Middleware] Added awareness for {len(gaps)} gaps")
        
        return enhanced_messages











