"""Analysis routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import Dict, Any
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case
from app.models.user import User
from app.models.analysis import AnalysisResult, Discrepancy, TimelineEvent
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
        
        valid_types = ["timeline", "discrepancies", "key_facts", "summary", "risk_analysis"]
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
    
    # Update case status
    case.status = "processing"
    if case.metadata is None:
        case.metadata = {}
    case.metadata["analysis_error"] = None
    db.commit()
    
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
                if background_case.metadata is None:
                    background_case.metadata = {}
                background_case.metadata["analysis_error"] = None
                background_case.metadata["analysis_completed_at"] = datetime.utcnow().isoformat()
                background_db.commit()
                logger.info(f"Analysis completed successfully for case {case_id}")
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Ошибка при анализе дела {case_id}: {error_msg}", exc_info=True)
                
                # Update case status to failed
                background_case.status = "failed"
                if background_case.metadata is None:
                    background_case.metadata = {}
                background_case.metadata["analysis_error"] = error_msg
                background_case.metadata["analysis_failed_at"] = datetime.utcnow().isoformat()
                background_db.commit()
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
        "case_status": case.status,
        "analysis_results": {
            result.analysis_type: {
                "status": result.status,
                "created_at": result.created_at.isoformat(),
                "updated_at": result.updated_at.isoformat()
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
                "date": event.date.isoformat(),
                "event_type": event.event_type,
                "description": event.description,
                "source_document": event.source_document,
                "source_page": event.source_page,
                "source_line": event.source_line,
                "metadata": event.metadata
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
        "facts": result.result_data,
        "created_at": result.created_at.isoformat()
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
    
    return {
        "summary": result.result_data.get("summary", ""),
        "key_facts": result.result_data.get("key_facts", {}),
        "created_at": result.created_at.isoformat()
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
    
    return {
        "analysis": result.result_data.get("analysis", ""),
        "discrepancies": result.result_data.get("discrepancies", {}),
        "created_at": result.created_at.isoformat()
    }

