"""
Simple ReAct Chat Agent - Классический ReAct агент с 12 инструментами

Ключевой принцип: ОДИН агент с фиксированным набором инструментов.
Агент САМ решает, какие инструменты вызвать на основе вопроса.

НЕ планирует заранее - думает и действует итеративно:
1. Получает вопрос
2. Думает: какой инструмент нужен?
3. Вызывает инструмент
4. Наблюдает результат
5. Повторяет 2-4 пока не готов ответить
6. Формирует финальный ответ

Использует langgraph.prebuilt.create_react_agent

ПАМЯТЬ:
- Агент помнит ВСЮ историю текущей сессии (не только последние 5 сообщений)
- Checkpointing через MemorySaver для сохранения состояния между вызовами
- Умное сжатие истории для больших контекстов
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging

from app.services.chat.events import SSESerializer
from app.services.chat.universal_tools import get_universal_tools
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)

# Максимальное количество сообщений в истории (для защиты от переполнения контекста)
MAX_HISTORY_MESSAGES = 50
# Максимальная длина одного сообщения в истории (символов)
MAX_MESSAGE_LENGTH = 2000
# Количество последних сообщений, которые НЕ сжимаются
RECENT_MESSAGES_FULL = 10


class SimpleReActAgent:
    """
    Простой ReAct агент с 12 универсальными инструментами.
    
    Агент НЕ планирует заранее - он думает и действует итеративно.
    Сам решает, какие инструменты вызвать и в каком порядке.
    """
    
    # Системный промпт для агента
    SYSTEM_PROMPT = """Ты - юридический AI-ассистент. Ты работаешь с документами дела.

## КРИТИЧЕСКИ ВАЖНО:

⚠️ У тебя НЕТ доступа к документам напрямую!
⚠️ Ты ОБЯЗАН использовать инструменты для получения информации!
⚠️ БЕЗ вызова инструментов ты НЕ МОЖЕШЬ знать что в документах!

## АЛГОРИТМ РАБОТЫ:

1. Получил вопрос о документах → ВЫЗОВИ search_in_documents
2. Нужен полный документ → ВЫЗОВИ get_document  
3. Нужны даты/суммы/имена → ВЫЗОВИ extract_structured_data
4. Нужно сравнить документы → ВЫЗОВИ compare_documents
5. Только ПОСЛЕ получения данных из инструментов → формируй ответ

## ДОСТУПНЫЕ ИНСТРУМЕНТЫ:

1. **search_in_documents(query, k)** - ГЛАВНЫЙ инструмент для поиска
   - Используй ВСЕГДА когда вопрос про документы
   - k=20 для обычных вопросов, k=50 для обзорных
   
2. **get_document(filename)** - получить полный текст документа

3. **extract_structured_data(entity_types)** - извлечь даты/суммы/имена
   - entity_types: "dates,amounts,persons,organizations"
   
4. **compare_documents(doc1_name, doc2_name)** - сравнить два документа

5. **generate_document(doc_type, variables)** - создать черновик
   
6. **list_templates()** - показать шаблоны

7. **validate_with_playbook(document_name)** - проверить документ

8. **get_user_playbooks()** - список правил

9. **calculate(expression)** - расчёты

10. **get_current_date()** - текущая дата

## СТРОГИЕ ПРАВИЛА:

❌ ЗАПРЕЩЕНО отвечать на вопросы о документах БЕЗ вызова инструментов
❌ ЗАПРЕЩЕНО придумывать информацию
❌ ЗАПРЕЩЕНО говорить "я не могу" - ВЫЗОВИ инструмент!

✅ ОБЯЗАТЕЛЬНО вызывать search_in_documents для любого вопроса о деле
✅ ОБЯЗАТЕЛЬНО цитировать источники [Документ]
✅ ОБЯЗАТЕЛЬНО использовать данные из инструментов

## ПРИМЕРЫ:

Вопрос: "О чём документы?"
→ ВЫЗОВИ: search_in_documents("суть дело предмет", k=50)
→ Затем ответь на основе результатов

