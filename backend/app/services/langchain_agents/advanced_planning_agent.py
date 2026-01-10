"""Advanced Planning Agent with subtask support (inspired by DeepAgents)"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.planning_validator import PlanningValidator
from app.services.context_manager import ContextManager
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage, SystemMessage
from app.services.langchain_agents.prompts import TABLE_DETECTION_PROMPT
from app.services.langchain_agents.models import TableDecision, TableColumnSpec
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.planning_agent import extract_doc_types_from_query
from sqlalchemy.orm import Session
import logging
import json
import re

logger = logging.getLogger(__name__)


class AdvancedPlanningAgent:
    """Продвинутый планировщик с поддержкой подзадач и разбивкой сложных задач"""
    
    def __init__(
        self,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None
    ):
        """Initialize advanced planning agent
        
        Args:
            rag_service: Optional RAG service for document retrieval
            document_processor: Optional document processor
        """
        # Initialize base planning agent
        self.base_planning_agent = PlanningAgent(
            rag_service=rag_service,
            document_processor=document_processor
        )
        
        # Initialize LLM for subtask analysis
        try:
            self.llm = create_llm(temperature=0.2)  # Немного выше для творческого разбиения
            logger.info("✅ Advanced Planning Agent initialized with GigaChat")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise
        
        self.rag_service = rag_service
        self.document_processor = document_processor
        self.validator = PlanningValidator()
        
        # Initialize Context Manager for learning from previous plans
        try:
            self.context_manager = ContextManager()
            logger.info("✅ Context Manager initialized in AdvancedPlanningAgent")
        except Exception as e:
            logger.warning(f"Failed to initialize ContextManager: {e}")
            self.context_manager = None
    
    def plan_hierarchically(
        self,
        user_task: str,
        case_id: str,
        max_depth: int = 3,
        available_documents: Optional[List[str]] = None,
        num_documents: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Создает иерархический план с рекурсивным разложением задач
        
        Args:
            user_task: Задача пользователя
            case_id: Case identifier
            max_depth: Максимальная глубина рекурсии
            available_documents: Список доступных документов
            num_documents: Количество документов
            
        Returns:
            Иерархический план с уровнями:
            {
                "main_task": "Analyze contract",
                "levels": [
                    {
                        "level": 1,
                        "subtasks": [
                            {"id": "parse_structure", "parallel": true},
                            {"id": "extract_parties", "parallel": true}
                        ]
                    },
                    {
                        "level": 2,
                        "subtasks": [
                            {"id": "assess_termination_risk", "parent": "parse_structure}
                        ]
                    }
                ],
                "execution_strategy": "parallel_levels"
            }
        """
        try:
            logger.info(f"Hierarchical planning: Creating recursive plan for: {user_task[:100]}...")
            
            # Level 1: Разбить на основные подзадачи
            level_1_subtasks = self._decompose_task(user_task, depth=1, max_depth=max_depth)
            
            # Level 2+: Рекурсивно разложить каждую подзадачу
            for subtask in level_1_subtasks:
                if self._needs_decomposition(subtask, max_depth):
                    subtask["children"] = self._decompose_task(
                        subtask["description"],
                        depth=2,
                        max_depth=max_depth,
                        parent_id=subtask.get("id")
                    )
            
            # Создаем структуру уровней
            levels = []
            level_1_items = [s for s in level_1_subtasks if s.get("level") == 1]
            if level_1_items:
                levels.append({
                    "level": 1,
                    "subtasks": level_1_items,
                    "parallel": True  # Параллельное выполнение на уровне 1
                })
            
            # Добавляем уровни 2+
            for subtask in level_1_subtasks:
                if "children" in subtask:
                    level_num = subtask.get("level", 1) + 1
                    levels.append({
                        "level": level_num,
                        "subtasks": subtask["children"],
                        "parent": subtask.get("id"),
                        "parallel": True  # Параллельное выполнение на каждом уровне
                    })
            
            return {
                "main_task": user_task,
                "levels": levels,
                "execution_strategy": "parallel_levels",
                "max_depth": max_depth,
                "case_id": case_id
            }
            
        except Exception as e:
            logger.error(f"Error in hierarchical planning: {e}", exc_info=True)
            # Fallback to regular subtask planning
            return self.plan_with_subtasks(user_task, case_id, available_documents, num_documents)
    
    def _decompose_task(
        self,
        task: str,
        depth: int = 1,
        max_depth: int = 3,
        parent_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Рекурсивно разлагает задачу на подзадачи"""
        if depth > max_depth:
            return []
        
        try:
            decomposition_prompt = f"""Ты эксперт по декомпозиции юридических задач.

Задача: {task}
Глубина: {depth}/{max_depth}
{"Родительская задача: " + parent_id if parent_id else ""}

Разложи задачу на 2-4 подзадачи, которые можно выполнить параллельно или последовательно.
Для каждой подзадачи укажи:
- id: уникальный идентификатор
- description: описание подзадачи
- agent_type: тип агента (timeline, key_facts, discrepancy, risk, etc.) или "custom"
- dependencies: список id зависимостей (если есть)
- parallel: можно ли выполнять параллельно с другими на этом уровне

Верни JSON массив объектов."""
            
            messages = [
                SystemMessage(content="Ты эксперт по декомпозиции задач для юридического анализа."),
                HumanMessage(content=decomposition_prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            # Парсим JSON
            try:
                # Извлекаем JSON из ответа
                import re
                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    subtasks = json.loads(json_match.group())
                else:
                    subtasks = json.loads(response_text)
                
                # Добавляем метаданные
                for subtask in subtasks:
                    subtask["level"] = depth
                    subtask["parent_id"] = parent_id
                    if "parallel" not in subtask:
                        subtask["parallel"] = True  # По умолчанию параллельно
                
                logger.debug(f"Decomposed task into {len(subtasks)} subtasks at depth {depth}")
                return subtasks
                
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse decomposition JSON: {e}, using fallback")
                return self._fallback_decomposition(task, depth)
                
        except Exception as e:
            logger.error(f"Error decomposing task: {e}", exc_info=True)
            return self._fallback_decomposition(task, depth)
    
    def _needs_decomposition(
        self,
        subtask: Dict[str, Any],
        max_depth: int
    ) -> bool:
        """Проверяет, нужно ли дальше разлагать подзадачу"""
        current_level = subtask.get("level", 1)
        if current_level >= max_depth:
            return False
        
        # Проверяем сложность подзадачи
        description = subtask.get("description", "")
        agent_type = subtask.get("agent_type", "")
        
        # Если это custom задача или очень сложная - разлагаем дальше
        if agent_type == "custom" or len(description) > 200:
            return True
        
        return False
    
    def _fallback_decomposition(
        self,
        task: str,
        depth: int
    ) -> List[Dict[str, Any]]:
        """Fallback декомпозиция на основе ключевых слов"""
        subtasks = []
        task_lower = task.lower()
        
        # Простая эвристика
        if "хронология" in task_lower or "timeline" in task_lower:
            subtasks.append({
                "id": f"subtask_timeline_{depth}",
                "description": "Извлечь хронологию событий",
                "agent_type": "timeline",
                "dependencies": [],
                "parallel": True,
                "level": depth
            })
        
        if "риск" in task_lower or "risk" in task_lower:
            subtasks.append({
                "id": f"subtask_risk_{depth}",
                "description": "Проанализировать риски",
                "agent_type": "risk",
                "dependencies": ["discrepancy"],
                "parallel": False,
                "level": depth
            })
        
        if not subtasks:
            # Общая подзадача
            subtasks.append({
                "id": f"subtask_general_{depth}",
                "description": task,
                "agent_type": "key_facts",
                "dependencies": [],
                "parallel": True,
                "level": depth
            })
        
        return subtasks
    
    def _determine_table_columns_from_task(
        self, 
        user_task: str,
        case_id: str = None,
        state: AnalysisState = None,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Определяет, требует ли задача создания таблицы, и если да - какие колонки нужны
        Если что-то неясно - задает уточняющие вопросы через interrupt()
        
        Args:
            user_task: Задача пользователя на естественном языке
            case_id: Case identifier (для получения доступных типов документов)
            state: Analysis state (для interrupt)
            db: Database session (для получения доступных типов документов)
            
        Returns:
            Dictionary с информацией о таблице:
            {
                "needs_table": bool,
                "table_name": str (если needs_table=True),
                "columns": List[Dict] (если needs_table=True),
                "doc_types": List[str] (если указаны),
                "reasoning": str
            }
        """
        try:
            logger.info(f"Determining table requirement for task: {user_task[:100]}...")
            
            # Используем LLM для определения таблицы с structured output
            from app.services.langchain_agents.models import TableDecision
            
            # Улучшенный промпт с явным указанием на JSON формат
            enhanced_prompt = f"""{TABLE_DETECTION_PROMPT}

КРИТИЧЕСКИ ВАЖНО:
- Ты ДОЛЖЕН вернуть ТОЛЬКО валидный JSON без дополнительного текста
- JSON должен начинаться с {{ и заканчиваться }}
- Все строки должны быть в двойных кавычках
- Не используй одинарные кавычки
- Не добавляй комментарии вне JSON
- Если needs_table: true, ОБЯЗАТЕЛЬНО укажи table_name и columns

Задача пользователя: {user_task}

Верни ТОЛЬКО JSON объект в следующем формате (без markdown, без code blocks, только чистый JSON):
{{
    "needs_table": true или false,
    "table_name": "Название таблицы" (если needs_table: true, иначе null),
    "columns": [{{"label": "...", "question": "...", "type": "..."}}] (если needs_table: true, иначе null),
    "doc_types": ["contract"] или null,
    "needs_clarification": true или false,
    "clarification_questions": ["..."] или null,
    "reasoning": "..."
}}"""
            
            messages = [
                SystemMessage(content=enhanced_prompt),
                HumanMessage(content=f"Задача пользователя: {user_task}\n\nВерни ТОЛЬКО валидный JSON объект без дополнительного текста.")
            ]
            
            # Пытаемся использовать structured output если доступен
            try:
                # Используем PydanticOutputParser для гарантированно валидного JSON
                from langchain_core.output_parsers import PydanticOutputParser
                parser = PydanticOutputParser(pydantic_object=TableDecision)
                
                # Добавляем инструкции парсера в промпт
                format_instructions = parser.get_format_instructions()
                messages[0] = SystemMessage(content=enhanced_prompt + f"\n\n{format_instructions}")
                
                response = self.llm.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Пытаемся распарсить через PydanticOutputParser
                result = None
                try:
                    parsed_result = parser.parse(response_text)
                    logger.info(f"Successfully parsed table detection using PydanticOutputParser")
                    # Преобразуем в dict для дальнейшей обработки
                    result_dict = parsed_result.dict() if hasattr(parsed_result, 'dict') else parsed_result.model_dump()
                    # Нормализуем doc_types ДО создания TableDecision
                    if "doc_types" in result_dict:
                        doc_types_val = result_dict["doc_types"]
                        if isinstance(doc_types_val, str):
                            if doc_types_val.lower() == "all":
                                result_dict["doc_types"] = None
                            else:
                                result_dict["doc_types"] = [doc_types_val]
                        elif doc_types_val is None:
                            result_dict["doc_types"] = None
                    result = TableDecision(**result_dict)
                except Exception as parse_error:
                    logger.warning(f"PydanticOutputParser failed: {parse_error}, trying manual parsing")
                    # Продолжаем с ручным парсингом
                    result = None
            except Exception as structured_error:
                logger.warning(f"Structured output not available: {structured_error}, using manual parsing")
                response = self.llm.invoke(messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим JSON ответ и валидируем через Pydantic
            # Если PydanticOutputParser успешно распарсил - используем результат
            if result is None:
                # Ручной парсинг JSON
                # Улучшенный парсинг JSON
                json_text = None
                
                # Пытаемся извлечь JSON из разных форматов
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    # Проверяем, есть ли JSON внутри code block
                    parts = response_text.split("```")
                    for i in range(1, len(parts), 2):
                        candidate = parts[i].strip()
                        if candidate.startswith("{") and candidate.endswith("}"):
                            json_text = candidate
                            break
                elif "{" in response_text:
                    start = response_text.find("{")
                    end = response_text.rfind("}") + 1
                    if end > start:
                        json_text = response_text[start:end]
                
                # Если не нашли JSON - пытаемся извлечь из всего ответа
                if not json_text:
                    logger.warning(f"No JSON found in response, trying to extract from full text: {response_text[:200]}")
                    # Пытаемся найти JSON в любом месте ответа
                    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
                    if json_match:
                        json_text = json_match.group(0)
                    else:
                        # Если совсем не нашли - возвращаем ошибку
                        logger.error(f"Could not extract JSON from response: {response_text[:500]}")
                        raise ValueError(f"Не удалось извлечь JSON из ответа LLM. Ответ: {response_text[:200]}")
                
                # Валидируем через Pydantic модель с улучшенной обработкой ошибок
                try:
                    # Пытаемся исправить распространенные ошибки JSON
                    json_text_cleaned = json_text.strip()
                    
                    # Убираем лишние запятые в конце объектов/массивов
                    json_text_cleaned = re.sub(r',\s*}', '}', json_text_cleaned)
                    json_text_cleaned = re.sub(r',\s*]', ']', json_text_cleaned)
                    
                    # Исправляем одинарные кавычки на двойные (только если нет двойных)
                    if "'" in json_text_cleaned:
                        # Заменяем одинарные кавычки внутри строк на двойные, но аккуратно
                        # Сначала заменяем ключи и простые строковые значения
                        json_text_cleaned = re.sub(r"'(\w+)'", r'"\1"', json_text_cleaned)
                    
                    # Убираем комментарии (если есть)
                    json_text_cleaned = re.sub(r'//.*?$', '', json_text_cleaned, flags=re.MULTILINE)
                    json_text_cleaned = re.sub(r'/\*.*?\*/', '', json_text_cleaned, flags=re.DOTALL)
                    
                    # Парсим JSON
                    parsed_json = json.loads(json_text_cleaned)
                    
                    # Нормализуем doc_types: если это строка "all", преобразуем в None (будет означать все документы)
                    if "doc_types" in parsed_json:
                        doc_types_val = parsed_json["doc_types"]
                        if isinstance(doc_types_val, str):
                            if doc_types_val.lower() == "all":
                                parsed_json["doc_types"] = None  # None означает все документы
                            else:
                                parsed_json["doc_types"] = [doc_types_val]  # Одиночную строку преобразуем в список
                        elif doc_types_val is None:
                            parsed_json["doc_types"] = None
                        # Если уже список - оставляем как есть
                    
                    # Валидируем через Pydantic
                    result = TableDecision(**parsed_json)
                    logger.info(f"Successfully parsed and validated table detection result: needs_table={result.needs_table}")
                    
                except json.JSONDecodeError as json_error:
                    logger.error(f"Failed to parse table detection JSON: {json_error}")
                    logger.error(f"JSON text (first 500 chars): {json_text[:500]}")
                    logger.error(f"Full response (first 500 chars): {response_text[:500]}")
                    # Повторная попытка с более агрессивной очисткой
                    try:
                        # Убираем все не-JSON символы до первой { и после последней }
                        start_idx = json_text.find('{')
                        end_idx = json_text.rfind('}') + 1
                        if start_idx >= 0 and end_idx > start_idx:
                            json_text_cleaned = json_text[start_idx:end_idx]
                            parsed_json = json.loads(json_text_cleaned)
                            
                            # Нормализуем doc_types: если это строка "all", преобразуем в None
                            if "doc_types" in parsed_json:
                                doc_types_val = parsed_json["doc_types"]
                                if isinstance(doc_types_val, str):
                                    if doc_types_val.lower() == "all":
                                        parsed_json["doc_types"] = None
                                    else:
                                        parsed_json["doc_types"] = [doc_types_val]
                                elif doc_types_val is None:
                                    parsed_json["doc_types"] = None
                            
                            result = TableDecision(**parsed_json)
                            logger.info(f"Successfully parsed after aggressive cleaning")
                        else:
                            raise ValueError(f"Не удалось найти JSON объект в ответе")
                    except Exception as retry_error:
                        logger.error(f"Retry parsing also failed: {retry_error}")
                        # Если все попытки не удались - пробуем еще раз с LLM с более строгим промптом
                        raise ValueError(f"Критическая ошибка парсинга JSON: {str(json_error)}. Ответ LLM: {response_text[:300]}")
                        
                except Exception as parse_error:
                    parsed_json_str = 'N/A'
                    try:
                        if 'parsed_json' in locals():
                            parsed_json_str = str(list(parsed_json.keys()))
                    except:
                        pass
                    logger.error(f"Failed to validate table detection result: {parse_error}, parsed_json keys: {parsed_json_str}")
                    # Продолжаем с повторной попыткой через LLM - result остается None
                    result = None
            
            # Если result все еще None - пробуем повторную попытку через LLM
            if result is None:
                # Это обработается в блоке except ниже
                raise ValueError("Не удалось распарсить результат через PydanticOutputParser и ручной парсинг")
            
            # Валидация результата
            needs_table = result.needs_table
            needs_clarification = result.needs_clarification
            clarification_questions = result.clarification_questions or []
            
            # Если нужны уточнения - задаем вопросы через interrupt()
            if needs_table and needs_clarification and clarification_questions:
                if state and case_id and db:
                        # Получаем список доступных типов документов в деле
                        try:
                            from app.models.analysis import DocumentClassification
                            available_types = db.query(DocumentClassification.doc_type).filter(
                                DocumentClassification.case_id == case_id
                            ).distinct().all()
                            available_types_list = [t[0] for t in available_types]
                        except Exception as e:
                            logger.warning(f"Failed to get available doc types: {e}")
                            available_types_list = []
                        
                        # Импортируем interrupt
                        try:
                            from langgraph.graph import interrupt
                            
                            # Формируем payload для interrupt
                            payload = {
                                "type": "table_clarification",
                                "questions": clarification_questions,
                                "context": {
                                    "task": user_task,
                                    "table_name": result.table_name,
                                    "partial_columns": [col.dict() for col in (result.columns or [])]
                                },
                                "available_doc_types": available_types_list
                            }
                            
                            # Вызываем interrupt - выполнение приостановится, ждем ответа
                            user_answers = interrupt(payload)
                            
                            # user_answers придет из Command(resume=...) когда пользователь ответит
                            # Формат: {"doc_types": ["contract"], "columns_clarification": "..."}
                            
                            if user_answers:
                                # Обновляем doc_types из ответа пользователя
                                if "doc_types" in user_answers:
                                    result.doc_types = user_answers["doc_types"]
                                
                                # Обновляем user_task с уточнениями если нужно
                                if "columns_clarification" in user_answers:
                                    user_task = f"{user_task}. Уточнение: {user_answers['columns_clarification']}"
                                
                                logger.info(f"Received clarification answers: {user_answers}")
                        except ImportError:
                            # Если interrupt не доступен (нет LangGraph контекста), возвращаем информацию о необходимости уточнений
                            logger.warning("LangGraph interrupt not available, returning clarification info")
                            # В этом случае нужно вернуть информацию о том, что нужны уточнения
                            # Это будет обработано в plan_with_subtasks
                            return {
                                "needs_table": True,
                                "table_name": result.table_name or "Таблица",
                                "columns": [col.dict() if hasattr(col, 'dict') else col for col in (result.columns or [])],
                                "doc_types": result.doc_types,
                                "needs_clarification": True,
                                "clarification_questions": clarification_questions,
                                "reasoning": result.reasoning or "Требуется уточнение информации для создания таблицы"
                            }
                        except Exception as interrupt_error:
                            logger.error(f"Error during interrupt: {interrupt_error}", exc_info=True)
                            # При ошибке interrupt также возвращаем информацию о необходимости уточнений
                            return {
                                "needs_table": True,
                                "table_name": result.table_name or "Таблица",
                                "columns": [col.dict() if hasattr(col, 'dict') else col for col in (result.columns or [])],
                                "doc_types": result.doc_types,
                                "needs_clarification": True,
                                "clarification_questions": clarification_questions,
                                "reasoning": result.reasoning or "Требуется уточнение информации для создания таблицы"
                            }
            
            # Извлекаем типы документов
            doc_types = result.doc_types
            if doc_types == ["all"] or (not doc_types and needs_table):
                # Пытаемся извлечь из запроса
                extracted_types = extract_doc_types_from_query(user_task)
                doc_types = extracted_types if extracted_types else None
            
            if needs_table:
                # Валидация колонок (уже валидированы через Pydantic)
                validated_columns = []
                for col in (result.columns or []):
                    if not col.label or not col.question:
                        logger.warning(f"Skipping invalid column: {col}")
                        continue
                    
                    validated_columns.append({
                        "label": col.label,
                        "question": col.question,
                        "type": col.type or "text"
                    })
                
                if not validated_columns:
                    logger.warning("No valid columns found, setting needs_table=False")
                    return {
                        "needs_table": False,
                        "reasoning": "Не удалось определить валидные колонки"
                    }
                
                return {
                    "needs_table": True,
                    "table_name": result.table_name,
                    "columns": validated_columns,
                    "doc_types": doc_types,  # ДОБАВЛЕНО
                    "reasoning": result.reasoning or "Задача требует систематического сбора данных"
                }
            else:
                return {
                    "needs_table": False,
                    "reasoning": result.reasoning or "Задача не требует создания таблицы"
                }
        
        except Exception as e:
            logger.error(f"Error in table detection: {e}", exc_info=True)
            # Не используем fallback - выбрасываем ошибку, чтобы система знала о проблеме
            raise ValueError(f"Критическая ошибка при определении необходимости таблицы: {str(e)}")
    
    def _fallback_table_detection(self, user_task: str) -> Dict[str, Any]:
        """
        Fallback метод для определения таблиц на основе простых эвристик
        
        Args:
            user_task: Задача пользователя
            
        Returns:
            Dictionary с информацией о таблице
        """
        task_lower = user_task.lower()
        
        # КРИТИЧНО: Если пользователь явно просит таблицу - это всегда таблица
        explicit_table_keywords = [
            "создай таблицу", "сделай таблицу", "таблица с", "в виде таблицы",
            "таблицу с", "таблицу из"
        ]
        
        is_explicit_table_request = any(keyword in task_lower for keyword in explicit_table_keywords)
        
        # Простые эвристики для определения таблиц
        table_keywords = [
            "извлеки все", "найди все", "собери все",
            "для каждого", "для всех", "из каждого", "из всех",
            "покажи все", "представь в виде"
        ]
        
        # Проверяем наличие ключевых слов для таблиц
        has_table_keywords = any(keyword in task_lower for keyword in table_keywords)
        
        # Если явный запрос на таблицу - игнорируем проверку на агентные задачи
        if is_explicit_table_request:
            has_table_keywords = True
        
        # Проверяем, не является ли это задачей для стандартных агентов
        # НО: если явно просится таблица - это приоритет
        agent_keywords = [
            "найди противоречия", "проанализируй риски", "извлеки ключевые факты",
            "создай резюме"
        ]
        
        is_agent_task = any(keyword in task_lower for keyword in agent_keywords) and not is_explicit_table_request
        
        if has_table_keywords and not is_agent_task:
            # Пытаемся определить колонки из задачи (простая эвристика)
            columns = []
            table_name = "Данные из документов"
            
            # Специальная обработка для хронологии событий
            if "хронология" in task_lower or ("события" in task_lower and "таблица" in task_lower):
                table_name = "Хронология событий"
                columns.append({
                    "label": "Дата события",
                    "question": "Какая дата события упоминается в документе?",
                    "type": "date"
                })
                columns.append({
                    "label": "Событие",
                    "question": "Какое событие произошло в указанную дату?",
                    "type": "text"
                })
                columns.append({
                    "label": "Документ",
                    "question": "В каком документе упоминается это событие?",
                    "type": "text"
                })
            # Извлекаем упоминания данных
            elif "дата" in task_lower or "даты" in task_lower:
                if "подписания" in task_lower:
                    columns.append({
                        "label": "Дата подписания",
                        "question": "Какая дата подписания документа?",
                        "type": "date"
                    })
                else:
                    columns.append({
                        "label": "Дата",
                        "question": "Какая дата упоминается в документе?",
                        "type": "date"
                    })
            
            if "сумма" in task_lower or "суммы" in task_lower:
                columns.append({
                    "label": "Сумма",
                    "question": "Какая сумма упоминается в документе?",
                    "type": "number"
                })
            
            if "сторона" in task_lower or "стороны" in task_lower:
                columns.append({
                    "label": "Стороны",
                    "question": "Кто являются сторонами договора?",
                    "type": "text"
                })
            
            # Если колонки не определены, но явно просится таблица - создаем базовые колонки
            if not columns and is_explicit_table_request:
                # Для явного запроса создаем базовые колонки
                if "хронология" in task_lower or "события" in task_lower:
                    table_name = "Хронология событий"
                    columns = [
                        {
                            "label": "Дата события",
                            "question": "Какая дата события упоминается в документе?",
                            "type": "date"
                        },
                        {
                            "label": "Событие",
                            "question": "Какое событие произошло в указанную дату?",
                            "type": "text"
                        },
                        {
                            "label": "Документ",
                            "question": "В каком документе упоминается это событие?",
                            "type": "text"
                        }
                    ]
                else:
                    columns = [
                        {
                            "label": "Данные",
                            "question": "Какие данные нужно извлечь из документа?",
                            "type": "text"
                        }
                    ]
            
            if columns:
                return {
                    "needs_table": True,
                    "table_name": table_name,
                    "columns": columns,
                    "reasoning": "Задача содержит ключевые слова для таблицы" + (" (явный запрос)" if is_explicit_table_request else "")
                }
        
        # По умолчанию - таблица не нужна
        return {
            "needs_table": False,
            "reasoning": "Задача не соответствует критериям для создания таблицы"
        }
    
    def plan_with_subtasks(
        self,
        user_task: str,
        case_id: str,
        available_documents: Optional[List[str]] = None,
        num_documents: Optional[int] = None,
        state: Optional[AnalysisState] = None,
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Создает план с разбивкой на подзадачи
        
        Args:
            user_task: Задача пользователя на естественном языке
            case_id: Идентификатор дела
            available_documents: Список доступных документов
            num_documents: Количество документов в деле
            state: Analysis state (для interrupt, опционально)
            db: Database session (для получения доступных типов документов, опционально)
            
        Returns:
            Dictionary с планом, включающим подзадачи:
            {
                "main_task": "основная задача",
                "subtasks": [
                    {
                        "subtask_id": "subtask_1",
                        "description": "описание подзадачи",
                        "agent_type": "timeline",
                        "dependencies": [],
                        "estimated_time": "5-10 мин",
                        "reasoning": "почему нужна эта подзадача"
                    }
                ],
                "dependencies": {"subtask_2": ["subtask_1"]},
                "estimated_time": "20-35 мин",
                "confidence": 0.9
            }
        """
        try:
            logger.info(f"Advanced planning: Analyzing task complexity for: {user_task[:100]}...")
            
            # 0. Загружаем контекст предыдущих планов для learning
            previous_plans_context = None
            if self.context_manager:
                try:
                    previous_plans_context = self.context_manager.load_context(
                        case_id=case_id,
                        analysis_type="planning"
                    )
                    if previous_plans_context:
                        logger.info("Loaded previous planning context for learning")
                        
                        # Use SummarizationMiddleware if context is too large
                        try:
                            from app.services.langchain_agents.summarization_middleware import SummarizationMiddleware
                            summarizer = SummarizationMiddleware(llm=self.llm)
                            
                            # Summarize context if it's a string
                            if isinstance(previous_plans_context, str):
                                previous_plans_context = summarizer.summarize_if_needed(
                                    previous_plans_context,
                                    context="Previous planning context"
                                )
                            elif isinstance(previous_plans_context, dict):
                                # Summarize large text fields in dict
                                previous_plans_context = summarizer.summarize_state(
                                    previous_plans_context,
                                    fields=["plan", "user_task", "context"]
                                )
                        except Exception as sum_error:
                            logger.debug(f"SummarizationMiddleware not available: {sum_error}")
                except Exception as ctx_error:
                    logger.warning(f"Failed to load previous planning context: {ctx_error}")
            
            # 1. Анализ сложности задачи
            task_analysis = self._analyze_task_complexity(user_task, case_id, previous_plans_context)
            
            # 1.5. Определение необходимости таблицы
            # Передаем state и db если доступны (для interrupt)
            table_detection_result = None
            try:
                table_detection_result = self._determine_table_columns_from_task(
                    user_task=user_task,
                    case_id=case_id,
                    state=state,
                    db=db
                )
                if table_detection_result:
                    needs_table = table_detection_result.get("needs_table", False)
                    logger.info(f"Table detection result: needs_table={needs_table}, table_name={table_detection_result.get('table_name')}, columns_count={len(table_detection_result.get('columns', []))}")
                else:
                    needs_table = False
                    logger.warning("Table detection returned None")
            except Exception as table_detection_error:
                logger.error(f"Error in table detection, but continuing: {table_detection_error}", exc_info=True)
                # Если ошибка при определении таблицы - проверяем явные ключевые слова
                task_lower = user_task.lower()
                explicit_table_keywords = ["создай таблицу", "сделай таблицу", "таблица с"]
                is_explicit = any(kw in task_lower for kw in explicit_table_keywords)
                
                if is_explicit:
                    # Если явный запрос на таблицу - создаем базовую таблицу
                    logger.warning(f"Table detection failed but explicit table request detected, creating default table")
                    if "хронология" in task_lower or "события" in task_lower:
                        table_detection_result = {
                            "needs_table": True,
                            "table_name": "Хронология событий",
                            "columns": [
                                {"label": "Дата события", "question": "Какая дата события упоминается в документе?", "type": "date"},
                                {"label": "Событие", "question": "Какое событие произошло в указанную дату?", "type": "text"},
                                {"label": "Документ", "question": "В каком документе упоминается это событие?", "type": "text"}
                            ],
                            "doc_types": None,
                            "reasoning": "Явный запрос на таблицу с хронологией (fallback из-за ошибки парсинга)"
                        }
                    else:
                        # Пытаемся извлечь колонки из задачи пользователя
                        columns = []
                        task_lower_for_cols = task_lower
                        
                        # Определяем колонки на основе ключевых слов
                        if "судья" in task_lower_for_cols or "судьи" in task_lower_for_cols:
                            columns.append({"label": "Фамилия судьи", "question": "Какая фамилия судьи указана в документе?", "type": "text"})
                        if "дата" in task_lower_for_cols or "дату" in task_lower_for_cols:
                            columns.append({"label": "Дата", "question": "Какая дата указана в документе?", "type": "date"})
                        if "суд" in task_lower_for_cols or "суда" in task_lower_for_cols:
                            columns.append({"label": "Название суда", "question": "Какое название суда указано в документе?", "type": "text"})
                        if "тип документа" in task_lower_for_cols or "тип" in task_lower_for_cols:
                            columns.append({"label": "Тип документа", "question": "Каков тип документа?", "type": "text"})
                        if "описание" in task_lower_for_cols:
                            columns.append({"label": "Описание", "question": "Каково описание документа?", "type": "text"})
                        
                        # Если не нашли колонок - используем дефолтную
                        if not columns:
                            columns = [{"label": "Данные", "question": "Какие данные нужно извлечь из документа?", "type": "text"}]
                        
                        table_detection_result = {
                            "needs_table": True,
                            "table_name": "Данные из документов",
                            "columns": columns,
                            "doc_types": None,
                            "reasoning": "Явный запрос на таблицу (fallback из-за ошибки парсинга)"
                        }
                    needs_table = True
                else:
                    table_detection_result = {"needs_table": False, "reasoning": f"Ошибка определения таблицы: {str(table_detection_error)}"}
                    needs_table = False
            
            # 2. Если задача простая - используем базовый планировщик
            if task_analysis.get("complexity") == "simple":
                logger.info("Task is simple, using base planning agent")
                base_plan = self.base_planning_agent.plan_analysis(
                    user_task=user_task,
                    case_id=case_id,
                    available_documents=available_documents,
                    num_documents=num_documents
                )
                # Преобразуем в формат с подзадачами
                result_plan = self._convert_to_subtasks_format(base_plan, user_task)
                
                # Добавляем таблицы, если нужно
                if needs_table and table_detection_result:
                    table_spec = {
                        "table_name": table_detection_result.get("table_name", "Данные из документов"),
                        "columns": table_detection_result.get("columns", [])
                    }
                    # Добавляем doc_types если указаны
                    doc_types = table_detection_result.get("doc_types")
                    if doc_types:
                        table_spec["doc_types"] = doc_types
                    result_plan["tables_to_create"] = [table_spec]
                    
                    # Передаем needs_clarification и clarification_questions в план, если они есть
                    if table_detection_result.get("needs_clarification"):
                        result_plan["needs_clarification"] = True
                        result_plan["clarification_questions"] = table_detection_result.get("clarification_questions", [])
                    
                    # Улучшаем reasoning, добавляя информацию о таблице на естественном языке
                    table_reasoning = self._format_table_info_for_plan(table_detection_result)
                    if result_plan.get("reasoning"):
                        result_plan["reasoning"] += f"\n\n{table_reasoning}"
                    else:
                        result_plan["reasoning"] = table_reasoning
                    
                    logger.info(f"Table creation added to simple plan: {table_detection_result.get('table_name')}")
                
                return result_plan
            
            # 3. Разбивка на подзадачи для сложных задач
            logger.info(f"Task is complex ({task_analysis.get('complexity')}), breaking into subtasks")
            subtasks = self._break_into_subtasks(user_task, task_analysis, case_id)
            
            # 4. Создание плана для каждой подзадачи
            plan = {
                "main_task": user_task,
                "task_analysis": task_analysis,
                "subtasks": [],
                "dependencies": {},
                "estimated_time": "0 мин",
                "confidence": 0.8
            }
            
            # Добавляем таблицы в план, если нужно
            if needs_table:
                table_spec = {
                    "table_name": table_detection_result.get("table_name", "Данные из документов"),
                    "columns": table_detection_result.get("columns", [])
                }
                # Добавляем doc_types если указаны
                doc_types = table_detection_result.get("doc_types")
                if doc_types:
                    table_spec["doc_types"] = doc_types
                plan["tables_to_create"] = [table_spec]
                
                # Передаем needs_clarification и clarification_questions в план, если они есть
                if table_detection_result.get("needs_clarification"):
                    plan["needs_clarification"] = True
                    plan["clarification_questions"] = table_detection_result.get("clarification_questions", [])
                
                # Улучшаем reasoning, добавляя информацию о таблице на естественном языке
                table_reasoning = self._format_table_info_for_plan(table_detection_result)
                if plan.get("reasoning"):
                    plan["reasoning"] += f"\n\n{table_reasoning}"
                else:
                    plan["reasoning"] = table_reasoning
                
                logger.info(f"Table creation added to plan: {table_detection_result.get('table_name')} with {len(table_detection_result.get('columns', []))} columns")
            
            total_time_minutes = 0
            for subtask in subtasks:
                subtask_plan = self._plan_subtask(subtask, case_id, available_documents, num_documents)
                plan["subtasks"].append(subtask_plan)
                
                # Учитываем зависимости
                if subtask_plan.get("dependencies"):
                    plan["dependencies"][subtask_plan["subtask_id"]] = subtask_plan["dependencies"]
                
                # Суммируем время
                estimated_time = subtask_plan.get("estimated_time", "5-10 мин")
                time_minutes = self._parse_time_estimate(estimated_time)
                total_time_minutes += time_minutes
            
            # Форматируем общее время
            plan["estimated_time"] = self._format_time_estimate(total_time_minutes)
            
            # 5. Извлекаем analysis_types из подзадач для совместимости
            analysis_types = []
            for subtask in plan["subtasks"]:
                agent_type = subtask.get("agent_type")
                if agent_type and agent_type not in analysis_types:
                    analysis_types.append(agent_type)
            
            plan["analysis_types"] = analysis_types
            
            # 6. Валидация плана
            validation_result = self.validator.validate_plan(plan, case_id)
            if validation_result.issues:
                logger.warning(f"Plan validation issues: {validation_result.issues}")
                plan["validation_issues"] = validation_result.issues
            
            if validation_result.optimized_plan:
                plan = validation_result.optimized_plan
                logger.info("Plan optimized by validator")
            
            # 7. Сохраняем план через TodoListMiddleware (Deep Agents pattern)
            try:
                from app.services.langchain_agents.todo_middleware import TodoListMiddleware
                
                # Convert subtasks to todos format
                todos = []
                for subtask in plan.get("subtasks", []):
                    todos.append({
                        "id": subtask.get("subtask_id", f"todo_{len(todos) + 1}"),
                        "description": subtask.get("description", ""),
                        "status": "pending",
                        "dependencies": subtask.get("dependencies", []),
                        "agent_type": subtask.get("agent_type"),
                        "estimated_time": subtask.get("estimated_time"),
                        "priority": subtask.get("priority", 1)
                    })
                
                # Create middleware and save todos
                todo_middleware = TodoListMiddleware()
                todo_middleware.write_todos(todos)
                
                # Add todos to plan for access by agents
                plan["todos"] = todo_middleware.read_todos()
                plan["todo_progress"] = todo_middleware.get_progress()
                
                logger.info(f"TodoList: Saved {len(todos)} todos for case {case_id}")
            except Exception as todo_error:
                logger.debug(f"TodoListMiddleware not available: {todo_error}")
            
            # 8. Сохраняем план в ContextManager для future learning
            if self.context_manager:
                try:
                    self.context_manager.save_context(
                        case_id=case_id,
                        analysis_type="planning",
                        context={
                            "user_task": user_task,
                            "plan": plan,
                            "task_analysis": task_analysis,
                            "validation_result": {
                                "is_valid": validation_result.is_valid,
                                "issues": validation_result.issues
                            }
                        }
                    )
                    logger.info("Saved planning context for future learning")
                except Exception as ctx_error:
                    logger.warning(f"Failed to save planning context: {ctx_error}")
            
            logger.info(
                f"Advanced planning completed: {len(plan['subtasks'])} subtasks, "
                f"estimated time: {plan['estimated_time']}, confidence: {plan.get('confidence', 0.8):.2f}"
            )
            
            return plan
            
        except Exception as e:
            logger.error(f"Error in advanced planning: {e}", exc_info=True)
            # Fallback на базовый планировщик
            logger.warning("Falling back to base planning agent")
            
            # Определяем таблицы даже в fallback
            table_detection_result = self._determine_table_columns_from_task(
                user_task=user_task,
                case_id=case_id
            )
            needs_table = table_detection_result.get("needs_table", False)
            
            base_plan = self.base_planning_agent.plan_analysis(
                user_task=user_task,
                case_id=case_id,
                available_documents=available_documents,
                num_documents=num_documents
            )
            result_plan = self._convert_to_subtasks_format(base_plan, user_task)
            
            # Добавляем таблицы, если нужно
            if needs_table:
                table_spec = {
                    "table_name": table_detection_result.get("table_name", "Данные из документов"),
                    "columns": table_detection_result.get("columns", [])
                }
                # Добавляем doc_types если указаны
                doc_types = table_detection_result.get("doc_types")
                if doc_types:
                    table_spec["doc_types"] = doc_types
                result_plan["tables_to_create"] = [table_spec]
                logger.info(f"Table creation added to fallback plan: {table_detection_result.get('table_name')}")
            
            return result_plan
    
    def _analyze_task_complexity(
        self,
        user_task: str,
        case_id: str,
        previous_plans_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Анализирует сложность задачи
        
        Returns:
            {
                "complexity": "simple" | "medium" | "complex",
                "reasoning": "объяснение",
                "suggested_approach": "approach_name"
            }
        """
        try:
            # Используем контекст предыдущих планов для learning
            learning_context = ""
            if previous_plans_context:
                prev_plan = previous_plans_context.get("plan", {})
                if prev_plan:
                    prev_complexity = prev_plan.get("task_analysis", {}).get("complexity", "")
                    prev_subtasks_count = len(prev_plan.get("subtasks", []))
                    learning_context = f"""

Контекст из предыдущих планов:
- Предыдущая сложность: {prev_complexity}
- Количество подзадач: {prev_subtasks_count}
- Используй похожие подходы для похожих задач"""
            
            prompt = f"""Ты эксперт по анализу юридических задач.

Задача пользователя: {user_task}
{learning_context}

Определи сложность задачи:
- simple: одна конкретная задача (например, "извлеки даты")
- medium: несколько связанных задач (например, "найди риски и противоречия")
- complex: многошаговая задача с зависимостями (например, "составь полный анализ дела с хронологией, рисками и связями между людьми")

Верни JSON:
{{
    "complexity": "simple|medium|complex",
    "reasoning": "объяснение почему такая сложность",
    "suggested_approach": "single_agent|multi_agent|subtasks"
}}"""
            
            messages = [
                SystemMessage(content="Ты эксперт по анализу сложности юридических задач."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим JSON
            try:
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()
                else:
                    json_text = response_text
                
                analysis = json.loads(json_text)
                return analysis
            except json.JSONDecodeError:
                # Fallback: определяем сложность по ключевым словам
                task_lower = user_task.lower()
                if any(word in task_lower for word in ["полный", "комплексный", "все", "составь", "создай"]):
                    return {"complexity": "complex", "reasoning": "Задача требует множественных анализов", "suggested_approach": "subtasks"}
                elif any(word in task_lower for word in ["и", "также", "плюс", "а также"]):
                    return {"complexity": "medium", "reasoning": "Задача включает несколько аспектов", "suggested_approach": "multi_agent"}
                else:
                    return {"complexity": "simple", "reasoning": "Простая конкретная задача", "suggested_approach": "single_agent"}
        
        except Exception as e:
            logger.warning(f"Error analyzing task complexity: {e}, defaulting to medium")
            return {"complexity": "medium", "reasoning": "Не удалось определить сложность", "suggested_approach": "multi_agent"}
    
    def _break_into_subtasks(
        self,
        user_task: str,
        task_analysis: Dict[str, Any],
        case_id: str
    ) -> List[Dict[str, Any]]:
        """
        Разбивает сложную задачу на подзадачи
        
        Returns:
            List of subtask dictionaries
        """
        try:
            # Используем LLM для разбивки на подзадачи
            prompt = f"""Ты эксперт по планированию юридических задач.

Задача пользователя: {user_task}

Анализ сложности: {task_analysis.get('complexity')} - {task_analysis.get('reasoning')}

Разбей задачу на подзадачи. Каждая подзадача должна:
1. Быть конкретной и выполнимой
2. Иметь четкий результат
3. Указывать тип агента для выполнения

Доступные типы агентов:
- timeline: извлечение дат и событий
- key_facts: извлечение ключевых фактов
- entity_extraction: извлечение сущностей (люди, организации)
- discrepancy: поиск противоречий
- risk: анализ рисков (требует discrepancy)
- relationship: построение графа связей (требует entity_extraction)
- summary: генерация резюме (требует key_facts)
- document_classifier: классификация документов

Верни JSON массив подзадач:
[
    {{
        "subtask_id": "subtask_1",
        "description": "описание подзадачи",
        "agent_type": "timeline",
        "dependencies": [],
        "estimated_time": "5-10 мин",
        "reasoning": "почему нужна эта подзадача"
    }}
]

ВАЖНО: Учитывай зависимости между агентами!"""
            
            messages = [
                SystemMessage(content="Ты эксперт по разбивке сложных юридических задач на подзадачи."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим JSON
            try:
                if "```json" in response_text:
                    json_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_text = response_text.split("```")[1].split("```")[0].strip()
                elif "[" in response_text:
                    start = response_text.find("[")
                    end = response_text.rfind("]") + 1
                    json_text = response_text[start:end]
                else:
                    json_text = response_text
                
                subtasks = json.loads(json_text)
                
                # Валидация подзадач
                validated_subtasks = []
                for i, subtask in enumerate(subtasks, 1):
                    if not isinstance(subtask, dict):
                        continue
                    
                    # Обеспечиваем наличие обязательных полей
                    validated_subtask = {
                        "subtask_id": subtask.get("subtask_id", f"subtask_{i}"),
                        "description": subtask.get("description", ""),
                        "agent_type": subtask.get("agent_type", ""),
                        "dependencies": subtask.get("dependencies", []),
                        "estimated_time": subtask.get("estimated_time", "5-10 мин"),
                        "reasoning": subtask.get("reasoning", "")
                    }
                    
                    # Проверяем, что agent_type валидный
                    valid_agents = ["timeline", "key_facts", "entity_extraction", "discrepancy", 
                                   "risk", "relationship", "summary", "document_classifier", 
                                   "privilege_check"]
                    if validated_subtask["agent_type"] not in valid_agents:
                        logger.warning(f"Invalid agent_type: {validated_subtask['agent_type']}, skipping")
                        continue
                    
                    validated_subtasks.append(validated_subtask)
                
                logger.info(f"Broken down into {len(validated_subtasks)} subtasks")
                return validated_subtasks
                
            except json.JSONDecodeError as e:
                logger.warning(f"Error parsing subtasks JSON: {e}, using fallback")
                return self._fallback_subtasks(user_task)
        
        except Exception as e:
            logger.error(f"Error breaking into subtasks: {e}", exc_info=True)
            return self._fallback_subtasks(user_task)
    
    def _fallback_subtasks(self, user_task: str) -> List[Dict[str, Any]]:
        """Fallback метод для создания подзадач"""
        task_lower = user_task.lower()
        subtasks = []
        
        # Определяем подзадачи по ключевым словам
        if "хронология" in task_lower or "даты" in task_lower or "события" in task_lower:
            subtasks.append({
                "subtask_id": "subtask_1",
                "description": "Извлечь хронологию событий",
                "agent_type": "timeline",
                "dependencies": [],
                "estimated_time": "5-10 мин",
                "reasoning": "Пользователь запросил хронологию"
            })
        
        if "люди" in task_lower or "связи" in task_lower or "участники" in task_lower:
            subtasks.append({
                "subtask_id": "subtask_2",
                "description": "Извлечь сущности и связи",
                "agent_type": "entity_extraction",
                "dependencies": [],
                "estimated_time": "10-15 мин",
                "reasoning": "Пользователь запросил информацию о людях"
            })
            
            subtasks.append({
                "subtask_id": "subtask_3",
                "description": "Построить граф связей",
                "agent_type": "relationship",
                "dependencies": ["subtask_2"],
                "estimated_time": "5-10 мин",
                "reasoning": "Требуется для визуализации связей между людьми"
            })
        
        if "риски" in task_lower or "риск" in task_lower:
            subtasks.append({
                "subtask_id": "subtask_4",
                "description": "Найти противоречия",
                "agent_type": "discrepancy",
                "dependencies": [],
                "estimated_time": "10-15 мин",
                "reasoning": "Необходимо для анализа рисков"
            })
            
            subtasks.append({
                "subtask_id": "subtask_5",
                "description": "Проанализировать риски",
                "agent_type": "risk",
                "dependencies": ["subtask_4"],
                "estimated_time": "5-10 мин",
                "reasoning": "Анализ рисков требует найденные противоречия"
            })
        
        # Если ничего не найдено - используем общий план
        if not subtasks:
            subtasks = [
                {
                    "subtask_id": "subtask_1",
                    "description": "Извлечь ключевые факты",
                    "agent_type": "key_facts",
                    "dependencies": [],
                    "estimated_time": "10-15 мин",
                    "reasoning": "Базовый анализ дела"
                }
            ]
        
        return subtasks
    
    def _plan_subtask(
        self,
        subtask: Dict[str, Any],
        case_id: str,
        available_documents: Optional[List[str]] = None,
        num_documents: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Создает детальный план для подзадачи
        
        Args:
            subtask: Dictionary с информацией о подзадаче
            case_id: Case identifier
            available_documents: Available documents
            num_documents: Number of documents
            
        Returns:
            Enhanced subtask dictionary with plan details
        """
        # Используем базовый планировщик для создания детального плана
        agent_type = subtask.get("agent_type")
        description = subtask.get("description", "")
        
        # Создаем задачу для базового планировщика
        task_for_agent = f"{description}. Используй агент {agent_type}."
        
        try:
            # Получаем базовый план для этой подзадачи
            base_plan = self.base_planning_agent.plan_analysis(
                user_task=task_for_agent,
                case_id=case_id,
                available_documents=available_documents,
                num_documents=num_documents
            )
            
            # Объединяем с информацией о подзадаче
            enhanced_subtask = subtask.copy()
            enhanced_subtask.update({
                "plan_details": base_plan,
                "steps": base_plan.get("steps", []),
                "tools": base_plan.get("tools", []),
                "sources": base_plan.get("sources", ["vault"])
            })
            
            return enhanced_subtask
            
        except Exception as e:
            logger.warning(f"Error planning subtask {subtask.get('subtask_id')}: {e}")
            return subtask
    
    def _convert_to_subtasks_format(
        self,
        base_plan: Dict[str, Any],
        user_task: str
    ) -> Dict[str, Any]:
        """Преобразует базовый план в формат с подзадачами"""
        analysis_types = base_plan.get("analysis_types", [])
        steps = base_plan.get("steps", [])
        
        subtasks = []
        for i, analysis_type in enumerate(analysis_types, 1):
            # Находим соответствующий step если есть
            step = next((s for s in steps if s.get("agent_name") == analysis_type), None)
            
            # Используем planned_reasoning если доступен, иначе reasoning
            step_reasoning = None
            if step:
                step_reasoning = step.get("planned_reasoning") or step.get("reasoning")
            
            subtask = {
                "subtask_id": f"subtask_{i}",
                "description": step.get("description", f"Выполнить анализ {analysis_type}") if step else f"Выполнить {analysis_type}",
                "agent_type": analysis_type,
                "dependencies": step.get("dependencies", []) if step else [],
                "estimated_time": step.get("estimated_time", "5-10 мин") if step else "5-10 мин",
                "reasoning": step_reasoning or base_plan.get("reasoning", "") if step else base_plan.get("reasoning", "")
            }
            
            if step:
                # Включаем все новые поля в plan_details
                subtask["plan_details"] = step
                # Также добавляем planned_reasoning и planned_actions отдельно для удобства
                if step.get("planned_reasoning"):
                    subtask["planned_reasoning"] = step.get("planned_reasoning")
                if step.get("planned_actions"):
                    subtask["planned_actions"] = step.get("planned_actions")
            
            subtasks.append(subtask)
        
        return {
            "main_task": user_task,
            "subtasks": subtasks,
            "dependencies": base_plan.get("dependencies", {}),
            "estimated_time": base_plan.get("estimated_execution_time", "неизвестно"),
            "confidence": base_plan.get("confidence", 0.8),
            "analysis_types": analysis_types,
            "reasoning": base_plan.get("reasoning", "")
        }
    
    def _parse_time_estimate(self, time_str: str) -> int:
        """Парсит строку времени в минуты"""
        try:
            # Формат: "5-10 мин" или "10 мин"
            time_str = time_str.lower().replace("мин", "").replace("min", "").strip()
            
            if "-" in time_str:
                # Берем среднее значение
                parts = time_str.split("-")
                min_time = int(parts[0].strip())
                max_time = int(parts[1].strip())
                return (min_time + max_time) // 2
            else:
                return int(time_str.strip())
        except:
            return 10  # Default
    
    def _format_time_estimate(self, minutes: int) -> str:
        """Форматирует минуты в строку"""
        if minutes < 60:
            return f"{minutes} мин"
        else:
            hours = minutes // 60
            mins = minutes % 60
            if mins == 0:
                return f"{hours} ч"
            else:
                return f"{hours} ч {mins} мин"
    
    def _format_table_info_for_plan(self, table_detection_result: Dict[str, Any]) -> str:
        """
        Форматирует информацию о таблице на естественном языке для включения в reasoning плана
        
        Args:
            table_detection_result: Результат определения таблицы
            
        Returns:
            Текст на естественном языке с описанием таблицы
        """
        table_name = table_detection_result.get("table_name", "Таблица")
        columns = table_detection_result.get("columns", [])
        doc_types = table_detection_result.get("doc_types")
        
        text = f"**Создание таблицы:** {table_name}\n"
        
        if columns:
            text += f"Таблица будет содержать {len(columns)} колонок:\n"
            for idx, col in enumerate(columns, 1):
                col_label = col.get("label", f"Колонка {idx}")
                col_type = col.get("type", "text")
                type_names = {
                    "text": "текст",
                    "date": "дата",
                    "number": "число",
                    "boolean": "да/нет"
                }
                type_name = type_names.get(col_type, col_type)
                text += f"  {idx}. {col_label} ({type_name})\n"
        
        if doc_types:
            if isinstance(doc_types, list) and len(doc_types) > 0:
                if "all" not in doc_types:
                    doc_type_names = {
                        "contract": "договоры",
                        "statement_of_claim": "исковые заявления",
                        "court_decision": "решения суда",
                        "correspondence": "переписка",
                        "motion": "ходатайства",
                        "appeal": "апелляции"
                    }
                    doc_names = [doc_type_names.get(dt, dt) for dt in doc_types]
                    text += f"Данные будут извлечены из документов типа: {', '.join(doc_names)}.\n"
                else:
                    text += "Данные будут извлечены из всех документов дела.\n"
        
        return text

