"""Chat Agent with smart tool selection for assistant chat"""
from typing import List, Optional, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from app.services.llm_factory import create_legal_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.services.langchain_agents.garant_tools import search_garant, get_garant_full_text
from app.services.langchain_agents.tools import retrieve_documents_tool, initialize_tools
from app.services.rag_service import RAGService
from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class ChatAgent:
    """
    Умный Chat Agent с автоматическим выбором источников.
    
    LLM сам определяет какие инструменты вызвать на основе вопроса:
    - search_garant - для поиска в ГАРАНТ (статьи, законы, судебные решения)
    - retrieve_documents_tool - для поиска в документах дела пользователя
    - get_garant_full_text - для получения полного текста из ГАРАНТ
    """
    
    def __init__(
        self,
        case_id: str,
        rag_service: RAGService,
        db: Session,
        legal_research_enabled: bool = True
    ):
        """
        Инициализировать Chat Agent
        
        Args:
            case_id: ID дела
            rag_service: RAG service для поиска в документах дела
            db: Database session
            legal_research_enabled: Включен ли поиск в ГАРАНТ
        """
        self.case_id = case_id
        self.rag_service = rag_service
        self.db = db
        self.legal_research_enabled = legal_research_enabled
        # Инициализируем инструменты для доступа к RAG в чате
        try:
            initialize_tools(self.rag_service, self.rag_service.document_processor)
            logger.info("[ChatAgent] Tools initialized with RAG service")
        except Exception as e:
            logger.warning(f"[ChatAgent] Failed to initialize tools: {e}")
        self.tools = self._create_tools()
        self.agent = self._create_agent()
    
    def _create_tools(self) -> List[BaseTool]:
        """Создать инструменты с привязкой к case_id"""
        tools = []
        
        # Всегда добавляем инструмент для поиска в документах дела
        # retrieve_documents_tool принимает case_id как параметр
        # Агент должен передать case_id при вызове инструмента
        tools.append(retrieve_documents_tool)
        
        # Добавляем инструменты ГАРАНТ только если включен legal_research
        if self.legal_research_enabled:
            tools.append(search_garant)
            tools.append(get_garant_full_text)
            logger.info(f"[ChatAgent] Initialized with {len(tools)} tools (including ГАРАНТ) for case {self.case_id}")
        else:
            logger.info(f"[ChatAgent] Initialized with {len(tools)} tools (ГАРАНТ disabled) for case {self.case_id}")
        
        return tools
    
    def _create_agent(self):
        """Создать агента с инструментами"""
        self.llm = create_legal_llm()  # Сохраняем LLM для fallback
        
        system_prompt = """Ты - юридический AI-ассистент, который помогает анализировать документы дела и отвечать на вопросы о праве.

ПРАВИЛА ВЫБОРА ИНСТРУМЕНТОВ:

1. search_garant - используй когда:
   - Вопрос про статью кодекса (ГК, ГПК, АПК, УК)
   - Вопрос про закон или нормативный акт
   - Нужна судебная практика или решения судов
   - Нужен комментарий к норме права
   - Пользователь просит найти что-то в законодательстве

2. retrieve_documents_tool - используй когда:
   - Вопрос про документы пользователя ("мой договор", "в иске", "что в документе")
   - Нужны факты из конкретного дела пользователя
   - Пользователь просит проанализировать загруженные документы
   - Нужна информация из файлов пользователя
   
   ВАЖНО: При вызове retrieve_documents_tool ВСЕГДА передавай case_id из контекста запроса!

3. get_garant_full_text - используй когда:
   - Нужен полный текст статьи/документа из ГАРАНТ
   - После search_garant для получения деталей
   - Пользователь явно просит "полный текст" или "весь текст"

ВАЖНО: 
- Выбирай инструменты на основе вопроса. Можешь вызвать несколько инструментов.
- Если вопрос смешанный (про документы дела И нормы права) - используй оба источника.
- Всегда используй правильный инструмент для правильного типа вопроса.
- При вызове retrieve_documents_tool обязательно передай case_id из контекста!

ФОРМАТИРОВАНИЕ ОТВЕТА:
- Используй Markdown форматирование
- При цитировании документов дела используй формат [1], [2], [3]
- При цитировании из ГАРАНТ указывай источник: [Название документа](URL)
- Будь точным и профессиональным
- НЕ возвращай JSON/структурированные поля, если пользователь явно не попросил формат JSON
"""
        
        try:
            agent = create_legal_agent(
                llm=self.llm,
                tools=self.tools,
                system_prompt=system_prompt
            )
            logger.info("[ChatAgent] Agent created successfully")
            return agent
        except Exception as e:
            logger.error(f"[ChatAgent] Failed to create agent: {e}", exc_info=True)
            raise

    @staticmethod
    def user_requested_json(question: str) -> bool:
        q = (question or "").lower()
        triggers = [
            "json",
            "в формате json",
            "в виде json",
            "структурирован",
            "структура",
        ]
        return any(t in q for t in triggers)

    def rewrite_json_response(self, json_text: str, question: str) -> str:
        """
        Преобразовать JSON-ответ в обычный текст, если JSON не запрошен.
        """
        try:
            if not json_text:
                return ""
            parsed = extract_json_from_response(json_text)
            if parsed is None:
                return ""
            system_message = SystemMessage(content=(
                "Ты - юридический AI-ассистент. Преобразуй структурированный JSON в обычный "
                "человеческий ответ без JSON. Используй краткие пункты и вывод. "
                "Не выдумывай факты, опирайся только на переданный JSON."
            ))
            human_message = HumanMessage(content=(
                f"Вопрос пользователя: {question}\n\n"
                f"JSON:\n{json_text}\n\n"
                "Ответ обычным текстом:"
            ))
            response = self.llm.invoke([system_message, human_message])
            if isinstance(response, AIMessage):
                content = getattr(response, 'content', None)
                return str(content) if content is not None else ""
            elif hasattr(response, 'content'):
                content = getattr(response, 'content', None)
                return str(content) if content is not None else ""
            return str(response) if response else ""
        except Exception as e:
            logger.warning(f"[ChatAgent] Failed to rewrite JSON response: {e}")
            return ""
    
    async def _direct_llm_fallback(self, question: str) -> str:
        """
        Прямой вызов LLM без агента и инструментов (последний fallback)
        
        Args:
            question: Вопрос пользователя (оригинальный, без внутреннего контекста)
            
        Returns:
            Ответ LLM
        """
        logger.info("[ChatAgent] Using direct LLM fallback without tools")
        
        # Убираем внутренний контекст если он случайно попал
        clean_question = question.split("[Контекст:")[0].strip() if "[Контекст:" in question else question
        
        try:
            # Простой системный промпт без инструкций по инструментам
            system_message = SystemMessage(content="""Ты - юридический AI-ассистент. 
Отвечай на вопросы пользователя кратко и по существу.
Если вопрос касается конкретных документов дела, укажи что для получения точного ответа нужно проанализировать загруженные документы.
Используй Markdown для форматирования.
НЕ возвращай JSON/структурированные поля, если пользователь явно не попросил формат JSON.""")
            
            human_message = HumanMessage(content=clean_question)
            
            # Вызываем LLM напрямую
            response = self.llm.invoke([system_message, human_message])
            
            # Извлекаем контент
            if isinstance(response, AIMessage):
                content = getattr(response, 'content', None)
                return str(content) if content is not None else ""
            elif hasattr(response, 'content'):
                content = getattr(response, 'content', None)
                return str(content) if content is not None else ""
            else:
                return str(response) if response else ""
                
        except Exception as e:
            logger.error(f"[ChatAgent] Direct LLM fallback failed: {e}", exc_info=True)
            return ""

    async def _direct_llm_with_rag_fallback(self, question: str) -> str:
        """
        Прямой вызов LLM с RAG контекстом (fallback при сбоях агента/инструментов)
        """
        logger.info("[ChatAgent] Using direct LLM + RAG fallback")
        clean_question = question.split("[Контекст:")[0].strip() if "[Контекст:" in question else question
        system_prompt = (
            "Ты - юридический AI-ассистент. Отвечай только по данным из документов дела. "
            "Если информации недостаточно, прямо скажи об этом. "
            "НЕ возвращай JSON/структурированные поля, если пользователь явно не попросил формат JSON."
        )
        try:
            return direct_llm_call_with_rag(
                case_id=self.case_id,
                system_prompt=system_prompt,
                user_query=clean_question,
                rag_service=self.rag_service,
                db=self.db,
                k=10
            )
        except Exception as e:
            logger.error(f"[ChatAgent] Direct LLM + RAG fallback failed: {e}", exc_info=True)
            return ""
    
    async def answer(self, question: str, config: Optional[Dict[str, Any]] = None) -> str:
        """
        Получить ответ на вопрос
        
        Args:
            question: Вопрос пользователя
            config: Опциональная конфигурация для агента
        
        Returns:
            Ответ агента
        """
        try:
            logger.info(f"[ChatAgent] Processing question: {question[:100]}...")
            
            # Создаем конфигурацию для агента
            agent_config = config or {}
            agent_config.setdefault("recursion_limit", 15)
            
            # Формируем вопрос с информацией о case_id для агента
            # Агент должен передать case_id при вызове retrieve_documents_tool
            enhanced_question = f"{question}\n\n[Контекст: case_id={self.case_id} - используй этот case_id при вызове retrieve_documents_tool]"
            
            # Вызываем агента
            result = safe_agent_invoke(
                agent=self.agent,
                llm=create_legal_llm(),
                input_data={
                    "messages": [HumanMessage(content=enhanced_question)]
                },
                config=agent_config
            )
            
            # Извлекаем ответ из результата
            if isinstance(result, dict):
                messages = result.get("messages", [])
                if messages:
                    # Логируем типы всех сообщений для диагностики
                    msg_types = [type(m).__name__ for m in messages]
                    logger.debug(f"[ChatAgent] Messages in result: {msg_types}")
                    
                    # Ищем последнее AIMessage с непустым контентом
                    # ВАЖНО: НЕ возвращаем HumanMessage - это сообщение пользователя!
                    for last_message in reversed(messages):
                        if isinstance(last_message, AIMessage):
                            # Правильная обработка None content
                            raw_content = getattr(last_message, 'content', None)
                            response = str(raw_content) if raw_content is not None else ""
                            
                            # Фильтруем внутренний контекст если он попал в ответ
                            if "[Контекст: case_id=" in response:
                                logger.warning("[ChatAgent] Response contains internal context, filtering it out")
                                response = response.split("[Контекст:")[0].strip()
                            
                            if response:
                                logger.info(f"[ChatAgent] Response generated from AIMessage, length: {len(response)} chars")
                                return response
                            else:
                                # Если есть tool_calls но нет контента, продолжаем искать
                                if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                                    logger.debug("[ChatAgent] Found AIMessage with tool_calls but no content, continuing search")
                                    continue
                        # НЕ обрабатываем другие типы сообщений (HumanMessage, ToolMessage) как ответы!
                        # Это была критическая ошибка - мы возвращали HumanMessage с контекстом
                    
                    # Если не нашли контент в AIMessage, пробуем RAG fallback
                    logger.warning(f"[ChatAgent] No AIMessage with content found in {len(messages)} messages (types: {msg_types})")
                    rag_fallback = await self._direct_llm_with_rag_fallback(question)
                    if rag_fallback:
                        logger.info(f"[ChatAgent] RAG fallback answer received: {len(rag_fallback)} chars")
                        return rag_fallback
            
            # Fallback если формат неожиданный или нет контента
            logger.warning(f"[ChatAgent] No valid response, trying RAG fallback")
            rag_fallback = await self._direct_llm_with_rag_fallback(question)
            if rag_fallback:
                logger.info(f"[ChatAgent] RAG fallback answer received: {len(rag_fallback)} chars")
                return rag_fallback
            return ""
            
        except Exception as e:
            logger.error(f"[ChatAgent] Error answering question: {e}", exc_info=True)
            raise
    
    async def answer_stream(self, question: str, config: Optional[Dict[str, Any]] = None):
        """
        Получить ответ в виде потока (streaming)
        
        Args:
            question: Вопрос пользователя
            config: Опциональная конфигурация для агента
        
        Yields:
            Части ответа
        """
        try:
            logger.info(f"[ChatAgent] Streaming answer for question: {question[:100]}...")
            
            agent_config = config or {}
            agent_config.setdefault("recursion_limit", 15)
            
            # Формируем вопрос с информацией о case_id для агента
            enhanced_question = f"{question}\n\n[Контекст: case_id={self.case_id} - используй этот case_id при вызове retrieve_documents_tool]"
            
            last_content = ""  # Отслеживаем последний контент для извлечения дельт
            seen_contents = set()  # Отслеживаем уже отправленные контенты
            total_chunks = 0
            ai_messages_count = 0
            tool_calls_count = 0
            
            # Вызываем агента с streaming
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=enhanced_question)]},
                config=agent_config
            ):
                total_chunks += 1
                # Детальное логирование chunk для диагностики
                logger.debug(f"[ChatAgent] Chunk #{total_chunks}: type={type(chunk).__name__}, keys={chunk.keys() if isinstance(chunk, dict) else 'N/A'}")
                
                # Извлекаем текст из chunk
                # LangGraph возвращает chunks в формате {"node_name": {"messages": [...]}}
                if isinstance(chunk, dict):
                    # Пробуем разные форматы ответа
                    messages = []
                    
                    # Формат 1: {"messages": [...]} (прямой)
                    if "messages" in chunk:
                        messages = chunk.get("messages", [])
                    else:
                        # Формат 2: {"node_name": {"messages": [...]}} (langgraph)
                        for node_name, node_data in chunk.items():
                            if isinstance(node_data, dict) and "messages" in node_data:
                                messages = node_data.get("messages", [])
                                logger.debug(f"[ChatAgent] Found messages in node '{node_name}'")
                                break
                    
                    # Логируем типы сообщений для диагностики
                    msg_types = [type(m).__name__ for m in messages]
                    logger.debug(f"[ChatAgent] Chunk #{total_chunks}: {len(messages)} messages, types: {msg_types}")
                    
                    if messages:
                        # Обрабатываем все типы сообщений для диагностики
                        from langchain_core.messages import ToolMessage
                        
                        for message in messages:
                            # Логируем ToolMessage для диагностики
                            if isinstance(message, ToolMessage):
                                tool_result = getattr(message, 'content', '')
                                logger.debug(f"[ChatAgent] ToolMessage received: {tool_result[:100] if tool_result else '(empty)'}...")
                                continue
                            
                            # Ищем AIMessage с контентом
                            if isinstance(message, AIMessage):
                                ai_messages_count += 1
                                
                                # Правильная обработка None content
                                raw_content = getattr(message, 'content', None)
                                content = str(raw_content) if raw_content is not None else ""
                                
                                # Проверяем наличие tool calls
                                has_tool_calls = hasattr(message, 'tool_calls') and message.tool_calls
                                if has_tool_calls:
                                    tool_calls_count += 1
                                    tool_names = [tc.get('name', 'unknown') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown') for tc in message.tool_calls]
                                    logger.info(f"[ChatAgent] AIMessage with tool_calls: {tool_names}, content: '{content[:50] if content else '(empty)'}...'")
                                    # НЕ пропускаем - это нормально, tool будет вызван, потом придёт финальный ответ
                                
                                # Если есть контент (даже если есть tool_calls), отправляем его
                                if content and content != last_content:
                                    # Фильтруем внутренний контекст если он попал
                                    if "[Контекст: case_id=" in content:
                                        logger.warning("[ChatAgent] Response contains internal context, filtering it out")
                                        content = content.split("[Контекст:")[0].strip()
                                    
                                    # Извлекаем только новую часть (дельту)
                                    if last_content and content.startswith(last_content):
                                        delta = content[len(last_content):]
                                        if delta and delta not in seen_contents:
                                            logger.debug(f"[ChatAgent] Yielding delta: {len(delta)} chars")
                                            seen_contents.add(delta)
                                            yield delta
                                    else:
                                        # Первый chunk или полная замена - отправляем весь контент
                                        if content and content not in seen_contents:
                                            logger.debug(f"[ChatAgent] Yielding full content: {len(content)} chars")
                                            seen_contents.add(content)
                                            yield content
                                    
                                    last_content = content
            
            logger.info(f"[ChatAgent] Streaming complete: {total_chunks} chunks, {ai_messages_count} AIMessages, {tool_calls_count} tool_calls, final content: {len(last_content)} chars")
            
            # Если после streaming не было контента, используем fallback
            if not last_content:
                logger.warning(
                    f"[ChatAgent] No content received from stream (chunks={total_chunks}, "
                    f"ai_msgs={ai_messages_count}, tool_calls={tool_calls_count}), using fallback"
                )
                try:
                    # Сначала пробуем обычный fallback через агента
                    answer = await self.answer(question, config)
                    if answer:
                        logger.info(f"[ChatAgent] Agent fallback answer received: {len(answer)} chars")
                        yield answer
                    else:
                        # Если агент тоже вернул пустой ответ, используем RAG fallback
                        logger.warning("[ChatAgent] Agent fallback returned empty, trying direct RAG")
                        rag_answer = await self._direct_llm_with_rag_fallback(question)
                        if rag_answer:
                            logger.info(f"[ChatAgent] Direct RAG fallback answer: {len(rag_answer)} chars")
                            yield rag_answer
                        else:
                            # Последний шанс - прямой вызов LLM без инструментов
                            logger.warning("[ChatAgent] Direct RAG fallback empty, trying direct LLM")
                            direct_answer = await self._direct_llm_fallback(question)
                            if direct_answer:
                                logger.info(f"[ChatAgent] Direct LLM fallback answer: {len(direct_answer)} chars")
                                yield direct_answer
                            else:
                                yield "Извините, не удалось получить ответ. Попробуйте переформулировать вопрос."
                except Exception as fallback_error:
                    logger.error(f"[ChatAgent] Agent fallback failed: {fallback_error}, trying direct RAG", exc_info=True)
                    try:
                        rag_answer = await self._direct_llm_with_rag_fallback(question)
                        if rag_answer:
                            logger.info(f"[ChatAgent] Direct RAG fallback after error: {len(rag_answer)} chars")
                            yield rag_answer
                        else:
                            direct_answer = await self._direct_llm_fallback(question)
                            if direct_answer:
                                logger.info(f"[ChatAgent] Direct LLM fallback after error: {len(direct_answer)} chars")
                                yield direct_answer
                            else:
                                yield "Извините, не удалось получить ответ. Попробуйте переформулировать вопрос."
                    except Exception as direct_error:
                        logger.error(f"[ChatAgent] Direct LLM fallback also failed: {direct_error}", exc_info=True)
                        yield "Извините, не удалось получить ответ. Попробуйте переформулировать вопрос."
                
        except Exception as e:
            logger.error(f"[ChatAgent] Error streaming answer: {e}", exc_info=True)
            # В случае ошибки пытаемся получить ответ без streaming
            try:
                logger.info("[ChatAgent] Falling back to non-streaming answer due to error")
                answer = await self.answer(question, config)
                if answer:
                    yield answer
                else:
                    # Прямой вызов LLM как последний resort
                    direct_answer = await self._direct_llm_fallback(question)
                    if direct_answer:
                        yield direct_answer
                    else:
                        yield f"Ошибка при генерации ответа: {str(e)}"
            except Exception as fallback_error:
                logger.error(f"[ChatAgent] All fallbacks failed: {fallback_error}", exc_info=True)
                # Последняя попытка - прямой вызов LLM
                try:
                    direct_answer = await self._direct_llm_fallback(question)
                    if direct_answer:
                        yield direct_answer
                    else:
                        yield f"Ошибка при генерации ответа: {str(e)}"
                except Exception:
                    yield f"Ошибка при генерации ответа: {str(e)}"

