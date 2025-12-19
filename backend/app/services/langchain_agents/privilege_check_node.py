"""Privilege check agent node for LangGraph - КРИТИЧНО для e-discovery!"""
from typing import Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService, PrivilegeCheckModel
from sqlalchemy.orm import Session
from app.models.case import File
import logging

logger = logging.getLogger(__name__)


def privilege_check_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
    file_id: Optional[str] = None
) -> AnalysisState:
    """
    Privilege check agent node for checking attorney-client privilege
    
    КРИТИЧНО: Ошибка = разглашение конфиденциального документа!
    Всегда требует human review.
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
        file_id: Optional file ID to check (if None, checks all files)
    
    Returns:
        Updated state with privilege_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Privilege check agent: Starting check for case {case_id}, file_id={file_id}")
        
        if not db:
            raise ValueError("Database session required for privilege check")
        
        # Get file(s) to check
        if file_id:
            files = db.query(File).filter(File.id == file_id, File.case_id == case_id).all()
        else:
            files = db.query(File).filter(File.case_id == case_id).all()
        
        if not files:
            logger.warning(f"No files found for privilege check in case {case_id}")
            new_state = state.copy()
            new_state["privilege_result"] = None
            return new_state
        
        # Initialize LLM with temperature=0 for deterministic privilege check
        llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0,  # Детерминизм КРИТИЧЕН для проверки привилегий!
            max_tokens=2000
        )
        
        # Get privilege check prompt
        from app.services.langchain_agents.prompts import get_agent_prompt
        system_prompt = get_agent_prompt("privilege_check")
        
        # Check each file
        privilege_results = []
        
        for file in files:
            try:
                # Get document text
                document_text = file.original_text or ""
                if not document_text:
                    logger.warning(f"File {file.id} has no text content, skipping privilege check")
                    continue
                
                # Extract sender and recipient from metadata if available
                sender = file.metadata.get("sender", "") if file.metadata else ""
                recipient = file.metadata.get("recipient", "") if file.metadata else ""
                
                # Create prompt for privilege check
                # Limit text to avoid token limits
                limited_text = document_text[:3000]
                
                user_prompt = f"""ТЕСТ НА ПРИВИЛЕГИЮ АДВОКАТА-КЛИЕНТА

ДОКУМЕНТ:
{limited_text}

ОТ: {sender if sender else "Не указан"}
КОМУ: {recipient if recipient else "Не указан"}

Проверь документ на привилегию адвоката-клиента и рабочие материалы адвоката."""
                
                # Try to use structured output
                try:
                    structured_llm = llm.with_structured_output(PrivilegeCheckModel)
                    prompt = ChatPromptTemplate.from_messages([
                        ("system", system_prompt),
                        ("human", user_prompt)
                    ])
                    chain = prompt | structured_llm
                    privilege_check = chain.invoke({})
                except Exception as e:
                    logger.warning(f"Structured output not supported, falling back to JSON parsing: {e}")
                    # Fallback to direct LLM call
                    from app.services.llm_service import LLMService
                    llm_service = LLMService()
                    response = llm_service.generate(system_prompt, user_prompt, temperature=0)
                    privilege_check = ParserService.parse_privilege_check(response)
                
                # Validate confidence (must be >95% for production)
                if privilege_check.confidence < 95.0:
                    logger.warning(
                        f"Privilege check confidence {privilege_check.confidence}% is below 95% threshold "
                        f"for file {file.id}. Human review REQUIRED!"
                    )
                
                # Log the decision (critical for audit)
                logger.info(
                    f"Privilege check for file {file.id}: "
                    f"is_privileged={privilege_check.is_privileged}, "
                    f"type={privilege_check.privilege_type}, "
                    f"confidence={privilege_check.confidence}%"
                )
                
                privilege_results.append({
                    "file_id": file.id,
                    "file_name": file.filename,
                    "is_privileged": privilege_check.is_privileged,
                    "privilege_type": privilege_check.privilege_type,
                    "confidence": privilege_check.confidence,
                    "reasoning": privilege_check.reasoning,
                    "withhold_recommendation": privilege_check.withhold_recommendation,
                    "requires_human_review": privilege_check.confidence < 95.0 or privilege_check.is_privileged
                })
                
            except Exception as e:
                logger.error(f"Error checking privilege for file {file.id}: {e}", exc_info=True)
                # On error, default to safe: not privileged, but flag for review
                privilege_results.append({
                    "file_id": file.id,
                    "file_name": file.filename,
                    "is_privileged": False,
                    "privilege_type": "none",
                    "confidence": 0.0,
                    "reasoning": [f"Ошибка при проверке: {str(e)}"],
                    "withhold_recommendation": False,
                    "requires_human_review": True,
                    "error": str(e)
                })
        
        # Create result
        result_data = {
            "privilege_checks": privilege_results,
            "total_files": len(files),
            "privileged_count": len([r for r in privilege_results if r["is_privileged"]]),
            "requires_review_count": len([r for r in privilege_results if r.get("requires_human_review", False)])
        }
        
        logger.info(
            f"Privilege check agent: Checked {len(files)} files, "
            f"found {result_data['privileged_count']} privileged, "
            f"{result_data['requires_review_count']} require human review"
        )
        
        # Update state
        new_state = state.copy()
        new_state["privilege_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Privilege check agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "privilege_check",
            "error": str(e)
        })
        new_state["privilege_result"] = None
        return new_state

