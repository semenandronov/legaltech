"""Evaluation metrics for assessing agent result quality"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
import logging

logger = logging.getLogger(__name__)


class EvaluationMetrics:
    """
    Calculates quality metrics for agent results:
    - Completeness: How complete is the result
    - Accuracy: How accurate is the result
    - Relevance: How relevant is the result to the task
    - Consistency: How consistent is the result
    """
    
    def __init__(self):
        """Initialize evaluation metrics calculator"""
        try:
            self.llm = create_llm(temperature=0.1)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM for metrics: {e}")
            self.llm = None
    
    def calculate_completeness(
        self,
        result: Dict[str, Any],
        agent_name: str,
        expected_items: Optional[int] = None
    ) -> float:
        """
        Calculates completeness score (0.0-1.0)
        
        Args:
            result: Agent result dictionary
            agent_name: Name of the agent
            expected_items: Expected number of items (optional)
        
        Returns:
            Completeness score (0.0-1.0)
        """
        if not result:
            return 0.0
        
        # Agent-specific completeness calculation
        if agent_name == "timeline":
            events = result.get("events", [])
            if expected_items:
                return min(len(events) / expected_items, 1.0)
            # Expect at least 5 events for a typical case
            return min(len(events) / 5.0, 1.0)
        
        elif agent_name == "key_facts":
            facts = result.get("facts", result.get("key_facts", []))
            if expected_items:
                return min(len(facts) / expected_items, 1.0)
            # Expect at least 5 key facts
            return min(len(facts) / 5.0, 1.0)
        
        elif agent_name == "discrepancy":
            discrepancies = result.get("discrepancies", [])
            # Completeness is 1.0 if we checked all documents (even if no discrepancies found)
            return 1.0 if "discrepancies" in result else 0.5
        
        elif agent_name == "risk":
            risks = result.get("risks", [])
            overall_risk = result.get("overall_risk_level")
            if overall_risk:
                return 1.0
            return min(len(risks) / 3.0, 1.0) if risks else 0.3
        
        elif agent_name == "summary":
            summary = result.get("summary", result.get("text", ""))
            if not summary:
                return 0.0
            # Check if summary is substantial (at least 100 words)
            word_count = len(summary.split())
            return min(word_count / 100.0, 1.0)
        
        elif agent_name == "entity_extraction":
            entities = result.get("entities", [])
            if expected_items:
                return min(len(entities) / expected_items, 1.0)
            # Expect at least 10 entities
            return min(len(entities) / 10.0, 1.0)
        
        else:
            # Generic: check if result has meaningful content
            has_content = any(
                v for k, v in result.items()
                if k not in ["error", "errors", "metadata"] and v
            )
            return 1.0 if has_content else 0.0
    
    def calculate_accuracy(
        self,
        result: Dict[str, Any],
        agent_name: str,
        context: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Calculates accuracy score (0.0-1.0)
        
        Args:
            result: Agent result dictionary
            agent_name: Name of the agent
            context: Optional context for accuracy assessment
        
        Returns:
            Accuracy score (0.0-1.0)
        """
        if not result:
            return 0.0
        
        # Check for errors
        if "error" in result or "errors" in result:
            return 0.0
        
        # Agent-specific accuracy checks
        if agent_name == "timeline":
            events = result.get("events", [])
            if not events:
                return 0.0
            
            # Check if events have required fields
            events_with_dates = sum(1 for e in events if e.get("date"))
            events_with_sources = sum(1 for e in events if e.get("source_document"))
            
            accuracy = (
                (events_with_dates / len(events) * 0.5) +
                (events_with_sources / len(events) * 0.5)
            ) if events else 0.0
            
            return accuracy
        
        elif agent_name == "key_facts":
            facts = result.get("facts", result.get("key_facts", []))
            if not facts:
                return 0.0
            
            # Check if facts have sources
            facts_with_sources = sum(
                1 for f in facts
                if isinstance(f, dict) and (f.get("source") or f.get("source_document"))
            )
            
            return facts_with_sources / len(facts) if facts else 0.0
        
        elif agent_name == "discrepancy":
            discrepancies = result.get("discrepancies", [])
            if not discrepancies:
                # No discrepancies is valid
                return 1.0
            
            # Check if discrepancies have descriptions
            valid_discrepancies = sum(
                1 for d in discrepancies
                if isinstance(d, dict) and d.get("description")
            )
            
            return valid_discrepancies / len(discrepancies) if discrepancies else 1.0
        
        elif agent_name in ["risk", "summary"]:
            # Use confidence from result if available
            return result.get("confidence", 0.7)
        
        else:
            # Generic: assume moderate accuracy if no errors
            return 0.7
    
    def calculate_relevance(
        self,
        result: Dict[str, Any],
        agent_name: str,
        task_description: Optional[str] = None
    ) -> float:
        """
        Calculates relevance score (0.0-1.0)
        
        Args:
            result: Agent result dictionary
            agent_name: Name of the agent
            task_description: Optional task description for relevance check
        
        Returns:
            Relevance score (0.0-1.0)
        """
        if not result:
            return 0.0
        
        # If we have LLM, use it for relevance assessment
        if self.llm and task_description:
            return self._llm_relevance_check(result, agent_name, task_description)
        
        # Rule-based relevance
        # If result has content and matches agent purpose, it's relevant
        has_content = any(
            v for k, v in result.items()
            if k not in ["error", "errors", "metadata"] and v
        )
        
        return 1.0 if has_content else 0.0
    
    def calculate_consistency(
        self,
        result: Dict[str, Any],
        agent_name: str,
        previous_results: Optional[List[Dict[str, Any]]] = None
    ) -> float:
        """
        Calculates consistency score (0.0-1.0)
        
        Args:
            result: Agent result dictionary
            agent_name: Name of the agent
            previous_results: Optional previous results for comparison
        
        Returns:
            Consistency score (0.0-1.0)
        """
        if not result:
            return 0.0
        
        # Check internal consistency
        consistency = 1.0
        
        # Check for conflicting information within result
        if agent_name == "timeline":
            events = result.get("events", [])
            # Check if dates are in chronological order
            dates = [e.get("date") for e in events if e.get("date")]
            if len(dates) > 1:
                # Simple check: if dates are sortable, assume consistent
                try:
                    sorted_dates = sorted(dates)
                    if sorted_dates != dates:
                        consistency = 0.8  # Slight penalty for unsorted
                except:
                    consistency = 0.7  # Can't sort dates
        
        # Compare with previous results if available
        if previous_results:
            # Check if result is consistent with previous similar results
            for prev_result in previous_results:
                if prev_result.get("agent_name") == agent_name:
                    # Simple consistency check: similar structure
                    prev_keys = set(prev_result.keys())
                    curr_keys = set(result.keys())
                    overlap = len(prev_keys & curr_keys) / len(prev_keys | curr_keys) if (prev_keys | curr_keys) else 0
                    consistency = min(consistency, 0.5 + overlap * 0.5)
        
        return consistency
    
    def _llm_relevance_check(
        self,
        result: Dict[str, Any],
        agent_name: str,
        task_description: str
    ) -> float:
        """Uses LLM to check relevance of result to task"""
        try:
            prompt = ChatPromptTemplate.from_messages([
                SystemMessage(content=f"""Ты оцениваешь релевантность результата агента {agent_name} к задаче пользователя.

Верни только число от 0.0 до 1.0, где:
- 1.0 = результат полностью релевантен задаче
- 0.5 = результат частично релевантен
- 0.0 = результат не релевантен

Отвечай ТОЛЬКО числом."""),
                HumanMessage(content=f"""Задача: {task_description}

Результат агента {agent_name}:
{str(result)[:1000]}

Релевантность (0.0-1.0):""")
            ])
            
            response = self.llm.invoke(prompt.format_messages())
            relevance_text = response.content.strip()
            
            # Extract number
            import re
            match = re.search(r'(\d+\.?\d*)', relevance_text)
            if match:
                relevance = float(match.group(1))
                return max(0.0, min(1.0, relevance / 10.0 if relevance > 1.0 else relevance))
            
            return 0.7  # Default moderate relevance
            
        except Exception as e:
            logger.warning(f"LLM relevance check failed: {e}")
            return 0.7
    
    def aggregate_metrics(
        self,
        completeness: float,
        accuracy: float,
        relevance: float,
        consistency: float,
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Aggregates individual metrics into overall quality score
        
        Args:
            completeness: Completeness score
            accuracy: Accuracy score
            relevance: Relevance score
            consistency: Consistency score
            weights: Optional weights for each metric
        
        Returns:
            Dictionary with aggregated metrics
        """
        if weights is None:
            weights = {
                "completeness": 0.3,
                "accuracy": 0.3,
                "relevance": 0.2,
                "consistency": 0.2
            }
        
        overall_score = (
            completeness * weights["completeness"] +
            accuracy * weights["accuracy"] +
            relevance * weights["relevance"] +
            consistency * weights["consistency"]
        )
        
        return {
            "completeness": completeness,
            "accuracy": accuracy,
            "relevance": relevance,
            "consistency": consistency,
            "overall_score": overall_score,
            "weights": weights
        }
    
    def evaluate_with_llm(
        self,
        result: Dict[str, Any],
        expected_output: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Uses LLM for deep evaluation of result
        
        Args:
            result: Agent result dictionary
            expected_output: Expected output description
            context: Context for evaluation
        
        Returns:
            Evaluation result with detailed analysis
        """
        if not self.llm:
            logger.warning("LLM not available for deep evaluation")
            return {
                "evaluation_type": "rule_based",
                "score": 0.7,
                "reasoning": "LLM evaluation not available"
            }
        
        try:
            prompt = ChatPromptTemplate.from_messages([
                SystemMessage(content="""Ты эксперт по оценке качества результатов AI-агентов.

Оцени результат по следующим критериям:
1. Соответствие ожидаемому выводу
2. Полнота информации
3. Точность данных
4. Структурированность

Верни JSON:
{
    "score": 0.0-1.0,
    "completeness": 0.0-1.0,
    "accuracy": 0.0-1.0,
    "strengths": ["сильная сторона 1", ...],
    "weaknesses": ["слабая сторона 1", ...],
    "recommendations": ["рекомендация 1", ...]
}"""),
                HumanMessage(content=f"""Ожидаемый вывод: {expected_output}

Контекст: {context.get('case_id', 'unknown')}, агент: {context.get('agent_name', 'unknown')}

Результат:
{str(result)[:2000]}

Оценка:""")
            ])
            
            response = self.llm.invoke(prompt.format_messages())
            response_text = response.content.strip()
            
            # Parse JSON from response
            import json
            import re
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                eval_result = json.loads(json_match.group(0))
                eval_result["evaluation_type"] = "llm_based"
                return eval_result
            
            return {
                "evaluation_type": "llm_based",
                "score": 0.7,
                "reasoning": "Failed to parse LLM response"
            }
            
        except Exception as e:
            logger.error(f"LLM evaluation error: {e}", exc_info=True)
            return {
                "evaluation_type": "error",
                "score": 0.5,
                "reasoning": f"Evaluation error: {str(e)}"
            }

