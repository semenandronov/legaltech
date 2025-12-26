"""API routes for folder management"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from app.models.folder import Folder, FolderService, FileTag
from app.models.case import Case
from app.routes.auth import get_current_user, get_db
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/folders", tags=["folders"])


# Pydantic models
class CreateFolderRequest(BaseModel):
    name: str
    parent_id: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None


class UpdateFolderRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    parent_id: Optional[str] = None


class MoveFolderRequest(BaseModel):
    new_parent_id: Optional[str] = None


class ReorderFoldersRequest(BaseModel):
    folder_ids: List[str]


class FolderResponse(BaseModel):
    id: str
    case_id: str
    parent_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    order_index: int = 0
    file_count: int = 0
    
    class Config:
        from_attributes = True


class CreateTagRequest(BaseModel):
    name: str
    color: Optional[str] = None


class TagResponse(BaseModel):
    id: str
    case_id: str
    name: str
    color: Optional[str] = None
    
    class Config:
        from_attributes = True


def _verify_case_access(case_id: str, user: User, db: Session) -> Case:
    """Verify user has access to the case"""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    
    return case


@router.get("/cases/{case_id}/folders")
async def get_folders(
    case_id: str,
    parent_id: Optional[str] = Query(None, description="Parent folder ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get folders for a case"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    folders = service.get_folders(case_id, parent_id)
    
    return [f.to_dict() for f in folders]


@router.get("/cases/{case_id}/folders/tree")
async def get_folder_tree(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get full folder tree for a case"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    tree = service.get_folder_tree(case_id)
    
    return tree


@router.post("/cases/{case_id}/folders")
async def create_folder(
    case_id: str,
    request: CreateFolderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new folder"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    folder = service.create_folder(
        case_id=case_id,
        name=request.name,
        parent_id=request.parent_id,
        description=request.description,
        color=request.color,
        icon=request.icon
    )
    
    return folder.to_dict()


@router.get("/cases/{case_id}/folders/{folder_id}")
async def get_folder(
    case_id: str,
    folder_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific folder"""
    _verify_case_access(case_id, current_user, db)
    
    folder = db.query(Folder).filter(
        Folder.id == folder_id,
        Folder.case_id == case_id
    ).first()
    
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    return folder.to_dict(include_children=True)


@router.put("/cases/{case_id}/folders/{folder_id}")
async def update_folder(
    case_id: str,
    folder_id: str,
    request: UpdateFolderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a folder"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    updates = request.model_dump(exclude_unset=True)
    folder = service.update_folder(folder_id, updates)
    
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    return folder.to_dict()


@router.delete("/cases/{case_id}/folders/{folder_id}")
async def delete_folder(
    case_id: str,
    folder_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a folder"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    if not service.delete_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    
    return {"message": "Folder deleted successfully"}


@router.post("/cases/{case_id}/folders/{folder_id}/move")
async def move_folder(
    case_id: str,
    folder_id: str,
    request: MoveFolderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Move a folder to a new parent"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    try:
        folder = service.move_folder(folder_id, request.new_parent_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        return folder.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cases/{case_id}/folders/reorder")
async def reorder_folders(
    case_id: str,
    request: ReorderFoldersRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Reorder folders"""
    _verify_case_access(case_id, current_user, db)
    
    service = FolderService(db)
    service.reorder_folders(request.folder_ids)
    
    return {"message": "Folders reordered successfully"}


# File Tags endpoints
@router.get("/cases/{case_id}/tags")
async def get_tags(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all tags for a case"""
    _verify_case_access(case_id, current_user, db)
    
    tags = db.query(FileTag).filter(FileTag.case_id == case_id).all()
    return [t.to_dict() for t in tags]


@router.post("/cases/{case_id}/tags")
async def create_tag(
    case_id: str,
    request: CreateTagRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new tag"""
    _verify_case_access(case_id, current_user, db)
    
    # Check if tag already exists
    existing = db.query(FileTag).filter(
        FileTag.case_id == case_id,
        FileTag.name == request.name
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Tag already exists")
    
    tag = FileTag(
        case_id=case_id,
        name=request.name,
        color=request.color
    )
    db.add(tag)
    db.commit()
    
    return tag.to_dict()


@router.delete("/cases/{case_id}/tags/{tag_id}")
async def delete_tag(
    case_id: str,
    tag_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a tag"""
    _verify_case_access(case_id, current_user, db)
    
    tag = db.query(FileTag).filter(
        FileTag.id == tag_id,
        FileTag.case_id == case_id
    ).first()
    
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    
    db.delete(tag)
    db.commit()
    
    return {"message": "Tag deleted successfully"}

