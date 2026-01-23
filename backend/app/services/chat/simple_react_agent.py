"""
RAG Chat Agent v6.0 - Архитектура на основе LangGraph StateGraph

На основе изучения LangChain/LangGraph архитектур выбран подход:
**RAG + StateGraph с явным контролем цикла**

Почему эта архитектура:
1. RAG гарантирует ответы на основе реальных данных из документов
2. StateGraph даёт полный контроль над потоком (retrieve → generate)
3. Явное управление циклом предотвращает игнорирование результатов LLM
4. Масштабируется от 1 до 1000+ документов

Архитектура:
```
User Question
     ↓
[RETRIEVE] → Поиск релевантных фрагментов в Vector DB
     ↓
[GENERATE] → LLM генерирует ответ СТРОГО на основе контекста
     ↓
Answer
```

Ключевое отличие от ReAct: LLM не выбирает инструменты, 
а сразу получает контекст и генерирует ответ.
"""

import logging
from typing import List, Dict, Any, Optional, AsyncGenerator, TypedDict
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.documents import Document

from app.models.user import User
from app.services.rag_service import RAGService
from app.services.chat.events import SSESerializer

logger = logging.getLogger(__name__)


# === LangGraph State ===
class ChatState(TypedDict):
    """Состояние чата для LangGraph StateGraph"""
    question: str  # Вопрос пользователя
    context: str  # Контекст из документов (результат retrieve)
    sources: List[str]  # Источники (названия файлов)
    answer: str  # Финальный ответ
    chat_history: List[Dict]  # История чата


