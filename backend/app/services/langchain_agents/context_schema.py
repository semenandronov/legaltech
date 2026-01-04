"""Context schema for agent system - immutable case metadata"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from app.models.case import Case


class CaseContext(BaseModel):
    """Неизменяемый контекст дела - метаданные, прокидываемые в runtime
    
    Это неизменяемая структура данных, содержащая метаданные дела,
    которые передаются во все tools и агенты через ToolRuntime.
    """
    
    case_id: str = Field(..., description="Идентификатор дела")
    user_id: str = Field(..., description="Идентификатор пользователя")
    jurisdiction: Optional[str] = Field(None, description="Юрисдикция дела (например, РФ, США)")
    case_type: Optional[str] = Field(None, description="Тип дела (litigation, contracts, dd, compliance, other)")
    client_name: Optional[str] = Field(None, description="Имя клиента")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Дата создания контекста")
    
    class Config:
        frozen = True  # Неизменяемая модель после создания
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    @classmethod
    def from_case_model(cls, case: Case) -> "CaseContext":
        """Создать CaseContext из модели Case из базы данных
        
        Args:
            case: Экземпляр модели Case из SQLAlchemy
            
        Returns:
            CaseContext с заполненными полями
        """
        # Извлекаем jurisdiction и client_name из case_metadata если они есть
        jurisdiction = None
        client_name = None
        
        if case.case_metadata and isinstance(case.case_metadata, dict):
            jurisdiction = case.case_metadata.get("jurisdiction")
            client_name = case.case_metadata.get("client_name")
        
        return cls(
            case_id=case.id,
            user_id=case.user_id or "",  # user_id может быть None, используем пустую строку
            jurisdiction=jurisdiction,
            case_type=case.case_type,
            client_name=client_name,
            created_at=case.created_at if case.created_at else datetime.utcnow()
        )
    
    @classmethod
    def from_minimal(cls, case_id: str, user_id: str = "") -> "CaseContext":
        """Создать минимальный CaseContext только с обязательными полями
        
        Используется когда полная модель Case недоступна,
        но нужно создать контекст для работы системы.
        
        Args:
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя (опционально)
            
        Returns:
            CaseContext с минимальными данными
        """
        return cls(
            case_id=case_id,
            user_id=user_id,
            jurisdiction=None,
            case_type=None,
            client_name=None,
            created_at=datetime.utcnow()
        )

