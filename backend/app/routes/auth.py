"""Authentication routes for Legal AI Vault"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import logging
from app.utils.database import get_db
from app.utils.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user
)
from app.models.user import User, UserSession
from app.config import config

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterRequest(BaseModel):
    """Request model for user registration"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100, description="Password must be at least 8 characters")
    full_name: str | None = Field(None, max_length=255, description="User's full name")
    company: str | None = Field(None, max_length=255, description="User's company")
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        if len(v) > 100:
            raise ValueError('Password must be at most 100 characters long')
        return v
    
    @field_validator('full_name')
    @classmethod
    def validate_full_name(cls, v: str | None) -> str | None:
        if v is not None and len(v.strip()) == 0:
            return None
        if v is not None and len(v) > 255:
            raise ValueError('Full name must be at most 255 characters')
        return v
    
    @field_validator('company')
    @classmethod
    def validate_company(cls, v: str | None) -> str | None:
        if v is not None and len(v.strip()) == 0:
            return None
        if v is not None and len(v) > 255:
            raise ValueError('Company name must be at most 255 characters')
        return v


class LoginRequest(BaseModel):
    """Request model for user login"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response model for authentication"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    """Response model for user info"""
    id: str
    email: str
    full_name: str | None
    company: str | None
    role: str
    created_at: str


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=TokenResponse)
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """Register a new user"""
    logger.info(f"Registration attempt for email: {request.email}")
    
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        logger.warning(f"Registration failed: email {request.email} already exists")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Validate password
    if len(request.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    # Create user
    user = User(
        email=request.email,
        password_hash=get_password_hash(request.password),
        full_name=request.full_name,
        company=request.company,
        role="user"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Create tokens
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})
    
    # Create session
    expires_at = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    session = UserSession(
        user_id=user.id,
        token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at
    )
    db.add(session)
    db.commit()
    
    logger.info(
        f"User registered successfully: {user.id}",
        extra={"user_id": user.id, "email": user.email}
    )
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "company": user.company,
            "role": user.role
        }
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """Login user"""
    # Find user
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # Verify password
    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    # Create tokens
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})
    
    # Create or update session
    expires_at = datetime.utcnow() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    session = db.query(UserSession).filter(
        UserSession.user_id == user.id,
        UserSession.is_active == True
    ).first()
    
    if session:
        # Update existing session
        session.token = access_token
        session.refresh_token = refresh_token
        session.expires_at = expires_at
        session.last_used_at = datetime.utcnow()
    else:
        # Create new session
        session = UserSession(
            user_id=user.id,
            token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at
        )
        db.add(session)
    
    db.commit()
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "company": user.company,
            "role": user.role
        }
    )


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Logout user - deactivate current session"""
    session = db.query(UserSession).filter(
        UserSession.user_id == current_user.id,
        UserSession.is_active == True
    ).first()
    
    if session:
        session.is_active = False
        db.commit()
    
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        company=current_user.company,
        role=current_user.role,
        created_at=current_user.created_at.isoformat()
    )


@router.post("/refresh")
async def refresh_token(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    """Refresh access token using refresh token"""
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Verify session
    session = db.query(UserSession).filter(
        UserSession.refresh_token == refresh_token,
        UserSession.is_active == True
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
    
    # Get user
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    # Create new access token
    new_access_token = create_access_token(data={"sub": user.id})
    session.token = new_access_token
    session.last_used_at = datetime.utcnow()
    db.commit()
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }

