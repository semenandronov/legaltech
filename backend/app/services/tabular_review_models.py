"""Pydantic models for Tabular Review structured output"""
from typing import Any, Optional, Dict
import re
import logging

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.tabular_column_type_contract import (
    is_blank_placeholder,
    strict_normalize_cell_value,
)
from app.services.tabular_extraction_policy import TABULAR_NA_VALUE, is_na_cell_value

logger = logging.getLogger(__name__)

# Канон yes_no для UI и новых извлечений (legacy Yes/No в БД принимаются без миграции).
YES_NO_VALUE_YES = "Да"
YES_NO_VALUE_NO = "Нет"
YES_NO_UNKNOWN = "Unknown"


def yes_no_normalized_key(canon: str) -> str:
    """Ключ для сравнения конфликтов: Да→да, Нет→нет; legacy Yes/No тоже."""
    if canon in (YES_NO_VALUE_YES, "Yes"):
        return "да"
    if canon in (YES_NO_VALUE_NO, "No"):
        return "нет"
    return (canon or "").strip().lower()


def coerce_optional_int(value: Any) -> Optional[int]:
    """Coerce LLM output (e.g. 'N/A', 'стр. 3') into optional int for Pydantic."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip().lower()
        if stripped in ("", "n/a", "na", "none", "null", "-", "—", "–", "нет", "не указано"):
            return None
        match = re.search(r"\d+", stripped)
        if match:
            return int(match.group(0))
    return None


def validate_currency(value: str) -> str:
    """Validate and normalize currency value to a plain numeric string."""
    if not value or not isinstance(value, str):
        raise ValueError(f"Invalid currency value: {value}")

    from app.services.ru_contract_value_normalize import money_plain_normalized

    plain = money_plain_normalized(value)
    if plain is None:
        raise ValueError(f"Invalid currency format: {value}")
    return plain


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
    """Validate and normalize yes/no to Russian canon (Да/Нет); accepts legacy Yes/No."""
    if not value or not isinstance(value, str):
        return YES_NO_UNKNOWN

    stripped = value.strip()
    if stripped in (YES_NO_VALUE_YES, "Yes"):
        return YES_NO_VALUE_YES
    if stripped in (YES_NO_VALUE_NO, "No"):
        return YES_NO_VALUE_NO

    value_clean = stripped.lower().rstrip(".,!?;:")

    yes_variants = [
        "yes",
        "да",
        "есть",
        "true",
        "1",
        "да, есть",
        "есть, да",
        "имеется",
        "присутствует",
        "существует",
        "найдено",
        "найден",
        "подтверждаю",
        "подтверждено",
        "согласен",
        "согласна",
        "верно",
        "правильно",
        "корректно",
        "так",
        "именно так",
    ]

    no_variants = [
        "no",
        "нет",
        "нету",
        "false",
        "0",
        "не",
        "отсутствует",
        "не имеется",
        "не присутствует",
        "не существует",
        "не найдено",
        "не найден",
        "не подтверждаю",
        "не подтверждено",
        "не согласен",
        "не согласна",
        "неверно",
        "неправильно",
        "некорректно",
        "не так",
        "не именно так",
        "отрицаю",
        "отрицается",
    ]

    if value_clean in yes_variants:
        return YES_NO_VALUE_YES
    if value_clean in no_variants:
        return YES_NO_VALUE_NO

    for yes_variant in yes_variants:
        if yes_variant in value_clean:
            return YES_NO_VALUE_YES

    for no_variant in no_variants:
        if no_variant in value_clean:
            return YES_NO_VALUE_NO

    return YES_NO_UNKNOWN


class SourceReference(BaseModel):
    """Model for source reference in document"""
    page: Optional[int] = Field(None, description="Номер страницы")
    section: Optional[str] = Field(None, description="Раздел документа")
    text: str = Field(description="Цитата из документа")
    bbox: Optional[Dict[str, float]] = Field(None, description="Bounding box coordinates: {x0, y0, x1, y1}")
    page_bbox: Optional[Dict[str, float]] = Field(None, description="Page dimensions: {width, height}")


class TabularCellExtractionModel(BaseModel):
    """Pydantic model for structured output of tabular cell extraction"""
    
    cell_value: str = Field(description="Извлеченное значение ячейки")
    normalized_value: Optional[str] = Field(None, description="Нормализованное значение (отдельно от cell_value)")
    verbatim_extract: Optional[str] = Field(None, description="Точная цитата из документа (для verbatim типа)")
    source_page: Optional[int] = Field(None, description="Номер страницы в документе, где найдена информация")
    source_section: Optional[str] = Field(None, description="Раздел документа (например, 'Раздел 3.1', 'Статья 5')")
    source_start_line: Optional[int] = Field(None, description="Начальная строка в документе (если доступно)")
    source_end_line: Optional[int] = Field(None, description="Конечная строка в документе (если доступно)")
    source_references: Optional[list] = Field(default_factory=list, description="Список ссылок на источники: [{page, section, text}]")
    confidence: float = Field(0.8, description="Уверенность в извлечении (0.0-1.0)", ge=0.0, le=1.0)
    reasoning: str = Field(description="Подробное объяснение как было извлечено значение и откуда")
    extraction_method: str = Field("llm", description="Метод извлечения: llm, regex, hybrid")
    
    # Store column_type for validation
    column_type: Optional[str] = Field(None, description="Тип колонки для валидации (не сохраняется в БД)")
    
    @field_validator('source_page', 'source_start_line', 'source_end_line', mode='before')
    @classmethod
    def validate_optional_int_fields(cls, v: Any) -> Optional[int]:
        return coerce_optional_int(v)

    @field_validator('cell_value')
    @classmethod
    def validate_cell_value(cls, v: str, info) -> str:
        """Basic validation - just trim whitespace and handle empty values"""
        if not v or v.strip() == "":
            return TABULAR_NA_VALUE
        if is_na_cell_value(v):
            return TABULAR_NA_VALUE
        return v.strip()
    
    @model_validator(mode='after')
    def validate_by_column_type(self):
        """Validate and normalize cell_value based on column_type after model creation."""
        if not self.column_type:
            if not self.normalized_value and self.cell_value and not is_na_cell_value(self.cell_value):
                self.normalized_value = self.cell_value.strip().lower()
            return self

        if is_blank_placeholder(self.cell_value or ""):
            self.cell_value = TABULAR_NA_VALUE
            self.normalized_value = TABULAR_NA_VALUE
            return self

        cell_value, norm_value, _rejection = strict_normalize_cell_value(
            self.cell_value,
            self.column_type,
        )
        self.cell_value = cell_value
        self.normalized_value = norm_value
        return self
    
    @model_validator(mode='after')
    def set_normalized_value(self):
        """Set normalized_value if not already set (fallback)"""
        if not self.normalized_value and self.cell_value and not is_na_cell_value(self.cell_value):
            # If not set by validate_by_column_type, set it here
            if self.column_type not in ['date', 'number', 'currency', 'yes_no']:
                self.normalized_value = self.cell_value.lower()
        return self
    
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

