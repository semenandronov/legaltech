"""Privilege check agent node for LangGraph - КРИТИЧНО для e-discovery!"""
from typing import Dict, Any, Optional
from app.services.llm_factory import create_llm
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
        
        # Initialize LLM через factory (GigaChat)
        llm = create_llm(temperature=0.1)  # Низкая температура для детерминизма
        
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
                # file_metadata удалено из модели, используем пустые значения
                sender = ""
                recipient = ""
                
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
                        privilege_check = ParserService.parse_privilege_check(response_text)
                    except Exception as fallback_error:
                        logger.error(f"Fallback LLM call failed: {fallback_error}, using default privilege check")
                        from app.services.langchain_parsers import PrivilegeCheckModel
                        privilege_check = PrivilegeCheckModel(
                            is_privileged=False,
                            confidence=0.0,
                            reasoning="Fallback: unable to determine privilege status"
                        )
                
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
        
        # Save to file system (DeepAgents pattern)
        try:
            from app.services.langchain_agents.file_system_helper import save_agent_result_to_file
            save_agent_result_to_file(state, "privilege", result_data)
        except Exception as fs_error:
            logger.debug(f"Failed to save privilege result to file: {fs_error}")
        
        # Update state
        new_state = state.copy()
        
        # Оптимизация: сохранить большие результаты в Store
        from app.services.langchain_agents.store_helper import (
            should_store_result,
            save_large_result_to_store
        )
        
        if should_store_result(result_data):
            # Сохранить в Store и получить ссылку
            privilege_ref = save_large_result_to_store(
                state=state,
                result_key="privilege_result",
                data=result_data,
                case_id=case_id
            )
            new_state["privilege_ref"] = privilege_ref
            # Сохранить summary в state для быстрого доступа
            if privilege_ref.get("summary"):
                new_state["privilege_summary"] = privilege_ref["summary"]
            logger.info(f"Privilege result stored in Store")
        else:
            # Маленький результат - сохранить напрямую в state
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

