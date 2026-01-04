"""Tools for LangChain agents in multi-agent analysis system"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from langchain_core.documents import Document
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.tool_schemas import DocumentSearchInput
from app.services.langchain_agents.tool_runtime import ToolRuntime
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


@tool(args_schema=DocumentSearchInput)
def retrieve_documents_tool(
    query: str,
    case_id: str,
    k: int = 20,
    use_iterative: bool = False,
    use_hybrid: bool = False,
    doc_types: Optional[List[str]] = None,
    **kwargs
) -> str:
    """
    Retrieve relevant documents from the case using semantic search.
    
    Use this tool to find documents related to a specific query.
    For critical analysis (risk, discrepancy), use_iterative=True or use_hybrid=True for better relevance.
    
    Args:
        query: Search query describing what information you need
        case_id: Case identifier
        k: Number of document chunks to retrieve (default: 20)
        use_iterative: If True, uses iterative search with query refinement (default: False)
        use_hybrid: If True, uses hybrid search (combines semantic + keyword search) (default: False)
                    Recommended for critical agents (risk, discrepancy)
        doc_types: Optional list of document types to filter by (e.g., ['statement_of_claim', 'contract'])
                   Use this when the user asks to work with specific document types
        **kwargs: Дополнительные параметры (runtime инжектируется middleware через kwargs)
    
    Returns:
        Formatted string with retrieved documents and their sources
    """
    # Проверяем, есть ли runtime в kwargs (инжектируется middleware)
    runtime: Optional[ToolRuntime] = kwargs.get("runtime")
    
    try:
        # Новый путь: использовать runtime.store если доступен
        if runtime and runtime.store:
            filters = {"doc_types": doc_types} if doc_types else None
            retrieval_strategy = "iterative" if use_iterative else ("hybrid" if use_hybrid else "multi_query")
            
            documents = runtime.store.search(
                query=query,
                filters=filters,
                k=k,
                retrieval_strategy=retrieval_strategy,
                use_iterative=use_iterative,
                use_hybrid=use_hybrid
            )
            
            # Форматируем документы через RAG service
            if documents and runtime.store.rag_service:
                formatted_docs = runtime.store.rag_service.format_sources_for_prompt(documents)
                logger.info(f"Retrieved {len(documents)} documents via runtime.store for query: {query[:50]}...")
                return formatted_docs
            elif documents:
                # Простое форматирование если нет доступа к format_sources_for_prompt
                formatted_parts = []
                for i, doc in enumerate(documents[:k], 1):
                    content = doc.page_content[:500] if hasattr(doc, 'page_content') else str(doc)[:500]
                    source = doc.metadata.get("source_file", "unknown") if hasattr(doc, 'metadata') else "unknown"
                    formatted_parts.append(f"[{i}] {source}\n{content}...")
                return "\n\n".join(formatted_parts)
        
        # Старый путь: fallback на глобальный _rag_service (обратная совместимость)
        if not _rag_service:
            raise ValueError("RAG service not initialized. Call initialize_tools() first.")
        
        # Use hybrid search if requested (best for critical agents)
        if use_hybrid:
            logger.info(f"Using hybrid search for query: {query[:50]}... (fallback mode)")
            documents = _rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=k,
                retrieval_strategy="hybrid",
                use_hybrid=True,
                doc_types=doc_types
            )
        # Use iterative search if requested (better for critical agents)
        elif use_iterative:
            logger.info(f"Using iterative search for query: {query[:50]}... (fallback mode)")
            documents = _rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=k,
                retrieval_strategy="iterative",
                use_iterative=True,
                doc_types=doc_types
            )
        else:
            # Retrieve relevant documents with multi_query (better than simple search)
            documents = _rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=k,
                retrieval_strategy="multi_query",
                doc_types=doc_types
            )
        
        if not documents:
            return "No relevant documents found for the query."
        
        # Format documents for agent
        formatted_docs = _rag_service.format_sources_for_prompt(documents)
        
        logger.info(f"Retrieved {len(documents)} documents for query: {query[:50]}... (iterative={use_iterative}, fallback mode)")
        return formatted_docs
    except Exception as e:
        logger.error(f"Error retrieving documents: {e}")
        return f"Error retrieving documents: {str(e)}"


@tool(args_schema=SaveTimelineInput)
def save_timeline_tool(timeline_data: str, case_id: str, **kwargs) -> str:
    """
    Save timeline extraction results to the state and database.
    
    Use this tool after extracting timeline events from documents.
    
    Args:
        timeline_data: JSON string with timeline events
        case_id: Case identifier
        **kwargs: Дополнительные параметры (runtime инжектируется middleware через kwargs)
    
    Returns:
        Success message
    """
    # Проверяем, есть ли runtime в kwargs (инжектируется middleware)
    runtime: Optional[ToolRuntime] = kwargs.get("runtime")
    
    try:
        import json
        from app.services.langchain_parsers import ParserService
        
        # Используем case_id из runtime если доступен
        actual_case_id = runtime.case_id if runtime else case_id
        
        # Parse timeline data
        events = ParserService.parse_timeline_events(timeline_data)
        
        # Save to database (will be done in the node, this is just for state)
        logger.info(f"Timeline tool: Parsed {len(events)} events for case {actual_case_id}")
        
        # Сохраняем событие анализа через runtime.store если доступен
        if runtime and runtime.store:
            runtime.store.save_analysis_event(
                event_type="timeline_extraction",
                data={"events_count": len(events), "case_id": actual_case_id}
            )
        
        return f"Successfully processed {len(events)} timeline events."
    except Exception as e:
        logger.error(f"Error in save_timeline_tool: {e}")
        return f"Error saving timeline: {str(e)}"


@tool(args_schema=SaveKeyFactsInput)
def save_key_facts_tool(key_facts_data: str, case_id: str, **kwargs) -> str:
    """
    Save key facts extraction results to the state and database.
    
    Use this tool after extracting key facts from documents.
    
    Args:
        key_facts_data: JSON string with key facts
        case_id: Case identifier
        **kwargs: Дополнительные параметры (runtime инжектируется middleware через kwargs)
    
    Returns:
        Success message
    """
    # Проверяем, есть ли runtime в kwargs (инжектируется middleware)
    runtime: Optional[ToolRuntime] = kwargs.get("runtime")
    
    try:
        import json
        from app.services.langchain_parsers import ParserService
        
        # Используем case_id из runtime если доступен
        actual_case_id = runtime.case_id if runtime else case_id
        
        # Parse key facts
        facts = ParserService.parse_key_facts(key_facts_data)
        
        logger.info(f"Key facts tool: Parsed {len(facts)} facts for case {actual_case_id}")
        
        # Сохраняем событие анализа через runtime.store если доступен
        if runtime and runtime.store:
            runtime.store.save_analysis_event(
                event_type="key_facts_extraction",
                data={"facts_count": len(facts), "case_id": actual_case_id}
            )
        
        return f"Successfully processed {len(facts)} key facts."
    except Exception as e:
        logger.error(f"Error in save_key_facts_tool: {e}")
        return f"Error saving key facts: {str(e)}"


@tool(args_schema=SaveDiscrepancyInput)
def save_discrepancy_tool(discrepancy_data: str, case_id: str, **kwargs) -> str:
    """
    Save discrepancy findings to the state and database.
    
    Use this tool after finding discrepancies between documents.
    
    Args:
        discrepancy_data: JSON string with discrepancies
        case_id: Case identifier
        **kwargs: Дополнительные параметры (runtime инжектируется middleware через kwargs)
    
    Returns:
        Success message
    """
    # Проверяем, есть ли runtime в kwargs (инжектируется middleware)
    runtime: Optional[ToolRuntime] = kwargs.get("runtime")
    
    try:
        import json
        from app.services.langchain_parsers import ParserService
        
        # Используем case_id из runtime если доступен
        actual_case_id = runtime.case_id if runtime else case_id
        
        # Parse discrepancies
        discrepancies = ParserService.parse_discrepancies(discrepancy_data)
        
        logger.info(f"Discrepancy tool: Parsed {len(discrepancies)} discrepancies for case {actual_case_id}")
        
        # Сохраняем событие анализа через runtime.store если доступен
        if runtime and runtime.store:
            runtime.store.save_analysis_event(
                event_type="discrepancy_finding",
                data={"discrepancies_count": len(discrepancies), "case_id": actual_case_id}
            )
        
        return f"Successfully processed {len(discrepancies)} discrepancies."
    except Exception as e:
        logger.error(f"Error in save_discrepancy_tool: {e}")
        return f"Error saving discrepancies: {str(e)}"


@tool(args_schema=SaveRiskInput)
def save_risk_analysis_tool(risk_data: str, case_id: str, **kwargs) -> str:
    """
    Save risk analysis results to the state and database.
    
    Use this tool after analyzing risks based on discrepancies.
    
    КРИТИЧНЫЙ TOOL - требует human approval перед сохранением (Фаза 9.2)
    
    Args:
        risk_data: JSON string or text with risk analysis
        case_id: Case identifier
        **kwargs: Дополнительные параметры (runtime инжектируется middleware через kwargs)
    
    Returns:
        Success message
    """
    # Проверяем, есть ли runtime в kwargs (инжектируется middleware)
    runtime: Optional[ToolRuntime] = kwargs.get("runtime")
    
    # Фаза 9.2: Проверяем requires_approval флаг
    requires_approval = True  # Критичный tool - всегда требует одобрения
    
    if requires_approval and runtime:
        try:
            from app.services.langchain_agents.human_feedback import get_feedback_service
            feedback_service = get_feedback_service()
            
            # Запрашиваем одобрение
            action = f"Сохранение анализа рисков для дела {runtime.case_id}"
            approved = feedback_service.request_approval(
                case_id=runtime.case_id,
                action=action,
                context={"tool": "save_risk_analysis"},
                timeout=300  # 5 минут таймаут
            )
            
            if not approved:
                logger.warning(f"Risk analysis tool: Approval denied for case {runtime.case_id}")
                return "Сохранение анализа рисков отклонено пользователем."
        except Exception as approval_error:
            logger.warning(f"Error requesting approval for risk tool: {approval_error}")
            # Продолжаем выполнение если approval service недоступен
    
    try:
        # Используем case_id из runtime если доступен
        actual_case_id = runtime.case_id if runtime else case_id
        
        logger.info(f"Risk analysis tool: Processing risk data for case {actual_case_id}")
        
        # Сохраняем событие анализа через runtime.store если доступен
        if runtime and runtime.store:
            runtime.store.save_analysis_event(
                event_type="risk_analysis",
                data={"case_id": actual_case_id}
            )
        
        return "Successfully processed risk analysis."
    except Exception as e:
        logger.error(f"Error in save_risk_analysis_tool: {e}")
        return f"Error saving risk analysis: {str(e)}"


@tool(args_schema=SaveSummaryInput)
def save_summary_tool(summary_data: str, case_id: str, **kwargs) -> str:
    """
    Save case summary to the state and database.
    
    Use this tool after generating a summary based on key facts.
    
    Args:
        summary_data: Text with case summary
        case_id: Case identifier
        **kwargs: Дополнительные параметры (runtime инжектируется middleware через kwargs)
    
    Returns:
        Success message
    """
    # Проверяем, есть ли runtime в kwargs (инжектируется middleware)
    runtime: Optional[ToolRuntime] = kwargs.get("runtime")
    
    try:
        # Используем case_id из runtime если доступен
        actual_case_id = runtime.case_id if runtime else case_id
        
        logger.info(f"Summary tool: Processing summary for case {actual_case_id}")
        
        # Сохраняем событие анализа через runtime.store если доступен
        if runtime and runtime.store:
            runtime.store.save_analysis_event(
                event_type="summary_generation",
                data={"case_id": actual_case_id}
            )
        
        return "Successfully processed case summary."
    except Exception as e:
        logger.error(f"Error in save_summary_tool: {e}")
        return f"Error saving summary: {str(e)}"


@tool
def retrieve_documents_iterative_tool(query: str, case_id: str, k: int = 20, doc_types: Optional[List[str]] = None) -> str:
    """
    Retrieve relevant documents using iterative search with query refinement.
    
    This tool automatically refines the search query and improves document relevance.
    Use this for critical analysis tasks like risk assessment or discrepancy detection.
    Better than retrieve_documents_tool for complex queries that need multiple refinement iterations.
    
    Args:
        query: Search query describing what information you need
        case_id: Case identifier
        k: Number of document chunks to retrieve (default: 20)
        doc_types: Optional list of document types to filter by (e.g., ['statement_of_claim', 'contract'])
                   Use this when the user asks to work with specific document types
    
    Returns:
        Formatted string with retrieved documents and their sources
    """
    if not _rag_service:
        raise ValueError("RAG service not initialized. Call initialize_tools() first.")
    
    try:
        # Always use iterative search for this tool
        logger.info(f"Using iterative search tool for query: {query[:50]}...")
        documents = _rag_service.retrieve_context(
            case_id=case_id,
            query=query,
            k=k,
            retrieval_strategy="iterative",
            use_iterative=True,
            doc_types=doc_types
        )
        
        if not documents:
            return "No relevant documents found for the query after iterative refinement."
        
        # Format documents for agent
        formatted_docs = _rag_service.format_sources_for_prompt(documents)
        
        logger.info(f"Iterative search retrieved {len(documents)} documents for query: {query[:50]}...")
        return formatted_docs
    except Exception as e:
        logger.error(f"Error in iterative document retrieval: {e}")
        return f"Error retrieving documents with iterative search: {str(e)}"


def get_all_tools() -> List:
    """Get all available tools including official legal sources"""
    from app.services.langchain_agents.legal_research_tool import get_legal_research_tools
    from app.services.langchain_agents.file_system_tools import get_file_system_tools
    from app.services.langchain_agents.web_research_tool import web_research_tool
    from app.services.langchain_agents.table_creator_tool import create_table_tool
    from app.services.langchain_agents.official_legal_sources_tool import (
        search_legislation_tool,
        search_supreme_court_tool,
        search_case_law_tool,
        smart_legal_search_tool
    )
    
    tools = [
        retrieve_documents_tool,
        retrieve_documents_iterative_tool,
        save_timeline_tool,
        save_key_facts_tool,
        save_discrepancy_tool,
        save_risk_analysis_tool,
        save_summary_tool,
        web_research_tool,  # Add web research tool
    ]
    
    # Add official legal sources tools
    try:
        tools.extend([
            search_legislation_tool,
            search_supreme_court_tool,
            search_case_law_tool,
            smart_legal_search_tool
        ])
        logger.debug("Official legal sources tools added to agent tools")
    except Exception as e:
        logger.warning(f"Official legal sources tools not available: {e}")
    
    # Add legal research tools
    try:
        legal_research_tools = get_legal_research_tools()
        tools.extend(legal_research_tools)
        logger.debug("Legal research tools added to agent tools")
    except Exception as e:
        logger.warning(f"Legal research tools not available: {e}")
    
    # Add file system tools (always available, auto-initializes if needed)
    try:
        file_system_tools = get_file_system_tools()
        tools.extend(file_system_tools)
        logger.debug("File system tools added to agent tools")
    except Exception as e:
        logger.warning(f"File system tools not available: {e}")
    
    # Add table creator tool (will be initialized when needed with db session)
    try:
        tools.append(create_table_tool)
        logger.debug("Table creator tool added to agent tools")
    except Exception as e:
        logger.warning(f"Table creator tool not available: {e}")
    
    return tools


def get_critical_agent_tools() -> List:
    """Get tools for critical agents (risk, discrepancy) - includes iterative search and legal research"""
    from app.services.langchain_agents.legal_research_tool import get_legal_research_tools
    from app.services.langchain_agents.file_system_tools import get_file_system_tools
    from app.services.langchain_agents.web_research_tool import web_research_tool
    from app.services.langchain_agents.table_creator_tool import create_table_tool
    from app.services.langchain_agents.official_legal_sources_tool import (
        search_legislation_tool,
        search_supreme_court_tool,
        search_case_law_tool,
        smart_legal_search_tool
    )
    
    tools = [
        retrieve_documents_tool,
        retrieve_documents_iterative_tool,  # Explicit iterative tool for critical agents
        save_discrepancy_tool,
        save_risk_analysis_tool,
        web_research_tool,  # Web research for critical analysis
    ]
    
    # Add official legal sources tools for critical agents
    try:
        tools.extend([
            search_legislation_tool,
            search_supreme_court_tool,
            search_case_law_tool,
            smart_legal_search_tool
        ])
        logger.debug("Official legal sources tools added to critical agent tools")
    except Exception as e:
        logger.warning(f"Official legal sources tools not available: {e}")
    
    # Add legal research tools for critical agents
    try:
        legal_research_tools = get_legal_research_tools()
        tools.extend(legal_research_tools)
        logger.debug("Legal research tools added to critical agent tools")
    except Exception as e:
        logger.warning(f"Legal research tools not available: {e}")
    
    # Add file system tools (always available, auto-initializes if needed)
    try:
        file_system_tools = get_file_system_tools()
        tools.extend(file_system_tools)
        logger.debug("File system tools added to critical agent tools")
    except Exception as e:
        logger.warning(f"File system tools not available: {e}")
    
    # Add table creator tool for critical agents
    try:
        tools.append(create_table_tool)
        logger.debug("Table creator tool added to critical agent tools")
    except Exception as e:
        logger.warning(f"Table creator tool not available: {e}")
    
    return tools
