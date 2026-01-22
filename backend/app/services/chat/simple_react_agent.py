"""
Simple ReAct Agent v5.0 - Полностью переписанный агент без LangGraph.

Проблема с LangGraph + GigaChat: GigaChat игнорирует результаты инструментов.
Решение: Ручной ReAct цикл с явным контролем результатов.

Архитектура:
1. LLM получает вопрос + описание инструментов
2. LLM решает какой инструмент вызвать (или отвечает напрямую)
3. Мы вызываем инструмент и получаем результат
4. LLM формирует финальный ответ НА ОСНОВЕ результата инструмента

Это гарантирует, что ответ будет основан на реальных данных из документов.
"""

import logging
import json
import re
from typing import List, Dict, Any, Optional, AsyncGenerator
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import BaseTool

from app.models.user import User
from app.services.rag_service import RAGService
from app.services.chat.events import SSESerializer

logger = logging.getLogger(__name__)


class SimpleReActAgent:
    """
    Простой ReAct агент с ручным контролем цикла.
    
    Гарантирует использование реальных данных из инструментов.
    """
    
    # Системный промпт для выбора инструмента
    TOOL_SELECTION_PROMPT = """Ты - юридический AI-ассистент. Работаешь с документами дела.

ДОСТУПНЫЕ ИНСТРУМЕНТЫ:
{tools_description}

ТВОЯ ЗАДАЧА: Выбрать ОДИН инструмент для ответа на вопрос пользователя.

ФОРМАТ ОТВЕТА (строго JSON):
{{"tool": "название_инструмента", "args": {{"arg1": "value1"}}}}

ПРИМЕРЫ:
- Вопрос "О чём документ?" → {{"tool": "search_in_documents", "args": {{"query": "суть содержание предмет", "k": 30}}}}
- Вопрос "Какая сумма?" → {{"tool": "search_in_documents", "args": {{"query": "сумма цена стоимость", "k": 30}}}}
- Вопрос "Покажи договор.pdf" → {{"tool": "get_document", "args": {{"filename": "договор.pdf"}}}}
- Вопрос "Сколько будет 100*5?" → {{"tool": "calculate", "args": {{"expression": "100*5"}}}}

ВАЖНО:
- Отвечай ТОЛЬКО JSON, без пояснений
- Используй search_in_documents для большинства вопросов о содержании
- Используй get_document только если нужен полный текст конкретного файла"""

    # Промпт для формирования финального ответа
    ANSWER_PROMPT = """Ты - юридический AI-ассистент. На основе полученных данных ответь на вопрос пользователя.

ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

ДАННЫЕ ИЗ ДОКУМЕНТОВ:
{tool_result}

ИНСТРУКЦИИ:
1. Используй ТОЛЬКО данные выше - не придумывай ничего
2. Отвечай кратко и по существу
3. Указывай источники в квадратных скобках: [Название документа]
4. Если данных недостаточно - так и скажи

ФОРМАТ ОТВЕТА:
- Пиши как профессиональный юрист
- Не пиши "На основе данных...", "Согласно информации..." - сразу к сути
- Используй конкретные факты: даты, суммы, имена из документов"""

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
        
        # Инициализируем инструменты
        self.tools = self._create_tools()
        self.tools_map = {t.name: t for t in self.tools}
        
        logger.info(
            f"[SimpleReActAgent] Initialized for case {case_id} "
            f"({len(self.tools)} tools, {len(self.chat_history)} history messages)"
        )
    
    def _process_history(self, history: List[Dict]) -> List[Dict]:
        """Обработка истории чата - оставляем последние сообщения."""
        if not history:
            return []
        
        # Берём последние 10 сообщений
        recent = history[-10:]
        
        # Обрезаем слишком длинные сообщения
        processed = []
        for msg in recent:
            content = msg.get("content", "")
            if len(content) > 2000:
                content = content[:2000] + "..."
            processed.append({
                "role": msg.get("role", "user"),
                "content": content
            })
        
        return processed
    
    def _create_llm(self):
        """Создать LLM."""
        from app.services.llm_factory import create_legal_llm
        return create_legal_llm(timeout=180.0)
    
    def _create_tools(self) -> List[BaseTool]:
        """Создать инструменты."""
        from app.services.chat.universal_tools import (
            get_universal_tools,
            initialize_universal_tools
        )
        
        initialize_universal_tools(
            db=self.db,
            rag_service=self.rag_service,
            case_id=self.case_id,
            user_id=self.user_id
        )
        
        return get_universal_tools(
            db=self.db,
            rag_service=self.rag_service,
            case_id=self.case_id,
            user_id=self.user_id,
            legal_research=self.legal_research,
            web_search=self.web_search
        )
    
    def _get_tools_description(self) -> str:
        """Получить описание инструментов для промпта."""
        descriptions = []
        for tool in self.tools:
            # Получаем описание и аргументы
            desc = tool.description or "Нет описания"
            # Берём только первые 200 символов описания
            short_desc = desc[:200] + "..." if len(desc) > 200 else desc
            
            # Получаем схему аргументов
            args_schema = ""
            if hasattr(tool, 'args_schema') and tool.args_schema:
                schema = tool.args_schema.schema() if hasattr(tool.args_schema, 'schema') else {}
                props = schema.get('properties', {})
                args_list = [f"{k}: {v.get('type', 'any')}" for k, v in props.items()]
                args_schema = f"({', '.join(args_list)})" if args_list else "()"
            
            descriptions.append(f"- {tool.name}{args_schema}: {short_desc}")
        
        return "\n".join(descriptions)
    
    async def handle(
        self,
        question: str,
        stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Обработать вопрос пользователя.
        
        Yields:
            SSE события
        """
        try:
            logger.info(f"[SimpleReActAgent] Processing: {question[:100]}...")
            
            yield SSESerializer.reasoning(
                phase="thinking",
                step=1,
                total_steps=3,
                content="Анализирую вопрос..."
            )
            
            # Шаг 1: Выбираем инструмент
            tool_choice = await self._select_tool(question)
            
            if tool_choice is None:
                # LLM решил ответить напрямую без инструмента
                yield SSESerializer.reasoning(
                    phase="answering",
                    step=2,
                    total_steps=3,
                    content="Формирую ответ..."
                )
                
                response = await self._direct_answer(question)
                yield SSESerializer.text_delta(response)
                return
            
            tool_name = tool_choice.get("tool")
            tool_args = tool_choice.get("args", {})
            
            logger.info(f"[SimpleReActAgent] Selected tool: {tool_name}, args: {tool_args}")
            
            yield SSESerializer.reasoning(
                phase="tool_call",
                step=2,
                total_steps=3,
                content=f"Использую инструмент: {tool_name}..."
            )
            
            # Шаг 2: Вызываем инструмент
            tool_result = await self._call_tool(tool_name, tool_args)
            
            if not tool_result or len(str(tool_result)) < 20:
                # Инструмент не вернул данных
                yield SSESerializer.text_delta(
                    "К сожалению, не удалось найти информацию по вашему запросу. "
                    "Попробуйте переформулировать вопрос или загрузить документы."
                )
                return
            
            logger.info(f"[SimpleReActAgent] Tool result length: {len(str(tool_result))}")
            
            yield SSESerializer.reasoning(
                phase="answering",
                step=3,
                total_steps=3,
                content="Формирую ответ на основе найденных данных..."
            )
            
            # Шаг 3: Формируем ответ на основе результата
            final_response = await self._generate_answer(question, tool_result)
            
            yield SSESerializer.text_delta(final_response)
            
            logger.info(
                f"[SimpleReActAgent] Completed. Tool: {tool_name}, "
                f"Result length: {len(str(tool_result))}, "
                f"Response length: {len(final_response)}"
            )
            
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка обработки запроса: {str(e)}")
    
    async def _select_tool(self, question: str) -> Optional[Dict]:
        """
        Выбрать инструмент для ответа на вопрос.
        
        Returns:
            {"tool": "name", "args": {...}} или None если ответ напрямую
        """
        tools_desc = self._get_tools_description()
        
        prompt = self.TOOL_SELECTION_PROMPT.format(tools_description=tools_desc)
        
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Вопрос пользователя: {question}")
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            logger.debug(f"[SimpleReActAgent] Tool selection response: {content[:200]}")
            
            # Парсим JSON из ответа
            tool_choice = self._parse_tool_choice(content)
            
            if tool_choice and tool_choice.get("tool") in self.tools_map:
                return tool_choice
            
            # Если не удалось распарсить - используем search_in_documents по умолчанию
            logger.warning(
                f"[SimpleReActAgent] Could not parse tool choice, using default. "
                f"Response: {content[:100]}"
            )
            return {
                "tool": "search_in_documents",
                "args": {"query": question, "k": 30}
            }
            
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Tool selection error: {e}")
            # Fallback на search_in_documents
            return {
                "tool": "search_in_documents",
                "args": {"query": question, "k": 30}
            }
    
    def _parse_tool_choice(self, content: str) -> Optional[Dict]:
        """Извлечь JSON с выбором инструмента из ответа LLM."""
        # Пробуем найти JSON в ответе
        json_patterns = [
            r'\{[^{}]*"tool"[^{}]*\}',  # Простой JSON
            r'```json\s*(\{.*?\})\s*```',  # JSON в блоке кода
            r'```\s*(\{.*?\})\s*```',  # JSON в блоке кода без указания языка
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if match.lastindex else match.group(0)
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
        
        # Пробуем распарсить весь контент как JSON
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass
        
        return None
    
    async def _call_tool(self, tool_name: str, tool_args: Dict) -> str:
        """Вызвать инструмент и получить результат."""
        tool = self.tools_map.get(tool_name)
        
        if not tool:
            logger.error(f"[SimpleReActAgent] Tool not found: {tool_name}")
            return ""
        
        try:
            # Вызываем инструмент
            result = await tool.ainvoke(tool_args)
            return str(result) if result else ""
            
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Tool call error: {e}", exc_info=True)
            return f"Ошибка вызова инструмента: {str(e)}"
    
    async def _generate_answer(self, question: str, tool_result: str) -> str:
        """
        Сгенерировать финальный ответ на основе результата инструмента.
        
        Это ключевой метод - он гарантирует, что LLM использует реальные данные.
        """
        # Обрезаем результат если слишком длинный
        max_result_length = 8000
        if len(tool_result) > max_result_length:
            tool_result = tool_result[:max_result_length] + "\n\n[... результат обрезан ...]"
        
        prompt = self.ANSWER_PROMPT.format(
            question=question,
            tool_result=tool_result
        )
        
        messages = [
            SystemMessage(content=prompt)
        ]
        
        # Добавляем историю чата для контекста
        for msg in self.chat_history[-4:]:  # Последние 4 сообщения
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                if role == "user":
                    messages.append(HumanMessage(content=content))
                else:
                    messages.append(AIMessage(content=content))
        
        # Добавляем текущий вопрос
        messages.append(HumanMessage(content=f"Сформируй ответ на вопрос: {question}"))
        
        try:
            response = await self.llm.ainvoke(messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Проверяем что ответ не пустой и не слишком короткий
            if not content or len(content.strip()) < 20:
                logger.warning(f"[SimpleReActAgent] Empty or short answer: {content}")
                # Возвращаем результат инструмента напрямую
                return f"Найденная информация:\n\n{tool_result[:3000]}"
            
            return content
            
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Answer generation error: {e}")
            # Возвращаем результат инструмента напрямую
            return f"Найденная информация:\n\n{tool_result[:3000]}"
    
    async def _direct_answer(self, question: str) -> str:
        """Ответить напрямую без инструмента (для простых вопросов)."""
        messages = [
            SystemMessage(content="Ты - юридический AI-ассистент. Отвечай кратко и по существу."),
            HumanMessage(content=question)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"[SimpleReActAgent] Direct answer error: {e}")
            return "Извините, произошла ошибка при обработке вашего запроса."
    
    # === Синхронные методы для совместимости ===
    
    def handle_sync(self, question: str) -> str:
        """Синхронная обработка вопроса."""
        import asyncio
        
        async def collect_response():
            response_parts = []
            async for event in self.handle(question, stream=False):
                # Извлекаем текст из SSE события
                if '"type":"text_delta"' in event or '"type":"answer"' in event:
                    try:
                        # Парсим SSE событие
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
                # Если уже в async контексте
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, collect_response())
                    return future.result()
            else:
                return loop.run_until_complete(collect_response())
        except RuntimeError:
            return asyncio.run(collect_response())
