"""
ReAct Chat Agent - Адаптивный агент для чата

Использует ReAct цикл (Reason + Act) для:
- Анализа вопроса пользователя
- Выбора нужных инструментов
- Итеративного получения информации
- Синтеза ответа

Ключевые особенности:
- Сам решает, какие инструменты использовать
- Адаптируется под тип вопроса (обзорный, конкретный, аналитический)
- Поддерживает пользовательские переключатели (GARANT, deep_think, web_search)
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging
import json

from app.services.chat.events import SSESerializer
from app.services.chat.chat_tools import get_chat_tools
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)


class ReActChatAgent:
    """
    Адаптивный агент для чата, использующий ReAct цикл.
    
    Сам анализирует вопрос и решает:
    - Какие инструменты вызвать
    - Сколько документов нужно (k=5 или k=100)
    - Нужен ли Map-Reduce для обзора всех документов
    """
    
    # Системный промпт для агента
    SYSTEM_PROMPT = """Ты - юридический AI-ассистент, который помогает анализировать документы дела и отвечать на вопросы.

ТВОЯ ЗАДАЧА: Понять вопрос пользователя и ВЫБРАТЬ ПРАВИЛЬНЫЕ ИНСТРУМЕНТЫ для ответа.

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:

1. **search_documents(query, k)** - Поиск по документам дела
   - Используй для конкретных вопросов ("какая сумма в договоре?", "что сказано о сроках?")
   - k=5-10 для простых вопросов
   - k=20-50 для сложных вопросов

2. **list_case_files()** - Список всех файлов в деле
   - Используй когда пользователь спрашивает "какие документы в деле?"

3. **summarize_all_documents()** - Обзор ВСЕХ документов (Map-Reduce)
   - ВАЖНО: Используй когда пользователь спрашивает:
     * "О чём все эти документы?"
     * "Расскажи о деле"
     * "Что содержится в документах?"
     * "Дай общий обзор"
   - Этот инструмент обрабатывает ВСЕ документы, даже если их 100+

4. **get_file_summary(filename)** - Обзор конкретного файла
   - Используй когда спрашивают о конкретном документе

5. **extract_entities(entity_types)** - Извлечь сущности (даты, имена, суммы)
   - Используй для вопросов "какие даты?", "какие суммы?", "кто участники?"

6. **find_contradictions()** - Найти противоречия между документами
   - Используй для вопросов о противоречиях и несоответствиях

7. **analyze_risks()** - Анализ юридических рисков
   - Используй для вопросов о рисках

8. **build_timeline()** - Построить хронологию событий
   - Используй для вопросов о последовательности событий

{optional_tools}

ПРАВИЛА:
1. ВСЕГДА используй инструменты для получения информации из документов
2. НЕ придумывай информацию - только то, что нашёл в документах
3. Для обзорных вопросов ОБЯЗАТЕЛЬНО используй summarize_all_documents
4. Можешь вызывать несколько инструментов для полного ответа
5. Цитируй источники в формате [Документ]

ФОРМАТ ОТВЕТА:
- Используй Markdown
- Структурируй ответ
- Указывай источники"""
    
    def __init__(
        self,
        case_id: str,
        db: Session,
        rag_service: RAGService,
        current_user: Optional[User] = None,
        # Пользовательские переключатели
        legal_research: bool = False,
        deep_think: bool = False,
        web_search: bool = False,
        chat_history: Optional[List[Dict[str, str]]] = None
    ):
        """
        Инициализация агента
        
        Args:
            case_id: ID дела
            db: SQLAlchemy сессия
            rag_service: RAG сервис
            current_user: Текущий пользователь
            legal_research: Включить поиск в GARANT
            deep_think: Включить глубокое мышление (GigaChat Pro)
            web_search: Включить веб-поиск
            chat_history: История чата
        """
        self.case_id = case_id
        self.db = db
        self.rag_service = rag_service
        self.current_user = current_user
        self.legal_research = legal_research
        self.deep_think = deep_think
        self.web_search = web_search
        self.chat_history = chat_history or []
        
        # Инициализируем инструменты
        self.tools = get_chat_tools(
            db=db,
            rag_service=rag_service,
            case_id=case_id,
            legal_research=legal_research,
            web_search=web_search
        )
        
        # Создаём LLM и агента
        self.llm = self._create_llm()
        self.agent = self._create_agent()
        
        logger.info(
            f"[ReActChatAgent] Initialized for case {case_id} "
            f"(tools={len(self.tools)}, deep_think={deep_think}, "
            f"legal_research={legal_research}, web_search={web_search})"
        )
    
    def _create_llm(self):
        """Создать LLM в зависимости от режима"""
        from app.services.llm_factory import create_legal_llm
        from app.config import config
        
        if self.deep_think:
            # Используем GigaChat Pro для глубокого анализа
            model = config.GIGACHAT_PRO_MODEL or "GigaChat-Pro"
            logger.info(f"[ReActChatAgent] Using deep_think mode with {model}")
            return create_legal_llm(model=model, temperature=0.2)
        else:
            # Стандартная модель
            return create_legal_llm(temperature=0.1)
    
    def _create_agent(self):
        """Создать ReAct агента с инструментами"""
        try:
            # Формируем системный промпт с опциональными инструментами
            optional_tools_text = ""
            if self.legal_research:
                optional_tools_text += """
