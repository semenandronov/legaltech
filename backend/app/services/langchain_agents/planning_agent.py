"""Planning agent for natural language task understanding and analysis planning"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.services.langchain_agents.planning_tools import get_planning_tools, AVAILABLE_ANALYSES
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.config import config
from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session
import json
import re
import logging

logger = logging.getLogger(__name__)


class PlanningAgent:
    """Agent that converts natural language tasks to analysis plans"""
    
    def __init__(self, rag_service: Optional[RAGService] = None, document_processor: Optional[DocumentProcessor] = None):
        """Initialize planning agent
        
        Args:
            rag_service: Optional RAG service for document retrieval
            document_processor: Optional document processor
        """
        # Initialize LLM через factory (GigaChat)
        try:
            self.llm = create_llm(temperature=0.1)  # Низкая температура для консистентности
            logger.info("✅ Using GigaChat for planning")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise ValueError(f"Ошибка инициализации LLM: {str(e)}")
        
        # Store RAG service for document retrieval
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Get planning tools
        planning_tools = get_planning_tools()
        
        # Add retrieve_documents_tool if RAG service is available
        self.tools = planning_tools
        if rag_service and document_processor:
            from app.services.langchain_agents.tools import initialize_tools, retrieve_documents_tool
            initialize_tools(rag_service, document_processor)
            self.tools = planning_tools + [retrieve_documents_tool]
            logger.info("✅ Planning agent has access to retrieve_documents_tool")
        
        # Get prompt
        prompt = get_agent_prompt("planning")
        
        # Create agent using create_legal_agent for consistency
        self.agent = create_legal_agent(self.llm, self.tools, system_prompt=prompt)
        
        logger.info("Planning Agent initialized")
    
    def plan_analysis(
        self, 
        user_task: str, 
        case_id: str,
        available_documents: Optional[List[str]] = None,
        num_documents: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Создает план анализа на основе задачи пользователя
        
        Args:
            user_task: Задача пользователя на естественном языке
            case_id: Идентификатор дела
            available_documents: Список доступных документов (опционально)
            num_documents: Количество документов в деле (опционально)
        
        Returns:
            Dictionary с планом анализа:
            {
                "analysis_types": ["timeline", "key_facts"],
                "reasoning": "Выбраны эти анализы потому что...",
                "confidence": 0.9
            }
        """
        try:
            logger.info(f"Planning analysis for task: {user_task[:100]}... (case_id: {case_id})")
            
            # Формируем сообщение для агента с информацией о документах
            task_message = f"Задача пользователя: {user_task}\n\n"
            
            # Добавляем информацию о количестве документов
            if num_documents is not None and num_documents > 0:
                task_message += f"В деле {case_id} загружено {num_documents} документов. "
            else:
                task_message += f"Для дела {case_id} "
            
            task_message += "Определи, какие анализы нужно выполнить для выполнения задачи пользователя."
            
            # Добавляем примеры документов, если есть
            if available_documents and len(available_documents) > 0:
                docs_preview = ', '.join(available_documents[:5])  # Первые 5 документов
                if len(available_documents) > 5:
                    docs_preview += f" и еще {len(available_documents) - 5} документов"
                task_message += f"\n\nПримеры документов в деле: {docs_preview}."
            
            # Если есть RAG service, ОБЯЗАТЕЛЬНО предлагаем использовать retrieve_documents_tool
            if self.rag_service:
                # Для задач про хронологию/события - обязательно использовать tool
                if any(keyword in user_task.lower() for keyword in ["хронология", "события", "даты", "timeline", "расположить", "временной"]):
                    task_message += f"\n\nКРИТИЧНО: Для понимания задачи используй retrieve_documents_tool с запросом про даты и события для дела {case_id}. Это покажет, какие документы есть и что в них содержится. Затем создай план анализа."
                else:
                    task_message += "\n\nВАЖНО: Документы уже загружены в систему. Если нужно увидеть содержимое документов для понимания задачи, используй retrieve_documents_tool для поиска релевантных документов."
            
            # GigaChat поддерживает function calling
            use_tools = hasattr(self.llm, 'bind_tools')
            
            if use_tools:
                logger.info("Planning agent: Using GigaChat with function calling - agent can use retrieve_documents_tool")
            else:
                logger.warning("Planning agent: GigaChat bind_tools not available, using direct RAG approach")
                # Fallback: используем прямой RAG если function calling недоступен
                if self.rag_service:
                    from app.utils.database import SessionLocal
                    
                    # Используем прямой RAG для получения контекста документов
                    db = SessionLocal()
                    try:
                        # Получаем релевантные документы через RAG
                        relevant_docs = self.rag_service.retrieve_context(
                            case_id=case_id,
                            query=user_task,
                            k=10,  # Небольшое количество для планирования
                            db=db
                        )
                        
                        if relevant_docs:
                            # Форматируем документы для промпта
                            sources_text = self.rag_service.format_sources_for_prompt(relevant_docs)
                            task_message += f"\n\n=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ===\n{sources_text}\n\nИспользуй эту информацию для понимания задачи и создания плана анализа."
                            logger.info(f"Planning agent: Retrieved {len(relevant_docs)} documents for context")
                        else:
                            logger.warning(f"Planning agent: No documents found via RAG for case {case_id}")
                    finally:
                        db.close()
            
            message = HumanMessage(content=task_message)
            
            # Выполняем агента с безопасным вызовом
            from app.services.langchain_agents.agent_factory import safe_agent_invoke
            try:
                result = safe_agent_invoke(
                    self.agent,
                    self.llm,
                    {"messages": [message]},
                    config={"recursion_limit": 15}
                )
                
                # Извлекаем ответ агента
                if isinstance(result, dict):
                    messages = result.get("messages", [])
                    if messages:
                        response_message = messages[-1]
                        if hasattr(response_message, 'content'):
                            response_text = response_message.content
                        else:
                            response_text = str(response_message)
                    else:
                        response_text = str(result)
                else:
                    response_text = str(result)
                
            except Exception as e:
                logger.warning(f"Agent execution error: {e}, using fallback")
                return self._fallback_planning(user_task)
            
            # Парсим JSON из ответа
            plan = self._parse_agent_response(response_text)
            
            # Валидация и добавление зависимостей
            validated_types = self._validate_and_add_dependencies(plan.get("analysis_types", []))
            plan["analysis_types"] = validated_types
            
            # Обеспечиваем наличие reasoning и confidence
            if "reasoning" not in plan:
                plan["reasoning"] = "План создан на основе анализа задачи пользователя"
            if "confidence" not in plan:
                plan["confidence"] = 0.8
            
            logger.info(
                f"Analysis plan created: {validated_types}, "
                f"confidence: {plan.get('confidence', 0.8):.2f}"
            )
            
            return plan
            
        except Exception as e:
            logger.error(f"Error in planning agent: {e}", exc_info=True)
            return self._fallback_planning(user_task)
    
    def _parse_agent_response(self, response_text: str) -> Dict[str, Any]:
        """
        Парсит JSON из ответа агента
        
        Args:
            response_text: Текст ответа агента
        
        Returns:
            Dictionary с планом анализа
        """
        # Убираем лишние пробелы
        response_text = response_text.strip()
        
        # Пытаемся найти JSON в разных форматах
        json_patterns = [
            # JSON в markdown code block
            r'```json\s*(\{.*?\})\s*```',
            r'```\s*(\{.*?\})\s*```',
            # JSON объект напрямую
            r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})',
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                try:
                    json_text = match.group(1)
                    plan = json.loads(json_text)
                    if "analysis_types" in plan:
                        logger.debug("Successfully parsed JSON from agent response")
                        return plan
                except json.JSONDecodeError as e:
                    logger.debug(f"JSON decode error with pattern {pattern}: {e}")
                    continue
        
        # Если не нашли JSON, пытаемся извлечь список типов из текста
        logger.warning("Could not parse JSON from agent response, trying text extraction")
        return self._extract_plan_from_text(response_text)
    
    def _extract_plan_from_text(self, text: str) -> Dict[str, Any]:
        """
        Извлекает план из текстового ответа (fallback)
        
        Args:
            text: Текст ответа
        
        Returns:
            Dictionary с планом
        """
        analysis_types = []
        text_lower = text.lower()
        
        # Ищем упоминания типов анализов
        for analysis_type in AVAILABLE_ANALYSES.keys():
            if analysis_type in text_lower:
                analysis_types.append(analysis_type)
        
        # Если ничего не найдено, используем общий план
        if not analysis_types:
            analysis_types = ["timeline", "key_facts", "discrepancy"]
        
        return {
            "analysis_types": analysis_types,
            "reasoning": f"План извлечен из текстового ответа: {text[:200]}...",
            "confidence": 0.6
        }
    
    def _validate_and_add_dependencies(self, analysis_types: List[str]) -> List[str]:
        """
        Валидирует типы анализов и добавляет зависимости
        
        Args:
            analysis_types: Список типов анализов
        
        Returns:
            Валидированный список с зависимостями
        """
        validated = []
        seen = set()
        
        def add_with_dependencies(analysis_type: str):
            """Рекурсивно добавляет анализ с его зависимостями"""
            if analysis_type in seen:
                return
            
            analysis_info = AVAILABLE_ANALYSES.get(analysis_type)
            if not analysis_info:
                logger.warning(f"Unknown analysis type: {analysis_type}, skipping")
                return
            
            # Добавляем зависимости сначала
            for dep in analysis_info["dependencies"]:
                add_with_dependencies(dep)
            
            # Добавляем сам анализ
            validated.append(analysis_type)
            seen.add(analysis_type)
        
        # Добавляем все анализы с зависимостями
        for analysis_type in analysis_types:
            if isinstance(analysis_type, str):
                add_with_dependencies(analysis_type)
        
        logger.debug(f"Dependency resolution: {analysis_types} -> {validated}")
        return validated
    
    def _fallback_planning(self, user_task: str) -> Dict[str, Any]:
        """
        Простое планирование на основе ключевых слов (fallback)
        
        Args:
            user_task: Задача пользователя
        
        Returns:
            План анализа
        """
        user_task_lower = user_task.lower()
        selected = []
        
        # Простая эвристика на основе ключевых слов
        for analysis_type, info in AVAILABLE_ANALYSES.items():
            for keyword in info["keywords"]:
                if keyword.lower() in user_task_lower:
                    selected.append(analysis_type)
                    break
        
        # Если ничего не найдено, возвращаем основные анализы
        if not selected:
            selected = ["timeline", "key_facts", "discrepancy"]
        
        # Добавляем зависимости
        validated = self._validate_and_add_dependencies(selected)
        
        return {
            "analysis_types": validated,
            "reasoning": f"Fallback планирование на основе ключевых слов. Задача: {user_task}",
            "confidence": 0.6
        }
