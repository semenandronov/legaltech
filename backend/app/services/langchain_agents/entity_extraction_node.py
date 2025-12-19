"""Entity extraction agent node for LangGraph"""
from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService, EntitiesExtractionModel
from sqlalchemy.orm import Session
from app.models.case import File
import logging

logger = logging.getLogger(__name__)


def entity_extraction_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
    file_id: Optional[str] = None
) -> AnalysisState:
    """
    Entity extraction agent node for extracting named entities (NER)
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
        file_id: Optional file ID to extract entities from (if None, extracts from all files)
    
    Returns:
        Updated state with entities_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Entity extraction agent: Starting extraction for case {case_id}, file_id={file_id}")
        
        if not db:
            raise ValueError("Database session required for entity extraction")
        
        # Get file(s) to extract entities from
        if file_id:
            files = db.query(File).filter(File.id == file_id, File.case_id == case_id).all()
        else:
            files = db.query(File).filter(File.case_id == case_id).all()
        
        if not files:
            logger.warning(f"No files found for entity extraction in case {case_id}")
            new_state = state.copy()
            new_state["entities_result"] = None
            return new_state
        
        # Initialize LLM with temperature=0 for deterministic extraction
        llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0,  # Детерминизм критичен для извлечения сущностей
            max_tokens=2000
        )
        
        # Get entity extraction prompt
        from app.services.langchain_agents.prompts import get_agent_prompt
        system_prompt = get_agent_prompt("entity_extraction")
        
        # Extract entities from each file
        all_entities = []
        
        for file in files:
            try:
                # Get document text
                document_text = file.original_text or ""
                if not document_text:
                    logger.warning(f"File {file.id} has no text content, skipping entity extraction")
                    continue
                
                # Limit text to avoid token limits
                limited_text = document_text[:5000]
                
                # Create prompt for entity extraction
                user_prompt = f"""ДОКУМЕНТ:
{limited_text}

Извлеки из документа ВСЕ юридически значимые сущности."""
                
                # Try to use structured output
                try:
                    structured_llm = llm.with_structured_output(EntitiesExtractionModel)
                    prompt = ChatPromptTemplate.from_messages([
                        ("system", system_prompt),
                        ("human", user_prompt)
                    ])
                    chain = prompt | structured_llm
                    entities_result = chain.invoke({})
                except Exception as e:
                    logger.warning(f"Structured output not supported, falling back to JSON parsing: {e}")
                    # Fallback to direct LLM call
                    from app.services.llm_service import LLMService
                    llm_service = LLMService()
                    response = llm_service.generate(system_prompt, user_prompt, temperature=0)
                    entities_result = ParserService.parse_entities(response)
                
                # Add file metadata to entities
                for entity in entities_result.entities:
                    all_entities.append({
                        "file_id": file.id,
                        "file_name": file.filename,
                        "text": entity.text,
                        "type": entity.type,
                        "confidence": entity.confidence,
                        "context": entity.context
                    })
                
                logger.info(
                    f"Extracted {len(entities_result.entities)} entities from file {file.id}"
                )
                
                # Save entities to database
                from app.models.analysis import ExtractedEntity
                for entity in entities_result.entities:
                    extracted_entity = ExtractedEntity(
                        case_id=case_id,
                        file_id=file.id,
                        entity_text=entity.text,
                        entity_type=entity.type,
                        confidence=str(entity.confidence),
                        context=entity.context,
                        source_document=file.filename,
                        source_page=None,  # Could be extracted from chunk metadata if available
                        source_line=None
                    )
                    db.add(extracted_entity)
                
            except Exception as e:
                logger.error(f"Error extracting entities from file {file.id}: {e}", exc_info=True)
                try:
                    db.rollback()
                except:
                    pass
                continue
        
        # Group entities by type
        entities_by_type = {}
        for entity in all_entities:
            entity_type = entity["type"]
            if entity_type not in entities_by_type:
                entities_by_type[entity_type] = []
            entities_by_type[entity_type].append(entity)
        
        # Create result
        result_data = {
            "entities": all_entities,
            "entities_by_type": entities_by_type,
            "total_entities": len(all_entities),
            "by_type_count": {etype: len(entities) for etype, entities in entities_by_type.items()}
        }
        
        # Commit all entities
        if db:
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Error committing entities: {e}", exc_info=True)
        
        logger.info(
            f"Entity extraction agent: Extracted {len(all_entities)} entities from {len(files)} files, "
            f"types: {list(entities_by_type.keys())}"
        )
        
        # Update state
        new_state = state.copy()
        new_state["entities_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Entity extraction agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "entity_extraction",
            "error": str(e)
        })
        new_state["entities_result"] = None
        return new_state

