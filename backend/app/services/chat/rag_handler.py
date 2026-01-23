"""
RAG Handler - Обработчик RAG-запросов

Отвечает за:
- Поиск релевантных документов
- Генерацию ответов с цитатами
- Интеграцию с ГАРАНТ
- Thinking (пошаговое мышление)

Production features:
- Circuit Breaker для ГАРАНТ
- Retry для LLM вызовов
- Graceful degradation
"""
from typing import AsyncGenerator, List, Dict, Any, Optional
from sqlalchemy.orm import Session
import logging
import re

from app.services.chat.events import (
    SSEEvent,
    TextDeltaEvent,
    CitationsEvent,
    ReasoningEvent,
    ErrorEvent,
    Citation,
    SSESerializer,
)
from app.services.chat.metrics import get_metrics, MetricTimer
from app.services.rag_service import RAGService
from app.models.user import User
from app.core.resilience import (
    CircuitBreakerRegistry,
    CircuitBreakerError,
    EXTERNAL_API_CIRCUIT_CONFIG,
    retry,
    RetryConfig,
    with_timeout,
)

logger = logging.getLogger(__name__)

# Circuit breakers для внешних сервисов
garant_circuit = CircuitBreakerRegistry.get("garant", EXTERNAL_API_CIRCUIT_CONFIG)


class RAGHandler:
    """
    Обработчик RAG-запросов.
    
    Выполняет:
    1. Поиск документов через RAG
    2. Поиск в ГАРАНТ (если включено)
    3. Thinking (пошаговое мышление)
    4. Генерация ответа с citations
    """
    
    def __init__(
        self,
        rag_service: RAGService,
        db: Session
    ):
        """
        Инициализация обработчика
        
        Args:
            rag_service: RAG сервис
            db: SQLAlchemy сессия
        """
        self.rag_service = rag_service
        self.db = db
        self.metrics = get_metrics()
    
    async def handle(
        self,
        case_id: str,
        question: str,
        current_user: User,
        chat_history: Optional[List[Dict[str, str]]] = None,
        legal_research: bool = False,
        deep_think: bool = False,
        web_search: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Обработать RAG-запрос
        
        Args:
            case_id: ID дела
            question: Вопрос пользователя
            current_user: Текущий пользователь
            chat_history: История чата
            legal_research: Включить поиск в ГАРАНТ
            deep_think: Включить глубокое мышление
            web_search: Включить веб-поиск
            
        Yields:
            SSE события (строки)
        """
        try:
            # 1. Получаем контекст из документов дела
            rag_docs = []
            rag_context = ""
            try:
                rag_docs = self.rag_service.retrieve_context(
                    case_id=case_id,
                    query=question,
                    k=5,
                    retrieval_strategy="multi_query",
                    db=self.db
                )
                if rag_docs:
                    rag_context = self.rag_service.format_sources_for_prompt(rag_docs, max_context_chars=4000)
                    logger.info(f"[RAGHandler] Retrieved {len(rag_docs)} docs for context")
            except Exception as e:
                logger.warning(f"[RAGHandler] RAG retrieval failed: {e}")
            
            # 2. Поиск в ГАРАНТ (если включено)
            garant_context = ""
            garant_citations = []
            if legal_research:
                garant_context, garant_citations = await self._search_garant(question)
            
            # 3. Thinking (пошаговое мышление)
            thinking_context = rag_context
            if garant_context:
                thinking_context += f"\n{garant_context}"
            
            async for event in self._run_thinking(question, thinking_context, deep_think):
                yield event
            
            # 4. Генерация ответа
            async for event in self._generate_response(
                question=question,
                rag_docs=rag_docs,
                rag_context=rag_context,
                garant_context=garant_context,
                garant_citations=garant_citations,
                chat_history=chat_history,
                deep_think=deep_think,
                legal_research=legal_research
            ):
                yield event
                
        except Exception as e:
            logger.error(f"[RAGHandler] Error: {e}", exc_info=True)
            yield SSESerializer.error(str(e))
    
    async def _search_garant(self, question: str) -> tuple[str, List[Dict[str, Any]]]:
        """
        Поиск в ГАРАНТ с Circuit Breaker
        
        Returns:
            (garant_context, garant_citations)
        """
        try:
            # Проверяем Circuit Breaker
            if not garant_circuit.can_execute():
                logger.warning("[RAGHandler] ГАРАНТ circuit breaker is OPEN, skipping")
                self.metrics.record_external_call("garant", success=False, reason="circuit_open")
                return "", []
            
            logger.info(f"[RAGHandler] Searching ГАРАНТ for: {question[:100]}…")
            from app.services.langchain_agents.utils import get_garant_source
            
            garant_source = get_garant_source()
            if not garant_source or not garant_source.api_key:
                logger.warning("[RAGHandler] ГАРАНТ source not available")
                return "", []
            
            # Выполняем поиск с Circuit Breaker
            async with garant_circuit:
                results = await garant_source.search(query=question, max_results=10)
            
            self.metrics.record_external_call("garant", success=True)
            
            if not results:
                logger.warning("[RAGHandler] ГАРАНТ returned no results")
                return "", []
            
            # Форматируем результаты
            formatted_parts = []
            citations = []
            
            for i, result in enumerate(results, 1):
                title = result.title or "Без названия"
                url = result.url or ""
                content = result.content[:1500] if result.content else ""
                
                metadata = getattr(result, 'metadata', {}) or {}
                doc_type = metadata.get('doc_type', '')
                doc_date = metadata.get('doc_date', '')
                doc_number = metadata.get('doc_number', '')
                doc_id = metadata.get('doc_id', '') or metadata.get('topic', '')
                
                formatted_parts.append(f"\n{'='*60}")
                formatted_parts.append(f"ДОКУМЕНТ {i} ИЗ ГАРАНТ")
                formatted_parts.append(f"{'='*60}")
                formatted_parts.append(f"Название: {title}")
                
                if doc_type:
                    formatted_parts.append(f"Тип: {doc_type}")
                if doc_date:
                    formatted_parts.append(f"Дата: {doc_date}")
                if doc_number:
                    formatted_parts.append(f"Номер: {doc_number}")
                if url:
                    formatted_parts.append(f"Ссылка: {url}")
                
                if content:
                    formatted_parts.append(f"\nСодержание:\n{content}")
                    if result.content and len(result.content) > 1500:
                        formatted_parts.append(f"\n[… документ обрезан …]")
                
                # Сохраняем для citations
                citations.append({
                    "source_id": f"garant_{doc_id or i}",
                    "file_name": title,
                    "page": None,
                    "quote": content[:500] if content else title,
                    "char_start": None,
                    "char_end": None,
                    "url": url,
                    "source_type": "garant",
                    "doc_type": doc_type,
                    "doc_date": doc_date,
                    "doc_number": doc_number
                })
            
            garant_context = f"\n\n=== РЕЗУЛЬТАТЫ ПОИСКА В ГАРАНТ ===\n" + "\n".join(formatted_parts) + "\n=== КОНЕЦ РЕЗУЛЬТАТОВ ГАРАНТ ===\n"
            logger.info(f"[RAGHandler] ГАРАНТ: {len(results)} results, {len(citations)} citations")
            
            return garant_context, citations
            
        except CircuitBreakerError as e:
            logger.warning(f"[RAGHandler] ГАРАНТ circuit breaker triggered: {e}")
            self.metrics.record_external_call("garant", success=False, reason="circuit_breaker")
            return "", []
        except Exception as e:
            logger.error(f"[RAGHandler] ГАРАНТ search error: {e}", exc_info=True)
            self.metrics.record_external_call("garant", success=False, reason="error")
            return "", []
    
    async def _run_thinking(
        self,
        question: str,
        context: str,
        deep_think: bool
    ) -> AsyncGenerator[str, None]:
        """
        Запустить thinking (пошаговое мышление)
        
        Yields:
            SSE события reasoning
        """
        try:
            from app.services.thinking_service import get_thinking_service
            
            thinking_service = get_thinking_service(deep_think=deep_think)
            mode = "DEEP THINK" if deep_think else "standard"
            logger.info(f"[RAGHandler] Starting {mode} thinking")
            
            async for step in thinking_service.think(
                question=question,
                context=context,
                stream_steps=True
            ):
                yield SSESerializer.reasoning(
                    phase=step.phase.value,
                    step=step.step_number,
                    total_steps=step.total_steps,
                    content=step.content
                )
                logger.debug(f"[RAGHandler] Thinking step {step.step_number}/{step.total_steps}")
                
        except Exception as e:
            logger.warning(f"[RAGHandler] Thinking error: {e}, continuing without thinking")
    
    async def _generate_response(
        self,
        question: str,
        rag_docs: List,
        rag_context: str,
        garant_context: str,
        garant_citations: List[Dict[str, Any]],
        chat_history: Optional[List[Dict[str, str]]],
        deep_think: bool,
        legal_research: bool
    ) -> AsyncGenerator[str, None]:
        """
        Генерация ответа
        
        Yields:
            SSE события (text_delta, citations)
        """
        # Собираем все citations
        all_citations = []
        
        # Добавляем ГАРАНТ citations
        if garant_citations:
            all_citations.extend(garant_citations)
        
        # Пробуем structured citations
        structured_result = None
        if rag_docs and not legal_research:
            try:
                structured_result = self.rag_service.generate_with_structured_citations(
                    query=question,
                    documents=rag_docs,
                    history=chat_history
                )
                
                if structured_result and structured_result.citations:
                    for citation in structured_result.citations:
                        all_citations.append({
                            "source_id": citation.source_id,
                            "file_name": citation.file_name,
                            "page": citation.page,
                            "quote": citation.quote,
                            "char_start": citation.char_start,
                            "char_end": citation.char_end,
                            "source_type": "document"
                        })
            except Exception as e:
                logger.warning(f"[RAGHandler] Structured citations failed: {e}")
        
        # Если есть structured result, используем его
        if structured_result and structured_result.answer:
            response_text = structured_result.answer
            
            # Добавляем inline citations если их нет
            if all_citations and not re.search(r"\[\d+\]", response_text):
                response_text = self._add_inline_citations(response_text, len(all_citations))
            
            # Stream по словам
            words = response_text.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield SSESerializer.text_delta(chunk)
        else:
            # Fallback на ChatAgent
            async for event in self._fallback_to_chat_agent(
                question=question,
                rag_context=rag_context,
                garant_context=garant_context,
                deep_think=deep_think,
                legal_research=legal_research
            ):
                yield event
        
        # Отправляем citations
        if all_citations:
            yield SSESerializer.citations(all_citations)
    
    def _add_inline_citations(self, text: str, num_citations: int) -> str:
        """Добавить inline citations в текст"""
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        rebuilt = []
        citation_idx = 0
        
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            if citation_idx < num_citations:
                sentence_stripped = sentence.rstrip()
                if sentence_stripped and sentence_stripped[-1] in '.!?':
                    punct = sentence_stripped[-1]
                    rebuilt.append(f"{sentence_stripped[:-1]}[{citation_idx + 1}]{punct}")
                else:
                    rebuilt.append(f"{sentence}[{citation_idx + 1}]")
                citation_idx += 1
            else:
                rebuilt.append(sentence)
        
        return " ".join(rebuilt)
    
    async def _fallback_to_chat_agent(
        self,
        question: str,
        rag_context: str,
        garant_context: str,
        deep_think: bool,
        legal_research: bool
    ) -> AsyncGenerator[str, None]:
        """
        Fallback на ChatAgent
        
        Yields:
            SSE события
        """
        try:
            from app.services.langchain_agents.legacy_stubs import ChatAgent
            
            # Формируем enhanced question
            enhanced_question = question
            
            if deep_think:
                enhanced_question = self._add_deep_think_instructions(enhanced_question)
            
            if garant_context:
                enhanced_question += f"\n\n{garant_context}\n{self._get_garant_instructions()}"
            
            if rag_context:
                enhanced_question += f"\n\n=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ДЕЛА ===\n{rag_context}\n=== КОНЕЦ КОНТЕКСТА ===\n"
            
            chat_agent = ChatAgent(
                case_id="",  # Не используется напрямую
                rag_service=self.rag_service,
                db=self.db,
                legal_research_enabled=legal_research
            )
            
            async for chunk in chat_agent.answer_stream(enhanced_question):
                if chunk:
                    yield SSESerializer.text_delta(chunk)
                    
        except Exception as e:
            logger.error(f"[RAGHandler] ChatAgent fallback error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка генерации ответа: {str(e)}")
    
    def _add_deep_think_instructions(self, question: str) -> str:
        """Добавить инструкции для deep think"""
        return f"""
=== РЕЖИМ ГЛУБОКОГО МЫШЛЕНИЯ (GigaChat Pro) ===
Ты ДОЛЖЕН предоставить всесторонний, детальный ответ:

1. **Правовой анализ**: Укажи применимые нормы права
2. **Судебная практика**: Приведи релевантные решения судов
3. **Анализ рисков**: Оцени возможные риски
4. **Контраргументы**: Рассмотри возможные возражения
5. **Рекомендации**: Дай конкретные практические рекомендации

Структурируй ответ:
📜 **Правовая база**
🏛️ **Судебная практика**
⚖️ **Анализ позиций**
⚠️ **Риски**
✅ **Рекомендации**
=== КОНЕЦ ИНСТРУКЦИИ ===

{question}"""
    
    def _get_garant_instructions(self) -> str:
        """Получить инструкции по использованию ГАРАНТ"""
        return """
=== ИНСТРУКЦИИ ПО ИСПОЛЬЗОВАНИЮ РЕЗУЛЬТАТОВ ГАРАНТ ===
1. Используй найденные документы для ответа
2. Цитируй конкретные статьи и законы
3. Указывай ссылки в формате [Название](URL)
4. Приоритет — информации из ГАРАНТ
=== КОНЕЦ ИНСТРУКЦИЙ ==="""


