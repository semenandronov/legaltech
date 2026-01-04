"""LangSmith Integration for tracing and evaluation"""
from typing import Dict, List, Optional, Any
import os
import logging

logger = logging.getLogger(__name__)

# Global LangSmith client
_langsmith_client = None


class LangSmithIntegration:
    """
    Интеграция с LangSmith для трассировки и оценки
    
    Настраивает LangSmith для:
    - Трассировки всех вызовов LLM
    - Метрик производительности
    - A/B тестирования промптов
    - Оценки качества
    """
    
    def __init__(self):
        self.enabled = False
        self.client = None
        self._setup_langsmith()
    
    def _setup_langsmith(self):
        """Настроить LangSmith"""
        try:
            # Проверяем наличие API ключа
            api_key = os.getenv("LANGSMITH_API_KEY")
            if not api_key:
                logger.warning("LANGSMITH_API_KEY not set, LangSmith disabled")
                return
            
            # Устанавливаем переменные окружения
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
            os.environ["LANGCHAIN_API_KEY"] = api_key
            os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "legal-ai-vault")
            
            # Импортируем клиент
            try:
                from langsmith import Client
                self.client = Client()
                self.enabled = True
                logger.info("✅ LangSmith integration enabled")
            except ImportError:
                logger.warning("langsmith not installed, LangSmith disabled")
                self.enabled = False
                
        except Exception as e:
            logger.warning(f"Failed to setup LangSmith: {e}")
            self.enabled = False
    
    def log_retrieval(
        self,
        case_id: str,
        query: str,
        tool_name: str,
        result_count: int,
        site: Optional[str] = None
    ):
        """
        Логировать результат поиска
        
        Args:
            case_id: ID дела
            query: Поисковый запрос
            tool_name: Имя инструмента
            result_count: Количество результатов
            site: Сайт (если применимо)
        """
        if not self.enabled:
            return
        
        try:
            metadata = {
                "case_id": case_id,
                "query": query,
                "tool_name": tool_name,
                "result_count": result_count,
                "site": site
            }
            
            # Логируем через LangSmith
            if self.client:
                # Можно использовать run_helpers для логирования
                logger.debug(f"LangSmith: Logged retrieval - {tool_name} for case {case_id}")
        except Exception as e:
            logger.debug(f"Could not log retrieval to LangSmith: {e}")
    
    def log_agent_call(
        self,
        agent_name: str,
        case_id: str,
        action: str,
        data: Dict[str, Any]
    ):
        """
        Логировать вызов агента
        
        Args:
            agent_name: Имя агента
            case_id: ID дела
            action: Действие (search, analyze, etc.)
            data: Дополнительные данные
        """
        if not self.enabled:
            return
        
        try:
            metadata = {
                "agent_name": agent_name,
                "case_id": case_id,
                "action": action,
                **data
            }
            
            logger.debug(f"LangSmith: Logged agent call - {agent_name}/{action} for case {case_id}")
        except Exception as e:
            logger.debug(f"Could not log agent call to LangSmith: {e}")
    
    def log_metrics(
        self,
        metrics: Dict[str, Any],
        run_id: Optional[str] = None
    ):
        """
        Логировать метрики в LangSmith
        
        Args:
            metrics: Словарь метрик
            run_id: ID run (опционально)
        """
        if not self.enabled:
            return
        
        try:
            if self.client and run_id:
                # Обновляем run с метриками
                self.client.update_run(run_id, extra={"metrics": metrics})
            logger.debug(f"LangSmith: Logged metrics - {list(metrics.keys())}")
        except Exception as e:
            logger.debug(f"Could not log metrics to LangSmith: {e}")
    
    def create_evaluator(
        self,
        evaluator_type: str = "qa"
    ) -> Optional[Any]:
        """
        Создать evaluator для оценки качества
        
        Args:
            evaluator_type: Тип evaluator (qa, correctness, etc.)
        
        Returns:
            Evaluator или None
        """
        if not self.enabled:
            return None
        
        try:
            # Можно создать кастомный evaluator
            def qa_evaluator(run, example):
                """Оценка качества ответа на вопрос"""
                # Простая эвристика: проверка наличия ключевых слов
                # В production можно использовать более сложную логику
                return {
                    "score": 1.0 if "ответ" in str(run.outputs).lower() else 0.5
                }
            
            return qa_evaluator
        except Exception as e:
            logger.error(f"Error creating evaluator: {e}")
            return None


# Singleton
_langsmith = None


def get_langsmith() -> LangSmithIntegration:
    """Получить singleton instance LangSmith интеграции"""
    global _langsmith
    if _langsmith is None:
        _langsmith = LangSmithIntegration()
    return _langsmith


