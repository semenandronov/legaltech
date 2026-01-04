"""Runtime Middleware - инжекция ToolRuntime в tools через LangGraph hooks"""
from typing import Any, Callable, Optional, Dict
from sqlalchemy.orm import Session
from app.services.langchain_agents.tool_runtime import ToolRuntime
from app.services.langchain_agents.context_schema import CaseContext
from app.services.langchain_agents.store import CaseStore
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from langchain_core.runnables import RunnableConfig
import logging

logger = logging.getLogger(__name__)


class RuntimeMiddleware:
    """
    Middleware для инжекции ToolRuntime в tools через LangGraph hooks
    
    Использует wrap_tool_call hook для перехвата вызовов tools и добавления runtime
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService
    ):
        """
        Инициализация RuntimeMiddleware
        
        Args:
            db: Сессия базы данных
            rag_service: RAG service для CaseStore
        """
        self.db = db
        self.rag_service = rag_service
    
    def create_runtime_from_state(self, state: AnalysisState) -> Optional[ToolRuntime]:
        """
        Создать ToolRuntime из состояния графа
        
        Args:
            state: Текущее состояние графа
            
        Returns:
            ToolRuntime или None если не удалось создать
        """
        try:
            case_id = state.get("case_id")
            if not case_id:
                logger.debug("RuntimeMiddleware: case_id not found in state")
                return None
            
            # Получаем context из state (если доступен)
            context = state.get("context")
            if context is None:
                # Создаём минимальный context если его нет
                context = CaseContext.from_minimal(case_id=case_id)
                logger.debug(f"RuntimeMiddleware: created minimal context for case {case_id}")
            elif isinstance(context, dict):
                # Если context это dict, конвертируем в CaseContext
                context = CaseContext(**context)
            elif not isinstance(context, CaseContext):
                # Если это не CaseContext, создаём новый
                context = CaseContext.from_minimal(case_id=case_id)
            
            # Создаём CaseStore
            store = CaseStore(db=self.db, case_id=case_id, rag_service=self.rag_service)
            
            # Создаём ToolRuntime
            runtime = ToolRuntime(context=context, store=store, state=state)
            
            logger.debug(f"RuntimeMiddleware: created runtime for case {case_id}")
            return runtime
            
        except Exception as e:
            logger.warning(f"RuntimeMiddleware: failed to create runtime from state: {e}")
            return None
    
    def wrap_tool_call(
        self,
        tool_call: Callable,
        config: RunnableConfig,
        state: Optional[AnalysisState] = None
    ) -> Callable:
        """
        LangGraph hook для обёртки вызовов tools
        
        Этот метод вызывается LangGraph перед каждым вызовом tool,
        позволяя нам инжектировать ToolRuntime через kwargs
        
        Args:
            tool_call: Оригинальная функция tool
            config: RunnableConfig от LangGraph (может содержать state)
            state: Опциональное состояние графа (если передано явно)
            
        Returns:
            Обёрнутая функция tool с runtime injection
        """
        def wrapped_tool_call(*args, **kwargs):
            """
            Обёрнутая функция tool с runtime injection
            """
            # Пытаемся получить state из config или использовать переданный
            current_state = state
            if current_state is None:
                # Пытаемся извлечь state из config
                # LangGraph может хранить state в config["configurable"] или config["recursion_limit"]
                if isinstance(config, dict):
                    # Проверяем различные места где может быть state
                    current_state = config.get("configurable", {}).get("state")
                    if current_state is None:
                        current_state = config.get("state")
            
            # Создаём runtime из state
            runtime = None
            if current_state:
                runtime = self.create_runtime_from_state(current_state)
            
            # Если runtime создан, добавляем его в kwargs
            if runtime:
                kwargs["runtime"] = runtime
                logger.debug(f"RuntimeMiddleware: injected runtime into {tool_call.__name__}")
            else:
                logger.debug(f"RuntimeMiddleware: no runtime available for {tool_call.__name__}, calling without runtime")
            
            # Вызываем оригинальную функцию tool
            return tool_call(*args, **kwargs)
        
        # Сохраняем метаданные оригинальной функции
        wrapped_tool_call.__name__ = getattr(tool_call, '__name__', 'wrapped_tool')
        wrapped_tool_call.__doc__ = getattr(tool_call, '__doc__', None)
        
        return wrapped_tool_call


def get_tools_with_runtime(
    state: AnalysisState,
    db: Session,
    rag_service: RAGService,
    critical_only: bool = False
) -> list:
    """
    Получить tools с runtime injection для использования в agent nodes
    
    Это основная функция для использования в agent nodes.
    Она получает tools и автоматически оборачивает их с runtime injection.
    
    Args:
        state: Текущее состояние графа (содержит context)
        db: Сессия базы данных
        rag_service: RAG service для CaseStore
        critical_only: Если True, возвращает только критические tools
        
    Returns:
        Список tools с runtime injection
        
    Usage:
        # В agent node:
        from app.services.langchain_agents.runtime_middleware import get_tools_with_runtime
        from app.services.langchain_agents.tools import get_all_tools, get_critical_agent_tools
        
        tools = get_tools_with_runtime(state, db, rag_service, critical_only=False)
        
        # Используем tools в агенте
        agent = create_legal_agent(llm, tools, ...)
    """
    # Получаем tools
    if critical_only:
        from app.services.langchain_agents.tools import get_critical_agent_tools
        tools = get_critical_agent_tools()
    else:
        from app.services.langchain_agents.tools import get_all_tools
        tools = get_all_tools()
    
    # Обёртываем с runtime injection
    return wrap_tools_with_runtime(tools, state, db, rag_service)


def wrap_tools_with_runtime(
    tools: list,
    state: AnalysisState,
    db: Session,
    rag_service: RAGService
) -> list:
    """
    Обернуть tools с runtime injection для использования в agent nodes
    
    Эта функция вызывается в agent nodes, где есть доступ к state,
    и оборачивает tools для инжекции ToolRuntime через kwargs
    
    Args:
        tools: Список LangChain tools для обёртки
        state: Текущее состояние графа (содержит context)
        db: Сессия базы данных
        rag_service: RAG service для CaseStore
        
    Returns:
        Список обёрнутых tools с runtime injection
        
    Usage:
        # В agent node:
        from app.services.langchain_agents.runtime_middleware import wrap_tools_with_runtime
        from app.services.langchain_agents.tools import get_all_tools
        
        tools = get_all_tools()
        wrapped_tools = wrap_tools_with_runtime(tools, state, db, rag_service)
        
        # Используем wrapped_tools в агенте
        agent = create_legal_agent(llm, wrapped_tools, ...)
    """
    middleware = RuntimeMiddleware(db=db, rag_service=rag_service)
    
    # Создаём runtime из state
    runtime = middleware.create_runtime_from_state(state)
    
    if runtime is None:
        logger.debug("RuntimeMiddleware: no runtime created, returning original tools")
        return tools
    
    wrapped_tools = []
    for tool in tools:
        if hasattr(tool, 'func'):
            # StructuredTool имеет func атрибут
            original_func = tool.func
            
            def make_wrapped_func(orig_func, rt):
                """Создать обёрнутую функцию с runtime injection"""
                def wrapped(*args, **kwargs):
                    kwargs["runtime"] = rt
                    return orig_func(*args, **kwargs)
                return wrapped
            
            # Создаём обёрнутую функцию
            wrapped_func = make_wrapped_func(original_func, runtime)
            
            # Создаём новую tool с обёрнутой функцией
            from langchain_core.tools import StructuredTool
            wrapped_tool = StructuredTool.from_function(
                func=wrapped_func,
                name=tool.name,
                description=tool.description,
                args_schema=getattr(tool, 'args_schema', None),
                return_direct=getattr(tool, 'return_direct', False)
            )
            wrapped_tools.append(wrapped_tool)
        else:
            # Простая функция - оборачиваем напрямую
            def make_wrapped_tool(t, rt):
                def wrapped(*args, **kwargs):
                    kwargs["runtime"] = rt
                    return t(*args, **kwargs)
                wrapped.__name__ = t.__name__
                wrapped.__doc__ = t.__doc__
                return wrapped
            
            wrapped_tools.append(make_wrapped_tool(tool, runtime))
    
    logger.debug(f"RuntimeMiddleware: wrapped {len(wrapped_tools)} tools with runtime (case_id={state.get('case_id')})")
    return wrapped_tools


def create_runtime_hook(
    db: Session,
    rag_service: RAGService,
    state: Optional[AnalysisState] = None
) -> Dict[str, Callable]:
    """
    Создать LangGraph hook для инжекции ToolRuntime
    
    Устаревший метод - используйте wrap_tools_with_runtime в agent nodes вместо этого.
    Оставлен для обратной совместимости.
    
    Args:
        db: Сессия базы данных
        rag_service: RAG service для CaseStore
        state: Опциональное начальное состояние (если доступно)
        
    Returns:
        Словарь с hook функциями для RunnableConfig
    """
    middleware = RuntimeMiddleware(db=db, rag_service=rag_service)
    
    def wrap_tool_call_hook(tool_call: Callable, config: RunnableConfig) -> Callable:
        """
        Hook функция для wrap_tool_call
        
        LangGraph вызывает эту функцию перед каждым tool call
        """
        return middleware.wrap_tool_call(tool_call, config, state)
    
    return {
        "wrap_tool_call": wrap_tool_call_hook
    }


def create_runtime_middleware(
    db: Session,
    rag_service: RAGService
) -> RuntimeMiddleware:
    """
    Создать RuntimeMiddleware экземпляр
    
    Устаревший метод для обратной совместимости.
    Используйте RuntimeMiddleware напрямую или create_runtime_hook.
    
    Args:
        db: Сессия базы данных
        rag_service: RAG service для CaseStore
        
    Returns:
        RuntimeMiddleware экземпляр
    """
    return RuntimeMiddleware(db=db, rag_service=rag_service)