Вопрос: "Какая сумма в договоре?"
→ ВЫЗОВИ: search_in_documents("сумма договор цена", k=20)
→ Затем ответь на основе результатов

Вопрос: "Сравни договор и акт"
→ ВЫЗОВИ: compare_documents("договор", "акт")
→ Затем ответь на основе результатов

## ПАМЯТЬ:
- Ты помнишь историю разговора
- Можешь ссылаться на предыдущие ответы

## ФОРМАТ ОТВЕТА:
- Markdown
- Структурированно
- С источниками [Документ]"""

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
        chat_history: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None
    ):
        self.case_id = case_id
        self.db = db
        self.rag_service = rag_service
        self.current_user = current_user
        self.legal_research = legal_research
        self.deep_think = deep_think
        self.web_search = web_search
        self.session_id = session_id
        
        # Обрабатываем историю чата с умным сжатием
        self.chat_history = self._process_chat_history(chat_history or [])
        
        # Создаём LLM
        self.llm = self._create_llm()
        
        # Получаем инструменты
        self.tools = get_universal_tools(
            db=db,
            rag_service=rag_service,
            case_id=case_id,
            user_id=current_user.id if current_user else None,
            legal_research=legal_research,
            web_search=web_search
        )
        
        # Создаём checkpointer для сохранения состояния
        self.checkpointer = self._create_checkpointer()
        
        # Флаг для ручного добавления системного промпта (если LangGraph не поддерживает prompt)
        self._needs_manual_system_prompt = False
        
        # Создаём агента с checkpointer
        self.agent = self._create_agent()
        
        logger.info(
            f"[SimpleReActAgent] Initialized for case {case_id} "
            f"({len(self.tools)} tools, {len(self.chat_history)} history messages, "
            f"deep_think={deep_think}, legal_research={legal_research})"
        )
    
    def _process_chat_history(
        self, 
        history: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        Умная обработка истории чата.
        
        Стратегия:
        1. Берём до MAX_HISTORY_MESSAGES сообщений
        2. Последние RECENT_MESSAGES_FULL сообщений оставляем полными
        3. Более старые сообщения сжимаем до MAX_MESSAGE_LENGTH символов
        
        Это позволяет:
        - Сохранить полный контекст недавнего разговора
        - Не потерять важную информацию из старых сообщений
        - Уместиться в контекстное окно LLM
        """
        if not history:
            return []
        
        # Ограничиваем количество сообщений
        history = history[-MAX_HISTORY_MESSAGES:]
        
        processed = []
        total_messages = len(history)
        
        for i, msg in enumerate(history):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if not content:
                continue
            
            # Последние RECENT_MESSAGES_FULL сообщений — полные
            is_recent = (total_messages - i) <= RECENT_MESSAGES_FULL
            
            if is_recent:
                # Полное сообщение
                processed.append({"role": role, "content": content})
            else:
                # Сжимаем старое сообщение
                if len(content) > MAX_MESSAGE_LENGTH:
                    compressed = content[:MAX_MESSAGE_LENGTH] + "... [сообщение сокращено]"
                    processed.append({"role": role, "content": compressed})
                else:
                    processed.append({"role": role, "content": content})
        
        logger.debug(
            f"[SimpleReActAgent] Processed history: {len(history)} -> {len(processed)} messages"
        )
        return processed
    
    def _create_checkpointer(self):
        """
        Создать checkpointer для сохранения состояния агента.
        
        Используем MemorySaver для простоты.
        В production можно заменить на PostgresSaver.
        """
        try:
            from langgraph.checkpoint.memory import MemorySaver
            
            checkpointer = MemorySaver()
            logger.debug("[SimpleReActAgent] Created MemorySaver checkpointer")
            return checkpointer
            
        except ImportError:
            logger.warning("[SimpleReActAgent] MemorySaver not available, running without checkpointing")
            return None
    
    def _create_llm(self):
        """Создать LLM для агента"""
        from app.services.llm_factory import create_legal_llm
        
        # Используем более мощную модель для deep_think
        if self.deep_think:
            try:
                return create_legal_llm(
                    model_name="GigaChat-Pro",
                    timeout=180.0
                )
            except Exception as e:
                logger.warning(f"[SimpleReActAgent] Failed to create GigaChat-Pro: {e}, using default")
        
        return create_legal_llm(timeout=180.0)
    
    def _create_agent(self):
        """
        Создать ReAct агента через LangGraph с checkpointer.
        
        Checkpointer позволяет:
        - Сохранять состояние агента между вызовами
        - Восстанавливаться после ошибок
        - Поддерживать долгие сессии
        
        ВАЖНО: Системный промпт передаётся через параметр `prompt`.
        В новых версиях LangGraph `state_modifier` был удалён.
        """
        try:
            from langgraph.prebuilt import create_react_agent
            
            # Создаём агента с системным промптом через prompt
            # В новых версиях LangGraph используется prompt вместо state_modifier
            if self.checkpointer:
                agent = create_react_agent(
                    self.llm,
                    self.tools,
                    prompt=self.SYSTEM_PROMPT,
                    checkpointer=self.checkpointer
                )
                logger.info("[SimpleReActAgent] Created agent with prompt and MemorySaver checkpointer")
            else:
                agent = create_react_agent(
                    self.llm,
                    self.tools,
                    prompt=self.SYSTEM_PROMPT
                )
                logger.info("[SimpleReActAgent] Created agent with prompt (no checkpointer)")
            
            return agent
            
        except ImportError as e:
            logger.error(f"[SimpleReActAgent] LangGraph not available: {e}")
            raise RuntimeError("LangGraph not installed. Install with: pip install langgraph")
        except TypeError as e:
            # Fallback для старых версий LangGraph без параметра prompt
            logger.warning(f"[SimpleReActAgent] prompt parameter not supported, using messages approach: {e}")
            return self._create_agent_fallback()
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Failed to create agent: {e}", exc_info=True)
            raise
    
    def _create_agent_fallback(self):
        """
        Fallback создание агента для версий LangGraph без параметра prompt.
        Системный промпт будет добавляться вручную в messages.
        """
        try:
            from langgraph.prebuilt import create_react_agent
            
            if self.checkpointer:
                agent = create_react_agent(
                    self.llm,
                    self.tools,
                    checkpointer=self.checkpointer
                )
                logger.info("[SimpleReActAgent] Created agent with fallback (no prompt param), using checkpointer")
            else:
                agent = create_react_agent(
                    self.llm,
                    self.tools
                )
                logger.info("[SimpleReActAgent] Created agent with fallback (no prompt param)")
            
            # Помечаем, что нужно добавлять системный промпт вручную
            self._needs_manual_system_prompt = True
            return agent
            
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Fallback agent creation failed: {e}", exc_info=True)
            raise
    
    async def handle(
        self,
        question: str,
        stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Обработать вопрос пользователя.
        
        Агент сам решает какие инструменты использовать.
        
        Args:
            question: Вопрос пользователя
            stream: Стримить ответ (по умолчанию True)
            
        Yields:
            SSE события
        """
        try:
            logger.info(f"[SimpleReActAgent] Processing: {question[:100]}...")
            
            # Отправляем статус начала
            yield SSESerializer.reasoning(
                phase="thinking",
                step=1,
                total_steps=1,
                content="Анализирую вопрос и выбираю инструменты..."
            )
            
            # Запускаем агента
            async for event in self._run_agent(question):
                yield event
                
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка обработки запроса: {str(e)}")
    
    async def _run_agent(self, question: str) -> AsyncGenerator[str, None]:
        """
        Запустить ReAct агента с полной историей чата.
        
        Память работает так:
        1. Системный промпт — передаётся через prompt в _create_agent (или вручную если fallback)
        2. ВСЯ история чата (обработанная) — контекст разговора
        3. Текущий вопрос — что нужно сделать
        
        thread_id = case_id + session_id — уникальный идентификатор разговора
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        try:
            messages = []
            
            # Если нужно добавить системный промпт вручную (fallback режим)
            if self._needs_manual_system_prompt:
                messages.append(SystemMessage(content=self.SYSTEM_PROMPT))
                logger.debug("[SimpleReActAgent] Added system prompt manually (fallback mode)")
            
            # Добавляем ВСЮ обработанную историю чата
            history_added = 0
            for msg in self.chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not content:
                    continue
                    
                if role == "user":
                    messages.append(HumanMessage(content=content))
                    history_added += 1
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
                    history_added += 1
            
            # Добавляем текущий вопрос
            messages.append(HumanMessage(content=question))
            
            logger.info(
                f"[SimpleReActAgent] Running with {history_added} history messages + current question"
            )
            logger.debug(
                f"[SimpleReActAgent] Question: {question[:100]}..., "
                f"Total messages: {len(messages)}, "
                f"Tools available: {len(self.tools)}"
            )
            
            # Уникальный thread_id для сессии
            # Используем case_id + session_id если есть, иначе только case_id
            thread_id = f"{self.case_id}_{self.session_id}" if self.session_id else self.case_id
            
            # Конфигурация с thread_id и recursion_limit
            config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 25  # Защита от зацикливания
            }
            
            # Собираем ответ
            final_response = ""
            tool_calls_count = 0
            all_messages = []
            event_count = 0
            
            # Используем stream для получения промежуточных результатов
            async for event in self.agent.astream(
                {"messages": messages},
                config=config,
                stream_mode="values"
            ):
                event_count += 1
                logger.debug(f"[SimpleReActAgent] Event #{event_count}: keys={list(event.keys())}")
                
                # Получаем последнее сообщение
                if "messages" in event:
                    all_messages = event["messages"]
                    last_message = all_messages[-1]
                    logger.debug(
                        f"[SimpleReActAgent] Last message type: {type(last_message).__name__}, "
                        f"has tool_calls: {hasattr(last_message, 'tool_calls') and bool(last_message.tool_calls)}, "
                        f"content length: {len(getattr(last_message, 'content', '') or '')}"
                    )
                    
                    # Если это AI message с tool_calls - показываем что агент думает
                    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                        tool_calls_count += len(last_message.tool_calls)
                        for tc in last_message.tool_calls:
                            tool_name = tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, 'name', 'unknown')
                            yield SSESerializer.reasoning(
                                phase="tool_call",
                                step=tool_calls_count,
                                total_steps=15,  # Увеличили лимит
                                content=f"Вызываю: {tool_name}..."
                            )
                    
                    # Если это финальный ответ AI (без tool_calls)
                    elif hasattr(last_message, 'content') and last_message.content:
                        # Проверяем, что это действительно финальный ответ (не промежуточный)
                        has_tool_calls = (
                            hasattr(last_message, 'tool_calls') and 
                            last_message.tool_calls and 
                            len(last_message.tool_calls) > 0
                        )
                        if not has_tool_calls:
                            final_response = last_message.content
            
            # Если есть финальный ответ - отправляем
            if final_response and len(final_response.strip()) > 10:
                yield SSESerializer.text_delta(final_response)
                logger.info(
                    f"[SimpleReActAgent] Completed with {tool_calls_count} tool calls, "
                    f"response length: {len(final_response)}, thread_id={thread_id}"
                )
            elif tool_calls_count == 0 and len(final_response.strip()) <= 10:
                # Fallback: если агент не вызвал инструменты и дал короткий ответ,
                # это может означать что GigaChat не поддерживает function calling
                # Попробуем вызвать инструмент вручную для вопроса о документах
                logger.warning(
                    f"[SimpleReActAgent] Agent returned short response ({len(final_response)} chars) "
                    f"without tool calls. Attempting manual tool call fallback."
                )
                
                # Для вопросов о документах вызываем search_in_documents вручную
                if any(keyword in question.lower() for keyword in ['документ', 'о чем', 'что в', 'расскажи']):
                    yield SSESerializer.reasoning(
                        phase="tool_call",
                        step=1,
                        total_steps=5,
                        content="Вызываю: search_in_documents..."
                    )
                    
                    # Вызываем инструмент вручную
                    search_tool = next((t for t in self.tools if t.name == "search_in_documents"), None)
                    if search_tool:
                        try:
                            # Формируем поисковый запрос из вопроса
                            search_query = question
                            if "о чем" in question.lower():
                                search_query = "суть дело предмет содержание"
                            
                            tool_result = await search_tool.ainvoke({"query": search_query, "k": 50})
                            
                            # Формируем финальный ответ на основе результатов
                            if tool_result and len(tool_result) > 50:
                                # Используем LLM для формирования ответа на основе результатов
                                from langchain_core.messages import HumanMessage
                                followup_prompt = f"""На основе найденной информации ответь на вопрос пользователя.

Вопрос: {question}

Найденная информация:
{tool_result[:5000]}

Сформируй краткий, но информативный ответ на основе найденной информации."""
                                
                                followup_response = await self.llm.ainvoke([HumanMessage(content=followup_prompt)])
                                if hasattr(followup_response, 'content') and followup_response.content:
                                    final_response = followup_response.content
                                    yield SSESerializer.text_delta(final_response)
                                    logger.info(f"[SimpleReActAgent] Fallback completed, response length: {len(final_response)}")
                                else:
                                    yield SSESerializer.text_delta(tool_result[:2000])
                            else:
                                yield SSESerializer.text_delta(
                                    "Не удалось найти информацию в документах. Попробуйте переформулировать вопрос."
                                )
                        except Exception as e:
                            logger.error(f"[SimpleReActAgent] Fallback tool call failed: {e}", exc_info=True)
                            yield SSESerializer.text_delta(
                                "К сожалению, произошла ошибка при поиске информации. Попробуйте переформулировать вопрос."
                            )
                    else:
                        yield SSESerializer.text_delta(
                            "К сожалению, не удалось получить ответ. Попробуйте переформулировать вопрос."
                        )
                else:
                    yield SSESerializer.text_delta(
                        "К сожалению, не удалось получить ответ. Попробуйте переформулировать вопрос."
                    )
                logger.warning("[SimpleReActAgent] Used fallback response")
            else:
                # Fallback - если агент не дал ответ
                yield SSESerializer.text_delta(
                    "К сожалению, не удалось получить ответ. Попробуйте переформулировать вопрос."
                )
                logger.warning(f"[SimpleReActAgent] No final response from agent, final_response length: {len(final_response)}")
                
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Agent execution error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка выполнения: {str(e)}")
    
    async def _run_agent_sync(self, question: str) -> str:
        """
        Синхронный запуск агента (для случаев когда нужен только результат).
        
        Returns:
            Ответ агента
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        try:
            messages = []
            
            # Если нужно добавить системный промпт вручную (fallback режим)
            if self._needs_manual_system_prompt:
                messages.append(SystemMessage(content=self.SYSTEM_PROMPT))
            
            # Используем ВСЮ обработанную историю
            for msg in self.chat_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not content:
                    continue
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            
            messages.append(HumanMessage(content=question))
            
            thread_id = f"{self.case_id}_{self.session_id}" if self.session_id else self.case_id
            config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 25
            }
            
            result = await self.agent.ainvoke(
                {"messages": messages},
                config=config
            )
            
            if "messages" in result:
                last_message = result["messages"][-1]
                if hasattr(last_message, 'content'):
                    return last_message.content
            
            return "Не удалось получить ответ."
            
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Sync execution error: {e}", exc_info=True)
            return f"Ошибка: {str(e)}"
    
    def get_conversation_summary(self) -> str:
        """
        Получить краткое описание текущего разговора.
        
        Полезно для отладки и понимания контекста.
        """
        if not self.chat_history:
            return "Нет истории разговора"
        
        user_msgs = sum(1 for m in self.chat_history if m.get("role") == "user")
        assistant_msgs = sum(1 for m in self.chat_history if m.get("role") == "assistant")
        
        first_msg = self.chat_history[0].get("content", "")[:50] if self.chat_history else ""
        last_msg = self.chat_history[-1].get("content", "")[:50] if self.chat_history else ""
        
        return (
            f"История: {len(self.chat_history)} сообщений "
            f"({user_msgs} от пользователя, {assistant_msgs} от ассистента). "
            f"Начало: '{first_msg}...' | Последнее: '{last_msg}...'"
        )

