"""Discrepancy agent node for LangGraph"""
from typing import Dict, Any
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from app.services.citation_verifier import CitationVerifier
from sqlalchemy.orm import Session
from app.models.analysis import Discrepancy
from langchain_core.messages import HumanMessage
import logging
import json

logger = logging.getLogger(__name__)


def discrepancy_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Discrepancy agent node for finding discrepancies in documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with discrepancy_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Discrepancy agent: Starting analysis for case {case_id}")
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools - include iterative search tool for critical agents
        from app.services.langchain_agents.tools import get_critical_agent_tools
        tools = get_critical_agent_tools()
        
        # Initialize LLM через factory (GigaChat)
        llm = create_llm(temperature=0.1)
        
        # Проверяем, поддерживает ли LLM function calling
        use_tools = hasattr(llm, 'bind_tools')
        
        # Get case type for pattern loading
        case_type = "general"
        if db:
            from app.models.case import Case
            case = db.query(Case).filter(Case.id == case_id).first()
            if case and case.case_type:
                case_type = case.case_type.lower().replace(" ", "_").replace("-", "_")
        
        # Загружаем сохраненные паттерны противоречий для этого типа дела
        known_discrepancies_text = ""
        try:
            from app.services.langchain_agents.pattern_loader import PatternLoader
            pattern_loader = PatternLoader(db)
            
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    known_discrepancy_patterns = []
                else:
                    known_discrepancy_patterns = loop.run_until_complete(
                        pattern_loader.load_discrepancy_patterns(case_type, limit=20)
                    )
            except RuntimeError:
                known_discrepancy_patterns = asyncio.run(
                    pattern_loader.load_discrepancy_patterns(case_type, limit=20)
                )
            
            if known_discrepancy_patterns:
                known_discrepancies_text = pattern_loader.format_patterns_for_prompt(
                    known_discrepancy_patterns,
                    pattern_type="discrepancies"
                )
                logger.info(f"Loaded {len(known_discrepancy_patterns)} known discrepancy patterns for case type: {case_type}")
        except Exception as e:
            logger.warning(f"Failed to load discrepancy patterns: {e}")
            known_discrepancies_text = ""
        
        if use_tools and rag_service:
            # GigaChat с function calling - агент сам вызовет retrieve_documents_tool
            logger.info("Using GigaChat with function calling for discrepancy agent")
            
            prompt = get_agent_prompt("discrepancy")
            
            # Добавляем известные противоречия в промпт, если они есть
            if known_discrepancies_text:
                prompt = prompt + "\n\n" + known_discrepancies_text
            
            # Создаем агента с tools
            agent = create_legal_agent(llm, tools, system_prompt=prompt)
            
            # Создаем запрос для агента
            user_query = f"Найди все противоречия и несоответствия между документами дела {case_id}. Используй retrieve_documents_iterative_tool для поиска и сравнения документов. Сначала проверь известные типичные противоречия (указаны в системном промпте), затем ищи новые. Верни результат в формате JSON массива противоречий с полями: type, severity, description, source_documents, details, reasoning, confidence."
            
            initial_message = HumanMessage(content=user_query)
            
            # Вызываем агента (он сам решит, когда вызывать tools)
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            callback = AnalysisCallbackHandler(agent_name="discrepancy")
            
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
                    response_text = response_message.content if hasattr(response_message, 'content') else str(response_message)
                else:
                    response_text = str(result)
            else:
                response_text = str(result)
        else:
            # GigaChat без tools - используем прямой RAG подход
            if not rag_service:
                raise ValueError("RAG service required for discrepancy finding")
            
            logger.info("Using direct RAG approach (GigaChat without tools)")
            
            # Используем helper для прямого вызова LLM с RAG
            from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            
            # Create callback for logging
            callback = AnalysisCallbackHandler(agent_name="discrepancy")
            
            prompt = get_agent_prompt("discrepancy")
            user_query = f"Найди все противоречия и несоответствия между документами дела {case_id}."
            
            response_text = direct_llm_call_with_rag(
                case_id=case_id,
                system_prompt=prompt,
                user_query=user_query,
                rag_service=rag_service,
                db=db,
                k=30,
                temperature=0.1,
                callbacks=[callback]
            )
        
        # Извлекаем JSON из ответа
        discrepancy_data = extract_json_from_response(response_text)
        
        # If we have discrepancy data, parse it
        if discrepancy_data:
            parsed_discrepancies = ParserService.parse_discrepancies(
                json.dumps(discrepancy_data) if isinstance(discrepancy_data, (list, dict)) else str(discrepancy_data)
            )
        else:
            # Fallback: use RAG to find discrepancies
            if not rag_service:
                raise ValueError("RAG service required for discrepancy finding")
            
            query = "Найди все противоречия, несоответствия и расхождения между документами"
            relevant_docs = rag_service.retrieve_context(case_id, query, k=30)
            
            # Use LLM with structured output for discrepancy detection
            from langchain_core.prompts import ChatPromptTemplate
            from app.services.langchain_parsers import DiscrepancyModel
            from typing import List
            
            sources_text = rag_service.format_sources_for_prompt(relevant_docs)
            system_prompt = get_agent_prompt("discrepancy")
            user_prompt = f"Проанализируй следующие документы и найди все противоречия:\n\n{sources_text}"
            
            # Try to use structured output if supported
            try:
                structured_llm = llm.with_structured_output(List[DiscrepancyModel])
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", user_prompt)
                ])
                chain = prompt | structured_llm
                parsed_discrepancies = chain.invoke({})
            except Exception as e:
                logger.warning(f"Structured output not supported, falling back to JSON parsing: {e}")
                # Fallback to direct LLM call and parsing
                from app.services.llm_service import LLMService
                llm_service = LLMService()
                response = llm_service.generate(system_prompt, user_prompt, temperature=0)
                parsed_discrepancies = ParserService.parse_discrepancies(response)
        
        # Verify citations: проверяем что цитаты в противоречиях реально присутствуют в документах
        if parsed_discrepancies and rag_service:
            try:
                citation_verifier = CitationVerifier(similarity_threshold=0.7)
                # Получаем source documents для верификации
                verify_docs = rag_service.retrieve_context(
                    case_id=case_id,
                    query="",
                    k=100,  # Получаем больше документов для верификации
                    db=db
                )
                
                # Верифицируем каждое противоречие (проверяем reasoning с цитатами и description)
                for discrepancy in parsed_discrepancies:
                    verification_result = citation_verifier.verify_extracted_fact(
                        fact=discrepancy if isinstance(discrepancy, dict) else {
                            "reasoning": getattr(discrepancy, 'reasoning', None),
                            "description": getattr(discrepancy, 'description', None),
                            "value": getattr(discrepancy, 'type', None)
                        },
                        source_documents=verify_docs,
                        tolerance=150  # Больше tolerance для противоречий, так как они могут быть сложными
                    )
                    
                    # Устанавливаем verification_status
                    verification_status = "verified" if verification_result.get("verified", False) else "unverified"
                    if hasattr(discrepancy, 'verification_status'):
                        discrepancy.verification_status = verification_status
                        # Снижаем confidence если не верифицировано
                        if not verification_result.get("verified", False):
                            current_confidence = getattr(discrepancy, 'confidence', 0.8)
                            discrepancy.confidence = max(0.3, current_confidence - 0.2)
                    elif isinstance(discrepancy, dict):
                        discrepancy['verification_status'] = verification_status
                        if not verification_result.get("verified", False):
                            current_confidence = discrepancy.get('confidence', 0.8)
                            discrepancy['confidence'] = max(0.3, current_confidence - 0.2)
                
                logger.info(f"Citation verification completed for {len(parsed_discrepancies)} discrepancies")
            except Exception as e:
                logger.warning(f"Error during citation verification: {e}, continuing without verification")
        
        # Deduplicate discrepancies
        if parsed_discrepancies:
            from app.services.deduplication import deduplicate_discrepancies
            try:
                parsed_discrepancies = deduplicate_discrepancies(parsed_discrepancies, similarity_threshold=0.80)
                logger.info(f"After deduplication: {len(parsed_discrepancies)} discrepancies")
            except Exception as e:
                logger.warning(f"Error during deduplication: {e}, continuing with original discrepancies")
        
        # Save discrepancies to database
        saved_discrepancies = []
        if db and parsed_discrepancies:
            for disc_model in parsed_discrepancies:
                try:
                    # Include reasoning and confidence in details
                    details_with_reasoning = disc_model.details.copy() if disc_model.details else {}
                    details_with_reasoning["reasoning"] = disc_model.reasoning if hasattr(disc_model, 'reasoning') else ""
                    details_with_reasoning["confidence"] = disc_model.confidence if hasattr(disc_model, 'confidence') else 0.0
                    
                    discrepancy = Discrepancy(
                        case_id=case_id,
                        type=disc_model.type,
                        severity=disc_model.severity,
                        description=disc_model.description,
                        source_documents=disc_model.source_documents,
                        details=details_with_reasoning
                    )
                    db.add(discrepancy)
                    saved_discrepancies.append(discrepancy)
                except Exception as e:
                    logger.warning(f"Ошибка при сохранении противоречия: {e}, discrepancy: {disc_model}")
                    continue
            
            if saved_discrepancies:
                db.commit()
        
        # Create result
        result_data = {
            "discrepancies": [
                {
                    "id": disc.id if hasattr(disc, 'id') else None,
                    "type": disc.type if hasattr(disc, 'type') else disc_model.type,
                    "severity": disc.severity if hasattr(disc, 'severity') else disc_model.severity,
                    "description": disc.description if hasattr(disc, 'description') else disc_model.description,
                    "source_documents": disc.source_documents if hasattr(disc, 'source_documents') else disc_model.source_documents,
                    "details": disc.details if hasattr(disc, 'details') else disc_model.details,
                    "reasoning": disc.details.get("reasoning", "") if hasattr(disc, 'details') and disc.details else (disc_model.reasoning if hasattr(disc_model, 'reasoning') else ""),
                    "confidence": disc.details.get("confidence", 0.0) if hasattr(disc, 'details') and disc.details else (disc_model.confidence if hasattr(disc_model, 'confidence') else 0.0)
                }
                for disc, disc_model in zip(saved_discrepancies, parsed_discrepancies) if saved_discrepancies
            ] or [
                {
                    "type": disc.type,
                    "severity": disc.severity,
                    "description": disc.description,
                    "source_documents": disc.source_documents,
                    "details": disc.details,
                    "reasoning": disc.reasoning if hasattr(disc, 'reasoning') else "",
                    "confidence": disc.confidence if hasattr(disc, 'confidence') else 0.0
                }
                for disc in parsed_discrepancies
            ],
            "total": len(parsed_discrepancies),
            "high_risk": len([d for d in parsed_discrepancies if d.severity == "HIGH"]),
            "medium_risk": len([d for d in parsed_discrepancies if d.severity == "MEDIUM"]),
            "low_risk": len([d for d in parsed_discrepancies if d.severity == "LOW"])
        }
        
        logger.info(f"Discrepancy agent: Found {len(parsed_discrepancies)} discrepancies for case {case_id}")
        
        # Save to file system (DeepAgents pattern)
        try:
            from app.services.langchain_agents.file_system_helper import save_agent_result_to_file
            save_agent_result_to_file(state, "discrepancy", result_data)
        except Exception as fs_error:
            logger.debug(f"Failed to save discrepancy result to file: {fs_error}")
        
        # Update state
        new_state = state.copy()
        new_state["discrepancy_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Discrepancy agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "discrepancy",
            "error": str(e)
        })
        new_state["discrepancy_result"] = None
        return new_state
