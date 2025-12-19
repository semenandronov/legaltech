"""Analysis routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File
from app.models.user import User
from app.models.analysis import (
    AnalysisResult, Discrepancy, TimelineEvent,
    DocumentClassification, ExtractedEntity, PrivilegeCheck
)
from app.models.case import File
from app.services.analysis_service import AnalysisService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalysisStartRequest(BaseModel):
    """Request model for starting analysis"""
    analysis_types: list[str] = Field(..., min_length=1, description="List of analysis types to run")
    
    @field_validator('analysis_types')
    @classmethod
    def validate_analysis_types(cls, v: list[str]) -> list[str]:
        if len(v) == 0:
            raise ValueError('At least one analysis type must be specified')
        if len(v) > 10:
            raise ValueError('At most 10 analysis types can be specified')
        
        valid_types = [
            "timeline", "discrepancies", "key_facts", "summary", "risk_analysis",
            "document_classifier", "entity_extraction", "privilege_check"
        ]
        for analysis_type in v:
            if analysis_type not in valid_types:
                raise ValueError(f'Invalid analysis type: {analysis_type}. Must be one of: {", ".join(valid_types)}')
        
        return v


@router.post("/{case_id}/start")
async def start_analysis(
    case_id: str,
    request: AnalysisStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start analysis for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        # Update case status
        case.status = "processing"
        if case.case_metadata is None:
            case.case_metadata = {}
        case.case_metadata["analysis_error"] = None
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при обновлении статуса дела {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при запуске анализа. Попробуйте позже.")
    
    # Start analysis in background
    # Note: We need to create a new DB session inside the background task
    from app.utils.database import SessionLocal
    
    def run_analysis():
        # Create new DB session for background task
        background_db = SessionLocal()
        try:
            # Reload case in new session
            background_case = background_db.query(Case).filter(Case.id == case_id).first()
            if not background_case:
                logger.error(f"Case {case_id} not found in background task")
                return
            
            analysis_service = AnalysisService(background_db)
            
            try:
                # Use agent system if enabled, otherwise use legacy sequential approach
                if analysis_service.use_agents:
                    logger.info(f"Using multi-agent system for case {case_id}")
                    # Map analysis type names
                    agent_types = []
                    for at in request.analysis_types:
                        if at == "discrepancies":
                            agent_types.append("discrepancy")
                        elif at == "risk_analysis":
                            agent_types.append("risk")
                        elif at == "document_classifier":
                            agent_types.append("document_classifier")
                        elif at == "entity_extraction":
                            agent_types.append("entity_extraction")
                        elif at == "privilege_check":
                            agent_types.append("privilege_check")
                        else:
                            agent_types.append(at)
                    
                    # Run all analyses through agent coordinator
                    results = analysis_service.run_agent_analysis(case_id, agent_types)
                    logger.info(f"Multi-agent analysis completed for case {case_id}, execution time: {results.get('execution_time', 0):.2f}s")
                else:
                    # Legacy sequential approach
                    logger.info(f"Using legacy sequential analysis for case {case_id}")
                    for analysis_type in request.analysis_types:
                        logger.info(f"Starting {analysis_type} analysis for case {case_id}")
                        if analysis_type == "timeline":
                            analysis_service.extract_timeline(case_id)
                        elif analysis_type == "discrepancies":
                            analysis_service.find_discrepancies(case_id)
                        elif analysis_type == "key_facts":
                            analysis_service.extract_key_facts(case_id)
                        elif analysis_type == "summary":
                            analysis_service.generate_summary(case_id)
                        elif analysis_type == "risk_analysis":
                            analysis_service.analyze_risks(case_id)
                        else:
                            logger.warning(f"Unknown analysis type: {analysis_type}")
                
                # Update case status to completed
                background_case.status = "completed"
                if background_case.case_metadata is None:
                    background_case.case_metadata = {}
                background_case.case_metadata["analysis_error"] = None
                background_case.case_metadata["analysis_completed_at"] = datetime.utcnow().isoformat()
                background_db.commit()
                logger.info(f"Analysis completed successfully for case {case_id}")
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Ошибка при анализе дела {case_id}: {error_msg}", exc_info=True)
                
                # Update case status to failed
                try:
                    background_case.status = "failed"
                    if background_case.case_metadata is None:
                        background_case.case_metadata = {}
                    background_case.case_metadata["analysis_error"] = error_msg
                    background_case.case_metadata["analysis_failed_at"] = datetime.utcnow().isoformat()
                    background_db.commit()
                except Exception as commit_error:
                    background_db.rollback()
                    logger.error(f"Ошибка при сохранении статуса ошибки для дела {case_id}: {commit_error}", exc_info=True)
        except Exception as e:
            logger.error(f"Critical error in background analysis task for case {case_id}: {e}", exc_info=True)
        finally:
            background_db.close()
    
    background_tasks.add_task(run_analysis)
    
    return {
        "status": "started",
        "message": f"Анализ запущен для типов: {', '.join(request.analysis_types)}"
    }


@router.get("/{case_id}/status")
async def get_analysis_status(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get analysis status for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get analysis results
    results = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id
    ).all()
    
    return {
        "case_status": case.status or "pending",
        "analysis_results": {
            result.analysis_type: {
                "status": result.status or "pending",
                "created_at": result.created_at.isoformat() if result.created_at else datetime.utcnow().isoformat(),
                "updated_at": result.updated_at.isoformat() if result.updated_at else datetime.utcnow().isoformat()
            }
            for result in results
        }
    }


@router.get("/{case_id}/timeline")
async def get_timeline(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get timeline for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get timeline events
    events = db.query(TimelineEvent).filter(
        TimelineEvent.case_id == case_id
    ).order_by(TimelineEvent.date.asc()).all()
    
    return {
        "events": [
            {
                "id": event.id,
                "date": event.date.isoformat() if event.date else datetime.utcnow().isoformat(),
                "event_type": event.event_type or None,
                "description": event.description or "",
                "source_document": event.source_document or "",
                "source_page": event.source_page if event.source_page is not None else None,
                "source_line": event.source_line if event.source_line is not None else None,
                "metadata": event.event_metadata or {}
            }
            for event in events
        ],
        "total": len(events)
    }


@router.get("/{case_id}/discrepancies")
async def get_discrepancies(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get discrepancies for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get discrepancies
    discrepancies = db.query(Discrepancy).filter(
        Discrepancy.case_id == case_id
    ).order_by(
        Discrepancy.severity.desc(),
        Discrepancy.created_at.desc()
    ).all()
    
    return {
        "discrepancies": [
            {
                "id": disc.id,
                "type": disc.type,
                "severity": disc.severity,
                "description": disc.description,
                "source_documents": disc.source_documents,
                "details": disc.details,
                "created_at": disc.created_at.isoformat()
            }
            for disc in discrepancies
        ],
        "total": len(discrepancies),
        "high_risk": len([d for d in discrepancies if d.severity == "HIGH"]),
        "medium_risk": len([d for d in discrepancies if d.severity == "MEDIUM"]),
        "low_risk": len([d for d in discrepancies if d.severity == "LOW"])
    }


@router.get("/{case_id}/key-facts")
async def get_key_facts(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get key facts for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get latest key facts result
    result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "key_facts"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    if not result:
        return {"facts": {}, "message": "Ключевые факты еще не извлечены"}
    
    return {
        "facts": result.result_data if result.result_data is not None else {},
        "created_at": result.created_at.isoformat() if result.created_at else datetime.utcnow().isoformat()
    }


@router.get("/{case_id}/summary")
async def get_summary(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get summary for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get latest summary result
    result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "summary"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    if not result:
        return {"summary": "", "message": "Резюме еще не сгенерировано"}
    
    result_data = result.result_data if result.result_data is not None else {}
    return {
        "summary": result_data.get("summary", "") if isinstance(result_data, dict) else "",
        "key_facts": result_data.get("key_facts", {}) if isinstance(result_data, dict) else {},
        "created_at": result.created_at.isoformat() if result.created_at else datetime.utcnow().isoformat()
    }


@router.get("/{case_id}/risks")
async def get_risks(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get risk analysis for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get latest risk analysis result
    result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "risk_analysis"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    if not result:
        return {"analysis": "", "message": "Анализ рисков еще не выполнен"}
    
    result_data = result.result_data if result.result_data is not None else {}
    return {
        "analysis": result_data.get("analysis", "") if isinstance(result_data, dict) else "",
        "discrepancies": result_data.get("discrepancies", {}) if isinstance(result_data, dict) else {},
        "created_at": result.created_at.isoformat() if result.created_at else datetime.utcnow().isoformat()
    }


class ClassifyRequest(BaseModel):
    """Request model for document classification"""
    file_id: str | None = Field(None, description="File ID to classify (if None, classifies all files)")


@router.post("/{case_id}/classify")
async def classify_documents(
    case_id: str,
    request: ClassifyRequest = ClassifyRequest(),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Classify documents in a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Run classification using agent system
    from app.services.langchain_agents.coordinator import AgentCoordinator
    from app.services.rag_service import RAGService
    from app.services.document_processor import DocumentProcessor
    
    try:
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        coordinator = AgentCoordinator(db, rag_service, document_processor)
        
        # Create state for classification
        from app.services.langchain_agents.state import AnalysisState
        state: AnalysisState = {
            "case_id": case_id,
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "classification_result": None,
            "entities_result": None,
            "privilege_result": None,
            "analysis_types": ["document_classifier"],
            "errors": [],
            "metadata": {}
        }
        
        # Run classifier node
        from app.services.langchain_agents.document_classifier_node import document_classifier_agent_node
        result_state = document_classifier_agent_node(state, db, rag_service, document_processor, request.file_id)
        
        return {
            "status": "completed",
            "classification": result_state.get("classification_result"),
            "errors": result_state.get("errors", [])
        }
    except Exception as e:
        logger.error(f"Error classifying documents for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при классификации документов: {str(e)}")


@router.get("/{case_id}/classify")
async def get_classifications(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get document classifications for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get classifications
    classifications = db.query(DocumentClassification).filter(
        DocumentClassification.case_id == case_id
    ).order_by(DocumentClassification.created_at.desc()).all()
    
    return {
        "classifications": [
            {
                "id": c.id,
                "file_id": c.file_id,
                "doc_type": c.doc_type,
                "relevance_score": c.relevance_score,
                "is_privileged": c.is_privileged == "true",
                "privilege_type": c.privilege_type,
                "key_topics": c.key_topics or [],
                "confidence": float(c.confidence) if c.confidence else 0.0,
                "reasoning": c.reasoning,
                "created_at": c.created_at.isoformat()
            }
            for c in classifications
        ],
        "total": len(classifications)
    }


class ExtractEntitiesRequest(BaseModel):
    """Request model for entity extraction"""
    file_id: str | None = Field(None, description="File ID to extract entities from (if None, extracts from all files)")


@router.post("/{case_id}/entities")
async def extract_entities(
    case_id: str,
    request: ExtractEntitiesRequest = ExtractEntitiesRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Extract entities from documents in a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Run entity extraction using agent system
    from app.services.langchain_agents.coordinator import AgentCoordinator
    from app.services.rag_service import RAGService
    from app.services.document_processor import DocumentProcessor
    
    try:
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        
        # Create state for entity extraction
        from app.services.langchain_agents.state import AnalysisState
        state: AnalysisState = {
            "case_id": case_id,
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "classification_result": None,
            "entities_result": None,
            "privilege_result": None,
            "analysis_types": ["entity_extraction"],
            "errors": [],
            "metadata": {}
        }
        
        # Run entity extraction node
        from app.services.langchain_agents.entity_extraction_node import entity_extraction_agent_node
        result_state = entity_extraction_agent_node(state, db, rag_service, document_processor, request.file_id)
        
        return {
            "status": "completed",
            "entities": result_state.get("entities_result"),
            "errors": result_state.get("errors", [])
        }
    except Exception as e:
        logger.error(f"Error extracting entities for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при извлечении сущностей: {str(e)}")


@router.get("/{case_id}/entities")
async def get_entities(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get extracted entities for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get entities
    entities = db.query(ExtractedEntity).filter(
        ExtractedEntity.case_id == case_id
    ).order_by(ExtractedEntity.created_at.desc()).all()
    
    # Group by type
    entities_by_type = {}
    for entity in entities:
        entity_type = entity.entity_type
        if entity_type not in entities_by_type:
            entities_by_type[entity_type] = []
        entities_by_type[entity_type].append({
            "id": entity.id,
            "file_id": entity.file_id,
            "text": entity.entity_text,
            "type": entity.entity_type,
            "confidence": float(entity.confidence) if entity.confidence else 0.0,
            "context": entity.context,
            "source_document": entity.source_document,
            "source_page": entity.source_page,
            "source_line": entity.source_line,
            "created_at": entity.created_at.isoformat()
        })
    
    return {
        "entities": [
            {
                "id": e.id,
                "file_id": e.file_id,
                "text": e.entity_text,
                "type": e.entity_type,
                "confidence": float(e.confidence) if e.confidence else 0.0,
                "context": e.context,
                "source_document": e.source_document,
                "source_page": e.source_page,
                "source_line": e.source_line,
                "created_at": e.created_at.isoformat()
            }
            for e in entities
        ],
        "entities_by_type": entities_by_type,
        "total": len(entities),
        "by_type_count": {etype: len(entities) for etype, entities in entities_by_type.items()}
    }


class PrivilegeCheckRequest(BaseModel):
    """Request model for privilege check"""
    file_id: str = Field(..., description="File ID to check (required)")


@router.post("/{case_id}/privilege")
async def check_privilege(
    case_id: str,
    request: PrivilegeCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check privilege for a document (КРИТИЧНО для e-discovery!)"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Verify file exists and belongs to case
    file = db.query(File).filter(
        File.id == request.file_id,
        File.case_id == case_id
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    # Run privilege check using agent system
    from app.services.langchain_agents.coordinator import AgentCoordinator
    from app.services.rag_service import RAGService
    from app.services.document_processor import DocumentProcessor
    
    try:
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        
        # Create state for privilege check
        from app.services.langchain_agents.state import AnalysisState
        state: AnalysisState = {
            "case_id": case_id,
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "classification_result": None,
            "entities_result": None,
            "privilege_result": None,
            "analysis_types": ["privilege_check"],
            "errors": [],
            "metadata": {}
        }
        
        # Run privilege check node
        from app.services.langchain_agents.privilege_check_node import privilege_check_agent_node
        result_state = privilege_check_agent_node(state, db, rag_service, document_processor, request.file_id)
        
        privilege_result = result_state.get("privilege_result")
        if privilege_result and privilege_result.get("privilege_checks"):
            # Save to database
            check_data = privilege_result["privilege_checks"][0]  # Should be one check for one file
            privilege_check = PrivilegeCheck(
                case_id=case_id,
                file_id=request.file_id,
                is_privileged="true" if check_data.get("is_privileged") else "false",
                privilege_type=check_data.get("privilege_type", "none"),
                confidence=str(check_data.get("confidence", 0.0)),
                reasoning=check_data.get("reasoning", []),
                withhold_recommendation="true" if check_data.get("withhold_recommendation") else "false",
                requires_human_review="true" if check_data.get("requires_human_review", True) else "false"
            )
            db.add(privilege_check)
            db.commit()
        
        return {
            "status": "completed",
            "privilege_check": privilege_result,
            "errors": result_state.get("errors", []),
            "warning": "ВСЕГДА требуется human review для финального решения!"
        }
    except Exception as e:
        logger.error(f"Error checking privilege for case {case_id}, file {request.file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при проверке привилегий: {str(e)}")


@router.get("/{case_id}/privilege")
async def get_privilege_checks(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get privilege checks for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get privilege checks
    checks = db.query(PrivilegeCheck).filter(
        PrivilegeCheck.case_id == case_id
    ).order_by(PrivilegeCheck.created_at.desc()).all()
    
    return {
        "privilege_checks": [
            {
                "id": c.id,
                "file_id": c.file_id,
                "is_privileged": c.is_privileged == "true",
                "privilege_type": c.privilege_type,
                "confidence": float(c.confidence) if c.confidence else 0.0,
                "reasoning": c.reasoning or [],
                "withhold_recommendation": c.withhold_recommendation == "true",
                "requires_human_review": c.requires_human_review == "true",
                "created_at": c.created_at.isoformat()
            }
            for c in checks
        ],
        "total": len(checks),
        "privileged_count": len([c for c in checks if c.is_privileged == "true"]),
        "requires_review_count": len([c for c in checks if c.requires_human_review == "true"])
    }


@router.post("/{case_id}/full")
async def run_full_analysis(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Run full analysis with all agents in correct order"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Start full analysis in background
    from app.utils.database import SessionLocal
    
    def run_full():
        background_db = SessionLocal()
        try:
            background_case = background_db.query(Case).filter(Case.id == case_id).first()
            if not background_case:
                return
            
            analysis_service = AnalysisService(background_db)
            
            if analysis_service.use_agents:
                # Run all analysis types in correct order
                all_types = [
                    "document_classifier",
                    "privilege_check",
                    "entity_extraction",
                    "timeline",
                    "key_facts",
                    "discrepancy",
                    "risk",
                    "summary"
                ]
                results = analysis_service.run_agent_analysis(case_id, all_types)
                logger.info(f"Full analysis completed for case {case_id}")
            
            background_case.status = "completed"
            background_db.commit()
        except Exception as e:
            logger.error(f"Error in full analysis for case {case_id}: {e}", exc_info=True)
            try:
                background_case.status = "failed"
                background_db.commit()
            except:
                background_db.rollback()
        finally:
            background_db.close()
    
    background_tasks.add_task(run_full)
    
    return {
        "status": "started",
        "message": "Полный анализ запущен со всеми агентами"
    }


@router.get("/{case_id}/report")
async def get_analysis_report(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить итоговый отчет анализа с категоризацией документов
    
    Возвращает структурированный отчет:
    - ✅ Документы на проверку вручную (высокая релевантность)
    - 🔒 Привилегированные документы (НЕ показывать оппоненту)
    - 🗑️ Мусор (не релевантно)
    """
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get all files
    files = db.query(File).filter(File.case_id == case_id).all()
    total_files = len(files)
    
    # Get classifications
    classifications = db.query(DocumentClassification).filter(
        DocumentClassification.case_id == case_id
    ).all()
    
    # Get privilege checks
    privilege_checks = db.query(PrivilegeCheck).filter(
        PrivilegeCheck.case_id == case_id
    ).all()
    
    # Get entities
    entities = db.query(ExtractedEntity).filter(
        ExtractedEntity.case_id == case_id
    ).all()
    
    # Categorize documents
    high_relevance = []  # ✅ На проверку вручную (релевантность > 70)
    privileged = []  # 🔒 Привилегированные
    low_relevance = []  # 🗑️ Мусор (релевантность < 30)
    medium_relevance = []  # Средняя релевантность (30-70)
    
    # Create mapping file_id -> classification
    classification_map = {c.file_id: c for c in classifications if c.file_id}
    privilege_map = {pc.file_id: pc for pc in privilege_checks if pc.file_id}
    
    for file in files:
        file_id = file.id
        classification = classification_map.get(file_id)
        privilege_check = privilege_map.get(file_id)
        
        file_info = {
            "file_id": file_id,
            "filename": file.filename,
            "classification": None,
            "privilege_check": None,
            "entities_count": len([e for e in entities if e.file_id == file_id])
        }
        
        if classification:
            file_info["classification"] = {
                "doc_type": classification.doc_type,
                "relevance_score": classification.relevance_score,
                "is_privileged": classification.is_privileged == "true",
                "privilege_type": classification.privilege_type,
                "key_topics": classification.key_topics or [],
                "confidence": float(classification.confidence) if classification.confidence else 0.0,
                "reasoning": classification.reasoning
            }
            
            # Categorize by relevance
            if classification.relevance_score > 70:
                high_relevance.append(file_info)
            elif classification.relevance_score < 30:
                low_relevance.append(file_info)
            else:
                medium_relevance.append(file_info)
        else:
            # No classification yet
            medium_relevance.append(file_info)
        
        # Check privilege
        if privilege_check:
            file_info["privilege_check"] = {
                "is_privileged": privilege_check.is_privileged == "true",
                "privilege_type": privilege_check.privilege_type,
                "confidence": float(privilege_check.confidence) if privilege_check.confidence else 0.0,
                "reasoning": privilege_check.reasoning or [],
                "withhold_recommendation": privilege_check.withhold_recommendation == "true",
                "requires_human_review": privilege_check.requires_human_review == "true"
            }
            
            # Add to privileged list if privileged
            if privilege_check.is_privileged == "true":
                if file_info not in privileged:
                    privileged.append(file_info)
    
    # Get summary statistics
    total_entities = len(entities)
    entities_by_type = {}
    for entity in entities:
        entity_type = entity.entity_type
        if entity_type not in entities_by_type:
            entities_by_type[entity_type] = 0
        entities_by_type[entity_type] += 1
    
    # Get timeline events count
    timeline_events = db.query(TimelineEvent).filter(
        TimelineEvent.case_id == case_id
    ).count()
    
    # Get discrepancies count
    discrepancies = db.query(Discrepancy).filter(
        Discrepancy.case_id == case_id
    ).count()
    
    return {
        "case_id": case_id,
        "case_title": case.title,
        "total_files": total_files,
        "categorization": {
            "high_relevance": {
                "count": len(high_relevance),
                "label": "✅ На проверку вручную (высокая релевантность >70%)",
                "files": high_relevance
            },
            "privileged": {
                "count": len(privileged),
                "label": "🔒 Привилегированные (НЕ показывать оппоненту)",
                "files": privileged,
                "warning": "ВСЕГДА требуется human review для финального решения!"
            },
            "medium_relevance": {
                "count": len(medium_relevance),
                "label": "⚠️ Средняя релевантность (30-70%)",
                "files": medium_relevance
            },
            "low_relevance": {
                "count": len(low_relevance),
                "label": "🗑️ Низкая релевантность (<30%)",
                "files": low_relevance
            }
        },
        "statistics": {
            "total_entities": total_entities,
            "entities_by_type": entities_by_type,
            "timeline_events": timeline_events,
            "discrepancies": discrepancies,
            "classified_files": len(classifications),
            "privilege_checked_files": len(privilege_checks)
        },
        "summary": {
            "high_relevance_count": len(high_relevance),
            "privileged_count": len(privileged),
            "low_relevance_count": len(low_relevance),
            "message": f"Из {total_files} документов: {len(high_relevance)} на проверку, {len(privileged)} привилегированных, {len(low_relevance)} не релевантных"
        }
    }

