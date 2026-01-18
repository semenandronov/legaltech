"""API routes for Playbooks - contract compliance checking"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from app.services.playbook_service import PlaybookService
from app.services.playbook_checker import PlaybookChecker
from app.services.redline_generator import RedlineGenerator, RedlineDocument, Redline
from app.routes.auth import get_current_user, get_db
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


# ==================== PYDANTIC MODELS ====================

class RuleConditionConfig(BaseModel):
    """Rule condition configuration"""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_duration: Optional[str] = None
    max_duration: Optional[str] = None
    patterns: Optional[List[str]] = None
    required_patterns: Optional[List[str]] = None
    forbidden_patterns: Optional[List[str]] = None
    match_type: Optional[str] = "any"


class PlaybookRuleCreate(BaseModel):
    """Request to create a playbook rule"""
    rule_type: str = Field(..., description="red_line, fallback, or no_go")
    clause_category: str = Field(..., description="Category of clause to check")
    rule_name: str = Field(..., description="Name of the rule")
    description: Optional[str] = None
    condition_type: str = Field(..., description="must_exist, must_not_exist, value_check, duration_check, text_match, text_not_match")
    condition_config: Optional[RuleConditionConfig] = None
    extraction_prompt: Optional[str] = None
    validation_prompt: Optional[str] = None
    suggested_clause_template: Optional[str] = None
    fallback_options: Optional[List[dict]] = None
    priority: int = 0
    severity: str = "medium"
    is_active: bool = True


class PlaybookRuleUpdate(BaseModel):
    """Request to update a playbook rule"""
    rule_type: Optional[str] = None
    clause_category: Optional[str] = None
    rule_name: Optional[str] = None
    description: Optional[str] = None
    condition_type: Optional[str] = None
    condition_config: Optional[RuleConditionConfig] = None
    extraction_prompt: Optional[str] = None
    validation_prompt: Optional[str] = None
    suggested_clause_template: Optional[str] = None
    fallback_options: Optional[List[dict]] = None
    priority: Optional[int] = None
    severity: Optional[str] = None
    is_active: Optional[bool] = None


class PlaybookCreate(BaseModel):
    """Request to create a playbook"""
    name: str = Field(..., description="Unique identifier name")
    display_name: str = Field(..., description="Display name")
    description: Optional[str] = None
    document_type: str = Field(..., description="Type of document this playbook is for")
    jurisdiction: Optional[str] = None
    is_public: bool = False
    rules: Optional[List[PlaybookRuleCreate]] = None


class PlaybookUpdate(BaseModel):
    """Request to update a playbook"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    document_type: Optional[str] = None
    jurisdiction: Optional[str] = None
    is_public: Optional[bool] = None


class CheckDocumentRequest(BaseModel):
    """Request to check a document"""
    document_id: str = Field(..., description="ID of the document to check")
    case_id: Optional[str] = None


class BatchCheckRequest(BaseModel):
    """Request to check multiple documents"""
    document_ids: List[str] = Field(..., description="List of document IDs to check")
    case_id: Optional[str] = None


# ==================== METADATA ENDPOINTS (most specific first) ====================

@router.get("/metadata/document-types")
async def get_document_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available document types"""
    service = PlaybookService(db)
    return service.get_document_types()


@router.get("/metadata/clause-categories")
async def get_clause_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available clause categories"""
    service = PlaybookService(db)
    return service.get_clause_categories()


@router.get("/metadata/jurisdictions")
async def get_jurisdictions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available jurisdictions"""
    service = PlaybookService(db)
    return service.get_jurisdictions()


@router.get("/metadata/rule-types")
async def get_rule_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available rule types"""
    service = PlaybookService(db)
    return service.get_rule_types()


@router.get("/metadata/condition-types")
async def get_condition_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get available condition types"""
    service = PlaybookService(db)
    return service.get_condition_types()


# ==================== CHECK RESULTS (before /{playbook_id} to avoid conflicts) ====================

@router.get("/checks")
async def list_checks(
    playbook_id: Optional[str] = Query(None),
    case_id: Optional[str] = Query(None),
    document_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List playbook checks"""
    service = PlaybookService(db)
    
    return service.get_checks(
        user_id=current_user.id,
        playbook_id=playbook_id,
        case_id=case_id,
        document_id=document_id,
        status=status,
        limit=limit,
        offset=offset
    )


