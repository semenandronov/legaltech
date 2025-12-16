"""Key facts agent node for LangGraph"""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
import logging
import json

logger = logging.getLogger(__name__)


def key_facts_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Key facts agent node for extracting key facts from documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with key_facts_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Key facts agent: Starting extraction for case {case_id}")
        
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
            temperature=0.3,
            max_tokens=2000
        )
        
        # Get prompt
        prompt = get_agent_prompt("key_facts")
        
        # Create agent
        agent = create_react_agent(llm, tools, messages_modifier=prompt)
        
        # Create initial message
        from langchain_core.messages import HumanMessage
        initial_message = HumanMessage(
            content=f"Извлеки ключевые факты из документов дела {case_id}. Используй retrieve_documents_tool для поиска документов."
        )
        
        # Run agent
        result = agent.invoke({
            "messages": [initial_message],
            "case_id": case_id
        })
        
        # Extract key facts from response
        response_text = result.get("messages", [])[-1].content if isinstance(result, dict) else str(result)
        
        # Try to extract JSON from response
        key_facts_data = None
        try:
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0].strip()
                key_facts_data = json.loads(json_text)
            elif "[" in response_text and "]" in response_text:
                start = response_text.find("[")
                end = response_text.rfind("]") + 1
                if start >= 0 and end > start:
                    json_text = response_text[start:end]
                    key_facts_data = json.loads(json_text)
        except Exception as e:
            logger.warning(f"Could not parse JSON from key facts agent response: {e}")
        
        # If we have key facts data, parse it
        if key_facts_data:
            parsed_facts = ParserService.parse_key_facts(json.dumps(key_facts_data) if isinstance(key_facts_data, (list, dict)) else str(key_facts_data))
        else:
            # Fallback: use RAG to extract key facts
            if not rag_service:
                raise ValueError("RAG service required for key facts extraction")
            
            query = "Извлеки ключевые факты: стороны спора, суммы, даты, суть спора, судья, суд"
            relevant_docs = rag_service.retrieve_context(case_id, query, k=20)
            
            # Use LLM to extract key facts
            from app.services.llm_service import LLMService
            llm_service = LLMService()
            
            sources_text = rag_service.format_sources_for_prompt(relevant_docs)
            system_prompt = get_agent_prompt("key_facts")
            user_prompt = f"Извлеки ключевые факты из следующих документов:\n\n{sources_text}"
            
            response = llm_service.generate(system_prompt, user_prompt, temperature=0.3)
            parsed_facts = ParserService.parse_key_facts(response)
        
        # Convert to structured format
        facts_data = {
            "parties": [],
            "amounts": [],
            "dates": [],
            "other": []
        }
        
        for fact_model in parsed_facts:
            fact_dict = {
                "fact_type": fact_model.fact_type,
                "value": fact_model.value,
                "description": fact_model.description,
                "source_document": fact_model.source_document,
                "source_page": fact_model.source_page,
                "confidence": fact_model.confidence
            }
            
            # Categorize facts
            if fact_model.fact_type in ["plaintiff", "defendant", "party"]:
                facts_data["parties"].append(fact_dict)
            elif fact_model.fact_type in ["amount", "payment", "penalty", "cost"]:
                facts_data["amounts"].append(fact_dict)
            elif fact_model.fact_type in ["date", "deadline", "event_date"]:
                facts_data["dates"].append(fact_dict)
            else:
                facts_data["other"].append(fact_dict)
        
        # Save to database
        result_id = None
        if db:
            result = AnalysisResult(
                case_id=case_id,
                analysis_type="key_facts",
                result_data=facts_data,
                status="completed"
            )
            db.add(result)
            db.commit()
            result_id = result.id
        
        logger.info(f"Key facts agent: Extracted {len(parsed_facts)} facts for case {case_id}")
        
        # Create result
        result_data = {
            "facts": facts_data,
            "result_id": result_id,
            "total_facts": len(parsed_facts)
        }
        
        # Update state
        new_state = state.copy()
        new_state["key_facts_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Key facts agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "key_facts",
            "error": str(e)
        })
        new_state["key_facts_result"] = None
        return new_state
