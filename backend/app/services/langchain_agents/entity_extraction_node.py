"""Entity extraction agent node for LangGraph"""
from typing import Dict, Any, Optional, List
from app.services.llm_factory import create_llm, create_legal_llm
from langchain_core.prompts import ChatPromptTemplate
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService, EntitiesExtractionModel
from app.services.regex_extractor import RegexExtractor
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
        
        # Initialize LLM через factory (GigaChat) - temperature=0.0 для детерминизма
        # Use use_rate_limiting=False for LangChain | operator compatibility
        llm = create_legal_llm(use_rate_limiting=False)
        
        # Get entity extraction prompt
        from app.services.langchain_agents.prompts import get_agent_prompt
        system_prompt = get_agent_prompt("entity_extraction")
        
        # Initialize regex extractor for pre-processing
        regex_extractor = RegexExtractor()
        
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
                
                # Pre-processing: используем regex для извлечения дат и сумм
                regex_results = regex_extractor.extract_all(limited_text)
                regex_hints = []
                
                # Формируем hints для LLM на основе результатов regex
                if regex_results.get("dates"):
                    dates_str = ", ".join([f"{d.get('date')} ({d.get('original_text')})" for d in regex_results["dates"][:10]])
                    regex_hints.append(f"Найденные даты (regex): {dates_str}")
                
                if regex_results.get("amounts"):
                    amounts_str = ", ".join([f"{a.get('amount')} {a.get('currency', '')}" for a in regex_results["amounts"][:10]])
                    regex_hints.append(f"Найденные суммы (regex): {amounts_str}")
                
                if regex_results.get("entities"):
                    entities_str = ", ".join([f"{e.get('text')} ({e.get('type')})" for e in regex_results["entities"][:10]])
                    regex_hints.append(f"Найденные сущности (regex): {entities_str}")
                
                hints_text = "\n".join(regex_hints) if regex_hints else ""
                
                # Create prompt for entity extraction with regex hints
                user_prompt = f"""ДОКУМЕНТ:
{limited_text}
{hints_text if hints_text else ''}

Извлеки из документа ВСЕ юридически значимые сущности. Используй информацию из regex как hints для более точного извлечения."""
                
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
                    # Fallback to direct LLM call using GigaChat
                    try:
                        from langchain_core.prompts import ChatPromptTemplate
                        prompt = ChatPromptTemplate.from_messages([
                            ("system", system_prompt),
                            ("human", user_prompt)
                        ])
                        chain = prompt | llm
                        response = chain.invoke({})
                        response_text = response.content if hasattr(response, 'content') else str(response)
                        entities_result = ParserService.parse_entities(response_text)
                    except Exception as fallback_error:
                        logger.error(f"Fallback LLM call failed: {fallback_error}, using empty entities")
                        from app.services.langchain_parsers import EntitiesExtractionModel
                        entities_result = EntitiesExtractionModel(entities=[])
                
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
        
        # Save frequently occurring entities to LangGraph Store
        if db and all_entities:
            try:
                from app.services.langchain_agents.store_service import LangGraphStoreService
                from app.models.case import Case
                import asyncio
                
                store_service = LangGraphStoreService(db)
                
                # Get case type for namespace
                case = db.query(Case).filter(Case.id == case_id).first()
                case_type = "general"
                if case and case.case_type:
                    case_type = case.case_type.lower().replace(" ", "_")
                
                # Save entities that appear frequently (more than once) or have high confidence
                entity_counts = {}
                for entity in all_entities:
                    entity_text = entity.get("text", "")
                    entity_type = entity.get("type", "")
                    key = f"{entity_text}_{entity_type}"
                    if key not in entity_counts:
                        entity_counts[key] = {"count": 0, "entity": entity}
                    entity_counts[key]["count"] += 1
                
                # Save entities that appear multiple times or have high confidence
                saved_count = 0
                for key, data in entity_counts.items():
                    entity = data["entity"]
                    count = data["count"]
                    confidence = float(entity.get("confidence", 0.5))
                    
                    # Save if appears multiple times or has high confidence
                    if count > 1 or confidence > 0.8:
                        namespace = f"entities/{case_type}/{entity.get('type', 'unknown')}"
                        entity_value = {
                            "text": entity.get("text", ""),
                            "type": entity.get("type", ""),
                            "confidence": confidence,
                            "context": entity.get("context", ""),
                            "occurrence_count": count
                        }
                        
                        metadata = {
                            "case_id": case_id,
                            "saved_at": datetime.now().isoformat(),
                            "source": "entity_extraction_agent",
                            "file_name": entity.get("file_name", "")
                        }
                        
                        # Use run_async_safe for async call from sync function
                        from app.utils.async_utils import run_async_safe
                        try:
                            run_async_safe(store_service.save_pattern(
                                namespace=namespace,
                                key=entity.get("text", "")[:200],
                                value=entity_value,
                                metadata=metadata
                            ))
                            saved_count += 1
                        except Exception as e:
                            logger.warning(f"Failed to save entity pattern: {e}")
                
                if saved_count > 0:
                    logger.info(f"Saved {saved_count} frequently occurring entities to Store")
            except Exception as e:
                logger.warning(f"Failed to save entities to Store: {e}")
        
        # Save to file system (DeepAgents pattern)
        try:
            from app.services.langchain_agents.file_system_helper import save_agent_result_to_file
            save_agent_result_to_file(state, "entities", result_data)
        except Exception as fs_error:
            logger.debug(f"Failed to save entities result to file: {fs_error}")
        
        # Update state
        new_state = state.copy()
        
        # Оптимизация: сохранить большие результаты в Store
        from app.services.langchain_agents.store_helper import (
            should_store_result,
            save_large_result_to_store
        )
        
        if should_store_result(result_data):
            # Сохранить в Store и получить ссылку
            entities_ref = save_large_result_to_store(
                state=state,
                result_key="entities_result",
                data=result_data,
                case_id=case_id
            )
            new_state["entities_ref"] = entities_ref
            # Сохранить summary в state для быстрого доступа
            if entities_ref.get("summary"):
                new_state["entities_summary"] = entities_ref["summary"]
            logger.info(f"Entities result stored in Store (size: {len(all_entities)} entities)")
        else:
            # Маленький результат - сохранить напрямую в state
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

