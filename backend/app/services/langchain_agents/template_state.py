"""State for document template workflow"""
from typing import TypedDict, Optional, Dict, Any, List
from langchain_core.messages import BaseMessage


class TemplateState(TypedDict):
    """State для графа работы с шаблонами документов"""
    
    # Входные данные
    user_query: str  # Запрос пользователя ("Создай договор поставки")
    case_id: str
    user_id: str
    
    # Результаты поиска
    cached_template: Optional[Dict[str, Any]]  # Найденный шаблон из кэша
    garant_template: Optional[Dict[str, Any]]  # Шаблон из Гаранта
    
    # Источник шаблона
    template_source: Optional[str]  # "cache", "garant" или "user_file"
    
    # Файл-шаблон от пользователя
    template_file_id: Optional[str]  # ID файла из БД
    template_file_content: Optional[str]  # HTML контент файла-шаблона
    
    # Контекст дела
    case_context: Optional[str]  # Извлеченные факты из документов дела
    
    # Финальный шаблон для использования
    final_template: Optional[Dict[str, Any]]  # Шаблон для адаптации
    
    # Результат адаптации
    adapted_content: Optional[str]  # Адаптированный HTML контент
    
    # Созданный документ
    document_id: Optional[str]  # ID созданного документа
    
    # Сообщения для логирования
    messages: List[BaseMessage]
    
    # Ошибки
    errors: List[str]
    
    # Метаданные
    metadata: Dict[str, Any]
    
    # Опциональные параметры
    should_adapt: bool  # Нужна ли адаптация шаблона через LLM
    document_title: Optional[str]  # Название создаваемого документа

