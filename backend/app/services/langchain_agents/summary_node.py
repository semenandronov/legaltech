"""Summary agent node for LangGraph"""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
import logging
import json

logger = logging.getLogger(__name__)


def summary_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Summary agent node for generating case summary based on key facts
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with summary_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Summary agent: Starting generation for case {case_id}")
        
        # Check if key facts result is available (dependency)
        key_facts_result = state.get("key_facts_result")
        if not key_facts_result:
            logger.warning(f"Summary agent: No key facts result available for case {case_id}, skipping")
            new_state = state.copy()
            new_state["summary_result"] = None
            return new_state
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools
        tools = get_all_tools()
        
        # Initialize LLM
        llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.7,  # Higher temperature for more creative summary
            max_tokens=2000
        )
        
        # Get prompt
        prompt = get_agent_prompt("summary")
        
        # Create agent
        agent = create_legal_agent(llm, tools, system_prompt=prompt)
        
        # Create initial message with key facts
        from langchain_core.messages import HumanMessage
        key_facts_text = json.dumps(key_facts_result.get("facts", {}), ensure_ascii=False, indent=2)
        initial_message = HumanMessage(
            content=f"""Создай краткое резюме дела на основе следующих ключевых фактов:

{key_facts_text}

Создай структурированное резюме с разделами:
1. Суть дела
2. Стороны спора
3. Ключевые факты
4. Основные даты
5. Текущий статус"""
        )
        
        # Run agent with safe invoke (handles tool use errors)
        from app.services.langchain_agents.agent_factory import safe_agent_invoke
        result = safe_agent_invoke(
            agent,
            llm,
            {
                "messages": [initial_message],
                "case_id": case_id
            },
            config={"recursion_limit": 25}
        )
        
        # Extract summary from response
        summary_text = result.get("messages", [])[-1].content if isinstance(result, dict) else str(result)
        
        # Save to database
        result_id = None
        if db:
            summary_result = AnalysisResult(
                case_id=case_id,
                analysis_type="summary",
                result_data={
                    "summary": summary_text,
                    "key_facts": key_facts_result
                },
                status="completed"
            )
            db.add(summary_result)
            db.commit()
            result_id = summary_result.id
        
        logger.info(f"Summary agent: Generated summary for case {case_id}")
        
        # Create result
        result_data = {
            "summary": summary_text,
            "key_facts": key_facts_result,
            "result_id": result_id
        }
        
        # Update state
        new_state = state.copy()
        new_state["summary_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Summary agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "summary",
            "error": str(e)
        })
        new_state["summary_result"] = None
        return new_state
