"""Pydantic models for LangChain agents"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, root_validator, Field
import logging

logger = logging.getLogger(__name__)


class TableColumnSpec(BaseModel):
    """Specification for a table column"""
    label: str = Field(..., description="Column label/name")
    question: str = Field(..., description="Question for extracting data")
    type: str = Field(default="text", description="Column type: date|number|text|boolean")


class TableDecision(BaseModel):
    """Decision about whether a task requires a table"""
    needs_table: bool = Field(..., description="Whether a table is needed")
    table_name: Optional[str] = Field(None, description="Table name if needs_table=True")
    columns: Optional[List[TableColumnSpec]] = Field(None, description="Table columns if needs_table=True")
    doc_types: Optional[List[str]] = Field(None, description="Document types to filter by (e.g., ['contract']) or ['all']")
    needs_clarification: bool = Field(default=False, description="Whether clarification is needed")
    clarification_questions: Optional[List[str]] = Field(None, description="Questions to ask user if needs_clarification=True")
    reasoning: Optional[str] = Field(None, description="Explanation of the decision")

    @root_validator
    def require_clarification_questions(cls, values):
        """Validate that clarification_questions are provided when needs_clarification=True"""
        needs = values.get("needs_clarification")
        q = values.get("clarification_questions")
        if needs and (not q or len(q) == 0):
            raise ValueError("clarification_questions is required when needs_clarification=True")
        return values

    @root_validator
    def require_table_fields(cls, values):
        """Validate that table fields are provided when needs_table=True"""
        needs = values.get("needs_table")
        if needs:
            if not values.get("table_name"):
                raise ValueError("table_name is required when needs_table=True")
            if not values.get("columns") or len(values.get("columns", [])) == 0:
                raise ValueError("columns is required when needs_table=True")
        return values

