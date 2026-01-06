"""Planning validator for validating and optimizing analysis plans"""
from typing import Dict, Any, List, Optional, Tuple
from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
from app.services.langchain_agents.state import PlanStep, PlanStepStatus
import logging

logger = logging.getLogger(__name__)


class ValidationResult:
    """Result of plan validation"""
    def __init__(
        self,
        is_valid: bool,
        issues: List[str] = None,
        warnings: List[str] = None,
        optimized_plan: Optional[Dict[str, Any]] = None,
        estimated_time: Optional[str] = None
    ):
        self.is_valid = is_valid
        self.issues = issues or []
        self.warnings = warnings or []
        self.optimized_plan = optimized_plan
        self.estimated_time = estimated_time
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": self.issues,
            "warnings": self.warnings,
            "optimized_plan": self.optimized_plan,
            "estimated_time": self.estimated_time
        }


class PlanningValidator:
    """
    Validates and optimizes analysis plans before execution.
    
    Performs:
    - Dependency validation
    - Agent availability checks
    - Execution time estimation
    - Conflict detection
    - Plan optimization (parallelization, ordering)
    """
    
    # Time estimates in minutes (min-max)
    TIME_ESTIMATES = {
        "document_classifier": (2, 5),
        "entity_extraction": (3, 7),
        "privilege_check": (2, 4),
        "timeline": (5, 10),
        "key_facts": (5, 10),
        "discrepancy": (7, 15),
        "relationship": (5, 10),
        "risk": (5, 10),
        "summary": (3, 7)
    }
    
    # Independent agents that can run in parallel
    INDEPENDENT_AGENTS = [
        "document_classifier",
        "entity_extraction",
        "timeline",
        "key_facts",
        "discrepancy"
    ]
    
    # Agents that depend on others
    DEPENDENT_AGENTS = {
        "risk": ["discrepancy"],
        "summary": ["key_facts"],
        "relationship": ["entity_extraction"]
    }
    
    def validate_plan(
        self,
        plan: Dict[str, Any],
        case_id: str
    ) -> ValidationResult:
        """
        Validates a plan and returns validation result with optimizations
        
        Args:
            plan: Plan dictionary (can be basic with analysis_types or multi-level with steps)
            case_id: Case identifier
        
        Returns:
            ValidationResult with validation status and optimized plan
        """
        issues = []
        warnings = []
        
        # Extract analysis types and steps
        analysis_types = plan.get("analysis_types", [])
        steps = plan.get("steps", [])
        
        # If we have steps, extract analysis types from them
        if steps and not analysis_types:
            analysis_types = [step.get("agent_name") for step in steps if step.get("agent_name")]
        
        # Validate analysis types exist
        for analysis_type in analysis_types:
            if analysis_type not in AVAILABLE_ANALYSES:
                issues.append(f"Unknown analysis type: {analysis_type}")
        
        # Validate dependencies
        dependency_issues = self._validate_dependencies(analysis_types)
        issues.extend(dependency_issues)
        
        # Check for conflicts
        conflict_warnings = self._check_conflicts(analysis_types, steps)
        warnings.extend(conflict_warnings)
        
        # Validate reasoning quality for each step
        user_task = plan.get("user_task") or plan.get("main_task")
        if steps:
            for step in steps:
                is_valid, reasoning_issues = self.validate_reasoning_quality(step, user_task)
                if not is_valid:
                    issues.extend([f"Step {step.get('step_id', 'unknown')}: {issue}" for issue in reasoning_issues])
        
        # Estimate execution time
        estimated_time = self._estimate_execution_time(analysis_types, steps)
        
        # Optimize plan
        optimized_plan = self._optimize_plan(plan, analysis_types, steps)
        
        is_valid = len(issues) == 0
        
        result = ValidationResult(
            is_valid=is_valid,
            issues=issues,
            warnings=warnings,
            optimized_plan=optimized_plan,
            estimated_time=estimated_time
        )
        
        logger.info(
            f"Plan validation for case {case_id}: valid={is_valid}, "
            f"issues={len(issues)}, warnings={len(warnings)}, "
            f"estimated_time={estimated_time}"
        )
        
        return result
    
    def _validate_dependencies(self, analysis_types: List[str]) -> List[str]:
        """Validates that all dependencies are included"""
        issues = []
        required_deps = set()
        
        for analysis_type in analysis_types:
            analysis_info = AVAILABLE_ANALYSES.get(analysis_type)
            if analysis_info:
                deps = analysis_info.get("dependencies", [])
                for dep in deps:
                    if dep not in analysis_types:
                        required_deps.add(dep)
                        issues.append(
                            f"Analysis '{analysis_type}' requires '{dep}' but it's not in the plan"
                        )
        
        return issues
    
    def validate_reasoning_quality(
        self,
        step: Dict[str, Any],
        user_task: Optional[str] = None
    ) -> Tuple[bool, List[str]]:
        """
        Валидирует качество reasoning для шага
        
        Args:
            step: Словарь с данными шага
            user_task: Задача пользователя (опционально)
            
        Returns:
            Tuple[is_valid, issues] - (валиден ли reasoning, список проблем)
        """
        issues = []
        reasoning = step.get("planned_reasoning") or step.get("reasoning", "")
        
        # Эвристические проверки
        if len(reasoning) < 50:
            issues.append("Reasoning слишком короткий (минимум 50 символов)")
        
        if user_task:
            # Проверяем упоминание задачи
            task_keywords = user_task.lower().split()[:5]  # Первые 5 слов
            reasoning_lower = reasoning.lower()
            mentions_task = any(keyword in reasoning_lower for keyword in task_keywords if len(keyword) > 3)
            if not mentions_task:
                issues.append("Reasoning не упоминает задачу пользователя")
        
        # Проверяем наличие структурированных элементов
        has_why = any(word in reasoning.lower() for word in ["почему", "необходим", "нужен", "требуется"])
        if not has_why:
            issues.append("Reasoning не объясняет, почему шаг нужен")
        
        has_documents = any(word in reasoning.lower() for word in ["документ", "файл", "источник", "материал"])
        if not has_documents:
            issues.append("Reasoning не упоминает используемые документы")
        
        # Проверяем зависимости
        dependencies = step.get("dependencies", [])
        if dependencies:
            has_deps = any(dep in reasoning.lower() for dep in dependencies)
            if not has_deps:
                issues.append("Reasoning не упоминает зависимости от других шагов")
        
        is_valid = len(issues) == 0
        return is_valid, issues
    
    def _check_conflicts(self, analysis_types: List[str], steps: List[Dict]) -> List[str]:
        """Checks for potential conflicts in the plan"""
        warnings = []
        
        # Check for duplicate analysis types
        seen = set()
        for analysis_type in analysis_types:
            if analysis_type in seen:
                warnings.append(f"Duplicate analysis type: {analysis_type}")
            seen.add(analysis_type)
        
        # Check for steps with duplicate step_ids
        if steps:
            step_ids = [step.get("step_id") for step in steps if step.get("step_id")]
            seen_ids = set()
            for step_id in step_ids:
                if step_id in seen_ids:
                    warnings.append(f"Duplicate step_id: {step_id}")
                seen_ids.add(step_id)
        
        return warnings
    
    def _estimate_execution_time(
        self,
        analysis_types: List[str],
        steps: List[Dict]
    ) -> str:
        """Estimates total execution time for the plan"""
        if steps:
            # Use estimated_time from steps if available
            total_min = 0
            total_max = 0
            for step in steps:
                estimated_time = step.get("estimated_time", "")
                if estimated_time:
                    # Parse "5-10 мин" format
                    try:
                        if "-" in estimated_time:
                            parts = estimated_time.split("-")
                            min_time = int(parts[0].strip())
                            max_time = int(parts[1].split()[0].strip())
                            total_min += min_time
                            total_max += max_time
                    except (ValueError, IndexError):
                        pass
            
            if total_min > 0 and total_max > 0:
                return f"{total_min}-{total_max} мин"
        
        # Fallback: estimate from analysis types
        total_min = 0
        total_max = 0
        
        for analysis_type in analysis_types:
            time_range = self.TIME_ESTIMATES.get(analysis_type, (5, 10))
            total_min += time_range[0]
            total_max += time_range[1]
        
        return f"{total_min}-{total_max} мин"
    
    def _optimize_plan(
        self,
        plan: Dict[str, Any],
        analysis_types: List[str],
        steps: List[Dict]
    ) -> Dict[str, Any]:
        """
        Optimizes the plan by:
        - Reordering steps for optimal execution
        - Identifying parallel execution opportunities
        - Optimizing resource usage
        """
        optimized = dict(plan)
        
        # If we have steps, optimize their order
        if steps:
            optimized_steps = self._optimize_step_order(steps)
            optimized["steps"] = optimized_steps
            
            # Update analysis_types to match optimized order
            optimized["analysis_types"] = [
                step.get("agent_name") for step in optimized_steps
                if step.get("agent_name")
            ]
        else:
            # Optimize analysis_types order
            optimized_types = self._optimize_analysis_order(analysis_types)
            optimized["analysis_types"] = optimized_types
        
        # Add parallelization hints
        if "strategy" not in optimized:
            optimized["strategy"] = self._determine_strategy(optimized.get("analysis_types", []))
        
        return optimized
    
    def _optimize_step_order(self, steps: List[Dict]) -> List[Dict]:
        """Optimizes the order of steps for execution"""
        # Separate steps by status and dependencies
        completed = [s for s in steps if s.get("status") == PlanStepStatus.COMPLETED.value]
        pending = [s for s in steps if s.get("status") == PlanStepStatus.PENDING.value]
        failed = [s for s in steps if s.get("status") == PlanStepStatus.FAILED.value]
        
        # Sort pending steps: independent first, then dependent
        independent = []
        dependent = []
        
        for step in pending:
            agent_name = step.get("agent_name", "")
            deps = step.get("dependencies", [])
            
            if not deps and agent_name in self.INDEPENDENT_AGENTS:
                independent.append(step)
            else:
                dependent.append(step)
        
        # Sort independent by estimated time (faster first)
        independent.sort(key=lambda s: self._get_step_time(s))
        
        # Sort dependent by number of dependencies (fewer first)
        dependent.sort(key=lambda s: len(s.get("dependencies", [])))
        
        # Reconstruct: completed -> independent -> dependent -> failed
        return completed + independent + dependent + failed
    
    def _optimize_analysis_order(self, analysis_types: List[str]) -> List[str]:
        """Optimizes the order of analysis types"""
        independent = []
        dependent = []
        
        for analysis_type in analysis_types:
            deps = AVAILABLE_ANALYSES.get(analysis_type, {}).get("dependencies", [])
            if not deps and analysis_type in self.INDEPENDENT_AGENTS:
                independent.append(analysis_type)
            else:
                dependent.append(analysis_type)
        
        # Sort dependent by number of dependencies
        dependent.sort(key=lambda a: len(
            AVAILABLE_ANALYSES.get(a, {}).get("dependencies", [])
        ))
        
        return independent + dependent
    
    def _get_step_time(self, step: Dict) -> int:
        """Extracts time estimate from step (returns min time in minutes)"""
        estimated_time = step.get("estimated_time", "")
        if estimated_time:
            try:
                if "-" in estimated_time:
                    return int(estimated_time.split("-")[0].strip())
            except (ValueError, IndexError):
                pass
        
        # Fallback to default
        agent_name = step.get("agent_name", "")
        time_range = self.TIME_ESTIMATES.get(agent_name, (5, 10))
        return time_range[0]
    
    def _determine_strategy(self, analysis_types: List[str]) -> str:
        """Determines execution strategy based on analysis types"""
        independent_count = sum(
            1 for a in analysis_types
            if a in self.INDEPENDENT_AGENTS
        )
        dependent_count = len(analysis_types) - independent_count
        
        if independent_count > 2 and dependent_count == 0:
            return "parallel_independent"
        elif independent_count > 0 and dependent_count > 0:
            return "parallel_optimized"
        elif dependent_count > 2:
            return "dependent_sequential"
        elif len(analysis_types) <= 2:
            return "simple_sequential"
        else:
            return "comprehensive_analysis"

