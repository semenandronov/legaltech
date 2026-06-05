"""Pydantic-схемы каталога полей шаблона Draft."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TemplateFieldSpec(BaseModel):
    field_id: str
    marker: str
    occurrence_index: int = 0
    start_offset: int = 0
    end_offset: int = 0
    context_snippet: str = ""
    semantic_label: str = ""
    what_to_find: str = ""
    retrieval_query: str = ""
    data_type: str = "other"
    entity_role: Optional[str] = None

    def to_placeholder_plan_item(self, data_status: str = "missing") -> Dict[str, Any]:
        return {
            "placeholder": self.marker,
            "field_id": self.field_id,
            "plan_to_fill": self.what_to_find or self.semantic_label,
            "data_status": data_status,
            "semantic_label": self.semantic_label,
            "retrieval_query": self.retrieval_query,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "TemplateFieldSpec":
        return cls.model_validate(raw)


class TemplateFieldCatalogSnapshot(BaseModel):
    template_key: str
    content_sha256: str = ""
    field_specs: List[TemplateFieldSpec] = Field(default_factory=list)
    indexed_html: str = ""
    indexer_version: str = "1"

    @classmethod
    def from_db_row(cls, row: Any) -> "TemplateFieldCatalogSnapshot":
        specs_raw = row.field_specs or []
        specs = [
            TemplateFieldSpec.from_dict(x) if isinstance(x, dict) else x
            for x in specs_raw
        ]
        return cls(
            template_key=str(row.template_key),
            content_sha256=str(row.content_sha256 or ""),
            field_specs=specs,
            indexed_html=str(row.indexed_html or ""),
            indexer_version=str(row.indexer_version or "1"),
        )
