"""Continuous Learning Service for improving system performance over time"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_agents.store_service import LangGraphStoreService
from app.config import config
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

# LangSmith integration
try:
    from langsmith import Client
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    logger.warning("LangSmith not available, continuous learning will work without it")


class ContinuousLearningService:
    """Сервис для непрерывного обучения на основе успешных и неуспешных примеров"""
    
    def __init__(self, db: Session):
        """Initialize continuous learning service
        
        Args:
            db: Database session
        """
        self.db = db
        self.store_service = LangGraphStoreService(db)
        
        # Initialize LangSmith client if available
        self.langsmith_client = None
        if LANGSMITH_AVAILABLE and config.LANGSMITH_API_KEY:
            try:
                self.langsmith_client = Client(
                    api_key=config.LANGSMITH_API_KEY,
                    api_url=config.LANGSMITH_ENDPOINT
                )
                logger.info("✅ LangSmith client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize LangSmith client: {e}")
        
        logger.info("✅ Continuous Learning Service initialized")
    
    async def save_successful_pattern(
        self,
        case_id: str,
        agent_name: str,
        pattern: Dict[str, Any],
        outcome: str = "success"
    ) -> bool:
        """
        Сохранить успешный паттерн для обучения
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            pattern: Pattern to save (prompt, result, context)
            outcome: "success" | "failure"
            
        Returns:
            True if saved successfully
        """
        try:
            namespace = f"learning_patterns/{agent_name}/{outcome}"
            pattern_key = f"{case_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            pattern_value = {
                "case_id": case_id,
                "agent_name": agent_name,
                "pattern": pattern,
                "outcome": outcome,
                "timestamp": datetime.now().isoformat()
            }
            
            metadata = {
                "case_id": case_id,
                "agent_name": agent_name,
                "outcome": outcome,
                "saved_at": datetime.now().isoformat()
            }
            
            await self.store_service.save_pattern(
                namespace=namespace,
                key=pattern_key,
                value=pattern_value,
                metadata=metadata
            )
            
            logger.info(f"Saved {outcome} pattern for {agent_name} agent")
            return True
            
        except Exception as e:
            logger.error(f"Error saving pattern: {e}", exc_info=True)
            return False
    
    async def save_feedback_with_traces(
        self,
        case_id: str,
        agent_name: str,
        feedback: str,
        traces: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None
    ) -> bool:
        """
        Save feedback with LangSmith traces for learning
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            feedback: Feedback text from user
            traces: Optional trace data from LangSmith
            run_id: Optional LangSmith run ID
            
        Returns:
            True if saved successfully
        """
        try:
            # Save to Store
            namespace = f"feedback/{agent_name}"
            feedback_key = f"{case_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            feedback_value = {
                "case_id": case_id,
                "agent_name": agent_name,
                "feedback": feedback,
                "traces": traces or {},
                "run_id": run_id,
                "timestamp": datetime.now().isoformat()
            }
            
            metadata = {
                "case_id": case_id,
                "agent_name": agent_name,
                "saved_at": datetime.now().isoformat()
            }
            
            await self.store_service.save_pattern(
                namespace=namespace,
                key=feedback_key,
                value=feedback_value,
                metadata=metadata
            )
            
            # Save to LangSmith as example if available
            if self.langsmith_client and run_id:
                try:
                    # Create example from feedback
                    example = {
                        "inputs": {
                            "case_id": case_id,
                            "agent_name": agent_name
                        },
                        "outputs": {
                            "feedback": feedback
                        },
                        "metadata": {
                            "run_id": run_id,
                            "case_id": case_id,
                            "agent_name": agent_name
                        }
                    }
                    
                    # Add to feedback dataset
                    dataset_name = f"feedback_{agent_name}"
                    try:
                        dataset = self.langsmith_client.read_dataset(dataset_name=dataset_name)
                    except:
                        # Create dataset if it doesn't exist
                        dataset = self.langsmith_client.create_dataset(
                            dataset_name=dataset_name,
                            description=f"Feedback dataset for {agent_name} agent"
                        )
                    
                    # Create example in dataset
                    self.langsmith_client.create_example(
                        dataset_id=dataset.id,
                        inputs=example["inputs"],
                        outputs=example["outputs"],
                        metadata=example.get("metadata")
                    )
                    
                    logger.info(f"Saved feedback to LangSmith dataset {dataset_name} for {agent_name}")
                except Exception as ls_error:
                    logger.warning(f"Failed to save feedback to LangSmith: {ls_error}")
            
            logger.info(f"Saved feedback for {agent_name} agent in case {case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving feedback: {e}", exc_info=True)
            return False
    
    async def improve_prompt(
        self,
        agent_name: str,
        successful_examples: List[Dict[str, Any]],
        failed_examples: List[Dict[str, Any]]
    ) -> str:
        """
        Улучшить промпт на основе примеров
        
        Args:
            agent_name: Name of the agent
            successful_examples: List of successful examples
            failed_examples: List of failed examples
            
        Returns:
            Improved prompt text
        """
        try:
            from app.services.llm_factory import create_llm
            from langchain_core.messages import SystemMessage, HumanMessage
            
            llm = create_llm(temperature=0.3)
            
            # Загружаем текущий промпт
            from app.services.langchain_agents.prompts import get_agent_prompt
            current_prompt = get_agent_prompt(agent_name)
            
            # Формируем примеры
            success_text = "\n".join([
                f"Пример {i+1} (успешный):\n{json.dumps(ex, ensure_ascii=False, indent=2)}"
                for i, ex in enumerate(successful_examples[:5])
            ])
            
            failure_text = "\n".join([
                f"Пример {i+1} (неуспешный):\n{json.dumps(ex, ensure_ascii=False, indent=2)}"
                for i, ex in enumerate(failed_examples[:3])
            ])
            
            improvement_prompt = f"""Ты эксперт по улучшению промптов для AI агентов.

