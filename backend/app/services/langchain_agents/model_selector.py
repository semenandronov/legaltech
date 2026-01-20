"""Model Selection Middleware for dynamic GigaChat Lite/Pro selection"""
from typing import Optional, Dict, Any
from app.config import config
from app.services.langchain_agents.state import AnalysisState
import logging

logger = logging.getLogger(__name__)

# Mapping агентов к моделям (Lite для простых, Pro для сложных)
AGENT_MODEL_MAPPING = {
    # Простые задачи - GigaChat Lite
    "document_classifier": "lite",  # Классификация документов
    "entity_extraction": "lite",  # Простые извлечения
    "timeline": "lite",  # Извлечение дат (может быть простым)
    "key_facts": "lite",  # Простые факты
    
    # Сложные задачи - GigaChat Pro
    "risk": "pro",  # Анализ рисков требует глубокого понимания
    "discrepancy": "pro",  # Поиск противоречий - сложная задача
    "deep_analysis": "pro",  # Глубокий анализ
    "planning": "pro",  # Сложное планирование
    "evaluation": "pro",  # Оценка результатов
    "supervisor": "lite",  # Supervisor может быть простым (rule-based) или сложным (LLM)
    "summary": "pro",  # Генерация резюме требует понимания контекста
    "relationship": "pro",  # Построение графа связей
    "privilege_check": "pro",  # Проверка привилегий - критично важна
}

# Пороговые значения для динамического выбора
CONTEXT_SIZE_THRESHOLD = 50000  # >50k токенов → Pro
DOCUMENT_COUNT_THRESHOLD = 20  # >20 файлов → Pro


class ModelSelector:
    """
    Middleware для динамического выбора модели GigaChat Lite/Pro
    
    Критерии выбора:
    1. По типу агента (hardcoded mapping)
    2. По сложности задачи (simple/medium/high)
    3. По размеру контекста (>50k токенов → Pro)
    4. По количеству документов (>20 файлов → Pro)
    """
    
    def __init__(self):
        self.model_selection_enabled = config.MODEL_SELECTION_ENABLED
        self.lite_model = config.GIGACHAT_LITE_MODEL
        self.pro_model = config.GIGACHAT_PRO_MODEL
        
        if not self.model_selection_enabled:
            logger.info("Model selection disabled, using default model")
    
    def select_model(
        self,
        agent_name: str,
        state: Optional[AnalysisState] = None,
        complexity: Optional[str] = None,
        context_size: Optional[int] = None,
        document_count: Optional[int] = None
    ) -> str:
        """
        Выбрать модель для агента
        
        Args:
            agent_name: Имя агента
            state: Состояние анализа (опционально)
            complexity: Сложность задачи (simple/medium/high)
            context_size: Размер контекста в токенах
            document_count: Количество документов
        
        Returns:
            Имя модели ("GigaChat-Lite" или "GigaChat-Pro")
        """
        if not self.model_selection_enabled:
            # Fallback к модели по умолчанию
            return config.GIGACHAT_MODEL
        
        # 1. Проверка по типу агента (приоритет 1)
        agent_mapping = AGENT_MODEL_MAPPING.get(agent_name)
        if agent_mapping:
            selected_model = self.lite_model if agent_mapping == "lite" else self.pro_model
            logger.debug(f"Model selected by agent mapping: {agent_name} → {selected_model}")
            return selected_model
        
        # 2. Проверка по размеру контекста (приоритет 2)
        if context_size and context_size > CONTEXT_SIZE_THRESHOLD:
            logger.debug(f"Model selected by context size: {context_size} tokens → {self.pro_model}")
            return self.pro_model
        
        # 3. Проверка по количеству документов (приоритет 3)
        if document_count and document_count > DOCUMENT_COUNT_THRESHOLD:
            logger.debug(f"Model selected by document count: {document_count} files → {self.pro_model}")
            return self.pro_model
        
        # 4. Проверка по сложности задачи (приоритет 4)
        if complexity:
            if complexity == "high":
                logger.debug(f"Model selected by complexity: {complexity} → {self.pro_model}")
                return self.pro_model
            elif complexity == "simple":
                logger.debug(f"Model selected by complexity: {complexity} → {self.lite_model}")
                return self.lite_model
        
        # 5. Извлечение сложности из state если доступно
        if state:
            understanding_result = state.get("understanding_result", {})
            state_complexity = understanding_result.get("complexity")
            if state_complexity:
                if state_complexity == "high":
                    return self.pro_model
                elif state_complexity == "simple":
                    return self.lite_model
            
            # Проверка количества документов из state
            context = state.get("context")
            if context and hasattr(context, 'num_documents'):
                if context.num_documents > DOCUMENT_COUNT_THRESHOLD:
                    return self.pro_model
        
        # 6. Fallback: по умолчанию используем Pro для безопасности
        # (лучше переплатить, чем получить плохой результат)
        logger.debug(f"Model selection fallback: {agent_name} → {self.pro_model} (default)")
        return self.pro_model
    
    def select_model_for_supervisor(
        self,
        state: AnalysisState,
        use_llm: bool = True
    ) -> str:
        """
        Выбрать модель для supervisor
        
        Args:
            state: Состояние анализа
            use_llm: Используется ли LLM для маршрутизации (или rule-based)
        
        Returns:
            Имя модели
        """
        if not use_llm:
            # Rule-based routing не требует LLM
            return self.lite_model
        
        # Для LLM supervisor проверяем сложность
        analysis_types = state.get("analysis_types", [])
        complexity = state.get("understanding_result", {}).get("complexity", "medium")
        
        # Если много типов анализа или высокая сложность → Pro
        if len(analysis_types) > 3 or complexity == "high":
            return self.pro_model
        
        return self.lite_model
    
    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """
        Получить информацию о модели
        
        Args:
            model_name: Имя модели
        
        Returns:
            Словарь с информацией о модели
        """
        is_lite = "lite" in model_name.lower() or model_name == self.lite_model
        return {
            "model": model_name,
            "type": "lite" if is_lite else "pro",
            "cost_tier": "low" if is_lite else "high",
            "capabilities": "basic" if is_lite else "advanced"
        }


# Глобальный экземпляр
_model_selector = None


def get_model_selector() -> ModelSelector:
    """Получить глобальный экземпляр ModelSelector"""
    global _model_selector
    if _model_selector is None:
        _model_selector = ModelSelector()
    return _model_selector







