@router.get("/checks/{check_id}")
async def get_check(
    check_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific check with full details"""
    service = PlaybookService(db)
    
    result = service.get_check(check_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Check not found")
    
    return result


@router.get("/checks/{check_id}/redlines")
async def get_check_redlines(
    check_id: str,
    format: str = Query("json", description="Output format: json, text, html"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get redlines for a check in various formats"""
    service = PlaybookService(db)
    
    check = service.get_check(check_id, current_user.id)
    
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    
    redlines_data = check.get("redlines", [])
    
    if format == "json":
        return {"redlines": redlines_data}
    
    # Convert to Redline objects for formatting
    generator = RedlineGenerator()
    redlines = [
        Redline(
            rule_id=r.get("rule_id", ""),
            rule_name=r.get("rule_name", ""),
            rule_type=r.get("rule_type", "red_line"),
            change_type=r.get("change_type", "replace"),
            original_text=r.get("original_text", ""),
            suggested_text=r.get("suggested_text", ""),
            location=r.get("location", {}),
            issue_description=r.get("issue_description", ""),
            priority=r.get("priority", "medium"),
            confidence=r.get("confidence", 0.0),
            reasoning=r.get("reasoning", "")
        )
        for r in redlines_data
    ]
    
    redline_doc = generator.generate_redline_document(
        document_id=check.get("document_id", ""),
        document_name=check.get("document_name", "Document"),
        redlines=redlines
    )
    
    if format == "text":
        content = generator.format_redlines_as_text(redline_doc)
        return Response(
            content=content,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=redlines_{check_id}.txt"}
        )
    elif format == "html":
        content = generator.format_redlines_as_html(redline_doc)
        return Response(
            content=content,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=redlines_{check_id}.html"}
        )
    else:
        return {"redlines": redlines_data}


# ==================== PLAYBOOK CRUD ====================

@router.get("/")
async def list_playbooks(
    document_type: Optional[str] = Query(None, description="Filter by document type"),
    jurisdiction: Optional[str] = Query(None, description="Filter by jurisdiction"),
    include_system: bool = Query(True, description="Include system playbooks"),
    include_public: bool = Query(True, description="Include public playbooks"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List available playbooks"""
    service = PlaybookService(db)
    return service.get_playbooks(
        user_id=current_user.id,
        document_type=document_type,
        jurisdiction=jurisdiction,
        include_system=include_system,
        include_public=include_public,
        limit=limit,
        offset=offset
    )


@router.post("/")
async def create_playbook(
    request: PlaybookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new playbook"""
    service = PlaybookService(db)
    
    try:
        rules_data = None
        if request.rules:
            rules_data = [r.model_dump(exclude_none=True) for r in request.rules]
            # Convert condition_config to dict
            for rule in rules_data:
                if rule.get("condition_config"):
                    rule["condition_config"] = dict(rule["condition_config"])
        
        return service.create_playbook(
            user_id=current_user.id,
            name=request.name,
            display_name=request.display_name,
            description=request.description,
            document_type=request.document_type,
            jurisdiction=request.jurisdiction,
            is_public=request.is_public,
            rules=rules_data
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== PLAYBOOK BY ID (must be after /checks, /metadata, etc.) ====================

@router.get("/{playbook_id}")
async def get_playbook(
    playbook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific playbook with all rules"""
    service = PlaybookService(db)
    playbook = service.get_playbook(playbook_id, current_user.id)
    
    if not playbook:
        raise HTTPException(status_code=404, detail="Playbook not found")
    
    return playbook


@router.put("/{playbook_id}")
async def update_playbook(
    playbook_id: str,
    request: PlaybookUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a playbook"""
    service = PlaybookService(db)
    
    updates = request.model_dump(exclude_unset=True)
    result = service.update_playbook(playbook_id, current_user.id, updates)
    
    if not result:
        raise HTTPException(status_code=404, detail="Playbook not found or access denied")
    
    return result


@router.delete("/{playbook_id}")
async def delete_playbook(
    playbook_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a playbook"""
    service = PlaybookService(db)
    
    if not service.delete_playbook(playbook_id, current_user.id):
        raise HTTPException(status_code=404, detail="Playbook not found or access denied")
    
    return {"message": "Playbook deleted successfully"}


@router.post("/{playbook_id}/duplicate")
async def duplicate_playbook(
    playbook_id: str,
    new_name: Optional[str] = Query(None, description="New name for the duplicate"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Duplicate a playbook to your library"""
    service = PlaybookService(db)
    
    result = service.duplicate_playbook(playbook_id, current_user.id, new_name)
    
    if not result:
        raise HTTPException(status_code=404, detail="Playbook not found or access denied")
    
    return result


# ==================== RULES CRUD ====================

@router.post("/{playbook_id}/rules")
async def add_rule(
    playbook_id: str,
    request: PlaybookRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add a rule to a playbook"""
    service = PlaybookService(db)
    
    rule_data = request.model_dump(exclude_none=True)
    if rule_data.get("condition_config"):
        rule_data["condition_config"] = dict(rule_data["condition_config"])
    
    result = service.add_rule(playbook_id, current_user.id, rule_data)
    
    if not result:
        raise HTTPException(status_code=404, detail="Playbook not found or access denied")
    
    return result


@router.put("/{playbook_id}/rules/{rule_id}")
async def update_rule(
    playbook_id: str,
    rule_id: str,
    request: PlaybookRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a rule"""
    service = PlaybookService(db)
    
    updates = request.model_dump(exclude_unset=True)
    if updates.get("condition_config"):
        updates["condition_config"] = dict(updates["condition_config"])
    
    result = service.update_rule(playbook_id, rule_id, current_user.id, updates)
    
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found or access denied")
    
    return result


@router.delete("/{playbook_id}/rules/{rule_id}")
async def delete_rule(
    playbook_id: str,
    rule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a rule"""
    service = PlaybookService(db)
    
    if not service.delete_rule(playbook_id, rule_id, current_user.id):
        raise HTTPException(status_code=404, detail="Rule not found or access denied")
    
    return {"message": "Rule deleted successfully"}


@router.get("/{playbook_id}/rules/{rule_id}")
async def get_rule(
    playbook_id: str,
    rule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific rule"""
    service = PlaybookService(db)
    
    result = service.get_rule(playbook_id, rule_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found or access denied")
    
    return result


# ==================== CHECKING ====================

@router.post("/{playbook_id}/check")
async def check_document(
    playbook_id: str,
    request: CheckDocumentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check a document against a playbook"""
    checker = PlaybookChecker(db)
    
    try:
        result = await checker.check_document(
            document_id=request.document_id,
            playbook_id=playbook_id,
            user_id=current_user.id,
            case_id=request.case_id
        )
        
        return {
            "check_id": result.check_id,
            "playbook_id": result.playbook_id,
            "document_id": result.document_id,
            "overall_status": result.overall_status,
            "compliance_score": result.compliance_score,
            "red_line_violations": result.red_line_violations,
            "fallback_issues": result.fallback_issues,
            "no_go_violations": result.no_go_violations,
            "passed_rules": result.passed_rules,
            "results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "rule_type": r.rule_type,
                    "status": r.status,
                    "issue_description": r.issue_description,
                    "confidence": r.confidence
                }
                for r in result.results
            ],
            "redlines_count": len(result.redlines),
            "processing_time_seconds": result.processing_time_seconds
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error checking document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to check document")


@router.post("/{playbook_id}/batch-check")
async def batch_check_documents(
    playbook_id: str,
    request: BatchCheckRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check multiple documents against a playbook (async)"""
    # For now, run synchronously. In production, use background tasks
    checker = PlaybookChecker(db)
    
    try:
        results = await checker.batch_check(
            document_ids=request.document_ids,
            playbook_id=playbook_id,
            user_id=current_user.id,
            case_id=request.case_id
        )
        
        return {
            "total_documents": len(request.document_ids),
            "completed": len([r for r in results if r.overall_status != "failed"]),
            "failed": len([r for r in results if r.overall_status == "failed"]),
            "results": [
                {
                    "document_id": r.document_id,
                    "check_id": r.check_id,
                    "overall_status": r.overall_status,
                    "compliance_score": r.compliance_score,
                    "violations": r.red_line_violations + r.no_go_violations
                }
                for r in results
            ]
        }
    except Exception as e:
        logger.error(f"Error in batch check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to check documents")
