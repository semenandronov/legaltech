"""Fallback handler for graceful degradation and partial results"""
from typing import Dict, Any, List, Optional, Tuple
from app.services.langchain_agents.state import AnalysisState, PlanStepStatus
from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
import logging

logger = logging.getLogger(__name__)


class FallbackResult:
    """Result of fallback handling"""
    def __init__(
        self,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        strategy: str = "none",
        message: str = "",
        partial: bool = False
    ):
        self.success = success
        self.result = result
        self.strategy = strategy
        self.message = message
        self.partial = partial
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "strategy": self.strategy,
            "message": self.message,
            "partial": self.partial
        }


class FallbackHandler:
    """
    Handles agent failures with fallback strategies.
    
    Strategies:
    1. Simplified approach - try with simpler parameters
    2. Alternative agent - use different agent for similar task
    3. Partial results - return what was successfully extracted
    4. User notification - inform user about failure
    """
    
    # Mapping of agents to alternative agents
    ALTERNATIVE_AGENTS = {
        "timeline": ["key_facts"],  # Can extract dates from key_facts
        "key_facts": ["entity_extraction"],  # Can use entities
        "discrepancy": [],  # No direct alternative
        "risk": ["discrepancy"],  # Can analyze risks from discrepancies manually
        "summary": ["key_facts"],  # Can create summary from key_facts
    }
    
    def handle_failure(
        self,
        agent_name: str,
        error: Exception,
        state: AnalysisState
    ) -> FallbackResult:
        """
        Handles agent failure with fallback strategies
        
        Args:
            agent_name: Name of failed agent
            error: Exception that occurred
            state: Current analysis state
        
        Returns:
            FallbackResult with handling strategy and result
        """
        error_str = str(error)
        error_lower = error_str.lower()
        
        logger.info(f"Handling failure for {agent_name}: {error_str[:100]}")
        
        # Determine fallback strategy based on error type
        if "timeout" in error_lower or "timed out" in error_lower:
            return self._handle_timeout(agent_name, state)
        elif "no result" in error_lower or "empty" in error_lower:
            return self._handle_no_result(agent_name, state)
        elif "dependency" in error_lower:
            return self._handle_dependency_error(agent_name, state)
        else:
            return self._handle_generic_error(agent_name, error, state)
    
    def _handle_timeout(
        self,
        agent_name: str,
        state: AnalysisState
    ) -> FallbackResult:
        """Handles timeout errors"""
        # Try simplified approach
        simplified_result = self._try_simplified_approach(agent_name, state)
        if simplified_result:
            return FallbackResult(
                success=True,
                result=simplified_result,
                strategy="simplified_approach",
                message=f"Успешно выполнено упрощенной версией после таймаута",
                partial=False
            )
        
        # Try alternative agent
        alternative_result = self._try_alternative_agent(agent_name, state)
        if alternative_result:
            return FallbackResult(
                success=True,
                result=alternative_result,
                strategy="alternative_agent",
                message=f"Использован альтернативный агент вместо {agent_name}",
                partial=False
            )
        
        # Return partial result if available
        partial = self._extract_partial_result(agent_name, state)
        if partial:
            return FallbackResult(
                success=True,
                result=partial,
                strategy="partial_result",
                message=f"Возвращены частичные результаты для {agent_name}",
                partial=True
            )
        
        # Last resort: notify user
        return FallbackResult(
            success=False,
            result=None,
            strategy="user_notification",
            message=f"Не удалось выполнить {agent_name} после таймаута. Требуется вмешательство пользователя.",
            partial=False
        )
    
    def _handle_no_result(
        self,
        agent_name: str,
        state: AnalysisState
    ) -> FallbackResult:
        """Handles no result errors"""
        # Check if it's expected (e.g., no discrepancies found)
        if agent_name == "discrepancy":
            return FallbackResult(
                success=True,
                result={"discrepancies": [], "message": "Противоречия не найдены"},
                strategy="expected_empty",
                message="Противоречия не найдены (это нормально)",
                partial=False
            )
        
        # Try alternative agent
        alternative_result = self._try_alternative_agent(agent_name, state)
        if alternative_result:
            return FallbackResult(
                success=True,
                result=alternative_result,
                strategy="alternative_agent",
                message=f"Использован альтернативный агент вместо {agent_name}",
                partial=False
            )
        
        # Return empty result with explanation
        return FallbackResult(
            success=True,
            result={agent_name: [], "message": f"Не удалось извлечь данные для {agent_name}"},
            strategy="empty_result",
            message=f"Результат пуст для {agent_name}",
            partial=True
        )
    
    def _handle_dependency_error(
        self,
        agent_name: str,
        state: AnalysisState
    ) -> FallbackResult:
        """Handles dependency errors"""
        # Check if dependencies are available
        dependencies = AVAILABLE_ANALYSES.get(agent_name, {}).get("dependencies", [])
        
        missing_deps = []
        for dep in dependencies:
            result_key = f"{dep}_result"
            if not state.get(result_key):
                missing_deps.append(dep)
        
        if missing_deps:
            return FallbackResult(
                success=False,
                result=None,
                strategy="wait_for_dependencies",
                message=f"{agent_name} требует выполнения: {', '.join(missing_deps)}",
                partial=False
            )
        
        # Dependencies should be available, try again
        return FallbackResult(
            success=False,
            result=None,
            strategy="retry",
            message=f"Зависимости доступны, можно повторить {agent_name}",
            partial=False
        )
    
    def _handle_generic_error(
        self,
        agent_name: str,
        error: Exception,
        state: AnalysisState
    ) -> FallbackResult:
        """Handles generic errors"""
        # Try simplified approach first
        simplified_result = self._try_simplified_approach(agent_name, state)
        if simplified_result:
            return FallbackResult(
                success=True,
                result=simplified_result,
                strategy="simplified_approach",
                message=f"Успешно выполнено упрощенной версией",
                partial=False
            )
        
        # Try alternative agent
        alternative_result = self._try_alternative_agent(agent_name, state)
        if alternative_result:
            return FallbackResult(
                success=True,
                result=alternative_result,
                strategy="alternative_agent",
                message=f"Использован альтернативный агент",
                partial=False
            )
        
        # Return error information
        return FallbackResult(
            success=False,
            result={"error": str(error), "agent": agent_name},
            strategy="error_propagation",
            message=f"Ошибка в {agent_name}: {str(error)[:200]}",
            partial=False
        )
    
    def _try_simplified_approach(
        self,
        agent_name: str,
        state: AnalysisState
    ) -> Optional[Dict[str, Any]]:
        """Tries simplified approach with basic parameters"""
        # This would typically call the agent again with simplified parameters
        # For now, return None to indicate it's not implemented at this level
        # (should be handled by retry mechanism)
        return None
    
    def _try_alternative_agent(
        self,
        agent_name: str,
        state: AnalysisState
    ) -> Optional[Dict[str, Any]]:
        """Tries alternative agent for similar task"""
        alternatives = self.ALTERNATIVE_AGENTS.get(agent_name, [])
        
        for alt_agent in alternatives:
            result_key = f"{alt_agent}_result"
            alt_result = state.get(result_key)
            
            if alt_result:
                # Transform alternative result to match expected format
                transformed = self._transform_alternative_result(agent_name, alt_agent, alt_result)
                if transformed:
                    logger.info(f"Using alternative agent {alt_agent} for {agent_name}")
                    return transformed
        
        return None
    
    def _transform_alternative_result(
        self,
        target_agent: str,
        source_agent: str,
        source_result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Transforms result from alternative agent to match target format"""
        if target_agent == "timeline" and source_agent == "key_facts":
            # Extract dates from key_facts
            facts = source_result.get("facts", source_result.get("key_facts", []))
            events = []
            for fact in facts:
                if isinstance(fact, dict):
                    fact_value = fact.get("value", "")
                    if any(keyword in str(fact_value).lower() for keyword in ["дата", "date", "2023", "2024"]):
                        events.append({
                            "date": fact.get("value", ""),
                            "event_type": "fact_extracted",
                            "description": fact.get("description", fact_value),
                            "source": "key_facts_alternative"
                        })
            if events:
                return {"events": events, "source": "alternative_agent"}
        
        return None
    
    def _extract_partial_result(
        self,
        agent_name: str,
        state: AnalysisState
    ) -> Optional[Dict[str, Any]]:
        """Extracts partial results from state if available"""
        # Check if there's any partial result stored in metadata
        metadata = state.get("metadata", {})
        partial_results = metadata.get("partial_results", {})
        
        if agent_name in partial_results:
            return partial_results[agent_name]
        
        return None
    
    def combine_results(
        self,
        results: List[Dict[str, Any]],
        agent_name: str
    ) -> Dict[str, Any]:
        """
        Combines results from multiple sources
        
        Args:
            results: List of result dictionaries
            agent_name: Name of the agent
        
        Returns:
            Combined result dictionary
        """
        if not results:
            return {}
        
        if agent_name == "timeline":
            all_events = []
            for result in results:
                events = result.get("events", [])
                if events:
                    all_events.extend(events)
            # Remove duplicates
            seen = set()
            unique_events = []
            for event in all_events:
                event_key = (event.get("date"), event.get("description"))
                if event_key not in seen:
                    seen.add(event_key)
                    unique_events.append(event)
            return {"events": unique_events, "total_events": len(unique_events)}
        
        elif agent_name == "key_facts":
            all_facts = []
            for result in results:
                facts = result.get("facts", result.get("key_facts", []))
                if facts:
                    all_facts.extend(facts)
            # Remove duplicates
            seen = set()
            unique_facts = []
            for fact in all_facts:
                if isinstance(fact, dict):
                    fact_key = fact.get("value", fact.get("description", ""))
                else:
                    fact_key = str(fact)
                if fact_key not in seen:
                    seen.add(fact_key)
                    unique_facts.append(fact)
            return {"facts": unique_facts, "total_facts": len(unique_facts)}
        
        else:
            # Generic combination: merge all keys
            combined = {}
            for result in results:
                for key, value in result.items():
                    if key not in ["error", "errors"]:
                        if key in combined:
                            if isinstance(combined[key], list) and isinstance(value, list):
                                combined[key].extend(value)
                            elif isinstance(combined[key], dict) and isinstance(value, dict):
                                combined[key].update(value)
                        else:
                            combined[key] = value
            return combined

