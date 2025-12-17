"""Tools for LangChain agents in multi-agent analysis system"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from langchain_core.documents import Document
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)

# Global instances (will be initialized per case)
_rag_service: Optional[RAGService] = None
_document_processor: Optional[DocumentProcessor] = None


def initialize_tools(rag_service: RAGService, document_processor: DocumentProcessor):
    """Initialize global tool instances"""
    global _rag_service, _document_processor
    _rag_service = rag_service
    _document_processor = document_processor


@tool
def retrieve_documents_tool(query: str, case_id: str, k: int = 20) -> str:
    """
    Retrieve relevant documents from the case using semantic search.
    
    Use this tool to find documents related to a specific query.
    
    Args:
        query: Search query describing what information you need
        case_id: Case identifier
        k: Number of document chunks to retrieve (default: 20)
    
    Returns:
        Formatted string with retrieved documents and their sources
    """
    if not _rag_service:
        raise ValueError("RAG service not initialized. Call initialize_tools() first.")
    
    try:
        # Retrieve relevant documents
        documents = _rag_service.retrieve_context(
            case_id=case_id,
            query=query,
            k=k,
            retrieval_strategy="multi_query"
        )
        
        if not documents:
            return "No relevant documents found for the query."
        
        # Format documents for agent
        formatted_docs = _rag_service.format_sources_for_prompt(documents)
        
        logger.info(f"Retrieved {len(documents)} documents for query: {query[:50]}...")
        return formatted_docs
    except Exception as e:
        logger.error(f"Error retrieving documents: {e}")
        return f"Error retrieving documents: {str(e)}"


@tool
def save_timeline_tool(timeline_data: str, case_id: str) -> str:
    """
    Save timeline extraction results to the state and database.
    
    Use this tool after extracting timeline events from documents.
    
    Args:
        timeline_data: JSON string with timeline events
        case_id: Case identifier
    
    Returns:
        Success message
    """
    try:
        import json
        from app.services.langchain_parsers import ParserService
        
        # Parse timeline data
        events = ParserService.parse_timeline_events(timeline_data)
        
        # Save to database (will be done in the node, this is just for state)
        logger.info(f"Timeline tool: Parsed {len(events)} events for case {case_id}")
        
        return f"Successfully processed {len(events)} timeline events."
    except Exception as e:
        logger.error(f"Error in save_timeline_tool: {e}")
        return f"Error saving timeline: {str(e)}"


@tool
def save_key_facts_tool(key_facts_data: str, case_id: str) -> str:
    """
    Save key facts extraction results to the state and database.
    
    Use this tool after extracting key facts from documents.
    
    Args:
        key_facts_data: JSON string with key facts
        case_id: Case identifier
    
    Returns:
        Success message
    """
    try:
        import json
        from app.services.langchain_parsers import ParserService
        
        # Parse key facts
        facts = ParserService.parse_key_facts(key_facts_data)
        
        logger.info(f"Key facts tool: Parsed {len(facts)} facts for case {case_id}")
        
        return f"Successfully processed {len(facts)} key facts."
    except Exception as e:
        logger.error(f"Error in save_key_facts_tool: {e}")
        return f"Error saving key facts: {str(e)}"


@tool
def save_discrepancy_tool(discrepancy_data: str, case_id: str) -> str:
    """
    Save discrepancy findings to the state and database.
    
    Use this tool after finding discrepancies between documents.
    
    Args:
        discrepancy_data: JSON string with discrepancies
        case_id: Case identifier
    
    Returns:
        Success message
    """
    try:
        import json
        from app.services.langchain_parsers import ParserService
        
        # Parse discrepancies
        discrepancies = ParserService.parse_discrepancies(discrepancy_data)
        
        logger.info(f"Discrepancy tool: Parsed {len(discrepancies)} discrepancies for case {case_id}")
        
        return f"Successfully processed {len(discrepancies)} discrepancies."
    except Exception as e:
        logger.error(f"Error in save_discrepancy_tool: {e}")
        return f"Error saving discrepancies: {str(e)}"


@tool
def save_risk_analysis_tool(risk_data: str, case_id: str) -> str:
    """
    Save risk analysis results to the state and database.
    
    Use this tool after analyzing risks based on discrepancies.
    
    Args:
        risk_data: JSON string or text with risk analysis
        case_id: Case identifier
    
    Returns:
        Success message
    """
    try:
        logger.info(f"Risk analysis tool: Processing risk data for case {case_id}")
        return "Successfully processed risk analysis."
    except Exception as e:
        logger.error(f"Error in save_risk_analysis_tool: {e}")
        return f"Error saving risk analysis: {str(e)}"


@tool
def save_summary_tool(summary_data: str, case_id: str) -> str:
    """
    Save case summary to the state and database.
    
    Use this tool after generating a summary based on key facts.
    
    Args:
        summary_data: Text with case summary
        case_id: Case identifier
    
    Returns:
        Success message
    """
    try:
        logger.info(f"Summary tool: Processing summary for case {case_id}")
        return "Successfully processed case summary."
    except Exception as e:
        logger.error(f"Error in save_summary_tool: {e}")
        return f"Error saving summary: {str(e)}"


def get_all_tools() -> List:
    """Get all available tools for agents"""
    return [
        retrieve_documents_tool,
        save_timeline_tool,
        save_key_facts_tool,
        save_discrepancy_tool,
        save_risk_analysis_tool,
        save_summary_tool,
    ]