9. **search_garant(query)** - Поиск в базе ГАРАНТ
   - Используй для вопросов о законах, статьях кодексов, судебной практике

10. **get_garant_full_text(doc_id)** - Полный текст документа из ГАРАНТ
"""
            if self.web_search:
                optional_tools_text += """
11. **web_research_tool(query)** - Поиск в интернете
   - Используй для актуальной информации, которой нет в документах
"""
            
            system_prompt = self.SYSTEM_PROMPT.format(
                optional_tools=optional_tools_text if optional_tools_text else "Дополнительные инструменты не включены."
            )
            
            # Пробуем создать агента через langgraph
            try:
                from langgraph.prebuilt import create_react_agent
                
                agent = create_react_agent(
                    self.llm,
                    self.tools,
                    messages_modifier=system_prompt
                )
                logger.info("[ReActChatAgent] Created agent via langgraph.prebuilt.create_react_agent")
                return agent
                
            except ImportError:
                # Fallback на agent_factory
                from app.services.langchain_agents.agent_factory import create_legal_agent
                
                agent = create_legal_agent(
                    llm=self.llm,
                    tools=self.tools,
                    system_prompt=system_prompt
                )
                logger.info("[ReActChatAgent] Created agent via agent_factory")
                return agent
                
        except Exception as e:
            logger.error(f"[ReActChatAgent] Failed to create agent: {e}", exc_info=True)
            raise
    
    async def handle(
        self,
        question: str,
        stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Обработать вопрос пользователя
        
        Args:
            question: Вопрос пользователя
            stream: Стримить ответ (по умолчанию True)
            
        Yields:
            SSE события
        """
        try:
            logger.info(f"[ReActChatAgent] Processing: {question[:100]}...")
            
            # Если включен deep_think, сначала запускаем thinking
            if self.deep_think:
                async for event in self._run_thinking(question):
                    yield event
            
            # Запускаем агента
            async for event in self._run_agent(question):
                yield event
                
        except Exception as e:
            logger.error(f"[ReActChatAgent] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка обработки запроса: {str(e)}")
    
    async def _run_thinking(self, question: str) -> AsyncGenerator[str, None]:
        """Запустить thinking (пошаговое мышление)"""
        try:
            from app.services.thinking_service import get_thinking_service
            
            thinking_service = get_thinking_service(deep_think=True)
            logger.info("[ReActChatAgent] Starting deep thinking process")
            
            # Получаем контекст для thinking
            context = ""
            try:
                docs = self.rag_service.retrieve_context(
                    case_id=self.case_id,
                    query=question,
                    k=10,
                    db=self.db
                )
                if docs:
                    context = self.rag_service.format_sources_for_prompt(docs, max_context_chars=3000)
            except Exception as e:
                logger.warning(f"[ReActChatAgent] Failed to get context for thinking: {e}")
            
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
                
        except Exception as e:
            logger.warning(f"[ReActChatAgent] Thinking error: {e}, continuing without thinking")
    
    async def _run_agent(self, question: str) -> AsyncGenerator[str, None]:
        """Запустить ReAct агента"""
        try:
            from langchain_core.messages import HumanMessage, AIMessage
            
            # Формируем входные данные
            messages = []
            
            # Добавляем историю чата (последние 10 сообщений)
            for msg in self.chat_history[-10:]:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
            
            # Добавляем текущий вопрос с контекстом
            enhanced_question = f"""Вопрос пользователя: {question}

ID дела: {self.case_id}

Проанализируй вопрос и используй подходящие инструменты для ответа.
Если вопрос об обзоре всех документов - используй summarize_all_documents.
Если конкретный вопрос - используй search_documents."""
            
            messages.append(HumanMessage(content=enhanced_question))
            
            # Запускаем агента
            input_data = {"messages": messages}
            
            # Пробуем стриминг
            try:
                response_text = ""
                tool_calls_made = []
                
                # Проверяем, поддерживает ли агент стриминг
                if hasattr(self.agent, 'astream'):
                    async for event in self.agent.astream(input_data):
                        # Обрабатываем события
                        if isinstance(event, dict):
                            # Событие от агента
                            if "messages" in event:
                                for msg in event["messages"]:
                                    if hasattr(msg, 'content') and msg.content:
                                        # Стримим контент
                                        yield SSESerializer.text_delta(msg.content)
                                        response_text += msg.content
                                    
                                    # Логируем tool calls
                                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                        for tc in msg.tool_calls:
                                            tool_name = tc.get('name', 'unknown')
                                            tool_calls_made.append(tool_name)
                                            logger.info(f"[ReActChatAgent] Tool call: {tool_name}")
                            
                            # Финальный ответ
                            elif "output" in event:
                                output = event["output"]
                                if output and output not in response_text:
                                    yield SSESerializer.text_delta(output)
                                    response_text += output
                else:
                    # Синхронный вызов с fallback
                    result = await self._invoke_agent_sync(input_data)
                    if result:
                        yield SSESerializer.text_delta(result)
                        response_text = result
                
                # Если ответ пустой, пробуем fallback
                if not response_text.strip():
                    logger.warning("[ReActChatAgent] Empty response, trying fallback")
                    fallback_response = await self._fallback_response(question)
                    yield SSESerializer.text_delta(fallback_response)
                
                logger.info(f"[ReActChatAgent] Completed. Tools used: {tool_calls_made}")
                
            except Exception as stream_error:
                logger.warning(f"[ReActChatAgent] Stream error: {stream_error}, trying sync invoke")
                result = await self._invoke_agent_sync(input_data)
                if result:
                    yield SSESerializer.text_delta(result)
                else:
                    fallback_response = await self._fallback_response(question)
                    yield SSESerializer.text_delta(fallback_response)
                    
        except Exception as e:
            logger.error(f"[ReActChatAgent] Agent error: {e}", exc_info=True)
            # Fallback на простой RAG
            fallback_response = await self._fallback_response(question)
            yield SSESerializer.text_delta(fallback_response)
    
    async def _invoke_agent_sync(self, input_data: Dict[str, Any]) -> str:
        """Синхронный вызов агента"""
        try:
            if hasattr(self.agent, 'ainvoke'):
                result = await self.agent.ainvoke(input_data)
            elif hasattr(self.agent, 'invoke'):
                import asyncio
                result = await asyncio.to_thread(self.agent.invoke, input_data)
            else:
                return ""
            
            # Извлекаем текст из результата
            if isinstance(result, dict):
                if "messages" in result:
                    messages = result["messages"]
                    if messages:
                        last_msg = messages[-1]
                        if hasattr(last_msg, 'content'):
                            return last_msg.content
                elif "output" in result:
                    return result["output"]
            elif hasattr(result, 'content'):
                return result.content
            
            return str(result) if result else ""
            
        except Exception as e:
            logger.error(f"[ReActChatAgent] Sync invoke error: {e}")
            return ""
    
    async def _fallback_response(self, question: str) -> str:
        """Fallback ответ через простой RAG"""
        try:
            logger.info("[ReActChatAgent] Using fallback RAG response")
            
            # Определяем тип вопроса
            question_lower = question.lower()
            is_overview = any(phrase in question_lower for phrase in [
                "о чём", "о чем", "обзор", "все документы", "что в деле",
                "расскажи о", "содержится", "какие документы"
            ])
            
            if is_overview:
                # Для обзорных вопросов используем summarize_all_documents напрямую
                from app.services.chat.chat_tools import summarize_all_documents, initialize_chat_tools
                initialize_chat_tools(self.db, self.rag_service, self.case_id)
                return summarize_all_documents.invoke({})
            else:
                # Для конкретных вопросов используем RAG
                docs = self.rag_service.retrieve_context(
                    case_id=self.case_id,
                    query=question,
                    k=10,
                    db=self.db
                )
                
                if not docs:
                    return "К сожалению, не удалось найти релевантную информацию в документах дела."
                
                context = self.rag_service.format_sources_for_prompt(docs)
                
                # Генерируем ответ
                from langchain_core.messages import HumanMessage, SystemMessage
                
                response = self.llm.invoke([
                    SystemMessage(content="Ты юридический ассистент. Отвечай на основе предоставленного контекста."),
                    HumanMessage(content=f"Контекст:\n{context}\n\nВопрос: {question}")
                ])
                
                return response.content if hasattr(response, 'content') else str(response)
                
        except Exception as e:
            logger.error(f"[ReActChatAgent] Fallback error: {e}")
            return f"Произошла ошибка при обработке запроса. Пожалуйста, попробуйте переформулировать вопрос."

