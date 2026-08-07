"""Case members API (closed product: add existing users only)."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.case_sharing_service import CaseSharingError, CaseSharingService
from app.utils.auth import get_current_user
from app.utils.authorization import get_case_role, require_case_access, require_case_manage
from app.utils.database import get_db

router = APIRouter()


class InviteMemberRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: Literal["editor", "viewer"] = "editor"


class UpdateMemberRoleRequest(BaseModel):
    role: Literal["editor", "viewer"]


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: str


class MembersListResponse(BaseModel):
    members: List[Dict[str, Any]]
    my_role: Optional[str] = None


@router.get("/{case_id}/members", response_model=MembersListResponse)
async def list_case_members(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_case_access(db, case_id, current_user.id)
    svc = CaseSharingService(db)
    return MembersListResponse(
        members=svc.list_members(case_id),
        my_role=get_case_role(db, case_id, current_user.id),
    )


@router.post("/{case_id}/members/invite")
async def invite_case_member(
    case_id: str,
    request: InviteMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = require_case_manage(db, case_id, current_user.id)
    svc = CaseSharingService(db)
    try:
        result = svc.invite(
            case=case,
            email=request.email,
            role=request.role,
            invited_by=current_user.id,
        )
    except CaseSharingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return result


@router.patch("/{case_id}/members/{user_id}")
async def update_case_member_role(
    case_id: str,
    user_id: str,
    request: UpdateMemberRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = require_case_manage(db, case_id, current_user.id)
    svc = CaseSharingService(db)
    try:
        member = svc.update_member_role(
            case=case,
            target_user_id=user_id,
            new_role=request.role,
            actor_user_id=current_user.id,
        )
    except CaseSharingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"user_id": member.user_id, "role": member.role}


@router.delete("/{case_id}/members/{user_id}", status_code=204)
async def remove_case_member(
    case_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = require_case_manage(db, case_id, current_user.id)
    svc = CaseSharingService(db)
    try:
        svc.remove_member(case=case, target_user_id=user_id)
    except CaseSharingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return None


@router.post("/{case_id}/transfer-ownership")
async def transfer_case_ownership(
    case_id: str,
    request: TransferOwnershipRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    case = require_case_manage(db, case_id, current_user.id)
    svc = CaseSharingService(db)
    try:
        svc.transfer_ownership(
            case=case,
            new_owner_id=request.new_owner_user_id,
            actor_id=current_user.id,
        )
    except CaseSharingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"case_id": case_id, "owner_user_id": request.new_owner_user_id}
