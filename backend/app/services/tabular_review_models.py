"""Pydantic models for Tabular Review structured output"""
from typing import Optional, Annotated
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
import re
import logging

from app.services.date_validator import parse_and_normalize_date

logger = logging.getLogger(__name__)


def validate_currency(value: str) -> str:
    """Validate and normalize currency value"""
    if not value or not isinstance(value, str):
        raise ValueError(f"Invalid currency value: {value}")
    
    # Remove currency symbols, spaces, and commas
    cleaned = re.sub(r'[^\d.,]', '', value.replace(' ', '').replace(',', '.'))
    
    # Try to parse as float
    try:
        float(cleaned)
        return cleaned
    except ValueError:
        raise ValueError(f"Invalid currency format: {value}")


def validate_number(value: str) -> str:
    """Validate and normalize number value"""
    if not value or not isinstance(value, str):
        raise ValueError(f"Invalid number value: {value}")
    
    # Remove spaces and replace comma with dot
    cleaned = value.replace(' ', '').replace(',', '.')
    
    # Try to parse as float
    try:
        float(cleaned)
        return cleaned
    except ValueError:
        raise ValueError(f"Invalid number format: {value}")


def validate_yes_no(value: str) -> str:
    """Validate and normalize yes/no value"""
    if not value or not isinstance(value, str):
        return "Unknown"
    
    value_lower = value.lower().strip()
    
    if value_lower in ['yes', 'да', 'есть', 'true', '1', 'да, есть', 'есть, да']:
        return 'Yes'
    elif value_lower in ['no', 'нет', 'нету', 'false', '0', 'не', 'отсутствует']:
        return 'No'
    else:
        return 'Unknown'


class TabularCellExtractionModel(BaseModel):
    """Pydantic model for structured output of tabular cell extraction"""
    
    cell_value: str = Field(description="Извлеченное значение ячейки")
    verbatim_extract: Optional[str] = Field(None, description="Точная цитата из документа (для verbatim типа)")
    source_page: Optional[int] = Field(None, description="Номер страницы в документе, где найдена информация")
    source_section: Optional[str] = Field(None, description="Раздел документа (например, 'Раздел 3.1', 'Статья 5')")
    source_start_line: Optional[int] = Field(None, description="Начальная строка в документе (если доступно)")
    source_end_line: Optional[int] = Field(None, description="Конечная строка в документе (если доступно)")
    confidence: float = Field(0.8, description="Уверенность в извлечении (0.0-1.0)", ge=0.0, le=1.0)
    reasoning: str = Field(description="Подробное объяснение как было извлечено значение и откуда")
    extraction_method: str = Field("llm", description="Метод извлечения: llm, regex, hybrid")
    
    # Store column_type for validation
    column_type: Optional[str] = Field(None, description="Тип колонки для валидации (не сохраняется в БД)")
    
    @field_validator('cell_value')
    @classmethod
    def validate_cell_value(cls, v: str, info) -> str:
        """Validate cell_value based on column_type"""
        if not v or v.strip() == "":
            # Allow empty for N/A cases
            return v.strip() if v else "N/A"
        
        # Get column_type from context if available
        column_type = None
        if hasattr(info, 'data') and info.data:
            column_type = info.data.get('column_type')
        
        # If no column_type, return as-is
        if not column_type:
            return v.strip()
        
        # Validate based on type
        if column_type == 'date':
            try:
                # Try to normalize date
                normalized = parse_and_normalize_date(v)
                # Verify it's valid date format
                datetime.strptime(normalized, "%Y-%m-%d")
                return normalized
            except Exception as e:
                logger.warning(f"Could not normalize date '{v}': {e}")
                # Return original if normalization fails
                return v.strip()
        
        elif column_type == 'currency':
            try:
                return validate_currency(v)
            except ValueError as e:
                logger.warning(f"Currency validation failed for '{v}': {e}")
                return v.strip()
        
        elif column_type == 'number':
            try:
                return validate_number(v)
            except ValueError as e:
                logger.warning(f"Number validation failed for '{v}': {e}")
                return v.strip()
        
        elif column_type == 'yes_no':
            return validate_yes_no(v)
        
        # For text, verbatim, tags - no validation needed
        return v.strip()
    
    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is in valid range"""
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v
    
    @model_validator(mode='after')
    def validate_verbatim_for_type(self):
        """Ensure verbatim_extract is set for verbatim type"""
        if self.column_type == 'verbatim' and not self.verbatim_extract:
            # If verbatim type but no verbatim_extract, use cell_value
            self.verbatim_extract = self.cell_value
        return self
    
    class Config:
        """Pydantic config"""
        # Allow extra fields (like column_type) that won't be saved to DB
        extra = 'allow'
        # Use enum values instead of enum names
        use_enum_values = True

