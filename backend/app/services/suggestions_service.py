"""Smart Suggestions Service - генерация умных подсказок на основе контекста дела"""
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.services.rag_service import RAGService
from app.services.rag_service import RAGService
from app.services.langchain_agents.store_integration import get_store_instance
from app.services.llm_factory import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
import logging
import json
import uuid

logger = logging.getLogger(__name__)


class Suggestion(BaseModel):
    """Умная подсказка"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Уникальный ID подсказки")
    text: str = Field(..., description="Текст подсказки (вопрос или действие)")
    type: str = Field(..., description="Тип: 'question', 'action', 'analysis'")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Уверенность в релевантности")
    context: Optional[str] = Field(None, description="Контекст подсказки")


class SuggestionsService:
    """
    Сервис для генерации умных подсказок на основе:
    1. Типов документов в деле (из анализа)
    2. Истории взаимодействий (из Store)
    3. Текущего контекста
    """
    
    def __init__(self, store: Optional[Any] = None, rag_service: Optional["RAGService"] = None):
        """
        Инициализация SuggestionsService
        
        Args:
            store: LangGraph Store instance (optional, будет получен автоматически)
            rag_service: RAGService instance (optional, нужен для анализа документов)
        """
        self.store = store or get_store_instance()
        self.rag_service = rag_service
    
    def get_suggestions(
        self,
        case_id: str,
        context: Optional[str] = None,
        limit: int = 5,
        db: Optional[Session] = None
    ) -> List[Suggestion]:
        """
        Генерирует умные подсказки на основе анализа документов и истории
        
        Args:
            case_id: ID дела
            context: Текущий контекст (опционально)
            limit: Максимальное количество подсказок
            db: Database session (опционально, для анализа документов)
            
        Returns:
            Список Suggestion объектов
        """
        namespace = ("suggestions", case_id)
        
        # Проверяем кэш в Store (только если нет контекста)
        if not context and self.store:
            try:
                cached = self._get_from_store(namespace, "cached_suggestions")
                if cached:
                    return [Suggestion(**s) for s in cached.get("suggestions", [])][:limit]
            except Exception as e:
                logger.debug(f"Failed to load cached suggestions: {e}")
        
        # Анализируем документы дела
        doc_analysis = self._analyze_documents(case_id, db)
        
        # Получаем историю из Store
        history = self._get_history(case_id)
        
        # Генерируем подсказки
        suggestions = self._generate_suggestions(
            doc_analysis=doc_analysis,
            history=history,
            context=context
        )
        
        # Кэшируем в Store (только если нет контекста)
        if not context and self.store and suggestions:
            try:
                self._save_to_store(
                    namespace,
                    "cached_suggestions",
                    {"suggestions": [s.dict() for s in suggestions]}
                )
            except Exception as e:
                logger.debug(f"Failed to cache suggestions: {e}")
        
        return suggestions[:limit]
    
    def _analyze_documents(self, case_id: str, db: Optional[Session] = None) -> Dict[str, Any]:
        """Анализирует документы дела для определения типа и ключевых сущностей"""
        doc_analysis = {
            "case_type": "unknown",
            "document_types": [],
            "entities": [],
            "file_count": 0
        }
        
        if not db:
            return doc_analysis
        
        try:
            from app.models.case import Case
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                doc_analysis["file_count"] = case.num_documents or 0
                doc_analysis["file_names"] = case.file_names or []
                
                # Попытаться определить тип дела из названий файлов
                file_names = case.file_names or []
                if any("договор" in name.lower() or "contract" in name.lower() for name in file_names):
                    doc_analysis["case_type"] = "contract"
                    doc_analysis["document_types"] = ["contract"]
                elif any("иск" in name.lower() or "claim" in name.lower() for name in file_names):
                    doc_analysis["case_type"] = "litigation"
                    doc_analysis["document_types"] = ["litigation"]
                elif any("суд" in name.lower() or "court" in name.lower() for name in file_names):
                    doc_analysis["case_type"] = "court"
                    doc_analysis["document_types"] = ["court_documents"]
                
        except Exception as e:
            logger.warning(f"Failed to analyze documents for case {case_id}: {e}")
        
        return doc_analysis
    
    def _get_history(self, case_id: str) -> List[Dict[str, Any]]:
        """Получает историю взаимодействий из Store"""
        if not self.store:
            return []
        
        try:
            history_namespace = ("history", case_id)
            history_items = self._search_in_store(history_namespace, limit=10)
            
            # Преобразуем в список словарей
            history = []
            for item in history_items:
                if isinstance(item, dict):
                    history.append(item)
                elif hasattr(item, 'value'):
                    history.append(item.value if hasattr(item.value, '__dict__') else item.value)
            
            return history
        except Exception as e:
            logger.debug(f"Failed to get history from store: {e}")
            return []
    
    def _generate_suggestions(
        self,
        doc_analysis: Dict[str, Any],
        history: List[Dict[str, Any]],
        context: Optional[str]
    ) -> List[Suggestion]:
        """Использует LLM для генерации релевантных подсказок"""
        
        # Формируем промпт
        doc_info = f"""
