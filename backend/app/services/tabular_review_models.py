"""Pydantic models for Tabular Review structured output"""
from typing import Optional, Annotated, Dict
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
    # #region agent log
    import json
    import os
    import logging
    logger = logging.getLogger(__name__)
    log_data = {
        "timestamp": int(__import__('time').time() * 1000),
        "location": "tabular_review_models.py:45",
        "message": "validate_yes_no called",
        "data": {
            "input_value": value,
            "input_type": str(type(value)),
            "is_empty": not value,
            "is_string": isinstance(value, str)
        },
        "sessionId": "debug-session",
        "runId": "run1",
        "hypothesisId": "G"
    }
    logger.info(f"[DEBUG] {json.dumps(log_data)}")
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a') as f:
            f.write(json.dumps(log_data) + "\n")
    except Exception:
        pass
    # #endregion
    
    if not value or not isinstance(value, str):
        return "Unknown"
    
    # Убираем все знаки препинания и лишние пробелы для более гибкого распознавания
    value_clean = value.lower().strip()
    # Убираем точки, запятые, восклицательные и вопросительные знаки
    value_clean = value_clean.rstrip('.,!?;:')
    
    # Расширенный список вариантов для "Yes"
    yes_variants = [
        'yes', 'да', 'есть', 'true', '1', 'да, есть', 'есть, да',
        'имеется', 'присутствует', 'существует', 'найдено', 'найден',
        'подтверждаю', 'подтверждено', 'согласен', 'согласна',
        'верно', 'правильно', 'корректно', 'так', 'именно так'
    ]
    
    # Расширенный список вариантов для "No"
    no_variants = [
        'no', 'нет', 'нету', 'false', '0', 'не', 'отсутствует',
        'не имеется', 'не присутствует', 'не существует', 'не найдено', 'не найден',
        'не подтверждаю', 'не подтверждено', 'не согласен', 'не согласна',
        'неверно', 'неправильно', 'некорректно', 'не так', 'не именно так',
        'отрицаю', 'отрицается'
    ]
    
    # Проверяем точное совпадение
    if value_clean in yes_variants:
        return 'Yes'
    elif value_clean in no_variants:
        return 'No'
    
    # Проверяем частичное совпадение (если значение содержит ключевые слова)
    for yes_variant in yes_variants:
        if yes_variant in value_clean:
            return 'Yes'
    
    for no_variant in no_variants:
        if no_variant in value_clean:
            return 'No'
    
    # #region agent log
    import logging
    logger = logging.getLogger(__name__)
    log_data = {
        "timestamp": int(__import__('time').time() * 1000),
        "location": "tabular_review_models.py:95",
        "message": "validate_yes_no returning Unknown",
        "data": {
            "value_clean": value_clean,
            "original_value": value,
            "reason": "not in yes or no lists"
        },
        "sessionId": "debug-session",
        "runId": "run1",
        "hypothesisId": "G"
    }
    logger.info(f"[DEBUG] {json.dumps(log_data)}")
    try:
        with open(log_path, 'a') as f:
            f.write(json.dumps(log_data) + "\n")
    except Exception:
        pass
    # #endregion
    
    return 'Unknown'


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
    
    @field_validator('cell_value')
    @classmethod
    def validate_cell_value(cls, v: str, info) -> str:
        """Basic validation - just trim whitespace and handle empty values"""
        if not v or v.strip() == "":
            return "N/A"
        return v.strip()
    
    @model_validator(mode='after')
    def validate_by_column_type(self):
        """Validate and normalize cell_value based on column_type after model creation"""
        if not self.column_type:
            # Если column_type не установлен, просто нормализуем
            if not self.normalized_value and self.cell_value and self.cell_value != "N/A":
                self.normalized_value = self.cell_value.strip().lower()
            return self
        
        if not self.cell_value or self.cell_value.strip() == "" or self.cell_value == "N/A":
            if not self.cell_value:
                self.cell_value = "N/A"
            if not self.normalized_value:
                self.normalized_value = "N/A"
            return self
        
        original_value = self.cell_value.strip()
        
        # Validate and normalize based on type
        if self.column_type == 'date':
            try:
                normalized = parse_and_normalize_date(original_value)
                datetime.strptime(normalized, "%Y-%m-%d")
                self.cell_value = normalized
                self.normalized_value = normalized
            except Exception as e:
                logger.warning(f"Could not normalize date '{original_value}': {e}")
                self.cell_value = original_value
                self.normalized_value = original_value
        
        elif self.column_type == 'currency':
            try:
                # Валидируем, что число корректно, но сохраняем оригинал с валютой
                normalized_num = validate_currency(original_value)
                # cell_value остается с валютой (оригинальное значение, если оно валидно)
                self.cell_value = original_value
                # normalized_value содержит только число
                self.normalized_value = normalized_num
            except ValueError as e:
                logger.warning(f"Currency validation failed for '{original_value}': {e}")
                self.cell_value = original_value
                self.normalized_value = original_value
        
        elif self.column_type == 'number':
            try:
                normalized = validate_number(original_value)
                self.cell_value = normalized
                self.normalized_value = normalized
            except ValueError as e:
                logger.warning(f"Number validation failed for '{original_value}': {e}")
                self.cell_value = original_value
                self.normalized_value = original_value
        
        elif self.column_type == 'yes_no':
            # #region agent log
            import json
            import os
            log_data = {
                "timestamp": int(__import__('time').time() * 1000),
                "location": "tabular_review_models.py:231",
                "message": "Validating yes_no value",
                "data": {
                    "original_value": original_value,
                    "original_value_type": str(type(original_value)),
                    "original_value_lower": original_value.lower() if original_value else None
                },
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "F"
            }
            logger.info(f"[DEBUG] {json.dumps(log_data)}")
            log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, 'a') as f:
                    f.write(json.dumps(log_data) + "\n")
            except Exception:
                pass
            # #endregion
            
            validated = validate_yes_no(original_value)
            
            # #region agent log
            log_data = {
                "timestamp": int(__import__('time').time() * 1000),
                "location": "tabular_review_models.py:255",
                "message": "After validate_yes_no",
                "data": {
                    "validated_value": validated,
                    "original_value": original_value
                },
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "F"
            }
            logger.info(f"[DEBUG] {json.dumps(log_data)}")
            try:
                with open(log_path, 'a') as f:
                    f.write(json.dumps(log_data) + "\n")
            except Exception:
                pass
            # #endregion
            
            self.cell_value = validated
            self.normalized_value = validated.lower()
        
        else:
            # For text, verbatim, tags - no validation needed, just normalize
            self.cell_value = original_value
            if not self.normalized_value:
                self.normalized_value = original_value.lower()
        
        return self
    
    @model_validator(mode='after')
    def set_normalized_value(self):
        """Set normalized_value if not already set (fallback)"""
        if not self.normalized_value and self.cell_value and self.cell_value != "N/A":
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

