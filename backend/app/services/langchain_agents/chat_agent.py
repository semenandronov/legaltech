"""Chat Agent with smart tool selection for assistant chat"""
from typing import List, Optional, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import BaseTool
from app.services.llm_factory import create_legal_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.services.langchain_agents.garant_tools import search_garant, get_garant_full_text
from app.services.langchain_agents.tools import retrieve_documents_tool
from app.services.rag_service import RAGService
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
        llm = create_legal_llm()
        
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
"""
        
        try:
            agent = create_legal_agent(
                llm=llm,
                tools=self.tools,
                system_prompt=system_prompt
            )
            logger.info("[ChatAgent] Agent created successfully")
            return agent
        except Exception as e:
            logger.error(f"[ChatAgent] Failed to create agent: {e}", exc_info=True)
            raise
    
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
                    last_message = messages[-1]
                    if isinstance(last_message, AIMessage):
                        response = last_message.content
                        logger.info(f"[ChatAgent] Response generated, length: {len(response)} chars")
                        return response
                    elif hasattr(last_message, 'content'):
                        response = str(last_message.content)
                        logger.info(f"[ChatAgent] Response generated, length: {len(response)} chars")
                        return response
            
            # Fallback если формат неожиданный
            logger.warning(f"[ChatAgent] Unexpected result format: {type(result)}")
            return str(result)
            
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
            
            # Вызываем агента с streaming
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=enhanced_question)]},
                config=agent_config
            ):
                # Извлекаем текст из chunk
                if isinstance(chunk, dict):
                    messages = chunk.get("messages", [])
                    if messages:
                        # Ищем последнее AIMessage с контентом (не ToolMessage)
                        for message in reversed(messages):
                            # Проверяем, что это AIMessage (не ToolMessage или HumanMessage)
                            if isinstance(message, AIMessage):
                                content = str(message.content) if hasattr(message, 'content') else ""
                                
                                # Пропускаем пустой контент и tool calls
                                if not content or (hasattr(message, 'tool_calls') and message.tool_calls):
                                    continue
                                
                                # Если контент изменился, отправляем дельту
                                if content and content != last_content:
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
                                break  # Берем только последнее AIMessage
            
            # Если после streaming не было контента, используем fallback
            if not last_content:
                logger.warning("[ChatAgent] No content received from stream, using fallback")
                try:
                    answer = await self.answer(question, config)
                    if answer:
                        logger.info(f"[ChatAgent] Fallback answer received: {len(answer)} chars")
                        yield answer
                except Exception as fallback_error:
                    logger.error(f"[ChatAgent] Fallback also failed: {fallback_error}", exc_info=True)
                    yield "Извините, не удалось получить ответ. Попробуйте переформулировать вопрос."
                
        except Exception as e:
            logger.error(f"[ChatAgent] Error streaming answer: {e}", exc_info=True)
            # В случае ошибки пытаемся получить ответ без streaming
            try:
                logger.info("[ChatAgent] Falling back to non-streaming answer due to error")
                answer = await self.answer(question, config)
                if answer:
                    yield answer
            except Exception as fallback_error:
                logger.error(f"[ChatAgent] Fallback also failed: {fallback_error}", exc_info=True)
                yield f"Ошибка при генерации ответа: {str(e)}"