Тип дела: {doc_analysis.get('case_type', 'unknown')}
Количество документов: {doc_analysis.get('file_count', 0)}
Типы документов: {', '.join(doc_analysis.get('document_types', []))}
"""
        
        history_text = ""
        if history:
            history_text = "\nПоследние вопросы:\n"
            for i, h in enumerate(history[-5:], 1):  # Последние 5
                question = h.get("question", h.get("text", ""))
                if question:
                    history_text += f"{i}. {question}\n"
        
        context_text = context or "Начало сессии"
        
        prompt = f"""На основе анализа документов и истории, предложи 5 релевантных вопросов или действий для пользователя.

Анализ документов:
{doc_info}
{history_text}
Текущий контекст: {context_text}

Предложи вопросы/действия, которые помогут пользователю эффективно работать с этим делом.
Ответь в JSON формате:
[{{"text": "вопрос или действие", "type": "question|action|analysis", "confidence": 0.0-1.0}}]
"""
        
        try:
            llm = create_llm()
            
            # Пытаемся использовать with_structured_output если доступен
            try:
                from typing import get_type_hints
                structured_llm = llm.with_structured_output(List[Suggestion])
                result = structured_llm.invoke([HumanMessage(content=prompt)])
                return result if isinstance(result, list) else []
            except (AttributeError, Exception) as e:
                logger.debug(f"with_structured_output not available, using manual parsing: {e}")
                # Fallback: обычный вызов и парсинг JSON
                messages = [
                    SystemMessage(content="Ты помощник-юрист. Отвечай ТОЛЬКО в формате JSON массива, без дополнительного текста."),
                    HumanMessage(content=prompt)
                ]
                response = llm.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Парсим JSON
                try:
                    # Извлекаем JSON из ответа (может быть обернут в markdown code blocks)
                    import re
                    json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                    if json_match:
                        json_text = json_match.group(0)
                        suggestions_data = json.loads(json_text)
                        return [Suggestion(**s) for s in suggestions_data]
                except (json.JSONDecodeError, KeyError, TypeError) as parse_error:
                    logger.warning(f"Failed to parse suggestions JSON: {parse_error}")
                    return self._get_fallback_suggestions(doc_analysis)
                
                return self._get_fallback_suggestions(doc_analysis)
        except Exception as e:
            logger.error(f"Error generating suggestions: {e}", exc_info=True)
            return self._get_fallback_suggestions(doc_analysis)
    
    def _get_fallback_suggestions(self, doc_analysis: Dict[str, Any]) -> List[Suggestion]:
        """Возвращает fallback подсказки если LLM генерация не удалась"""
        case_type = doc_analysis.get("case_type", "unknown")
        
        fallback_suggestions = [
            Suggestion(
                text="Какие ключевые сроки важны в этом деле?",
                type="question",
                confidence=0.7
            ),
            Suggestion(
                text="Какие ключевые факты можно извлечь из документов?",
                type="analysis",
                confidence=0.7
            ),
            Suggestion(
                text="Есть ли противоречия между документами?",
                type="question",
                confidence=0.6
            ),
        ]
        
        if case_type == "contract":
            fallback_suggestions.append(Suggestion(
                text="Какие риски есть в договоре?",
                type="question",
                confidence=0.8
            ))
        
        return fallback_suggestions[:5]
    
    def _save_to_store(self, namespace: tuple, key: str, value: Dict[str, Any]) -> bool:
        """Сохраняет данные в Store"""
        if not self.store:
            return False
        
        try:
            namespace_str = "/".join(namespace) if isinstance(namespace, tuple) else str(namespace)
            if hasattr(self.store, 'put'):
                self.store.put(namespace_str, key, value)
            elif hasattr(self.store, 'set'):
                self.store.set(namespace_str, key, value)
            return True
        except Exception as e:
            logger.debug(f"Failed to save to store: {e}")
            return False
    
    def _get_from_store(self, namespace: tuple, key: str) -> Optional[Dict[str, Any]]:
        """Получает данные из Store"""
        if not self.store:
            return None
        
        try:
            namespace_str = "/".join(namespace) if isinstance(namespace, tuple) else str(namespace)
            if hasattr(self.store, 'get'):
                return self.store.get(namespace_str, key)
            return None
        except Exception as e:
            logger.debug(f"Failed to get from store: {e}")
            return None
    
    def _search_in_store(self, namespace: tuple, limit: int = 10) -> List[Any]:
        """Ищет данные в Store"""
        if not self.store:
            return []
        
        try:
            namespace_str = "/".join(namespace) if isinstance(namespace, tuple) else str(namespace)
            if hasattr(self.store, 'list'):
                items = self.store.list(namespace_str)
                return list(items)[:limit] if items else []
            return []
        except Exception as e:
            logger.debug(f"Failed to search in store: {e}")
            return []
    
    def _format_history(self, history: List[Dict[str, Any]]) -> str:
        """Форматирует историю для промпта"""
        if not history:
            return "Истории взаимодействий нет"
        
        formatted = []
        for h in history[-10:]:  # Последние 10
            question = h.get("question", h.get("text", ""))
            if question:
                formatted.append(f"- {question}")
        
        return "\n".join(formatted) if formatted else "Истории взаимодействий нет"

