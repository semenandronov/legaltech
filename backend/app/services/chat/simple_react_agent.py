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
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging

from app.services.chat.events import SSESerializer
from app.services.chat.universal_tools import get_universal_tools
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)


class SimpleReActAgent:
    """
    Простой ReAct агент с 12 универсальными инструментами.
    
    Агент НЕ планирует заранее - он думает и действует итеративно.
    Сам решает, какие инструменты вызвать и в каком порядке.
    """
    
    # Системный промпт для агента
    SYSTEM_PROMPT = """Ты - юридический AI-ассистент. Помогаешь юристам анализировать документы и отвечать на вопросы.

У тебя есть инструменты для работы. ИСПОЛЬЗУЙ ИХ для получения информации.

## ДОСТУПНЫЕ ИНСТРУМЕНТЫ:

### Работа с документами:
1. **get_document(filename)** - получить полный текст документа
   - Используй когда нужен весь документ
   
2. **search_in_documents(query, k)** - поиск по документам
   - Используй для поиска конкретной информации
   - k=10 для простых вопросов, k=30-50 для сложных
   
3. **extract_structured_data(entity_types)** - извлечь даты/суммы/имена
   - entity_types: "dates,amounts,persons,organizations"
   
4. **compare_documents(doc1_name, doc2_name)** - сравнить два документа

### Законодательство (если включено):
5. **search_garant(query)** - поиск в базе законов
   - Используй для поиска статей, законов, судебной практики
   
6. **get_law_article(article_ref)** - получить текст статьи

### Генерация документов:
7. **generate_document(doc_type, variables)** - создать черновик
   - doc_type: contract, claim, pretension, letter, memo, power_of_attorney
   - variables: "ключ=значение; ключ2=значение2"
   
8. **list_templates()** - показать доступные шаблоны

### Playbook:
9. **validate_with_playbook(document_name, playbook_name)** - проверить документ
10. **get_user_playbooks()** - список правил

### Вспомогательные:
11. **calculate(expression)** - расчёты (проценты, пени, сроки)
    - Примеры: "100000 * 0.1", "percent(100000, 10)", "penalty_cb(100000, 30)"
    
12. **get_current_date()** - текущая дата

## ПРАВИЛА:

1. **ВСЕГДА используй инструменты** для получения информации из документов
2. **НЕ ПРИДУМЫВАЙ** информацию - только то, что нашёл в документах
3. **Можешь вызвать несколько инструментов** для полного ответа
4. **Цитируй источники** в формате [Документ]
5. Для обзорных вопросов используй search_in_documents с k=50
6. Для сравнения - сначала найди документы, потом compare_documents
7. Для законов - используй search_garant

## ФОРМАТ ОТВЕТА:
- Используй Markdown
- Структурируй ответ с заголовками
- Указывай источники
- Будь точен и профессионален"""

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
        self.case_id = case_id
        self.db = db
        self.rag_service = rag_service
        self.current_user = current_user
        self.legal_research = legal_research
        self.deep_think = deep_think
        self.web_search = web_search
        self.chat_history = chat_history or []
        
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
        
        # Создаём агента
        self.agent = self._create_agent()
        
        logger.info(
            f"[SimpleReActAgent] Initialized for case {case_id} "
            f"({len(self.tools)} tools, deep_think={deep_think}, legal_research={legal_research})"
        )
    
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
        """Создать ReAct агента через LangGraph"""
        try:
            from langgraph.prebuilt import create_react_agent
            
            agent = create_react_agent(
                self.llm,
                self.tools
            )
            
            logger.info("[SimpleReActAgent] Created agent via langgraph.prebuilt.create_react_agent")
            return agent
            
        except ImportError as e:
            logger.error(f"[SimpleReActAgent] LangGraph not available: {e}")
            raise RuntimeError("LangGraph not installed. Install with: pip install langgraph")
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Failed to create agent: {e}", exc_info=True)
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
        """Запустить ReAct агента"""
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        
        try:
            # Формируем сообщения
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT)
            ]
            
            # Добавляем историю чата (последние 5 сообщений)
            for msg in self.chat_history[-5:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            
            # Добавляем текущий вопрос
            messages.append(HumanMessage(content=question))
            
            # Запускаем агента
            config = {"configurable": {"thread_id": self.case_id}}
            
            # Собираем ответ
            final_response = ""
            tool_calls_count = 0
            
            # Используем stream для получения промежуточных результатов
            async for event in self.agent.astream(
                {"messages": messages},
                config=config,
                stream_mode="values"
            ):
                # Получаем последнее сообщение
                if "messages" in event:
                    last_message = event["messages"][-1]
                    
                    # Если это AI message с tool_calls - показываем что агент думает
                    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                        tool_calls_count += len(last_message.tool_calls)
                        for tc in last_message.tool_calls:
                            tool_name = tc.get("name", "unknown")
                            yield SSESerializer.reasoning(
                                phase="tool_call",
                                step=tool_calls_count,
                                total_steps=10,  # Примерно
                                content=f"Вызываю: {tool_name}..."
                            )
                    
                    # Если это финальный ответ AI (без tool_calls)
                    elif hasattr(last_message, 'content') and last_message.content:
                        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
                            final_response = last_message.content
            
            # Если есть финальный ответ - отправляем
            if final_response:
                yield SSESerializer.text_delta(final_response)
                logger.info(f"[SimpleReActAgent] Completed with {tool_calls_count} tool calls")
            else:
                # Fallback - если агент не дал ответ
                yield SSESerializer.text_delta(
                    "К сожалению, не удалось получить ответ. Попробуйте переформулировать вопрос."
                )
                logger.warning("[SimpleReActAgent] No final response from agent")
                
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Agent execution error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка выполнения: {str(e)}")
    
    async def _run_agent_sync(self, question: str) -> str:
        """
        Синхронный запуск агента (для случаев когда нужен только результат).
        
        Returns:
            Ответ агента
        """
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        
        try:
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT)
            ]
            
            for msg in self.chat_history[-5:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            
            messages.append(HumanMessage(content=question))
            
            config = {"configurable": {"thread_id": self.case_id}}
            
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

