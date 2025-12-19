"""Timeline agent node for LangGraph"""
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from sqlalchemy.orm import Session
from app.models.analysis import TimelineEvent
import logging
import json

logger = logging.getLogger(__name__)


def timeline_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Timeline agent node for extracting timeline events from documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with timeline_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Timeline agent: Starting extraction for case {case_id}")
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools for timeline agent
        tools = get_all_tools()
        
        # Initialize LLM
        llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.3,  # Lower temperature for more consistent extraction
            max_tokens=2000
        )
        
        # Get prompt
        prompt = get_agent_prompt("timeline")
        
        # Create agent
        agent = create_legal_agent(llm, tools, system_prompt=prompt)
        
        # Create initial message
        from langchain_core.messages import HumanMessage
        initial_message = HumanMessage(
            content=f"Извлеки все даты и события из документов дела {case_id}. Используй retrieve_documents_tool для поиска документов."
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
        
        # Extract timeline data from agent response
        # The agent should have used save_timeline_tool, but we also parse the response
        response_text = result.get("messages", [])[-1].content if isinstance(result, dict) else str(result)
        
        # Try to extract JSON from response
        timeline_data = None
        try:
            # Look for JSON in the response
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0].strip()
                timeline_data = json.loads(json_text)
            elif "[" in response_text and "]" in response_text:
                # Try to extract JSON array
                start = response_text.find("[")
                end = response_text.rfind("]") + 1
                if start >= 0 and end > start:
                    json_text = response_text[start:end]
                    timeline_data = json.loads(json_text)
        except Exception as e:
            logger.warning(f"Could not parse JSON from timeline agent response: {e}")
        
        # If we have timeline data, parse and save
        if timeline_data:
            parsed_events = ParserService.parse_timeline_events(json.dumps(timeline_data) if isinstance(timeline_data, (list, dict)) else str(timeline_data))
        else:
            # Fallback: use RAG to extract timeline
            if not rag_service:
                raise ValueError("RAG service required for timeline extraction")
            
            query = "Найди все даты и события в хронологическом порядке с указанием источников"
            relevant_docs = rag_service.retrieve_context(case_id, query, k=20)
            
            # Use LLM to extract timeline
            from app.services.llm_service import LLMService
            llm_service = LLMService()
            
            sources_text = rag_service.format_sources_for_prompt(relevant_docs)
            system_prompt = get_agent_prompt("timeline")
            user_prompt = f"Извлеки все даты и события из следующих документов:\n\n{sources_text}"
            
            response = llm_service.generate(system_prompt, user_prompt, temperature=0.3)
            parsed_events = ParserService.parse_timeline_events(response)
        
        # Save events to database
        saved_events = []
        if db and parsed_events:
            from datetime import datetime
            
            for event_model in parsed_events:
                try:
                    # Parse date
                    date_str = event_model.date
                    try:
                        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except:
                        # Try other date formats or use current date
                        event_date = datetime.now().date()
                    
                    # Create timeline event
                    event = TimelineEvent(
                        case_id=case_id,
                        date=event_date,
                        event_type=event_model.event_type,
                        description=event_model.description,
                        source_document=event_model.source_document,
                        source_page=event_model.source_page,
                        source_line=event_model.source_line,
                        event_metadata={"parsed_from_agent": True}
                    )
                    db.add(event)
                    saved_events.append(event)
                except Exception as e:
                    logger.warning(f"Ошибка при сохранении события: {e}, event: {event_model}")
                    continue
            
            if saved_events:
                db.commit()
        
        # Create result
        result_data = {
            "events": [
                {
                    "id": event.id if hasattr(event, 'id') else None,
                    "date": event.date.isoformat() if hasattr(event, 'date') and event.date else event_model.date,
                    "event_type": event.event_type if hasattr(event, 'event_type') else event_model.event_type,
                    "description": event.description if hasattr(event, 'description') else event_model.description,
                    "source_document": event.source_document if hasattr(event, 'source_document') else event_model.source_document,
                    "source_page": event.source_page if hasattr(event, 'source_page') else event_model.source_page,
                    "source_line": event.source_line if hasattr(event, 'source_line') else event_model.source_line
                }
                for event, event_model in zip(saved_events, parsed_events) if saved_events
            ] or [
                {
                    "date": event.date,
                    "event_type": event.event_type,
                    "description": event.description,
                    "source_document": event.source_document,
                    "source_page": event.source_page,
                    "source_line": event.source_line
                }
                for event in parsed_events
            ],
            "total_events": len(parsed_events)
        }
        
        logger.info(f"Timeline agent: Extracted {len(parsed_events)} events for case {case_id}")
        
        # Update state
        new_state = state.copy()
        new_state["timeline_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Timeline agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "timeline",
            "error": str(e)
        })
        new_state["timeline_result"] = None
        return new_state
