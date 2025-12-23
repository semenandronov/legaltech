"""Timeline agent node for LangGraph"""
from typing import Dict, Any
from app.services.yandex_llm import ChatYandexGPT
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
        
        # Initialize LLM with temperature=0 for deterministic extraction
        # Только YandexGPT, без fallback
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) or not config.YANDEX_FOLDER_ID:
            raise ValueError("YANDEX_API_KEY/YANDEX_IAM_TOKEN и YANDEX_FOLDER_ID должны быть настроены")
        
        # YandexGPT не поддерживает инструменты, используем прямой RAG подход
        if not rag_service:
            raise ValueError("RAG service required for timeline extraction")
        
        # Используем helper для прямого вызова LLM с RAG
        from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
        
        prompt = get_agent_prompt("timeline")
        user_query = f"Извлеки все даты и события из документов дела {case_id}. Верни результат в формате JSON массива событий с полями: date, event_type, description, source_document, source_page."
        
        response_text = direct_llm_call_with_rag(
            case_id=case_id,
            system_prompt=prompt,
            user_query=user_query,
            rag_service=rag_service,
            db=db,
            k=20,
            temperature=0.1
        )
        
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
            
            # Use LLM with structured output for timeline extraction
            from langchain_core.prompts import ChatPromptTemplate
            from app.services.langchain_parsers import TimelineEventModel
            from typing import List
            
            sources_text = rag_service.format_sources_for_prompt(relevant_docs)
            system_prompt = get_agent_prompt("timeline")
            user_prompt = f"Извлеки все даты и события из следующих документов:\n\n{sources_text}"
            
            # Try to use structured output if supported
            try:
                # Use with_structured_output for guaranteed structured response
                structured_llm = llm.with_structured_output(List[TimelineEventModel])
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", user_prompt)
                ])
                chain = prompt | structured_llm
                parsed_events = chain.invoke({})
            except Exception as e:
                logger.warning(f"Structured output not supported, falling back to JSON parsing: {e}")
                # Fallback to direct LLM call and parsing
                from app.services.llm_service import LLMService
                llm_service = LLMService()
                response = llm_service.generate(system_prompt, user_prompt, temperature=0)
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
                    
                    # Create timeline event with reasoning and confidence
                    event = TimelineEvent(
                        case_id=case_id,
                        date=event_date,
                        event_type=event_model.event_type,
                        description=event_model.description,
                        source_document=event_model.source_document,
                        source_page=event_model.source_page,
                        source_line=event_model.source_line,
                        event_metadata={
                            "parsed_from_agent": True,
                            "reasoning": event_model.reasoning,
                            "confidence": event_model.confidence
                        }
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
                    "source_line": event.source_line if hasattr(event, 'source_line') else event_model.source_line,
                    "reasoning": (event.event_metadata.get("reasoning", "") if event.event_metadata else "") if hasattr(event, 'event_metadata') else (event_model.reasoning if hasattr(event_model, 'reasoning') else ""),
                    "confidence": (event.event_metadata.get("confidence", 0.0) if event.event_metadata else 0.0) if hasattr(event, 'event_metadata') else (event_model.confidence if hasattr(event_model, 'confidence') else 0.0)
                }
                for event, event_model in zip(saved_events, parsed_events) if saved_events
            ] or [
                {
                    "date": event.date,
                    "event_type": event.event_type,
                    "description": event.description,
                    "source_document": event.source_document,
                    "source_page": event.source_page,
                    "source_line": event.source_line,
                    "reasoning": (event.event_metadata.get("reasoning", "") if event.event_metadata else "") if hasattr(event, 'event_metadata') else "",
                    "confidence": (event.event_metadata.get("confidence", 0.0) if event.event_metadata else 0.0) if hasattr(event, 'event_metadata') else 0.0
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
