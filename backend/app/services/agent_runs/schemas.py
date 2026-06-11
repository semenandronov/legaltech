"""Pydantic contracts for agent runs, tools, and SSE."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class AgentRunStatusEnum(str, Enum):
    pending = "pending"
    running = "running"
    waiting_for_user = "waiting_for_user"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AgentTodoItem(BaseModel):
    content: str
    status: str = "pending"


class CreateAgentRunRequest(BaseModel):
    case_id: str = Field(..., min_length=1)
    user_task: str = Field(..., min_length=1, max_length=32_000)
    file_ids: Optional[List[str]] = Field(default=None, description="Документы дела в scope задачи")
    input_config: Optional[Dict[str, Any]] = None

    @field_validator("user_task")
    @classmethod
    def strip_task(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("user_task must not be empty")
        return text


class AgentRunResponse(BaseModel):
    id: str
    case_id: str
    thread_id: str
    status: AgentRunStatusEnum
    user_task: str
    created_at: Optional[datetime] = None


class AgentRunDetailResponse(AgentRunResponse):
    selected_file_ids: Optional[List[str]] = None
    todos: Optional[List[Dict[str, Any]]] = None
    artifacts: Optional[Dict[str, Any]] = None
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    total_tool_calls: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AgentRunListItem(BaseModel):
    id: str
    case_id: str
    status: AgentRunStatusEnum
    user_task: str
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    total_tool_calls: int = 0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AgentRunListResponse(BaseModel):
    items: List[AgentRunListItem]
    total: int


class CaseWorkflowResponse(BaseModel):
    id: str
    case_id: str
    title: str
    description: Optional[str] = None
    user_task: str
    default_file_ids: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreateCaseWorkflowRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    user_task: str = Field(..., min_length=10, max_length=32_000)
    description: Optional[str] = Field(default=None, max_length=2000)
    default_file_ids: Optional[List[str]] = None

    @field_validator("title", "user_task")
    @classmethod
    def strip_required(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ResumeAgentRunRequest(BaseModel):
    """Payload for LangGraph Command(resume=...) after human approval."""

    approved: bool = True
    payload: Optional[Dict[str, Any]] = None


# --- Tool I/O (strict) ---


class PingToolInput(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="Тестовое сообщение для проверки рантайма")


class PingToolOutput(BaseModel):
    status: Literal["success"] = "success"
    echo: str
    run_id: str


class TabularColumnSpec(BaseModel):
    column_label: str = Field(..., min_length=1, max_length=255)
    column_type: str = Field(
        ...,
        description="text | number | currency | yes_no | date | tag | verbatim | manual_input",
    )
    prompt: str = Field(..., min_length=1, max_length=4000)

    @field_validator("column_type")
    @classmethod
    def normalize_column_type(cls, value: str) -> str:
        from app.services.tabular_column_type_contract import validate_column_type

        return validate_column_type(value)

    @field_validator("column_label", "prompt")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class TabularReviewToolInput(BaseModel):
    review_name: str = Field(..., min_length=1, max_length=255, description="Название таблицы")
    columns: List[TabularColumnSpec] = Field(..., min_length=1, max_length=12)
    description: Optional[str] = Field(default=None, max_length=2000)
    file_ids: Optional[List[str]] = Field(
        default=None,
        description="Документы дела; если не задано — scope из запуска агента",
    )

    @field_validator("review_name")
    @classmethod
    def strip_review_name(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("review_name must not be empty")
        return text


class TabularReviewToolOutput(BaseModel):
    status: Literal["completed", "failed"] = "completed"
    review_id: str
    review_name: str
    saved_count: int = 0
    error_count: int = 0
    total_tasks: int = 0
    rows: List[Dict[str, Any]] = Field(default_factory=list)


class CaseRagToolInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    k: int = Field(default=8, ge=3, le=20)
    file_ids: Optional[List[str]] = Field(
        default=None,
        description="Ограничить поиск файлами дела; иначе scope запуска",
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 2:
            raise ValueError("query too short")
        return text


class RagHit(BaseModel):
    file_name: str
    file_id: Optional[str] = None
    page: Optional[Any] = None
    snippet: str


class CaseRagToolOutput(BaseModel):
    status: Literal["success", "empty"] = "success"
    query: str
    hit_count: int = 0
    hits: List[RagHit] = Field(default_factory=list)


class LegalCorpusToolInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    k: int = Field(default=6, ge=2, le=12)
    instrument_ids: Optional[List[str]] = Field(
        default=None,
        description="Опциональный фильтр по instrument_id корпуса",
    )

    @field_validator("query")
    @classmethod
    def strip_legal_query(cls, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 2:
            raise ValueError("query too short")
        return text


class LegalCorpusHit(BaseModel):
    source_filename: str
    instrument_id: Optional[str] = None
    section_title: Optional[str] = None
    snippet: str


class LegalCorpusToolOutput(BaseModel):
    status: Literal["success", "empty"] = "success"
    query: str
    hit_count: int = 0
    hits: List[LegalCorpusHit] = Field(default_factory=list)


class DraftToolInput(BaseModel):
    user_prompt: str = Field(
        ...,
        min_length=10,
        max_length=16_000,
        description="Что нужно составить: тип документа, стороны, факты, требования",
    )
    template_system_id: Optional[str] = Field(
        default=None,
        description="Опциональный системный шаблон (draft admin templates)",
    )
    file_ids: Optional[List[str]] = Field(
        default=None,
        description="Документы дела в scope; иначе — file_ids запуска агента",
    )

    @field_validator("user_prompt")
    @classmethod
    def strip_user_prompt(cls, value: str) -> str:
        text = (value or "").strip()
        if len(text) < 10:
            raise ValueError("user_prompt too short")
        return text


class DraftToolOutput(BaseModel):
    status: Literal["completed", "failed"] = "completed"
    document_id: str
    title: str
    preview: str = ""
    editor_path: str
    run_id: str


# --- SSE event union ---


class AgentRunEventType(str, Enum):
    stream_open = "stream_open"
    run_started = "run_started"
    status = "status"
    todos_updated = "todos_updated"
    tool_started = "tool_started"
    tool_completed = "tool_completed"
    text_delta = "text_delta"
    interrupt = "interrupt"
    run_completed = "run_completed"
    run_failed = "run_failed"
    run_cancelled = "run_cancelled"
    error = "error"


class AgentRunStreamEvent(BaseModel):
    type: AgentRunEventType
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    def to_sse(self) -> str:
        import json

        payload = self.model_dump(mode="json", exclude_none=True)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
