"""
Type-specific structured output schemas for tabular cell extraction.

Each column_type gets an LLM schema whose field descriptions encode the answer contract.
Post-LLM values are finalized via tabular_column_type_contract.finalize_extraction_dict.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, create_model

from app.models.tabular_review import TabularColumn
from app.services.tabular_column_type_contract import finalize_extraction_dict, validate_column_type
from app.services.tabular_review_models import TabularCellExtractionModel, coerce_optional_int


class _ExtractionProvenance(BaseModel):
    """Shared provenance fields for all column types."""

    verbatim_extract: Optional[str] = Field(
        None,
        description="Дословная цитата из документа, подтверждающая ответ (5–25 слов)",
    )
    source_page: Optional[int] = Field(None, description="Номер страницы (целое число) или omit")
    source_section: Optional[str] = Field(None, description="Раздел документа, если известен")
    source_references: Optional[list] = Field(
        default_factory=list,
        description="Массив цитат: [{text, page?, section?}]",
    )
    confidence: float = Field(0.8, ge=0.0, le=1.0, description="Уверенность 0.0–1.0")
    reasoning: str = Field(description="Краткое объяснение: откуда взято значение")

    class Config:
        extra = "ignore"


class TextCellExtraction(_ExtractionProvenance):
    cell_value: str = Field(
        description=(
            "Краткий ответ (обычно фраза или предложение) строго по подтверждающей цитате, "
            "или ровно «—». Не пиши длинное эссе."
        ),
    )


class VerbatimCellExtraction(_ExtractionProvenance):
    cell_value: str = Field(
        description="Точная цитата из документа как в тексте, или ровно «—»",
    )
    verbatim_extract: str = Field(
        description="Та же дословная цитата, что и cell_value (обязательно, если не «—»)",
    )


class DateCellExtraction(_ExtractionProvenance):
    cell_value: str = Field(
        description="Дата строго в формате YYYY-MM-DD, или ровно «—» если дата не найдена",
    )


class NumberCellExtraction(_ExtractionProvenance):
    cell_value: str = Field(
        description="Числовое значение (Arabic digits, точка как десятичный разделитель), или «—»",
    )


class CurrencyCellExtraction(_ExtractionProvenance):
    cell_value: str = Field(
        description="Денежная сумма с валютой (например '150 000 руб.' или '1000 USD'), или «—»",
    )


class YesNoCellExtraction(_ExtractionProvenance):
    cell_value: str = Field(
        description='Строго одно из: «Да», «Нет», «—» (если в документе нет основания для ответа)',
    )


_EXTRACTION_SCHEMA_BY_TYPE: Dict[str, Type[BaseModel]] = {
    "text": TextCellExtraction,
    "verbatim": VerbatimCellExtraction,
    "date": DateCellExtraction,
    "number": NumberCellExtraction,
    "currency": CurrencyCellExtraction,
    "yes_no": YesNoCellExtraction,
    "manual_input": TextCellExtraction,
}


def _tag_options(column: TabularColumn) -> List[str]:
    cfg = column.column_config if isinstance(column.column_config, dict) else {}
    options = cfg.get("options") or []
    labels: List[str] = []
    for item in options:
        if isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            if label:
                labels.append(label)
    return labels


def extraction_schema_for_column(column: TabularColumn) -> Type[BaseModel]:
    """
    Return the Pydantic model the LLM must fill for this column's type contract.
    """
    column_type = validate_column_type(str(column.column_type or "text"))

    if column_type == "tag":
        labels = _tag_options(column)
        if labels:
            options_text = ", ".join(labels)
            description = (
                f"Ровно одно значение из списка: {options_text}. "
                "Или ровно «—», если ни один вариант не подходит."
            )
        else:
            description = "Один тег из предопределённого списка, или «—»"

        return create_model(
            "TagCellExtraction",
            __base__=_ExtractionProvenance,
            cell_value=(str, Field(description=description)),
        )

    return _EXTRACTION_SCHEMA_BY_TYPE.get(column_type, TextCellExtraction)


def cell_value_field_description(column: TabularColumn) -> str:
    """Human-readable contract for prompts (mirrors schema descriptions)."""
    schema = extraction_schema_for_column(column)
    field = schema.model_fields.get("cell_value")
    if field and field.description:
        return str(field.description)
    return "Значение ячейки или «—»"


def typed_extraction_to_cell_model(
    raw: Any,
    *,
    column: TabularColumn,
) -> TabularCellExtractionModel:
    """Convert type-specific LLM output to canonical TabularCellExtractionModel."""
    if hasattr(raw, "model_dump"):
        payload: Dict[str, Any] = raw.model_dump()
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        payload = raw.__dict__ if hasattr(raw, "__dict__") else {}

    payload.setdefault("extraction_method", "llm_rag")
    if not payload.get("reasoning"):
        payload["reasoning"] = "Извлечено из документа"

    finalized = finalize_extraction_dict(
        payload,
        column_type=str(column.column_type),
        column_config=column.column_config if isinstance(column.column_config, dict) else None,
    )

    # Preserve int coercion for provenance fields
    for int_field in ("source_page", "source_start_line", "source_end_line"):
        if int_field in finalized:
            finalized[int_field] = coerce_optional_int(finalized[int_field])

    return TabularCellExtractionModel(**finalized)