class SimpleReActAgent:
    """
    RAG Chat Agent с архитектурой StateGraph.
    
    Гарантирует ответы на основе реальных данных из документов.
    """
    
    # Системный промпт для генерации ответа
    GENERATE_PROMPT = """Ты - юридический AI-ассистент. Отвечай на вопросы пользователя СТРОГО на основе предоставленного контекста из документов.

КОНТЕКСТ ИЗ ДОКУМЕНТОВ:
{context}

ПРАВИЛА:
1. Используй ТОЛЬКО информацию из контекста выше
2. НЕ придумывай факты, даты, суммы, имена
3. Если информации недостаточно - честно скажи об этом
4. Указывай источники в формате [Название документа]
5. Отвечай кратко и по существу, как профессиональный юрист

ФОРМАТ ОТВЕТА:
- Пиши сразу ответ, без "На основе документов...", "Согласно контексту..."
- Используй конкретные данные: даты, суммы, имена из контекста
- В конце укажи источники

ЗАПРЕЩЕНО:
- Выдумывать информацию
- Отвечать на основе общих знаний (только контекст!)
- Писать "Дело № ХХХХ", "сторона A" - только реальные данные"""

    def __init__(
        self,
        case_id: str,
        db: Session,
        rag_service: RAGService,
        current_user: Optional[User] = None,
        legal_research: bool = False,
        deep_think: bool = False,
        web_search: bool = False,
        chat_history: Optional[List[Dict]] = None,
        session_id: Optional[str] = None
    ):
        """Инициализация агента."""
        self.case_id = case_id
        self.db = db
        self.rag_service = rag_service
        self.current_user = current_user
        self.user_id = str(current_user.id) if current_user else None
        self.session_id = session_id
        
        # Опции
        self.legal_research = legal_research
        self.deep_think = deep_think
        self.web_search = web_search
        
        # История чата
        self.chat_history = self._process_history(chat_history or [])
        
        # Создаём LLM
        self.llm = self._create_llm()
        
        logger.info(
            f"[RAGChatAgent] Initialized for case {case_id} "
            f"({len(self.chat_history)} history messages)"
        )
    
    def _process_history(self, history: List[Dict]) -> List[Dict]:
        """Обработка истории чата."""
        if not history:
            return []
        
        # Берём последние 10 сообщений
        recent = history[-10:]
        
        processed = []
        for msg in recent:
            content = msg.get("content", "")
            if len(content) > 1500:
                content = content[:1500] + "..."
            processed.append({
                "role": msg.get("role", "user"),
                "content": content
            })
        
        return processed
    
    def _create_llm(self):
        """Создать LLM."""
        from app.services.llm_factory import create_legal_llm
        return create_legal_llm(timeout=120.0)
    
    async def handle(
        self,
        question: str,
        stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Обработать вопрос пользователя.
        
        Архитектура StateGraph:
        1. RETRIEVE - поиск релевантных документов
        2. GENERATE - генерация ответа на основе контекста
            
        Yields:
            SSE события
        """
        try:
            logger.info(f"[RAGChatAgent] Processing: {question[:100]}...")
            
            # === Шаг 1: RETRIEVE ===
            yield SSESerializer.reasoning(
                phase="retrieve",
                step=1,
                total_steps=2,
                content="Поиск в документах дела..."
            )
            
            context, sources = await self._retrieve(question)
            
            if not context:
                yield SSESerializer.text_delta(
                    "В документах дела не найдена информация по вашему запросу. "
                    "Попробуйте переформулировать вопрос или загрузите необходимые документы."
            )
                return
            
            logger.info(f"[RAGChatAgent] Retrieved {len(sources)} sources, context length: {len(context)}")
            
            # === Шаг 2: GENERATE ===
            yield SSESerializer.reasoning(
                phase="generate",
                step=2,
                total_steps=2,
                content="Формирую ответ на основе документов..."
            )
            
            answer = await self._generate(question, context, sources)
            
            yield SSESerializer.text_delta(answer)
            
            logger.info(
                f"[RAGChatAgent] Completed. Sources: {len(sources)}, "
                f"Context: {len(context)} chars, Answer: {len(answer)} chars"
            )
                
        except Exception as e:
            logger.error(f"[RAGChatAgent] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка обработки запроса: {str(e)}")
    
    async def _retrieve(self, question: str) -> tuple[str, List[str]]:
        """
        RETRIEVE: Поиск релевантных документов.
        
        Использует RAG service для поиска в Vector DB.
        
        Returns:
            (context, sources) - контекст и список источников
        """
        try:
            # Получаем документы через RAG
            documents = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=question,
                k=30,  # Получаем больше для лучшего покрытия
                db=self.db
            )
            
            if not documents:
                logger.warning(f"[RAGChatAgent] No documents found for case {self.case_id}")
                return "", []
            
            # Форматируем контекст
            context_parts = []
            sources = []
            total_chars = 0
            max_chars = 12000  # Лимит контекста
            
            for i, doc in enumerate(documents):
                # Получаем источник
                source = doc.metadata.get("source_file", f"Документ {i+1}")
                if source not in sources:
                    sources.append(source)
                
                # Получаем контент
                content = doc.page_content
                if not content:
                    continue
                    
                # Проверяем лимит
                if total_chars + len(content) > max_chars:
                    # Обрезаем последний документ
                    available = max_chars - total_chars
                    if available > 200:
                        content = content[:available] + "..."
                    else:
                        break
                
                context_parts.append(f"[{source}]:\n{content}")
                total_chars += len(content)
            
            context = "\n\n---\n\n".join(context_parts)
            
            return context, sources
                
        except Exception as e:
            logger.error(f"[RAGChatAgent] Retrieve error: {e}", exc_info=True)
            return "", []
    
    async def _generate(self, question: str, context: str, sources: List[str]) -> str:
        """
        GENERATE: Генерация ответа на основе контекста.
        
        LLM получает ТОЛЬКО контекст из документов и генерирует ответ.
        Это гарантирует, что ответ основан на реальных данных.
        
        Returns:
            Ответ на вопрос
        """
        # Формируем промпт с контекстом
        system_prompt = self.GENERATE_PROMPT.format(context=context)
        
        messages = [SystemMessage(content=system_prompt)]
        
        # Добавляем историю чата для контекста разговора
        for msg in self.chat_history[-4:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                if role == "user":
                    messages.append(HumanMessage(content=content))
                else:
                    messages.append(AIMessage(content=content))
        
        # Добавляем текущий вопрос
        messages.append(HumanMessage(content=question))
            
        try:
            response = await self.llm.ainvoke(messages)
            answer = response.content if hasattr(response, 'content') else str(response)
            
            # Проверяем качество ответа
            if not answer or len(answer.strip()) < 20:
                logger.warning(f"[RAGChatAgent] Short answer: {len(answer)} chars")
                # Возвращаем контекст напрямую если LLM не справился
                return self._format_context_as_answer(context, sources)
            
            # Добавляем источники если их нет в ответе
            if sources and not any(s in answer for s in sources[:3]):
                answer += f"\n\n📁 Источники: {', '.join(sources[:5])}"
            
            return answer
            
        except Exception as e:
            logger.error(f"[RAGChatAgent] Generate error: {e}", exc_info=True)
            # Fallback - возвращаем контекст
            return self._format_context_as_answer(context, sources)
    
    def _format_context_as_answer(self, context: str, sources: List[str]) -> str:
        """Форматировать контекст как ответ (fallback)."""
        if not context:
            return "Не удалось найти информацию по вашему запросу."
        
        # Обрезаем если слишком длинный
        if len(context) > 3000:
            context = context[:3000] + "..."
        
        answer = f"Найденная информация из документов:\n\n{context}"
        if sources:
            answer += f"\n\n📁 Источники: {', '.join(sources[:5])}"
        
        return answer
    
    # === Синхронные методы для совместимости ===
    
    def handle_sync(self, question: str) -> str:
        """Синхронная обработка вопроса."""
        import asyncio
        import json
        
        async def collect_response():
            response_parts = []
            async for event in self.handle(question, stream=False):
                if '"type":"text_delta"' in event or '"type":"answer"' in event:
                    try:
                        for line in event.split('\n'):
                            if line.startswith('data:'):
                                data = json.loads(line[5:].strip())
                                if data.get('type') in ['text_delta', 'answer']:
                                    response_parts.append(data.get('content', ''))
                    except:
                        pass
            return ''.join(response_parts)
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, collect_response())
                    return future.result()
            else:
                return loop.run_until_complete(collect_response())
        except RuntimeError:
            return asyncio.run(collect_response())
