"""Settings routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from app.utils.database import get_db
from app.utils.auth import get_current_user, get_password_hash, verify_password
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    """Request model for profile update"""
    full_name: Optional[str] = Field(None, max_length=255, description="User's full name")
    company: Optional[str] = Field(None, max_length=255, description="User's company")
    specialization: Optional[list[str]] = Field(None, description="List of specializations")
    
    @field_validator('full_name')
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
            if len(v) > 255:
                raise ValueError('Full name must be at most 255 characters')
        return v
    
    @field_validator('company')
    @classmethod
    def validate_company(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
            if len(v) > 255:
                raise ValueError('Company name must be at most 255 characters')
        return v
    
    @field_validator('specialization')
    @classmethod
    def validate_specialization(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            if len(v) > 20:
                raise ValueError('Specialization list must have at most 20 items')
            # Validate each item
            for item in v:
                if not isinstance(item, str) or len(item.strip()) == 0:
                    raise ValueError('Each specialization must be a non-empty string')
                if len(item) > 100:
                    raise ValueError('Each specialization must be at most 100 characters')
        return v


class PasswordUpdateRequest(BaseModel):
    """Request model for password update"""
    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=8, max_length=72, description="New password (8-72 bytes)")
    
    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('New password must be at least 8 characters long')
        # Bcrypt limitation: 72 bytes max
        password_bytes = v.encode('utf-8')
        if len(password_bytes) > 72:
            raise ValueError('Password cannot exceed 72 bytes (approximately 72 characters for ASCII)')
        return v


class NotificationsSettings(BaseModel):
    """Notifications settings model"""
    email_on_analysis_complete: bool = True
    email_on_critical_discrepancies: bool = True
    weekly_digest: bool = False
    reminders_for_important_dates: bool = True
    news_and_updates: bool = False


class IntegrationsSettings(BaseModel):
    """Integrations settings model"""
    google_drive_enabled: bool = False
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = Field(None, max_length=500, description="Slack webhook URL")
    
    @field_validator('slack_webhook_url')
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
            if not v.startswith(('http://', 'https://')):
                raise ValueError('Webhook URL must start with http:// or https://')
            if len(v) > 500:
                raise ValueError('Webhook URL must be at most 500 characters')
        return v


@router.get("/profile")
async def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user profile"""
    # Безопасный доступ к полям для совместимости
    user_full_name = current_user.full_name if hasattr(current_user, 'full_name') else (current_user.name if hasattr(current_user, 'name') else None)
    user_company = getattr(current_user, 'company', None)
    user_created_at = current_user.created_at if hasattr(current_user, 'created_at') else (current_user.createdAt if hasattr(current_user, 'createdAt') else None)
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": user_full_name,
        "company": user_company,
        "role": current_user.role,
        "created_at": user_created_at.isoformat() if user_created_at else None
    }


@router.put("/profile")
async def update_profile(
    request: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update user profile"""
    try:
        if request.full_name is not None:
            # Используем свойство full_name или напрямую name
            if hasattr(current_user, 'full_name'):
                current_user.full_name = request.full_name
            elif hasattr(current_user, 'name'):
                current_user.name = request.full_name
        
        if request.company is not None:
            if hasattr(current_user, 'company'):
                current_user.company = request.company
        
        db.commit()
        db.refresh(current_user)
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при обновлении профиля пользователя {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при обновлении профиля. Попробуйте позже.")
    
    # Безопасный доступ к полям для ответа
    user_full_name = current_user.full_name if hasattr(current_user, 'full_name') else (current_user.name if hasattr(current_user, 'name') else None)
    user_company = getattr(current_user, 'company', None)
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": user_full_name,
        "company": user_company,
        "role": current_user.role
    }


@router.put("/password")
async def update_password(
    request: PasswordUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update user password"""
    # Verify current password
    if not verify_password(request.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль")
    
    # Validate new password
    if len(request.new_password) < 8:
        raise HTTPException(status_code=400, detail="Новый пароль должен быть не менее 8 символов")
    # Bcrypt limitation: 72 bytes max
    password_bytes = request.new_password.encode('utf-8')
    if len(password_bytes) > 72:
        raise HTTPException(
            status_code=400,
            detail="Пароль не может превышать 72 байта (примерно 72 символа для ASCII)"
        )
    
    try:
        # Update password
        current_user.password_hash = get_password_hash(request.new_password)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при обновлении пароля пользователя {current_user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при обновлении пароля. Попробуйте позже.")
    
    return {"message": "Пароль успешно обновлен"}


@router.get("/notifications")
async def get_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get notifications settings"""
    # In future, store in separate table or user metadata
    # For now, return defaults
    return {
        "email_on_analysis_complete": True,
        "email_on_critical_discrepancies": True,
        "weekly_digest": False,
        "reminders_for_important_dates": True,
        "news_and_updates": False
    }


@router.put("/notifications")
async def update_notifications(
    settings: NotificationsSettings,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update notifications settings"""
    # In future, save to database
    # For now, just return success
    return {
        "message": "Настройки уведомлений обновлены",
        "settings": settings.dict()
    }


@router.get("/integrations")
async def get_integrations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get integrations settings"""
    # In future, store in separate table
    return {
        "google_drive": {
            "enabled": False,
            "connected_account": None
        },
        "slack": {
            "enabled": False,
            "workspace": None,
            "webhook_url": None
        }
    }


@router.put("/integrations")
async def update_integrations(
    settings: IntegrationsSettings,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update integrations settings"""
    # In future, save to database and handle OAuth
    return {
        "message": "Настройки интеграций обновлены",
        "settings": settings.dict()
    }