Текущий промпт для агента {agent_name}:
{current_prompt[:1000]}...

Успешные примеры:
{success_text}

Неуспешные примеры:
{failure_text}

Проанализируй успешные и неуспешные примеры и улучши промпт:
1. Что работает хорошо в успешных примерах?
2. Что не работает в неуспешных примерах?
3. Как можно улучшить промпт для повышения успешности?

Верни только улучшенный промпт, без пояснений."""
            
            messages = [
                SystemMessage(content="Ты эксперт по улучшению промптов для AI агентов в юридической области."),
                HumanMessage(content=improvement_prompt)
            ]
            
            response = llm.invoke(messages)
            improved_prompt = response.content if hasattr(response, 'content') else str(response)
            
            # Сохраняем улучшенный промпт
            await self.store_service.save_pattern(
                namespace=f"improved_prompts/{agent_name}",
                key=f"prompt_{datetime.now().strftime('%Y%m%d')}",
                value={
                    "original_prompt": current_prompt,
                    "improved_prompt": improved_prompt,
                    "successful_examples_count": len(successful_examples),
                    "failed_examples_count": len(failed_examples),
                    "improved_at": datetime.now().isoformat()
                },
                metadata={
                    "agent_name": agent_name,
                    "improved_at": datetime.now().isoformat()
                }
            )
            
            logger.info(f"Improved prompt for {agent_name} agent")
            return improved_prompt.strip()
            
        except Exception as e:
            logger.error(f"Error improving prompt: {e}", exc_info=True)
            return current_prompt  # Return original on error
    
    async def generate_evaluation_dataset(
        self,
        case_id: str
    ) -> Dict[str, Any]:
        """
        Создать dataset для LangSmith evaluation
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dataset dictionary for LangSmith
        """
        try:
            # Собираем все результаты анализа для дела
            from app.models.analysis import AnalysisResult
            results = self.db.query(AnalysisResult).filter(
                AnalysisResult.case_id == case_id
            ).all()
            
            examples = []
            for result in results:
                example = {
                    "inputs": {
                        "case_id": case_id,
                        "analysis_type": result.analysis_type,
                        "task": result.result_data.get("task", "unknown")
                    },
                    "outputs": {
                        "result": result.result_data,
                        "status": result.status
                    },
                    "metadata": {
                        "created_at": result.created_at.isoformat() if result.created_at else None,
                        "result_id": result.id
                    }
                }
                examples.append(example)
            
            dataset = {
                "name": f"legal_analysis_{case_id}",
                "description": f"Evaluation dataset for case {case_id}",
                "examples": examples,
                "created_at": datetime.now().isoformat()
            }
            
            logger.info(f"Generated evaluation dataset with {len(examples)} examples for case {case_id}")
            
            # Upload to LangSmith if available
            if self.langsmith_client and config.LANGSMITH_PROJECT:
                try:
                    dataset_name = f"legal_analysis_{case_id}"
                    
                    # Create dataset in LangSmith
                    langsmith_dataset = self.langsmith_client.create_dataset(
                        dataset_name=dataset_name,
                        description=dataset["description"]
                    )
                    
                    # Add examples
                    for example in examples:
                        self.langsmith_client.create_example(
                            inputs=example["inputs"],
                            outputs=example["outputs"],
                            dataset_id=langsmith_dataset.id,
                            metadata=example.get("metadata", {})
                        )
                    
                    logger.info(f"Uploaded dataset to LangSmith: {dataset_name}")
                    dataset["langsmith_dataset_id"] = langsmith_dataset.id
                    
                except Exception as e:
                    logger.warning(f"Failed to upload dataset to LangSmith: {e}")
            
            return dataset
            
        except Exception as e:
            logger.error(f"Error generating evaluation dataset: {e}", exc_info=True)
            return {
                "name": f"legal_analysis_{case_id}",
                "examples": [],
                "error": str(e)
            }
    
    async def analyze_performance_trends(
        self,
        agent_name: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Анализирует тренды производительности агентов
        
        Args:
            agent_name: Optional agent name to filter
            days: Number of days to analyze
            
        Returns:
            Performance trends analysis
        """
        try:
            # Загружаем паттерны из Store
            namespace = f"learning_patterns/{agent_name}" if agent_name else "learning_patterns"
            
            # Получаем все паттерны
            all_patterns = await self.store_service.search_precedents(
                namespace=namespace,
                limit=1000
            )
            
            # Фильтруем по дате
            cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)
            
            recent_patterns = [
                p for p in all_patterns
                if p.get("metadata", {}).get("saved_at")
                and datetime.fromisoformat(p["metadata"]["saved_at"]).timestamp() > cutoff_date
            ]
            
            # Анализируем успешность
            success_count = sum(1 for p in recent_patterns if p.get("value", {}).get("outcome") == "success")
            failure_count = sum(1 for p in recent_patterns if p.get("value", {}).get("outcome") == "failure")
            total = len(recent_patterns)
            
            success_rate = success_count / total if total > 0 else 0.0
            
            trends = {
                "agent_name": agent_name or "all",
                "period_days": days,
                "total_patterns": total,
                "success_count": success_count,
                "failure_count": failure_count,
                "success_rate": success_rate,
                "trend": "improving" if success_rate > 0.7 else "needs_improvement" if success_rate < 0.5 else "stable"
            }
            
            logger.info(f"Performance trends: {trends['trend']} (success_rate: {success_rate:.2%})")
            return trends
            
        except Exception as e:
            logger.error(f"Error analyzing performance trends: {e}", exc_info=True)
            return {
                "error": str(e),
                "agent_name": agent_name,
                "period_days": days
            }
    
    async def get_best_practices(
        self,
        agent_name: str
    ) -> List[Dict[str, Any]]:
        """
        Получить лучшие практики для агента на основе успешных примеров
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            List of best practices
        """
        try:
            # Загружаем успешные паттерны
            success_patterns = await self.store_service.search_precedents(
                namespace=f"learning_patterns/{agent_name}/success",
                limit=20
            )
            
            # Извлекаем общие паттерны
            best_practices = []
            
            for pattern in success_patterns:
                pattern_data = pattern.get("value", {})
                pattern_info = pattern_data.get("pattern", {})
                
                if pattern_info:
                    best_practices.append({
                        "case_id": pattern_data.get("case_id"),
                        "pattern": pattern_info,
                        "timestamp": pattern_data.get("timestamp"),
                        "confidence": pattern.get("metadata", {}).get("confidence", 0.8)
                    })
            
            # Сортируем по confidence
            best_practices.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
            
            logger.info(f"Retrieved {len(best_practices)} best practices for {agent_name}")
            return best_practices[:10]  # Top 10
            
        except Exception as e:
            logger.error(f"Error getting best practices: {e}", exc_info=True)
            return []

