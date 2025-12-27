"""Summary agent node for LangGraph"""
from typing import Dict, Any
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
from langchain_core.messages import HumanMessage
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
        
        # Initialize LLM через factory (GigaChat)
        llm = create_llm(temperature=0.3)  # Creative задача, но все еще контролируемая
        
        # Проверяем, поддерживает ли LLM function calling
        use_tools = hasattr(llm, 'bind_tools')
        
        key_facts_text = json.dumps(key_facts_result.get("facts", {}), ensure_ascii=False, indent=2)
        
        if use_tools and rag_service:
            # GigaChat с function calling - агент может вызвать retrieve_documents_tool для уточнения
            logger.info("Using GigaChat with function calling for summary agent")
            
            prompt = get_agent_prompt("summary")
            
            # Создаем агента с tools
            agent = create_legal_agent(llm, tools, system_prompt=prompt)
            
            # Создаем запрос для агента
            user_query = f"""Создай краткое резюме дела на основе следующих ключевых фактов:

{key_facts_text}

Если нужно больше информации, используй retrieve_documents_tool для поиска дополнительных документов.

Создай структурированное резюме с разделами:
1. Суть дела
2. Стороны спора
3. Ключевые факты
4. Основные даты
5. Текущий статус"""
            
            initial_message = HumanMessage(content=user_query)
            
            # Вызываем агента (он сам решит, когда вызывать tools)
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            callback = AnalysisCallbackHandler(agent_name="summary")
            
            result = safe_agent_invoke(
                agent,
                llm,
                {
                    "messages": [initial_message],
                    "case_id": case_id
                },
                config={"recursion_limit": 15, "callbacks": [callback]}
            )
            
            # Извлекаем ответ
            if isinstance(result, dict):
                messages = result.get("messages", [])
                if messages:
                    response_message = messages[-1]
                    summary_text = response_message.content if hasattr(response_message, 'content') else str(response_message)
                else:
                    summary_text = str(result)
            else:
                summary_text = str(result)
        else:
            # GigaChat без tools - используем прямой подход
            logger.info("Using direct approach (GigaChat without tools)")
            
            # Используем helper для прямого вызова LLM
            from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            
            # Create callback for logging
            callback = AnalysisCallbackHandler(agent_name="summary")
            
            prompt = get_agent_prompt("summary")
            user_query = f"""Создай краткое резюме дела на основе следующих ключевых фактов:

{key_facts_text}

Создай структурированное резюме с разделами:
1. Суть дела
2. Стороны спора
3. Ключевые факты
4. Основные даты
5. Текущий статус"""
            
            # Для summary можем использовать RAG, если нужно, но обычно достаточно key_facts
            if rag_service:
                summary_text = direct_llm_call_with_rag(
                    case_id=case_id,
                    system_prompt=prompt,
                    user_query=user_query,
                    rag_service=rag_service,
                    db=db,
                    k=10,  # Меньше документов для summary
                    temperature=0.3,
                    callbacks=[callback]
                )
            else:
                # Прямой вызов без RAG (используем только key_facts)
                messages = [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_query}
                ]
                response = llm.invoke([HumanMessage(content=user_query)])
                summary_text = response.content if hasattr(response, 'content') else str(response)
        
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
