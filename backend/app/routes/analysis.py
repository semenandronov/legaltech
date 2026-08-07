"""Analysis routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import Dict, Any, List
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.utils.authorization import require_case_access, require_case_write
from app.models.case import Case, File
from app.models.user import User
from app.models.case import File as FileModel
from app.models.analysis import (
    AnalysisResult, Discrepancy, TimelineEvent,
    DocumentClassification, ExtractedEntity, PrivilegeCheck,
    RelationshipNode, RelationshipEdge
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
    case = require_case_write(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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


@router.get("/{case_id}/relationship-graph")
async def get_relationship_graph(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get relationship graph for a case"""
    # Verify case ownership
    case = require_case_access(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get all nodes for this case
    nodes = db.query(RelationshipNode).filter(
        RelationshipNode.case_id == case_id
    ).all()
    
    # Get all edges for this case
    edges = db.query(RelationshipEdge).filter(
        RelationshipEdge.case_id == case_id
    ).all()
    
    # Format nodes for D3.js
    formatted_nodes = [
        {
            "id": node.node_id,
            "type": node.node_type,
            "label": node.node_label,
            "properties": node.properties if node.properties is not None else {},
            "source_document": node.source_document,
            "source_page": node.source_page
        }
        for node in nodes
    ]
    
    # Format links for D3.js
    formatted_links = [
        {
            "source": edge.source_node_id,
            "target": edge.target_node_id,
            "type": edge.relationship_type,
            "label": edge.relationship_label,
            "source_document": edge.source_document,
            "source_page": edge.source_page,
            "properties": edge.properties if edge.properties is not None else {}
        }
        for edge in edges
    ]
    
    return {
        "nodes": formatted_nodes,
        "links": formatted_links
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
    case = require_case_write(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Run classification using agent system
    from app.services.langchain_agents.legacy_stubs import AgentCoordinator
    from app.services.rag_service import RAGService
    from app.services.document_processor import DocumentProcessor
    
    try:
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        coordinator = AgentCoordinator(db, rag_service, document_processor)
        
        # Create state for classification
        from app.services.langchain_agents.legacy_stubs import AnalysisState
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
        from app.services.langchain_agents.legacy_stubs import document_classifier_agent_node
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_write(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Run entity extraction using agent system
    from app.services.langchain_agents.legacy_stubs import AgentCoordinator
    from app.services.rag_service import RAGService
    from app.services.document_processor import DocumentProcessor
    
    try:
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        
        # Create state for entity extraction
        from app.services.langchain_agents.legacy_stubs import AnalysisState
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
        from app.services.langchain_agents.legacy_stubs import entity_extraction_agent_node
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_write(db, case_id, current_user.id)
    
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
    from app.services.langchain_agents.legacy_stubs import AgentCoordinator
    from app.services.rag_service import RAGService
    from app.services.document_processor import DocumentProcessor
    
    try:
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        
        # Create state for privilege check
        from app.services.langchain_agents.legacy_stubs import AnalysisState
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
        from app.services.langchain_agents.legacy_stubs import privilege_check_agent_node
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
    case = require_case_access(db, case_id, current_user.id)
    
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
    case = require_case_write(db, case_id, current_user.id)
    
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
    case = require_case_access(db, case_id, current_user.id)
    
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


# Batch Actions
class BatchActionRequest(BaseModel):
    """Request model for batch actions"""
    file_ids: list[str] = Field(..., min_length=1, description="List of file IDs to process")


@router.post("/{case_id}/batch/confirm")
async def batch_confirm(
    case_id: str,
    request: BatchActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Batch confirm documents (mark as relevant/confirmed)"""
    # Verify case ownership
    case = require_case_write(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get files
    files = db.query(FileModel).filter(
        FileModel.id.in_(request.file_ids),
        FileModel.case_id == case_id
    ).all()
    
    if len(files) != len(request.file_ids):
        raise HTTPException(status_code=400, detail="Некоторые файлы не найдены")
    
    try:
        # Update file metadata with status
        # file_metadata удалено из модели, используем другие способы хранения статуса
        # Статус review можно хранить в отдельной таблице или в case_metadata
        # TODO: Реализовать хранение статуса review в отдельной таблице или case_metadata
        for file in files:
            pass  # Пока ничего не делаем, так как file_metadata удалено
        
        db.commit()
        
        # TODO: Create audit log entries
        logger.info(
            f"Batch confirmed {len(files)} documents in case {case_id}",
            extra={
                "user_id": current_user.id,
                "case_id": case_id,
                "file_ids": request.file_ids,
                "action": "batch_confirm"
            }
        )
        
        return {
            "status": "success",
            "message": f"Подтверждено {len(files)} документов",
            "confirmed_count": len(files)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при batch confirm для дела {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при подтверждении документов")


@router.post("/{case_id}/batch/reject")
async def batch_reject(
    case_id: str,
    request: BatchActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Batch reject documents (mark as not relevant)"""
    # Verify case ownership
    case = require_case_write(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get files
    files = db.query(FileModel).filter(
        FileModel.id.in_(request.file_ids),
        FileModel.case_id == case_id
    ).all()
    
    if len(files) != len(request.file_ids):
        raise HTTPException(status_code=400, detail="Некоторые файлы не найдены")
    
    try:
        # Update file metadata with status
        # file_metadata удалено из модели, используем другие способы хранения статуса
        # TODO: Реализовать хранение статуса review в отдельной таблице или case_metadata
        for file in files:
            pass  # Пока ничего не делаем, так как file_metadata удалено
        
        db.commit()
        
        logger.info(
            f"Batch rejected {len(files)} documents in case {case_id}",
            extra={
                "user_id": current_user.id,
                "case_id": case_id,
                "file_ids": request.file_ids,
                "action": "batch_reject"
            }
        )
        
        return {
            "status": "success",
            "message": f"Отклонено {len(files)} документов",
            "rejected_count": len(files)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при batch reject для дела {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при отклонении документов")


@router.post("/{case_id}/batch/withhold")
async def batch_withhold(
    case_id: str,
    request: BatchActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Batch withhold documents (mark as privileged/withheld)"""
    # Verify case ownership
    case = require_case_write(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get files
    files = db.query(FileModel).filter(
        FileModel.id.in_(request.file_ids),
        FileModel.case_id == case_id
    ).all()
    
    if len(files) != len(request.file_ids):
        raise HTTPException(status_code=400, detail="Некоторые файлы не найдены")
    
    try:
        # Update file metadata with status
        # file_metadata удалено из модели, используем другие способы хранения статуса
        # TODO: Реализовать хранение статуса review в отдельной таблице или case_metadata
        for file in files:
            pass  # Пока ничего не делаем, так как file_metadata удалено
        
        db.commit()
        
        logger.info(
            f"Batch withheld {len(files)} documents in case {case_id}",
            extra={
                "user_id": current_user.id,
                "case_id": case_id,
                "file_ids": request.file_ids,
                "action": "batch_withhold"
            }
        )
        
        return {
            "status": "success",
            "message": f"Заблокировано {len(files)} документов",
            "withheld_count": len(files)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при batch withhold для дела {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при блокировке документов")


@router.get("/{case_id}/files/{file_id}/related")
async def get_related_documents(
    case_id: str,
    file_id: str,
    limit: int = Query(5, ge=1, le=20, description="Maximum number of related documents"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get related documents based on shared entities and topics"""
    # Verify case ownership
    case = require_case_access(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get source file
    source_file = db.query(FileModel).filter(
        FileModel.id == file_id,
        FileModel.case_id == case_id
    ).first()
    
    if not source_file:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    # Get source file entities
    source_entities = db.query(ExtractedEntity).filter(
        ExtractedEntity.file_id == file_id,
        ExtractedEntity.case_id == case_id
    ).all()
    
    # Get source file classification
    source_classification = db.query(DocumentClassification).filter(
        DocumentClassification.file_id == file_id,
        DocumentClassification.case_id == case_id
    ).first()
    
    # Find related documents by shared entities
    related_files = []
    file_scores: Dict[str, float] = {}  # Initialize before use in topic matching
    if source_entities:
        # Get entity types and values from source file
        source_entity_types = set(e.entity_type for e in source_entities)
        source_entity_texts = set(e.text.lower() for e in source_entities)
        
        # Find files with shared entities
        all_entities = db.query(ExtractedEntity).filter(
            ExtractedEntity.case_id == case_id,
            ExtractedEntity.file_id != file_id
        ).all()
        
        # Group entities by file_id
        entities_by_file: Dict[str, List[ExtractedEntity]] = {}
        for entity in all_entities:
            if entity.file_id not in entities_by_file:
                entities_by_file[entity.file_id] = []
            entities_by_file[entity.file_id].append(entity)
        
        # Calculate similarity scores
        # file_scores already initialized above
        for file_id, entities in entities_by_file.items():
            score = 0.0
            shared_entities = 0
            
            for entity in entities:
                if entity.entity_type in source_entity_types:
                    score += 0.5
                if entity.text.lower() in source_entity_texts:
                    score += 1.0
                    shared_entities += 1
            
            if score > 0:
                # Normalize score
                score = min(100, (score / max(len(source_entities), 1)) * 100)
                file_scores[file_id] = score
        
        # Sort by score and get top files
        sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        # Get file details
        for file_id, score in sorted_files:
            file = db.query(FileModel).filter(FileModel.id == file_id).first()
            if file:
                classification = db.query(DocumentClassification).filter(
                    DocumentClassification.file_id == file_id
                ).first()
                
                related_files.append({
                    "file_id": file.id,
                    "filename": file.filename,
                    "relevance_score": round(score, 1),
                    "classification": {
                        "doc_type": classification.doc_type if classification else None,
                        "relevance_score": classification.relevance_score if classification else 0
                    } if classification else None
                })
    
    # Also consider documents with similar topics
    if source_classification and source_classification.key_topics:
        source_topics = set(source_classification.key_topics)
        
        # Find classifications with overlapping topics
        similar_classifications = db.query(DocumentClassification).filter(
            DocumentClassification.case_id == case_id,
            DocumentClassification.file_id != file_id
        ).all()
        
        topic_scores: Dict[str, float] = {}
        for classification in similar_classifications:
            if classification.key_topics:
                classification_topics = set(classification.key_topics)
                overlap = len(source_topics.intersection(classification_topics))
                if overlap > 0:
                    score = (overlap / max(len(source_topics), 1)) * 100
                    if classification.file_id not in file_scores:  # Don't duplicate
                        topic_scores[classification.file_id] = score
        
        # Add topic-based matches
        for file_id, score in sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)[:limit]:
            if file_id not in [f["file_id"] for f in related_files]:
                file = db.query(FileModel).filter(FileModel.id == file_id).first()
                if file:
                    classification = db.query(DocumentClassification).filter(
                        DocumentClassification.file_id == file_id
                    ).first()
                    
                    related_files.append({
                        "file_id": file.id,
                        "filename": file.filename,
                        "relevance_score": round(score, 1),
                        "classification": {
                            "doc_type": classification.doc_type if classification else None,
                            "relevance_score": classification.relevance_score if classification else 0
                        } if classification else None
                    })
    
    # Sort all related files by relevance score
    related_files.sort(key=lambda x: x["relevance_score"], reverse=True)
    
    return {
        "source_file_id": file_id,
        "source_filename": source_file.filename,
        "related_documents": related_files[:limit],
        "total_related": len(related_files)
    }


@router.get("/{case_id}/cost-stats")
async def get_cost_statistics(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Возвращает статистику расходов по кейсу.
    
    Показывает стоимость использования LLM для каждого агента
    и общую стоимость анализа.
    """
    # Verify case ownership
    case = require_case_access(db, case_id, current_user.id)
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        from app.services.langchain_agents.legacy_stubs import MetricsCollector
        
        metrics_collector = MetricsCollector(db)
        cost_stats = metrics_collector.get_cost_statistics(case_id)
        
        return cost_stats
        
    except Exception as e:
        logger.error(f"Error getting cost statistics for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при получении статистики расходов")

