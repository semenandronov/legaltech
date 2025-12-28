"""SubAgent Manager for dynamic subagent creation (inspired by DeepAgents)"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)


class SubAgent:
    """Represents a subagent for a specific subtask"""
    
    def __init__(
        self,
        subtask_id: str,
        agent_type: str,
        task: str,
        context: Dict[str, Any],
        agent_instance: Any
    ):
        """Initialize subagent
        
        Args:
            subtask_id: Unique identifier for subtask
            agent_type: Type of agent (timeline, key_facts, etc.)
            task: Task description
            context: Context dictionary
            agent_instance: LangChain agent instance
        """
        self.subtask_id = subtask_id
        self.agent_type = agent_type
        self.task = task
        self.context = context
        self.agent_instance = agent_instance
        self.status = "created"  # created, running, completed, failed
        self.result = None
        self.error = None
    
    def run(self, state: Dict[str, Any], max_retries: int = 2) -> Dict[str, Any]:
        """Execute subagent task with retry mechanism
        
        Args:
            state: Current analysis state
            max_retries: Maximum number of retry attempts
            
        Returns:
            Result dictionary
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                self.status = "running"
                if attempt > 0:
                    logger.info(f"SubAgent {self.subtask_id} retry attempt {attempt}/{max_retries}")
                else:
                    logger.info(f"SubAgent {self.subtask_id} ({self.agent_type}) starting execution")
                
                # Execute agent with context
                result = self.agent_instance.invoke({
                    "input": self.task,
                    "case_id": state.get("case_id"),
                    "context": self.context,
                    **state
                })
                
                self.result = result
                self.status = "completed"
                logger.info(f"SubAgent {self.subtask_id} completed successfully")
                
                return result
                
            except Exception as e:
                last_error = e
                self.status = "failed"
                self.error = str(e)
                logger.warning(f"SubAgent {self.subtask_id} attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries:
                    # Wait before retry (exponential backoff)
                    import time
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying SubAgent {self.subtask_id} after {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"SubAgent {self.subtask_id} failed after {max_retries + 1} attempts: {e}", exc_info=True)
        
        # All retries failed
        raise last_error


class SubAgentManager:
    """Управление под-агентами для динамических задач (вдохновлено DeepAgents)"""
    
    def __init__(
        self,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None
    ):
        """Initialize subagent manager
        
        Args:
            rag_service: Optional RAG service
            document_processor: Optional document processor
        """
        self.rag_service = rag_service
        self.document_processor = document_processor
        self.subagents: Dict[str, SubAgent] = {}
        
        try:
            self.llm = create_llm(temperature=0.1)
            logger.info("✅ SubAgent Manager initialized")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise
    
    def spawn_subagent(
        self,
        subtask: Dict[str, Any],
        context: Dict[str, Any],
        state: Dict[str, Any]
    ) -> SubAgent:
        """
        Создает под-агента для конкретной подзадачи
        
        Args:
            subtask: Dictionary with subtask information:
                - subtask_id: Unique identifier
                - agent_type: Type of agent
                - description: Task description
                - dependencies: List of dependency subtask IDs
            context: Context dictionary with previous results
            state: Current analysis state
            
        Returns:
            SubAgent instance
        """
        subtask_id = subtask.get("subtask_id")
        agent_type = subtask.get("agent_type", "key_facts")
        description = subtask.get("description", "")
        dependencies = subtask.get("dependencies", [])
        
        logger.info(f"Spawning subagent {subtask_id} of type {agent_type}")
        
        # Определяем тип агента если auto
        if agent_type == "auto":
            agent_type = self._determine_agent_type(description)
        
        # Создаем специализированного агента
        try:
            agent_instance = create_legal_agent(
                agent_type=agent_type,
                rag_service=self.rag_service,
                document_processor=self.document_processor
            )
            
            # Создаем SubAgent
            subagent = SubAgent(
                subtask_id=subtask_id,
                agent_type=agent_type,
                task=description,
                context={
                    **context,
                    "dependencies": dependencies,
                    "previous_results": self._get_dependency_results(dependencies)
                },
                agent_instance=agent_instance
            )
            
            # Сохраняем в словарь
            self.subagents[subtask_id] = subagent
            
            logger.info(f"SubAgent {subtask_id} spawned successfully")
            return subagent
            
        except Exception as e:
            logger.error(f"Error spawning subagent {subtask_id}: {e}", exc_info=True)
            raise
    
    def _determine_agent_type(self, task_description: str) -> str:
        """Определяет тип агента на основе описания задачи"""
        task_lower = task_description.lower()
        
        # Маппинг ключевых слов на типы агентов
        if any(word in task_lower for word in ["хронология", "даты", "события", "timeline"]):
            return "timeline"
        elif any(word in task_lower for word in ["люди", "сущности", "entities", "участники"]):
            return "entity_extraction"
        elif any(word in task_lower for word in ["связи", "relationship", "граф"]):
            return "relationship"
        elif any(word in task_lower for word in ["противоречия", "discrepancy", "несоответствия"]):
            return "discrepancy"
        elif any(word in task_lower for word in ["риски", "risk", "опасности"]):
            return "risk"
        elif any(word in task_lower for word in ["факты", "key_facts", "ключевые"]):
            return "key_facts"
        elif any(word in task_lower for word in ["резюме", "summary", "краткое"]):
            return "summary"
        else:
            return "key_facts"  # Default
    
    def _get_dependency_results(self, dependencies: List[str]) -> Dict[str, Any]:
        """Получает результаты зависимых подзадач"""
        results = {}
        
        for dep_id in dependencies:
            if dep_id in self.subagents:
                subagent = self.subagents[dep_id]
                if subagent.status == "completed" and subagent.result:
                    results[dep_id] = subagent.result
        
        return results
    
    def reconcile_results(
        self,
        subagent_results: List[Dict[str, Any]],
        main_task: str
    ) -> Dict[str, Any]:
        """
        Объединяет результаты под-агентов
        
        Args:
            subagent_results: List of result dictionaries from subagents
            main_task: Main task description
            
        Returns:
            Reconciled result dictionary
        """
        try:
            logger.info(f"Reconciling {len(subagent_results)} subagent results")
            
            # Объединяем результаты
            reconciled = {
                "main_task": main_task,
                "subtask_results": {},
                "combined_data": {},
                "summary": ""
            }
            
            # Собираем результаты по типам
            for result in subagent_results:
                if not isinstance(result, dict):
                    continue
                
                subtask_id = result.get("subtask_id", "unknown")
                agent_type = result.get("agent_type", "unknown")
                data = result.get("data", result.get("result", {}))
                
                reconciled["subtask_results"][subtask_id] = {
                    "agent_type": agent_type,
                    "data": data
                }
                
                # Объединяем данные по типам
                if agent_type not in reconciled["combined_data"]:
                    reconciled["combined_data"][agent_type] = []
                
                if isinstance(data, list):
                    reconciled["combined_data"][agent_type].extend(data)
                else:
                    reconciled["combined_data"][agent_type].append(data)
            
            # Дедупликация
            reconciled = self._deduplicate_results(reconciled)
            
            # Генерируем summary используя LLM
            reconciled["summary"] = self._generate_summary(reconciled, main_task)
            
            logger.info("Results reconciled successfully")
            return reconciled
            
        except Exception as e:
            logger.error(f"Error reconciling results: {e}", exc_info=True)
            # Возвращаем частичные результаты
            return {
                "main_task": main_task,
                "subtask_results": {i: r for i, r in enumerate(subagent_results)},
                "error": str(e)
            }
    
    def _deduplicate_results(self, reconciled: Dict[str, Any]) -> Dict[str, Any]:
        """Улучшенная дедупликация результатов с конфликт resolution"""
        # Для timeline - дедупликация по дате и описанию
        if "timeline" in reconciled["combined_data"]:
            timeline_events = reconciled["combined_data"]["timeline"]
            seen = {}
            deduplicated = []
            
            for event in timeline_events:
                if isinstance(event, dict):
                    # Создаем ключ для дедупликации
                    date = event.get("date", "")
                    description = event.get("description", "")[:100]  # Первые 100 символов
                    key = f"{date}_{description}"
                    
                    if key not in seen:
                        seen[key] = event
                        deduplicated.append(event)
                    else:
                        # Конфликт resolution: выбираем событие с более высоким confidence
                        existing = seen[key]
                        existing_conf = existing.get("confidence", existing.get("event_metadata", {}).get("confidence", 0.5))
                        new_conf = event.get("confidence", event.get("event_metadata", {}).get("confidence", 0.5))
                        
                        if new_conf > existing_conf:
                            # Заменяем существующее событие
                            deduplicated.remove(existing)
                            deduplicated.append(event)
                            seen[key] = event
                else:
                    deduplicated.append(event)
            
            reconciled["combined_data"]["timeline"] = deduplicated
        
        # Для entities - дедупликация по тексту и типу с конфликт resolution
        if "entity_extraction" in reconciled["combined_data"]:
            entities = reconciled["combined_data"]["entity_extraction"]
            seen = {}
            deduplicated = []
            
            for entity in entities:
                if isinstance(entity, dict):
                    text = entity.get("entity_text", entity.get("text", ""))
                    entity_type = entity.get("entity_type", entity.get("type", ""))
                    key = f"{text}_{entity_type}"
                    
                    if key not in seen:
                        seen[key] = entity
                        deduplicated.append(entity)
                    else:
                        # Конфликт resolution: выбираем сущность с более высоким confidence
                        existing = seen[key]
                        existing_conf = float(existing.get("confidence", 0.5))
                        new_conf = float(entity.get("confidence", 0.5))
                        
                        if new_conf > existing_conf:
                            # Заменяем существующую сущность
                            deduplicated.remove(existing)
                            deduplicated.append(entity)
                            seen[key] = entity
                else:
                    deduplicated.append(entity)
            
            reconciled["combined_data"]["entity_extraction"] = deduplicated
        
        # Агрегация confidence scores
        reconciled["aggregated_confidence"] = self._aggregate_confidence(reconciled)
        
        # Quality scoring
        reconciled["quality_score"] = self._calculate_quality_score(reconciled)
        
        return reconciled
    
    def _aggregate_confidence(self, reconciled: Dict[str, Any]) -> float:
        """Агрегирует confidence scores из всех результатов"""
        confidences = []
        
        for subtask_result in reconciled.get("subtask_results", {}).values():
            data = subtask_result.get("data", {})
            if isinstance(data, dict):
                conf = data.get("confidence")
                if conf is not None:
                    try:
                        confidences.append(float(conf))
                    except (ValueError, TypeError):
                        pass
        
        if confidences:
            return sum(confidences) / len(confidences)
        return 0.7  # Default confidence
    
    def _calculate_quality_score(self, reconciled: Dict[str, Any]) -> float:
        """Вычисляет общий quality score объединенных результатов"""
        score = 0.0
        factors = 0
        
        # Фактор 1: Количество подзадач
        subtask_count = len(reconciled.get("subtask_results", {}))
        if subtask_count > 0:
            score += min(subtask_count / 5.0, 1.0) * 0.3
            factors += 1
        
        # Фактор 2: Агрегированный confidence
        agg_conf = reconciled.get("aggregated_confidence", 0.7)
        score += agg_conf * 0.4
        factors += 1
        
        # Фактор 3: Количество объединенных данных
        combined_data = reconciled.get("combined_data", {})
        total_items = sum(len(v) if isinstance(v, list) else 1 for v in combined_data.values())
        if total_items > 0:
            score += min(total_items / 20.0, 1.0) * 0.3
            factors += 1
        
        if factors > 0:
            return score / factors
        return 0.7  # Default quality score
    
    def _generate_summary(
        self,
        reconciled: Dict[str, Any],
        main_task: str
    ) -> str:
        """Генерирует summary объединенных результатов"""
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            # Формируем промпт
            combined_data_summary = {}
            for agent_type, data in reconciled["combined_data"].items():
                if isinstance(data, list):
                    combined_data_summary[agent_type] = f"{len(data)} items"
                else:
                    combined_data_summary[agent_type] = str(data)[:200]
            
            prompt = f"""Ты эксперт по анализу юридических документов.

Основная задача: {main_task}

Результаты анализа:
{combined_data_summary}

Создай краткое резюме (2-3 предложения) объединенных результатов анализа."""
            
            messages = [
                SystemMessage(content="Ты эксперт по созданию резюме результатов юридического анализа."),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            summary = response.content if hasattr(response, 'content') else str(response)
            
            return summary.strip()
            
        except Exception as e:
            logger.warning(f"Error generating summary: {e}, using default")
            return f"Объединены результаты {len(reconciled['subtask_results'])} подзадач для задачи: {main_task}"
    
    def get_subagent(self, subtask_id: str) -> Optional[SubAgent]:
        """Получает под-агента по ID"""
        return self.subagents.get(subtask_id)
    
    def get_all_subagents(self) -> List[SubAgent]:
        """Получает все под-агенты"""
        return list(self.subagents.values())
    
    def clear(self):
        """Очищает все под-агенты"""
        self.subagents.clear()
        logger.info("SubAgent Manager cleared")

