"""
Factory для создания assistants.

Создаёт экземпляры графов с преднастроенными конфигурациями.
"""
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
from sqlalchemy.orm import Session
import logging

from app.services.langchain_agents.assistants.config import (
    AssistantConfig,
    GraphType,
    get_assistant_config,
    ASSISTANT_CONFIGS,
)

logger = logging.getLogger(__name__)


@dataclass
class AssistantInstance:
    """
    Экземпляр assistant.
    
    Содержит скомпилированный граф и конфигурацию.
    """
    config: AssistantConfig
    graph: Any  # Compiled LangGraph
    
    async def invoke(
        self,
        input_state: Dict[str, Any],
        thread_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Выполнить запрос к assistant.
        
        Args:
            input_state: Входное состояние
            thread_id: ID потока для checkpointing
            **kwargs: Дополнительные параметры
        
        Returns:
            Результат выполнения
        """
        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}
        
        # Добавляем метаданные из конфигурации
        if self.config.metadata.mode:
            input_state.setdefault("mode", self.config.metadata.mode)
        
        input_state.setdefault("enable_garant", self.config.metadata.enable_garant)
        
        return await self.graph.ainvoke(input_state, config)
    
    async def stream(
        self,
        input_state: Dict[str, Any],
        thread_id: Optional[str] = None,
        stream_mode: str = "updates",
        **kwargs
    ):
        """
        Стримить выполнение assistant.
        
        Args:
            input_state: Входное состояние
            thread_id: ID потока
            stream_mode: Режим стриминга (values, updates, messages)
            **kwargs: Дополнительные параметры
        
        Yields:
            Chunks из графа
        """
        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}
        
        # Добавляем метаданные
        if self.config.metadata.mode:
            input_state.setdefault("mode", self.config.metadata.mode)
        
        input_state.setdefault("enable_garant", self.config.metadata.enable_garant)
        
        async for chunk in self.graph.astream(input_state, config, stream_mode=stream_mode):
            yield chunk


def create_assistant(
    config: AssistantConfig,
    db: Session = None,
    rag_service=None,
    **kwargs
) -> AssistantInstance:
    """
    Создать экземпляр assistant из конфигурации.
    
    Args:
        config: Конфигурация assistant
        db: Database session
        rag_service: RAG service
        **kwargs: Дополнительные параметры для графа
    
    Returns:
        AssistantInstance
    """
    logger.info(f"[Assistants] Creating assistant: {config.id}")
    
    # Создаём граф в зависимости от типа
    if config.graph == GraphType.CHAT:
        from app.services.langchain_agents.graphs.chat_graph import create_chat_graph
        
        graph = create_chat_graph(
            db=db,
            rag_service=rag_service,
            use_checkpointing=config.use_checkpointing,
            enable_memory_management=config.enable_memory_management,
            interrupt_before=config.interrupt_before or None,
            interrupt_after=config.interrupt_after or None,
            **kwargs
        )
    
    elif config.graph == GraphType.TABULAR:
        from app.services.langchain_agents.graphs.tabular_graph import create_tabular_graph
        
        graph = create_tabular_graph(
            db=db,
            use_checkpointing=config.use_checkpointing,
            use_send_api=config.use_send_api,
            interrupt_before=config.interrupt_before or None,
            interrupt_after=config.interrupt_after or None,
            **kwargs
        )
    
    elif config.graph == GraphType.WORKFLOW:
        from app.services.langchain_agents.graphs.workflow_graph import create_workflow_graph
        
        graph = create_workflow_graph(
            db=db,
            rag_service=rag_service,
            use_checkpointing=config.use_checkpointing,
            use_send_api=config.use_send_api,
            interrupt_before=config.interrupt_before or None,
            interrupt_after=config.interrupt_after or None,
            **kwargs
        )
    
    else:
        raise ValueError(f"Unknown graph type: {config.graph}")
    
    logger.info(f"[Assistants] Assistant {config.id} created successfully")
    
    return AssistantInstance(config=config, graph=graph)


def get_assistant(
    assistant_id: str,
    db: Session = None,
    rag_service=None,
    **kwargs
) -> AssistantInstance:
    """
    Получить assistant по ID.
    
    Args:
        assistant_id: ID assistant
        db: Database session
        rag_service: RAG service
        **kwargs: Дополнительные параметры
    
    Returns:
        AssistantInstance
    
    Raises:
        ValueError: Если assistant не найден
    """
    config = get_assistant_config(assistant_id)
    
    if not config:
        available = list(ASSISTANT_CONFIGS.keys())
        raise ValueError(f"Assistant '{assistant_id}' not found. Available: {available}")
    
    return create_assistant(config, db=db, rag_service=rag_service, **kwargs)


# Кэш для assistants
_assistant_cache: Dict[str, AssistantInstance] = {}


def get_cached_assistant(
    assistant_id: str,
    db: Session = None,
    rag_service=None,
    force_recreate: bool = False,
    **kwargs
) -> AssistantInstance:
    """
    Получить assistant с кэшированием.
    
    Args:
        assistant_id: ID assistant
        db: Database session
        rag_service: RAG service
        force_recreate: Пересоздать даже если есть в кэше
        **kwargs: Дополнительные параметры
    
    Returns:
        AssistantInstance
    """
    global _assistant_cache
    
    if force_recreate or assistant_id not in _assistant_cache:
        _assistant_cache[assistant_id] = get_assistant(
            assistant_id,
            db=db,
            rag_service=rag_service,
            **kwargs
        )
    
    return _assistant_cache[assistant_id]


def clear_assistant_cache():
    """Очистить кэш assistants."""
    global _assistant_cache
    _assistant_cache.clear()

