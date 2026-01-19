"""Context Summarizer for long-horizon tasks

Automatically summarizes completed phases to prevent context overflow
in long-running analysis tasks.
"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.llm_factory import create_llm
from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag
import logging
import json

logger = logging.getLogger(__name__)

# Threshold for context overflow (in tokens, approximate)
CONTEXT_THRESHOLD = 100_000  # ~100K tokens


class ContextSummarizer:
    """
    Суммаризация завершённых фаз для длинных задач.
    
    Когда контекст графа переполняется, автоматически суммаризирует
    завершённые этапы работы и сохраняет их в Store для последующего
    retrieval.
    """
    
    def __init__(self, llm=None, threshold: int = CONTEXT_THRESHOLD):
        """
        Initialize context summarizer.
        
        Args:
            llm: LLM instance for summarization (optional)
            threshold: Token threshold for triggering summarization
        """
        self.llm = llm or create_llm(temperature=0.1)
        self.threshold = threshold
    
    def estimate_tokens(self, state: AnalysisState) -> int:
        """
        Оценить количество токенов в состоянии.
        
        Args:
            state: Current graph state
        
        Returns:
            Estimated token count
        """
        # Rough estimation: ~4 characters per token
        total_chars = 0
        
        # Count characters in all state fields
        for key, value in state.items():
            if value is None:
                continue
            if isinstance(value, (str, dict, list)):
                total_chars += len(json.dumps(value, ensure_ascii=False))
            else:
                total_chars += len(str(value))
        
        return total_chars // 4
    
    def check_overflow(self, state: AnalysisState) -> bool:
        """
        Проверяет, нужна ли суммаризация.
        
        Args:
            state: Current graph state
        
        Returns:
            True if summarization is needed
        """
        estimated_tokens = self.estimate_tokens(state)
        return estimated_tokens > self.threshold
    
    def summarize_completed_phases(
        self,
        state: AnalysisState,
        case_id: str,
        rag_service=None,
        db=None
    ) -> AnalysisState:
        """
        Суммаризирует завершённые этапы, сохраняет в Store.
        
        Args:
            state: Current graph state
            case_id: Case identifier
            rag_service: Optional RAG service
            db: Optional database session
        
        Returns:
            Updated state with summaries
        """
        case_id = case_id or state.get("case_id", "unknown")
        logger.info(f"[ContextSummarizer] Summarizing completed phases for case {case_id}")
        
        # Collect completed agent results
        completed_results = {}
        result_keys = [
            ("timeline_result", "timeline"),
            ("key_facts_result", "key_facts"),
            ("discrepancy_result", "discrepancy"),
            ("classification_result", "document_classifier"),
            ("entities_result", "entity_extraction"),
        ]
        
        for result_key, agent_name in result_keys:
            result = state.get(result_key)
            if result:
                completed_results[agent_name] = result
        
        if not completed_results:
            logger.debug("[ContextSummarizer] No completed results to summarize")
            return state
        
        # Create summary prompt
        summary_prompt = f"""Суммаризируй результаты завершённых этапов анализа дела {case_id}.

Результаты агентов:
{json.dumps(completed_results, ensure_ascii=False, indent=2)[:5000]}

Создай краткую сводку (максимум 500 слов), включающую:
1. Ключевые выводы из каждого агента
2. Важные факты и даты
3. Критические находки (противоречия, риски)
4. Основные сущности (люди, организации, суммы)

Верни JSON с полями:
- summary: краткая текстовая сводка
- key_findings: список ключевых выводов
- critical_facts: список критических фактов
- entities_summary: список основных сущностей
"""
        
        try:
            # Use LLM to create summary
            if rag_service:
                summary_text = direct_llm_call_with_rag(
                    case_id=case_id,
                    system_prompt="Ты помощник для суммаризации результатов анализа.",
                    user_query=summary_prompt,
                    rag_service=rag_service,
                    db=db,
                    k=5,
                    temperature=0.1
                )
            else:
                # Direct LLM call without RAG
                from langchain_core.messages import SystemMessage, HumanMessage
                response = self.llm.invoke([
                    SystemMessage(content="Ты помощник для суммаризации результатов анализа."),
                    HumanMessage(content=summary_prompt)
                ])
                summary_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse summary (try JSON first, fallback to text)
            try:
                summary_data = json.loads(summary_text)
            except:
                summary_data = {"summary": summary_text}
            
            # Save to Store
            try:
                from app.services.langchain_agents.store_helper import save_phase_summary
                summary_ref = save_phase_summary(
                    state=state,
                    case_id=case_id,
                    summary_data=summary_data,
                    completed_agents=list(completed_results.keys())
                )
                
                # Update state with summary reference
                new_state = dict(state)
                if "metadata" not in new_state:
                    new_state["metadata"] = {}
                if "phase_summaries" not in new_state["metadata"]:
                    new_state["metadata"]["phase_summaries"] = []
                
                new_state["metadata"]["phase_summaries"].append({
                    "summary_ref": summary_ref,
                    "completed_agents": list(completed_results.keys()),
                    "timestamp": json.dumps({"timestamp": "now"})  # Will be set properly
                })
                
                # Clear detailed results from state (keep only refs)
                # This reduces state size
                for result_key, agent_name in result_keys:
                    if agent_name in completed_results:
                        # Keep ref if exists, otherwise clear result
                        ref_key = f"{agent_name.replace('_', '')}_ref"
                        if not state.get(ref_key):
                            new_state[result_key] = None
                
                logger.info(
                    f"[ContextSummarizer] Summarized {len(completed_results)} agents, "
                    f"saved to Store: {summary_ref}"
                )
                
                return new_state
                
            except Exception as store_error:
                logger.warning(f"[ContextSummarizer] Failed to save summary to Store: {store_error}")
                # Return state with summary in metadata anyway
                new_state = dict(state)
                if "metadata" not in new_state:
                    new_state["metadata"] = {}
                new_state["metadata"]["last_summary"] = summary_data
                return new_state
                
        except Exception as e:
            logger.error(f"[ContextSummarizer] Error summarizing phases: {e}", exc_info=True)
            return state
    
    def retrieve_phase_summaries(
        self,
        state: AnalysisState,
        case_id: str
    ) -> str:
        """
        Получить все сохранённые summaries для контекста.
        
        Args:
            state: Current graph state
            case_id: Case identifier
        
        Returns:
            Concatenated summaries as text
        """
        try:
            from app.services.langchain_agents.store_helper import retrieve_phase_summaries
            
            summaries = retrieve_phase_summaries(state, case_id)
            
            if not summaries:
                return ""
            
            # Combine summaries
            summary_texts = []
            for summary in summaries:
                if isinstance(summary, dict):
                    summary_text = summary.get("summary", "")
                    if summary_text:
                        summary_texts.append(summary_text)
                else:
                    summary_texts.append(str(summary))
            
            return "\n\n".join(summary_texts)
            
        except Exception as e:
            logger.warning(f"[ContextSummarizer] Error retrieving summaries: {e}")
            return ""

























