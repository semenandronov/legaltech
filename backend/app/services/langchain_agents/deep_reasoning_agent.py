"""Deep Reasoning Agent for complex multi-step legal analysis"""
from typing import Dict, Any, Optional, List
from app.services.llm_factory import create_llm
from app.services.langchain_agents.tools import get_all_tools
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from langchain_core.messages import HumanMessage
import logging

logger = logging.getLogger(__name__)


class DeepReasoningAgent:
    """
    Для сложных юридических задач с многошаговым reasoning
    
    Используется когда задача требует глубокого анализа:
    - "Проанализируй риски с учетом прецедентов ВАС"
    - "Сравни условия договора с практикой судов"
    - "Найди все противоречия и оцени их юридические последствия"
    
    В отличие от обычных агентов, DeepReasoningAgent:
    1. Разбивает задачу на подзадачи
    2. Выполняет многошаговое рассуждение
    3. Синтезирует результаты из разных источников
    4. Объясняет reasoning на каждом уровне
    """
    
    def __init__(self, max_depth: int = 5):
        """
        Initialize Deep Reasoning Agent
        
        Args:
            max_depth: Maximum depth of reasoning steps (default: 5)
        """
        self.max_depth = max_depth
        self.llm = create_llm(temperature=0.2)  # Slightly higher temperature for reasoning
        self.tools = get_all_tools()
        
        # Create agent with tools
        try:
            # Try to use experimental DeepAgentExecutor if available
            try:
                from langchain_experimental.reasoning import DeepAgentExecutor
                self.deep_executor = DeepAgentExecutor(
                    llm=self.llm,
                    tools=self.tools,
                    max_depth=max_depth
                )
                self.use_experimental = True
                logger.info(f"✅ Using DeepAgentExecutor (experimental) with max_depth={max_depth}")
            except ImportError:
                # Fallback to regular ReAct agent with multi-step reasoning
                self.use_experimental = False
                self.agent = create_legal_agent(
                    llm=self.llm,
                    tools=self.tools,
                    agent_type="react"
                )
                logger.info(f"✅ Using ReAct agent with multi-step reasoning (max_depth={max_depth})")
        except Exception as e:
            logger.error(f"Failed to initialize DeepReasoningAgent: {e}")
            raise
    
    def analyze_complex_issue(
        self,
        question: str,
        context: Dict[str, Any],
        case_id: str
    ) -> Dict[str, Any]:
        """
        Анализирует сложный вопрос с многошаговым reasoning
        
        Args:
            question: Сложный вопрос для анализа
            context: Контекст (результаты других агентов, документы, etc.)
            case_id: Идентификатор дела
        
        Returns:
            Dictionary с результатом анализа и reasoning trace
        """
        try:
            logger.info(f"[DeepReasoning] Analyzing complex issue: {question[:100]}...")
            
            # Формируем промпт с контекстом
            prompt = self._build_reasoning_prompt(question, context, case_id)
            
            if self.use_experimental:
                # Use DeepAgentExecutor
                result = self.deep_executor.invoke({
                    "input": prompt,
                    "context": context,
                    "depth_level": "deep"
                })
            else:
                # Use regular agent with multi-step reasoning instructions
                message = HumanMessage(content=prompt)
                result = safe_agent_invoke(
                    self.agent,
                    self.llm,
                    {"messages": [message]},
                    config={"recursion_limit": self.max_depth * 3}  # More steps for deep reasoning
                )
            
            # Parse result
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
            
            # Extract reasoning trace
            reasoning_trace = self._extract_reasoning_trace(result)
            
            return {
                "analysis": response_text,
                "reasoning_trace": reasoning_trace,
                "depth": self.max_depth,
                "context_used": list(context.keys()) if isinstance(context, dict) else [],
                "status": "completed"
            }
            
        except Exception as e:
            logger.error(f"[DeepReasoning] Error analyzing complex issue: {e}", exc_info=True)
            return {
                "analysis": f"Error during deep reasoning: {str(e)}",
                "reasoning_trace": [],
                "status": "failed",
                "error": str(e)
            }
    
    def _build_reasoning_prompt(
        self,
        question: str,
        context: Dict[str, Any],
        case_id: str
    ) -> str:
        """Строит промпт для многошагового reasoning"""
        prompt_parts = []
        
        prompt_parts.append("Ты - эксперт-юрист, выполняющий глубокий многошаговый анализ сложной юридической задачи.")
        prompt_parts.append("")
        prompt_parts.append("ЗАДАЧА:")
        prompt_parts.append(question)
        prompt_parts.append("")
        
        # Добавляем контекст
        if context:
            prompt_parts.append("КОНТЕКСТ:")
            if context.get("timeline_result"):
                prompt_parts.append("- Хронология событий доступна")
            if context.get("key_facts_result"):
                prompt_parts.append("- Ключевые факты извлечены")
            if context.get("discrepancy_result"):
                prompt_parts.append("- Противоречия найдены")
            if context.get("risk_result"):
                prompt_parts.append("- Анализ рисков выполнен")
            prompt_parts.append("")
        
        prompt_parts.append("ПРОЦЕСС РАССУЖДЕНИЯ:")
        prompt_parts.append("1. СНАЧАЛА: Разбей задачу на подзадачи")
        prompt_parts.append("2. ЗАТЕМ: Для каждой подзадачи используй соответствующие инструменты")
        prompt_parts.append("3. ДАЛЕЕ: Синтезируй результаты из разных источников")
        prompt_parts.append("4. ПОТОМ: Сделай выводы на основе синтеза")
        prompt_parts.append("5. НАКОНЕЦ: Объясни reasoning на каждом шаге")
        prompt_parts.append("")
        prompt_parts.append("Используй доступные инструменты для поиска информации, анализа документов и верификации фактов.")
        prompt_parts.append("")
        prompt_parts.append(f"Дело: {case_id}")
        
        return "\n".join(prompt_parts)
    
    def _extract_reasoning_trace(self, result: Any) -> List[str]:
        """Извлекает trace reasoning из результата"""
        trace = []
        
        if isinstance(result, dict):
            messages = result.get("messages", [])
            for msg in messages:
                if hasattr(msg, 'content'):
                    content = msg.content
                    if content and len(content) > 50:  # Skip very short messages
                        trace.append(content[:200])  # Limit length
        
        return trace

