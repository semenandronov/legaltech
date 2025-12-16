"""Reports routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, Response, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case
from app.models.user import User
from app.models.analysis import AnalysisResult, Discrepancy, TimelineEvent
from app.services.report_generator import ReportGenerator
from app.services.analysis_service import AnalysisService
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{case_id}/generate")
async def generate_report(
    case_id: str,
    report_type: str = Query(...),  # executive_summary, detailed_analysis, court_filing, contract_comparison
    format: str = Query("word"),  # word, pdf, excel
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate a report for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get analysis data
    summary_result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "summary"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    key_facts_result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "key_facts"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    risk_result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "risk_analysis"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    timeline_events = db.query(TimelineEvent).filter(
        TimelineEvent.case_id == case_id
    ).order_by(TimelineEvent.date.asc()).all()
    
    discrepancies = db.query(Discrepancy).filter(
        Discrepancy.case_id == case_id
    ).all()
    
    # Prepare data
    summary = summary_result.result_data.get("summary", "") if summary_result else ""
    key_facts = key_facts_result.result_data if key_facts_result else {}
    risk_analysis = risk_result.result_data.get("analysis", "") if risk_result else None
    
    timeline_data = [
        {
            "date": event.date.isoformat(),
            "description": event.description,
            "source_document": event.source_document,
            "source_page": event.source_page,
            "source_line": event.source_line
        }
        for event in timeline_events
    ]
    
    discrepancies_data = [
        {
            "type": disc.type,
            "severity": disc.severity,
            "description": disc.description,
            "source_documents": disc.source_documents,
            "details": disc.details
        }
        for disc in discrepancies
    ]
    
    # Generate report
    report_generator = ReportGenerator(db)
    
    try:
        if report_type == "executive_summary":
            if format == "word":
                buffer = report_generator.generate_executive_summary(
                    case_id, summary, key_facts, risk_analysis
                )
                return Response(
                    content=buffer.read(),
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="executive_summary_{case_id}.docx"'}
                )
            elif format == "pdf":
                buffer = report_generator.generate_pdf_report(case_id, summary, key_facts)
                return Response(
                    content=buffer.read(),
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="executive_summary_{case_id}.pdf"'}
                )
        
        elif report_type == "detailed_analysis":
            buffer = report_generator.generate_detailed_analysis(
                case_id, timeline_data, discrepancies_data, key_facts, summary, risk_analysis
            )
            return Response(
                content=buffer.read(),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="detailed_analysis_{case_id}.docx"'}
            )
        
        elif report_type == "court_filing":
            buffer = report_generator.generate_court_filing(
                case_id, {}, key_facts, timeline_data, discrepancies_data
            )
            return Response(
                content=buffer.read(),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f'attachment; filename="court_filing_{case_id}.docx"'}
            )
        
        elif report_type == "contract_comparison":
            # For contract comparison, need contracts data
            contracts_data = []  # Would need to extract from case documents
            buffer = report_generator.generate_contract_comparison(case_id, contracts_data)
            return Response(
                content=buffer.read(),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="contract_comparison_{case_id}.xlsx"'}
            )
        
        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип отчета")
    
    except Exception as e:
        logger.error(f"Ошибка при генерации отчета: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при генерации отчета: {str(e)}")


@router.get("/{case_id}")
async def get_reports_list(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of available reports for a case"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Return available report types
    return {
        "case_id": case_id,
        "available_reports": [
            {
                "type": "executive_summary",
                "name": "Executive Summary",
                "formats": ["word", "pdf"],
                "description": "Краткое резюме дела (1-2 страницы)"
            },
            {
                "type": "detailed_analysis",
                "name": "Detailed Analysis",
                "formats": ["word"],
                "description": "Полный анализ (5-10 страниц)"
            },
            {
                "type": "court_filing",
                "name": "Court Filing",
                "formats": ["word"],
                "description": "Документ для подачи в суд"
            },
            {
                "type": "contract_comparison",
                "name": "Contract Comparison",
                "formats": ["excel"],
                "description": "Сравнение контрактов (Excel)"
            }
        ]
    }

