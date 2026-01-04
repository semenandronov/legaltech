"""ToolRuntime - runtime context для tools с доступом к context, store и state"""
from typing import Optional, Any, Dict
from app.services.langchain_agents.context_schema import CaseContext
from app.services.langchain_agents.store import CaseStore
from app.services.langchain_agents.state import AnalysisState
import logging

logger = logging.getLogger(__name__)


class ToolRuntime:
    """
    Runtime контекст для tools - предоставляет доступ к:
    - context: неизменяемые метаданные дела
    - store: долгосрочная память (RAG, entities, events)
    - state: текущее состояние анализа (read-only snapshot)
    
    Инжектируется в tools через middleware для унифицированного доступа
    к данным дела без необходимости передавать множество параметров.
    """
    
    def __init__(
        self,
        context: CaseContext,
        store: CaseStore,
        state: Optional[AnalysisState] = None
    ):
        """
        Инициализация ToolRuntime
        
        Args:
            context: Неизменяемый контекст дела
            store: Store для доступа к данным дела
            state: Текущее состояние анализа (опционально, read-only)
        """
        self.context = context
        self.store = store
        self._state = state
        
        logger.debug(f"ToolRuntime created for case_id={context.case_id}, user_id={context.user_id}")
    
    @property
    def case_id(self) -> str:
        """Удобный доступ к case_id из context"""
        return self.context.case_id
    
    @property
    def user_id(self) -> str:
        """Удобный доступ к user_id из context"""
        return self.context.user_id
    
    def get_state_field(self, field: str, default: Any = None) -> Any:
        """
        Безопасное чтение поля из state
        
        Args:
            field: Имя поля для чтения
            default: Значение по умолчанию если поле отсутствует
            
        Returns:
            Значение поля или default
        """
        if self._state is None:
            return default
        
        return self._state.get(field, default)
    
    def get_state_result(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Получить результат конкретного агента из state
        
        Args:
            agent_name: Имя агента (timeline, key_facts, discrepancy, и т.д.)
            
        Returns:
            Результат агента или None если не найден
        """
        result_key = f"{agent_name}_result"
        return self.get_state_field(result_key)
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для логирования/отладки"""
        return {
            "case_id": self.case_id,
            "user_id": self.user_id,
            "jurisdiction": self.context.jurisdiction,
            "case_type": self.context.case_type,
            "client_name": self.context.client_name,
            "has_state": self._state is not None,
            "state_keys": list(self._state.keys()) if self._state else []
        }

