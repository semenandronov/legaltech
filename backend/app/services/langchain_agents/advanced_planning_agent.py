"""Advanced Planning Agent with subtask support (inspired by DeepAgents)"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.planning_validator import PlanningValidator
from app.services.context_manager import ContextManager
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage, SystemMessage
import logging
import json

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
    
    def plan_with_subtasks(
        self,
        user_task: str,
        case_id: str,
        available_documents: Optional[List[str]] = None,
        num_documents: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Создает план с разбивкой на подзадачи
        
        Args:
            user_task: Задача пользователя на естественном языке
            case_id: Идентификатор дела
            available_documents: Список доступных документов
            num_documents: Количество документов в деле
            
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
                except Exception as ctx_error:
                    logger.warning(f"Failed to load previous planning context: {ctx_error}")
            
            # 1. Анализ сложности задачи
            task_analysis = self._analyze_task_complexity(user_task, case_id, previous_plans_context)
            
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
                return self._convert_to_subtasks_format(base_plan, user_task)
            
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
            
            # 7. Сохраняем план в ContextManager для future learning
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
            base_plan = self.base_planning_agent.plan_analysis(
                user_task=user_task,
                case_id=case_id,
                available_documents=available_documents,
                num_documents=num_documents
            )
            return self._convert_to_subtasks_format(base_plan, user_task)
    
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
            
            subtask = {
                "subtask_id": f"subtask_{i}",
                "description": step.get("description", f"Выполнить анализ {analysis_type}") if step else f"Выполнить {analysis_type}",
                "agent_type": analysis_type,
                "dependencies": step.get("dependencies", []) if step else [],
                "estimated_time": step.get("estimated_time", "5-10 мин") if step else "5-10 мин",
                "reasoning": step.get("reasoning", base_plan.get("reasoning", "")) if step else base_plan.get("reasoning", "")
            }
            
            if step:
                subtask["plan_details"] = step
            
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

