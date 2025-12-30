"""Planning agent for natural language task understanding and analysis planning"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.services.langchain_agents.planning_tools import get_planning_tools, AVAILABLE_ANALYSES
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.langchain_agents.planning_validator import PlanningValidator
from app.services.langchain_agents.tool_selector import ToolSelector
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.config import config
from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session
from datetime import datetime
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
        
        # Initialize document analysis tools if available
        if rag_service and document_processor:
            from app.services.langchain_agents.planning_tools import initialize_document_analysis_tools
            initialize_document_analysis_tools(rag_service, document_processor)
            logger.info("✅ Document analysis tools initialized")
        
        # Get planning tools (includes document analysis tools if initialized)
        planning_tools = get_planning_tools()
        
        # Add retrieve_documents_tool if RAG service is available
        self.tools = planning_tools
        if rag_service and document_processor:
            from app.services.langchain_agents.tools import initialize_tools, retrieve_documents_tool
            initialize_tools(rag_service, document_processor)
            self.tools = planning_tools + [retrieve_documents_tool]
            logger.info("✅ Planning agent has access to retrieve_documents_tool and document analysis tools")
        
        # Get prompt
        prompt = get_agent_prompt("planning")
        
        # Create agent using create_legal_agent for consistency
        self.agent = create_legal_agent(self.llm, self.tools, system_prompt=prompt)
        
        # Initialize validator
        self.validator = PlanningValidator()
        
        # Initialize tool selector
        try:
            from app.services.external_sources.source_router import SourceRouter
            source_router = SourceRouter()
            self.tool_selector = ToolSelector(source_router=source_router)
        except Exception as e:
            logger.warning(f"Failed to initialize source router: {e}")
            self.tool_selector = ToolSelector()
        
        logger.info("Planning Agent initialized")
    
    def analyze_documents_for_planning(
        self,
        case_id: str,
        user_task: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Автономно анализирует документы для понимания контекста БЕЗ явной задачи пользователя.
        
        Этот метод:
        1. Классифицирует документы
        2. Определяет тип дела
        3. Извлекает ключевые индикаторы
        4. Предлагает план анализа на основе документов
        
        Args:
            case_id: Идентификатор дела
            user_task: Опциональная задача пользователя для контекста
        
        Returns:
            Dictionary с анализом документов:
            {
                "case_type": "contract_dispute",
                "document_structure": {...},
                "key_indicators": [...],
                "suggested_analyses": ["timeline", "key_facts"],
                "reasoning": "..."
            }
        """
        if not self.rag_service or not self.document_processor:
            logger.warning("Cannot analyze documents: RAG service or document processor not available")
            return {
                "case_type": "unknown",
                "document_structure": {},
                "key_indicators": [],
                "suggested_analyses": [],
                "reasoning": "Document analysis tools not available"
            }
        
        try:
            from app.utils.database import SessionLocal
            db = SessionLocal()
            
            try:
                # 1. Анализируем структуру документов
                from app.services.langchain_agents.planning_tools import analyze_document_structure_tool
                structure_result = analyze_document_structure_tool.invoke({"case_id": case_id})
                structure_data = json.loads(structure_result) if isinstance(structure_result, str) else structure_result
                
                # 2. Классифицируем тип дела
                from app.services.langchain_agents.planning_tools import classify_case_type_tool
                case_type_result = classify_case_type_tool.invoke({"case_id": case_id})
                case_type_data = json.loads(case_type_result) if isinstance(case_type_result, str) else case_type_result
                
                # 3. Извлекаем ключевые индикаторы из документов
                key_indicators = []
                if user_task:
                    # Используем задачу пользователя для поиска релевантных индикаторов
                    relevant_docs = self.rag_service.retrieve_context(
                        case_id=case_id,
                        query=user_task,
                        k=5,
                        db=db
                    )
                    for doc in relevant_docs[:3]:
                        # Document объекты имеют атрибуты page_content и metadata
                        content = ""
                        source = "unknown"
                        if hasattr(doc, 'page_content'):
                            content = doc.page_content[:200]
                        elif isinstance(doc, dict):
                            content = doc.get("content", "")[:200]
                        
                        if hasattr(doc, 'metadata') and doc.metadata:
                            source = doc.metadata.get("source_file", doc.metadata.get("file", "unknown"))
                        elif isinstance(doc, dict):
                            source = doc.get("file", "unknown")
                        
                        key_indicators.append({
                            "content": content,
                            "source": source
                        })
                else:
                    # Общий поиск ключевых элементов
                    general_docs = self.rag_service.retrieve_context(
                        case_id=case_id,
                        query="ключевые факты даты суммы стороны",
                        k=5,
                        db=db
                    )
                    for doc in general_docs[:3]:
                        # Document объекты имеют атрибуты page_content и metadata
                        content = ""
                        source = "unknown"
                        if hasattr(doc, 'page_content'):
                            content = doc.page_content[:200]
                        elif isinstance(doc, dict):
                            content = doc.get("content", "")[:200]
                        
                        if hasattr(doc, 'metadata') and doc.metadata:
                            source = doc.metadata.get("source_file", doc.metadata.get("file", "unknown"))
                        elif isinstance(doc, dict):
                            source = doc.get("file", "unknown")
                        
                        key_indicators.append({
                            "content": content,
                            "source": source
                        })
                
                # 4. Предлагаем анализы на основе типа дела и структуры
                suggested_analyses = []
                case_type = case_type_data.get("case_type", "general")
                file_count = structure_data.get("file_count", 0)
                
                # Базовые анализы для всех дел
                suggested_analyses.extend(["document_classifier", "key_facts"])
                
                # Специфичные анализы в зависимости от типа дела
                if case_type in ["contract_dispute", "litigation"]:
                    suggested_analyses.extend(["timeline", "discrepancy"])
                    if file_count > 3:
                        suggested_analyses.append("risk")
                
                if case_type == "corporate":
                    suggested_analyses.extend(["entity_extraction", "relationship"])
                
                # Убираем дубликаты
                suggested_analyses = list(dict.fromkeys(suggested_analyses))
                
                reasoning = (
                    f"Проанализировано {file_count} документов. "
                    f"Тип дела: {case_type} (уверенность: {case_type_data.get('confidence', 0.5):.0%}). "
                    f"Рекомендуемые анализы: {', '.join(suggested_analyses)}"
                )
                
                result = {
                    "case_type": case_type,
                    "case_type_confidence": case_type_data.get("confidence", 0.5),
                    "document_structure": structure_data,
                    "key_indicators": key_indicators,
                    "suggested_analyses": suggested_analyses,
                    "reasoning": reasoning
                }
                
                logger.info(f"Document analysis completed for case {case_id}: {case_type}, {len(suggested_analyses)} suggested analyses")
                return result
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error in analyze_documents_for_planning: {e}", exc_info=True)
            return {
                "case_type": "unknown",
                "document_structure": {},
                "key_indicators": [],
                "suggested_analyses": ["timeline", "key_facts", "discrepancy"],
                "reasoning": f"Error during analysis: {str(e)}"
            }
    
    def plan_analysis(
        self, 
        user_task: str, 
        case_id: str,
        available_documents: Optional[List[str]] = None,
        num_documents: Optional[int] = None,
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Создает план анализа на основе задачи пользователя
        
        Args:
            user_task: Задача пользователя на естественном языке
            case_id: Идентификатор дела
            available_documents: Список доступных документов (опционально)
            num_documents: Количество документов в деле (опционально)
            db: Database session для доступа к Store
        
        Returns:
            Dictionary с многоуровневым планом анализа:
            {
                "goals": ["найти риски", "извлечь даты"],
                "strategy": "comprehensive_analysis",
                "analysis_types": ["timeline", "key_facts"],
                "steps": [
                    {
                        "step_id": "...",
                        "agent_name": "discrepancy",
                        "reasoning": "Нужен для анализа рисков",
                        "parameters": {"depth": "deep", "focus": "contracts"},
                        "estimated_time": "5-10 мин"
                    }
                ],
                "reasoning": "Выбраны эти анализы потому что...",
                "confidence": 0.9,
                "alternative_plans": []
            }
        """
        try:
            logger.info(f"Planning analysis for task: {user_task[:100]}... (case_id: {case_id})")
            
            # ШАГ 0: Попытка загрузить успешные планы из Store
            similar_plans = []
            if db:
                try:
                    from app.services.langchain_agents.store_service import LangGraphStoreService
                    from app.utils.async_utils import run_async_safe
                    
                    store_service = LangGraphStoreService(db)
                    
                    # Ищем похожие успешные планы
                    similar_plans = run_async_safe(store_service.search_precedents(
                                namespace="successful_plans",
                                query=user_task[:100],  # Первые 100 символов задачи
                            limit=3
                        ))
                    
                    if similar_plans:
                        logger.info(f"Found {len(similar_plans)} similar successful plans in Store")
                        # Используем первый похожий план как основу, если он очень похож
                        for plan_data in similar_plans:
                            plan_value = plan_data.get("value", {})
                            if plan_value.get("confidence", 0) > 0.8:
                                logger.info(f"Using similar plan as reference: {plan_data.get('key', 'unknown')}")
                                # Можно использовать этот план как основу для адаптации
                except Exception as e:
                    logger.warning(f"Failed to load plans from Store: {e}")
            
            # ШАГ 1: Автономный анализ документов для понимания контекста
            document_analysis = None
            if self.rag_service and self.document_processor:
                try:
                    document_analysis = self.analyze_documents_for_planning(case_id, user_task)
                    logger.info(f"Document analysis completed: case_type={document_analysis.get('case_type')}, "
                              f"suggested={document_analysis.get('suggested_analyses')}")
                except Exception as e:
                    logger.warning(f"Document analysis failed: {e}, continuing without it")
            
            # Формируем сообщение для агента с информацией о документах
            task_message = f"Задача пользователя: {user_task}\n\n"
            
            # Добавляем результаты автономного анализа документов
            if document_analysis:
                task_message += f"=== АВТОНОМНЫЙ АНАЛИЗ ДОКУМЕНТОВ ===\n"
                task_message += f"Тип дела: {document_analysis.get('case_type', 'unknown')} "
                task_message += f"(уверенность: {document_analysis.get('case_type_confidence', 0.5):.0%})\n"
                task_message += f"Документов в деле: {document_analysis.get('document_structure', {}).get('file_count', 0)}\n"
                
                suggested = document_analysis.get('suggested_analyses', [])
                if suggested:
                    task_message += f"Рекомендуемые анализы на основе документов: {', '.join(suggested)}\n"
                
                key_indicators = document_analysis.get('key_indicators', [])
                if key_indicators:
                    task_message += f"\nКлючевые индикаторы из документов:\n"
                    for idx, indicator in enumerate(key_indicators[:3], 1):
                        task_message += f"{idx}. {indicator.get('content', '')[:150]}... (из {indicator.get('source', 'unknown')})\n"
                
                task_message += f"\nОбъяснение: {document_analysis.get('reasoning', '')}\n\n"
            
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
            
            # Если есть RAG service, ОБЯЗАТЕЛЬНО предлагаем использовать инструменты анализа
            if self.rag_service:
                # Если автономный анализ не был выполнен, предлагаем использовать инструменты
                if not document_analysis:
                    task_message += "\n\nВАЖНО: Используй доступные инструменты для анализа документов:"
                    task_message += "\n- analyze_document_structure_tool - для понимания структуры документов"
                    task_message += "\n- classify_case_type_tool - для определения типа дела"
                    task_message += "\n- retrieve_documents_tool - для поиска релевантных документов"
                
                # Для задач про хронологию/события - обязательно использовать tool
                if any(keyword in user_task.lower() for keyword in ["хронология", "события", "даты", "timeline", "расположить", "временной"]):
                    task_message += f"\n\nКРИТИЧНО: Для понимания задачи используй retrieve_documents_tool с запросом про даты и события для дела {case_id}. Это покажет, какие документы есть и что в них содержится. Затем создай план анализа."
                elif not document_analysis:
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
            
            # Преобразуем в многоуровневую структуру, если еще не сделано
            plan["case_id"] = case_id  # Add case_id for tool selection
            plan = self._enhance_plan_with_levels(plan, user_task, document_analysis)
            
            # Валидируем и оптимизируем план
            validation_result = self.validator.validate_plan(plan, case_id)
            
            if validation_result.issues:
                logger.warning(f"Plan validation found issues: {validation_result.issues}")
                # Добавляем предупреждения в reasoning
                if "reasoning" not in plan:
                    plan["reasoning"] = ""
                plan["reasoning"] += f"\n\nВНИМАНИЕ: Обнаружены проблемы при валидации: {', '.join(validation_result.issues)}"
            
            if validation_result.warnings:
                logger.info(f"Plan validation warnings: {validation_result.warnings}")
            
            # Используем оптимизированный план, если доступен
            if validation_result.optimized_plan:
                plan = validation_result.optimized_plan
                logger.info("Plan optimized by validator")
            
            # Добавляем оценку времени выполнения
            if validation_result.estimated_time:
                plan["estimated_execution_time"] = validation_result.estimated_time
            
            # Обеспечиваем наличие reasoning и confidence
            if "reasoning" not in plan:
                plan["reasoning"] = "План создан на основе анализа задачи пользователя"
            if "confidence" not in plan:
                plan["confidence"] = 0.8
            
            logger.info(
                f"Multi-level analysis plan created and validated: {len(plan.get('goals', []))} goals, "
                f"{len(plan.get('steps', plan.get('analysis_types', [])))} steps, "
                f"confidence: {plan.get('confidence', 0.8):.2f}, "
                f"valid: {validation_result.is_valid}"
            )
            
            # Сохраняем успешный план в Store для будущего использования
            if db and validation_result.is_valid and plan.get("confidence", 0) > 0.7:
                try:
                    from app.services.langchain_agents.store_service import LangGraphStoreService
                    import asyncio
                    
                    store_service = LangGraphStoreService(db)
                    
                    # Создаем ключ на основе задачи
                    plan_key = f"{user_task[:50]}_{case_id}"[:200]  # Ограничиваем длину ключа
                    
                    plan_value = {
                        "analysis_types": plan.get("analysis_types", []),
                        "goals": plan.get("goals", []),
                        "strategy": plan.get("strategy", ""),
                        "confidence": plan.get("confidence", 0.8),
                        "reasoning": plan.get("reasoning", "")
                    }
                    
                    metadata = {
                        "case_id": case_id,
                        "user_task": user_task[:200],
                        "saved_at": datetime.now().isoformat(),
                        "source": "planning_agent"
                    }
                    
                    # Use run_async_safe for async call from sync function
                    from app.utils.async_utils import run_async_safe
                    run_async_safe(store_service.save_pattern(
                            namespace="successful_plans",
                            key=plan_key,
                            value=plan_value,
                            metadata=metadata
                        ))
                    
                    logger.info(f"Saved successful plan to Store: {plan_key}")
                except Exception as e:
                    logger.warning(f"Failed to save plan to Store: {e}")
            
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
        
        # Метод 1: Попытка найти JSON в markdown code blocks
        json_patterns = [
            r'```json\s*(\{.*?\})\s*```',
            r'```\s*(\{.*?\})\s*```',
        ]
        
        for pattern in json_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                try:
                    json_text = match.group(1)
                    plan = json.loads(json_text)
                    # Принимаем как базовый план (с analysis_types) или многоуровневый (со steps)
                    if "analysis_types" in plan or "steps" in plan:
                        logger.debug("Successfully parsed JSON from agent response (method 1: markdown)")
                        return plan
                except json.JSONDecodeError as e:
                    logger.debug(f"JSON decode error with pattern {pattern}: {e}")
                    continue
        
        # Метод 2: Найти первый валидный JSON объект в тексте
        # Ищем открывающую скобку и пытаемся найти закрывающую
        brace_start = response_text.find('{')
        if brace_start != -1:
            brace_count = 0
            for i in range(brace_start, len(response_text)):
                if response_text[i] == '{':
                    brace_count += 1
                elif response_text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        try:
                            json_text = response_text[brace_start:i+1]
                            plan = json.loads(json_text)
                            if "analysis_types" in plan or "steps" in plan:
                                logger.debug("Successfully parsed JSON from agent response (method 2: brace matching)")
                                return plan
                        except json.JSONDecodeError:
                            pass
        
        # Метод 3: Fallback - извлечение из текста
        logger.debug("Could not parse JSON from agent response, using text extraction")
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
    
    def _enhance_plan_with_levels(
        self,
        plan: Dict[str, Any],
        user_task: str,
        document_analysis: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Преобразует базовый план в многоуровневую структуру
        
        Args:
            plan: Базовый план с analysis_types
            user_task: Задача пользователя
            document_analysis: Результаты автономного анализа документов
        
        Returns:
            Многоуровневый план с целями, стратегией и детальными шагами
        """
        analysis_types = plan.get("analysis_types", [])
        
        # Уровень 1: Высокоуровневые цели
        goals = self._extract_goals_from_task(user_task, analysis_types)
        
        # Уровень 2: Стратегия выполнения
        strategy = self._determine_strategy(analysis_types, document_analysis)
        
        # Уровень 3: Детальные шаги с параметрами
        # Extract case_id from plan if available, otherwise use "unknown"
        case_id = plan.get("case_id", "unknown")
        steps = self._create_detailed_steps(analysis_types, goals, document_analysis, case_id)
        
        # Генерируем альтернативные планы для сложных задач
        alternative_plans = []
        if plan.get("confidence", 1.0) < 0.8 and len(analysis_types) > 3:
            alternative_plans = self._generate_alternative_plans(analysis_types, user_task)
        
        enhanced_plan = {
            "goals": goals,
            "strategy": strategy,
            "analysis_types": analysis_types,  # Оставляем для обратной совместимости
            "steps": steps,
            "reasoning": plan.get("reasoning", ""),
            "confidence": plan.get("confidence", 0.8),
            "alternative_plans": alternative_plans
        }
        
        return enhanced_plan
    
    def _extract_goals_from_task(self, user_task: str, analysis_types: List[str]) -> List[Dict[str, Any]]:
        """Извлекает высокоуровневые цели из задачи пользователя"""
        goals = []
        task_lower = user_task.lower()
        
        # Маппинг ключевых слов на цели
        goal_keywords = {
            "найти риски": ["риск", "риски", "опасность", "угроза"],
            "извлечь даты": ["дата", "даты", "хронология", "события", "timeline"],
            "найти противоречия": ["противоречие", "несоответствие", "расхождение", "discrepancy"],
            "извлечь факты": ["факт", "факты", "ключевые факты", "key facts"],
            "создать резюме": ["резюме", "summary", "краткое содержание", "сводка"],
            "классифицировать документы": ["классификация", "тип документа", "document classifier"],
            "извлечь сущности": ["сущность", "entity", "имена", "организации"]
        }
        
        for goal_desc, keywords in goal_keywords.items():
            if any(keyword in task_lower for keyword in keywords):
                goals.append({
                    "goal_id": f"goal_{len(goals) + 1}",
                    "description": goal_desc,
                    "priority": 1 if len(goals) == 0 else len(goals) + 1
                })
        
        # Если цели не найдены, создаем общие цели на основе analysis_types
        if not goals:
            for idx, analysis_type in enumerate(analysis_types[:3], 1):
                goal_map = {
                    "timeline": "извлечь хронологию событий",
                    "key_facts": "извлечь ключевые факты",
                    "discrepancy": "найти противоречия",
                    "risk": "проанализировать риски",
                    "summary": "создать резюме дела"
                }
                goals.append({
                    "goal_id": f"goal_{idx}",
                    "description": goal_map.get(analysis_type, f"выполнить {analysis_type}"),
                    "priority": idx
                })
        
        return goals
    
    def _determine_strategy(
        self,
        analysis_types: List[str],
        document_analysis: Optional[Dict[str, Any]] = None
    ) -> str:
        """Определяет стратегию выполнения на основе типов анализов и контекста"""
        if document_analysis:
            case_type = document_analysis.get("case_type", "general")
            file_count = document_analysis.get("document_structure", {}).get("file_count", 0)
            
            if case_type in ["contract_dispute", "litigation"] and file_count > 5:
                return "comprehensive_analysis"
            elif file_count > 10:
                return "parallel_optimized"
            elif len(analysis_types) > 4:
                return "sequential_dependent"
        
        if len(analysis_types) <= 2:
            return "simple_sequential"
        elif any(agent in analysis_types for agent in ["risk", "summary", "relationship"]):
            return "dependent_sequential"
        else:
            return "parallel_independent"
    
    def _create_detailed_steps(
        self,
        analysis_types: List[str],
        goals: List[Dict[str, Any]],
        document_analysis: Optional[Dict[str, Any]] = None,
        case_id: str = "unknown"
    ) -> List[Dict[str, Any]]:
        """Создает детальные шаги с параметрами выполнения"""
        from app.services.langchain_agents.state import PlanStep
        import uuid
        
        steps = []
        goal_map = {goal["goal_id"]: goal for goal in goals}
        
        # Оценка времени выполнения по типам
        time_estimates = {
            "document_classifier": "2-5 мин",
            "entity_extraction": "3-7 мин",
            "privilege_check": "2-4 мин",
            "timeline": "5-10 мин",
            "key_facts": "5-10 мин",
            "discrepancy": "7-15 мин",
            "relationship": "5-10 мин",
            "risk": "5-10 мин",
            "summary": "3-7 мин"
        }
        
        # Параметры по умолчанию для разных типов
        default_parameters = {
            "timeline": {"depth": "standard", "include_relative_dates": True},
            "key_facts": {"focus": "all", "detail_level": "standard"},
            "discrepancy": {"depth": "deep", "focus": "all_documents"},
            "risk": {"severity_threshold": "medium", "include_mitigation": False},
            "summary": {"length": "medium", "include_sources": True}
        }
        
        for idx, analysis_type in enumerate(analysis_types):
            step_id = f"{analysis_type}_{uuid.uuid4().hex[:8]}"
            
            # Определяем, к какой цели относится шаг
            goal_id = None
            for goal in goals:
                if analysis_type in goal.get("description", "").lower():
                    goal_id = goal["goal_id"]
                    break
            if not goal_id and goals:
                goal_id = goals[0]["goal_id"]  # Привязываем к первой цели по умолчанию
            
            # Получаем зависимости
            from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
            dependencies = AVAILABLE_ANALYSES.get(analysis_type, {}).get("dependencies", [])
            
            # Reasoning для шага
            reasoning = f"Выполнение {analysis_type} для достижения цели"
            if document_analysis:
                suggested = document_analysis.get("suggested_analyses", [])
                if analysis_type in suggested:
                    reasoning += f". Рекомендован автономным анализом документов."
            
            # Select tools for this agent
            selected_tools = self.tool_selector.select_tools(
                task=f"Execute {analysis_type} analysis",
                context={
                    "agent_name": analysis_type,
                    "case_id": case_id
                }
            )
            
            # Select data sources
            selected_sources = self.tool_selector.select_sources(
                task=f"Execute {analysis_type} analysis",
                context={
                    "agent_name": analysis_type,
                    "case_id": case_id
                }
            )
            
            step = {
                "step_id": step_id,
                "agent_name": analysis_type,
                "description": f"Выполнить анализ {analysis_type}",
                "status": "pending",
                "dependencies": dependencies,
                "result_key": f"{analysis_type}_result",
                "reasoning": reasoning,
                "parameters": default_parameters.get(analysis_type, {}),
                "estimated_time": time_estimates.get(analysis_type, "5-10 мин"),
                "goal_id": goal_id,
                "tools": selected_tools,  # Add tools to step
                "sources": selected_sources  # Add sources to step
            }
            
            steps.append(step)
        
        return steps
    
    def _generate_alternative_plans(
        self,
        analysis_types: List[str],
        user_task: str
    ) -> List[Dict[str, Any]]:
        """Генерирует альтернативные планы для сложных задач"""
        alternatives = []
        
        # Альтернатива 1: Упрощенный план (только основные анализы)
        if len(analysis_types) > 3:
            core_analyses = ["document_classifier", "key_facts", "timeline"]
            simplified = [a for a in analysis_types if a in core_analyses]
            if simplified:
                alternatives.append({
                    "name": "Упрощенный план",
                    "analysis_types": simplified,
                    "reasoning": "Фокус на основных анализах для быстрого результата",
                    "estimated_time": "10-15 мин"
                })
        
        # Альтернатива 2: Расширенный план (добавляем дополнительные анализы)
        if "discrepancy" in analysis_types and "risk" not in analysis_types:
            extended = analysis_types + ["risk"]
            alternatives.append({
                "name": "Расширенный план",
                "analysis_types": extended,
                "reasoning": "Добавлен анализ рисков на основе противоречий",
                "estimated_time": "20-30 мин"
            })
        
        return alternatives
    
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
        
        base_plan = {
            "analysis_types": validated,
            "reasoning": f"Fallback планирование на основе ключевых слов. Задача: {user_task}",
            "confidence": 0.6
        }
        
        # Преобразуем в многоуровневую структуру
        return self._enhance_plan_with_levels(base_plan, user_task)
