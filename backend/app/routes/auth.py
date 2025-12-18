"""Authentication routes for Legal AI Vault"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
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
    email: str  # Изменено с EmailStr на str для совместимости
    password: str = Field(..., min_length=8, max_length=72, description="Password must be at least 8 characters and not exceed 72 bytes")
    full_name: str | None = Field(None, max_length=255, description="User's full name")
    company: str | None = Field(None, max_length=255, description="User's company")
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Валидация email"""
        if not v or '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower().strip()  # Нормализуем email
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        # Bcrypt limitation: 72 bytes max
        # For UTF-8, most characters are 1 byte, but some can be up to 4 bytes
        # To be safe, limit to 72 characters (which should be <= 72 bytes for ASCII)
        password_bytes = v.encode('utf-8')
        if len(password_bytes) > 72:
            raise ValueError('Password cannot exceed 72 bytes (approximately 72 characters for ASCII)')
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
    email: str  # Изменено с EmailStr на str для совместимости
    password: str
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Валидация email"""
        if not v or '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower().strip()  # Нормализуем email


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
    # Bcrypt limitation: 72 bytes max
    password_bytes = request.password.encode('utf-8')
    if len(password_bytes) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password cannot exceed 72 bytes (approximately 72 characters for ASCII)"
        )
    
    # Create user - используем поля, которые есть в БД
    user = User(
        email=request.email,
        password=get_password_hash(request.password),  # Используем password, не password_hash
        name=request.full_name,  # Используем name, не full_name
        role="USER"  # Используем "USER" вместо "user" для соответствия enum в БД
    )
    # company может отсутствовать в БД, пропускаем если нет поля
    if hasattr(User, 'company'):
        user.company = request.company
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
    
    # Используем property для совместимости
    user_full_name = user.full_name if hasattr(user, 'full_name') else (user.name if hasattr(user, 'name') else None)
    user_company = user.company if hasattr(user, 'company') else None
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user.id,
            "email": user.email,
            "full_name": user_full_name,
            "company": user_company,
            "role": user.role
        }
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """Login user"""
    try:
        logger.info(f"Login attempt for email: {request.email}")
        
        # Дополнительная валидация email (на случай проблем с EmailStr)
        if not request.email or '@' not in request.email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid email format"
            )
        
        # Валидация пароля
        if not request.password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password is required"
            )
        
    # Find user
    user = db.query(User).filter(User.email == request.email).first()
        if not user:
            logger.warning(f"Login failed: user not found for email {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
        # Проверка is_active через property (безопасно)
        try:
            if hasattr(user, 'is_active') and not user.is_active:
                logger.warning(f"Login failed: account inactive for email {request.email}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is inactive"
                )
        except (AttributeError, TypeError):
            # Если is_active не существует или не работает, пропускаем проверку
            pass
        
        # Verify password - используем password_hash property, который возвращает password
        # Сначала пробуем через property, потом напрямую
        try:
            password_to_check = user.password_hash
        except (AttributeError, TypeError):
            password_to_check = getattr(user, 'password', None)
        
        if not password_to_check:
            logger.error(f"Login failed: password field not found for user {user.id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error"
            )
        
        if not verify_password(request.password, password_to_check):
            logger.warning(f"Login failed: incorrect password for email {request.email}")
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
        
        # Используем property для совместимости
        try:
            user_full_name = user.full_name
        except (AttributeError, TypeError):
            user_full_name = getattr(user, 'name', None)
        
        user_company = getattr(user, 'company', None)
        
        logger.info(f"Login successful for user: {user.id}")
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user.id,
            "email": user.email,
                "full_name": user_full_name,
                "company": user_company,
            "role": user.role
        }
    )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
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
    # Используем property для совместимости
    user_full_name = current_user.full_name if hasattr(current_user, 'full_name') else (current_user.name if hasattr(current_user, 'name') else None)
    user_company = current_user.company if hasattr(current_user, 'company') else None
    user_created_at = current_user.created_at if hasattr(current_user, 'created_at') else (current_user.createdAt if hasattr(current_user, 'createdAt') else datetime.utcnow())
    
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=user_full_name,
        company=user_company,
        role=current_user.role,
        created_at=user_created_at.isoformat() if hasattr(user_created_at, 'isoformat') else str(user_created_at)
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
    
    # Get user - проверка is_active через try/except для совместимости
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    # Проверка is_active если поле существует
    try:
        if hasattr(user, 'is_active') and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is inactive"
            )
    except AttributeError:
        pass
    
    # Create new access token
    new_access_token = create_access_token(data={"sub": user.id})
    session.token = new_access_token
    session.last_used_at = datetime.utcnow()
    db.commit()
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }

