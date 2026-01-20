"""
Core module - Ядро приложения

Содержит:
- container: Dependency Injection контейнер
- events: Базовые типы событий
"""

from app.core.container import (
    Container,
    get_container,
    get_rag_service,
    get_document_processor,
    get_chat_orchestrator,
    get_classifier,
    get_history_service,
)

__all__ = [
    "Container",
    "get_container",
    "get_rag_service",
    "get_document_processor",
    "get_chat_orchestrator",
    "get_classifier",
    "get_history_service",
]


