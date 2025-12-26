"""API routes for prompt library"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.services.prompt_library_service import PromptLibraryService
from app.routes.auth import get_current_user, get_db
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])


# Pydantic models
class VariableSchema(BaseModel):
    name: str
    type: str = "text"
    description: Optional[str] = None
    required: bool = False


class CreatePromptRequest(BaseModel):
    title: str
    prompt_text: str
    category: str = "custom"
    description: Optional[str] = None
    variables: Optional[List[VariableSchema]] = None
    tags: Optional[List[str]] = None
    is_public: bool = False


class UpdatePromptRequest(BaseModel):
    title: Optional[str] = None
    prompt_text: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    variables: Optional[List[VariableSchema]] = None
    tags: Optional[List[str]] = None
    is_public: Optional[bool] = None


class UsePromptRequest(BaseModel):
    variables: Optional[dict] = None


class PromptResponse(BaseModel):
    id: str
    title: str
    prompt_text: str
    category: str
    description: Optional[str] = None
    variables: List[dict] = []
    tags: List[str] = []
    is_public: bool = False
    is_system: bool = False
    usage_count: int = 0
    
    class Config:
        from_attributes = True


@router.get("/categories")
async def get_categories(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get all prompt categories"""
    service = PromptLibraryService(db)
    return service.get_categories()


@router.get("/")
async def list_prompts(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search in title and description"),
    include_public: bool = Query(True, description="Include public templates"),
    include_system: bool = Query(True, description="Include system templates"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """List prompt templates"""
    service = PromptLibraryService(db)
    return service.get_templates(
        user_id=current_user.id,
        category=category,
        search=search,
        include_public=include_public,
        include_system=include_system,
        limit=limit,
        offset=offset
    )


@router.get("/popular")
async def get_popular_prompts(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get most popular prompts"""
    service = PromptLibraryService(db)
    return service.get_popular_templates(
        user_id=current_user.id,
        limit=limit
    )


@router.get("/recent")
async def get_recent_prompts(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get recently used prompts"""
    service = PromptLibraryService(db)
    return service.get_recent_templates(
        user_id=current_user.id,
        limit=limit
    )


@router.get("/{prompt_id}")
async def get_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get a specific prompt template"""
    service = PromptLibraryService(db)
    template = service.get_template(prompt_id, current_user.id)
    
    if not template:
        raise HTTPException(status_code=404, detail="Prompt not found")
    
    return template


@router.post("/")
async def create_prompt(
    request: CreatePromptRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Create a new prompt template"""
    service = PromptLibraryService(db)
    
    variables = None
    if request.variables:
        variables = [v.model_dump() for v in request.variables]
    
    return service.create_template(
        user_id=current_user.id,
        title=request.title,
        prompt_text=request.prompt_text,
        category=request.category,
        description=request.description,
        variables=variables,
        tags=request.tags,
        is_public=request.is_public
    )


@router.put("/{prompt_id}")
async def update_prompt(
    prompt_id: str,
    request: UpdatePromptRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update a prompt template"""
    service = PromptLibraryService(db)
    
    updates = request.model_dump(exclude_unset=True)
    if "variables" in updates and updates["variables"]:
        updates["variables"] = [v.model_dump() if hasattr(v, 'model_dump') else v for v in updates["variables"]]
    
    result = service.update_template(prompt_id, current_user.id, updates)
    
    if not result:
        raise HTTPException(status_code=404, detail="Prompt not found or access denied")
    
    return result


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete a prompt template"""
    service = PromptLibraryService(db)
    
    if not service.delete_template(prompt_id, current_user.id):
        raise HTTPException(status_code=404, detail="Prompt not found or access denied")
    
    return {"message": "Prompt deleted successfully"}


@router.post("/{prompt_id}/use")
async def use_prompt(
    prompt_id: str,
    request: UsePromptRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Use a prompt template - renders it and tracks usage"""
    service = PromptLibraryService(db)
    
    rendered = service.use_template(
        template_id=prompt_id,
        user_id=current_user.id,
        variables=request.variables
    )
    
    if rendered is None:
        raise HTTPException(status_code=404, detail="Prompt not found or access denied")
    
    return {"rendered_prompt": rendered}


@router.post("/{prompt_id}/duplicate")
async def duplicate_prompt(
    prompt_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Duplicate a prompt template to your library"""
    service = PromptLibraryService(db)
    
    result = service.duplicate_template(prompt_id, current_user.id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Prompt not found or access denied")
    
    return result


@router.post("/init-system")
async def init_system_prompts(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Initialize system prompts (admin only)"""
    # TODO: Add admin check
    service = PromptLibraryService(db)
    service.init_system_prompts()
    return {"message": "System prompts initialized"}

