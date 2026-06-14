"""Pydantic schemas for the decomposed Draft pipeline."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RetrievalSubQuery(BaseModel):
    """One focused search task derived from lawyer brief."""

    query_id: str
    role: str = ""
    search_query: str
    purpose: str = ""


class DraftTaskPlan(BaseModel):
    """Layer 1 output: decomposed retrieval + extraction plan."""

    target_document_type: str = ""
    case_category: str = ""
    required_doc_roles: List[str] = Field(default_factory=list)
    sub_queries: List[RetrievalSubQuery] = Field(default_factory=list)
    source: str = "llm"

    def to_state_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class TriagedFile(BaseModel):
    file_id: str
    filename: str = ""
    doc_type: str = "other"
    role: str = ""
    tier: Literal["core_data", "sidebar_context", "excluded"] = "excluded"
    score: float = 0.0


class DocumentTriageResult(BaseModel):
    """Layer 1 triage: filtered file set for extraction."""

    core_files: List[TriagedFile] = Field(default_factory=list)
    sidebar_files: List[TriagedFile] = Field(default_factory=list)
    excluded_count: int = 0

    @property
    def core_file_ids(self) -> List[str]:
        return [f.file_id for f in self.core_files if f.file_id]

    @property
    def sidebar_file_ids(self) -> List[str]:
        return [f.file_id for f in self.sidebar_files if f.file_id]

    @property
    def all_active_file_ids(self) -> List[str]:
        return self.core_file_ids + self.sidebar_file_ids

    def to_state_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class DocumentExtractionRecord(BaseModel):
    """Layer 2: isolated extraction from one file."""

    file_id: str
    filename: str = ""
    role: str = ""
    doc_type: str = "other"
    schema_name: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["high", "partial", "missing"] = "partial"


class FinancialLineItem(BaseModel):
    """One partial payment or adjustment found in case materials."""

    date: str = ""
    amount: str = ""
    source: str = ""
    note: str = ""


class VerifiedCalculations(BaseModel):
    """Python-verified monetary and date calculations — authoritative for document text."""

    payment_deadline: str = ""
    penalty_start_date: str = ""
    penalty_end_date: str = ""
    penalty_days: int = 0
    principal_outstanding: str = ""
    penalty_amount: str = ""
    total_claim: str = ""
    state_duty: str = ""
    penalty_rate_percent_per_day: str = ""
    computation_trace: str = ""
    source: str = "python_rf_calendar_v1"


class PenaltyTerms(BaseModel):
    """Raw contractual terms for deterministic penalty calculation (from LLM extraction)."""

    payment_term_value: int = 0
    payment_term_unit: Literal["business_days", "calendar_days"] = "business_days"
    payment_term_from: Literal["act_signed", "contract_signed", "delivery", "other"] = "act_signed"
    term_count_starts: Literal["next_day", "same_day"] = "next_day"
    act_date: Optional[str] = None
    contract_date: Optional[str] = None
    penalty_rate_percent_per_day: Optional[str] = None
    principal_amount: Optional[str] = None
    penalty_end_date: Optional[str] = None
    partial_payments: List[FinancialLineItem] = Field(default_factory=list)

    @classmethod
    def from_llm_dict(cls, raw: Any) -> "PenaltyTerms":
        if not isinstance(raw, dict):
            return cls()
        unit = str(raw.get("payment_term_unit") or "business_days").lower()
        if unit not in ("business_days", "calendar_days"):
            unit = "business_days"
        term_from = str(raw.get("payment_term_from") or "act_signed").lower()
        if term_from not in ("act_signed", "contract_signed", "delivery", "other"):
            term_from = "act_signed"
        starts = str(raw.get("term_count_starts") or "next_day").lower()
        if starts not in ("next_day", "same_day"):
            starts = "next_day"
        try:
            term_val = int(raw.get("payment_term_value") or 0)
        except (TypeError, ValueError):
            term_val = 0
        payments_raw = raw.get("partial_payments") or []
        payments: List[FinancialLineItem] = []
        if isinstance(payments_raw, list):
            for item in payments_raw:
                if isinstance(item, dict):
                    payments.append(
                        FinancialLineItem(
                            date=str(item.get("date") or ""),
                            amount=str(item.get("amount") or ""),
                            source=str(item.get("source") or ""),
                            note=str(item.get("note") or ""),
                        )
                    )
        return cls(
            payment_term_value=term_val,
            payment_term_unit=unit,  # type: ignore[arg-type]
            payment_term_from=term_from,  # type: ignore[arg-type]
            term_count_starts=starts,  # type: ignore[arg-type]
            act_date=str(raw.get("act_date") or "") or None,
            contract_date=str(raw.get("contract_date") or "") or None,
            penalty_rate_percent_per_day=(
                str(raw.get("penalty_rate_percent_per_day") or raw.get("penalty_rate") or "") or None
            ),
            principal_amount=str(raw.get("principal_amount") or "") or None,
            penalty_end_date=str(raw.get("penalty_end_date") or "") or None,
            partial_payments=payments,
        )


class FinancialSummary(BaseModel):
    """Structured monetary passport — single source of truth for amounts in document."""

    principal_claim: str = ""
    penalty_claim: str = ""
    partial_payments: List[FinancialLineItem] = Field(default_factory=list)
    total_to_claim: str = ""
    computation_method: str = ""
    confidence: Literal["high", "partial", "missing"] = "missing"
    verified: Optional[VerifiedCalculations] = None

    @classmethod
    def from_llm_dict(cls, raw: Any) -> "FinancialSummary":
        if not isinstance(raw, dict):
            return cls()
        payments_raw = raw.get("partial_payments") or []
        payments: List[FinancialLineItem] = []
        if isinstance(payments_raw, list):
            for item in payments_raw:
                if isinstance(item, dict):
                    payments.append(
                        FinancialLineItem(
                            date=str(item.get("date") or ""),
                            amount=str(item.get("amount") or ""),
                            source=str(item.get("source") or ""),
                            note=str(item.get("note") or ""),
                        )
                    )
        conf = str(raw.get("confidence") or "missing").lower()
        if conf not in ("high", "partial", "missing"):
            conf = "missing"
        verified_raw = raw.get("verified")
        verified = None
        if isinstance(verified_raw, dict):
            try:
                verified = VerifiedCalculations.model_validate(verified_raw)
            except Exception:
                verified = None
        return cls(
            principal_claim=str(raw.get("principal_claim") or ""),
            penalty_claim=str(raw.get("penalty_claim") or ""),
            partial_payments=payments,
            total_to_claim=str(raw.get("total_to_claim") or ""),
            computation_method=str(raw.get("computation_method") or ""),
            confidence=conf,  # type: ignore[arg-type]
            verified=verified,
        )


class CaseRetrievalSnapshot(BaseModel):
    """
    Result of a single case assistant retrieval pass for Draft.

    Immutable SSOT for raw case text in the decomposed pipeline — section nodes must not
    re-query case documents; they read ``ExtractedFacts`` plus this shared context.
    """

    rag_context: str = ""
    scoped_file_ids: List[str] = Field(default_factory=list)
    retrieval_task: Dict[str, Any] = Field(default_factory=dict)
    context_pipeline_meta: Dict[str, Any] = Field(default_factory=dict)
    citations: List[Dict[str, Any]] = Field(default_factory=list)

    sub_queries_executed: int = 0
    extraction_records: List[Dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_pipeline_result(cls, raw: Dict[str, Any]) -> "CaseRetrievalSnapshot":
        if not isinstance(raw, dict):
            return cls()
        scoped = raw.get("scoped_file_ids")
        file_ids = [str(x) for x in scoped if str(x).strip()] if isinstance(scoped, list) else []
        task = raw.get("retrieval_task")
        citations_raw = raw.get("citations")
        return cls(
            rag_context=str(raw.get("rag_context") or ""),
            scoped_file_ids=file_ids,
            retrieval_task=dict(task) if isinstance(task, dict) else {},
            context_pipeline_meta=dict(raw.get("context_pipeline_meta") or {}),
            citations=list(citations_raw) if isinstance(citations_raw, list) else [],
            sub_queries_executed=int(raw.get("sub_queries_executed") or 0),
            extraction_records=list(raw.get("extraction_records") or []),
        )

    def to_state_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class ExtractedFacts(BaseModel):
    """Case fact passport — immutable source of truth for all section nodes."""

    document_type: str = ""
    parties: Dict[str, str] = Field(default_factory=dict)
    amounts: Dict[str, str] = Field(default_factory=dict)
    dates: Dict[str, str] = Field(default_factory=dict)
    identifiers: Dict[str, str] = Field(default_factory=dict)
    other: Dict[str, str] = Field(default_factory=dict)
    financial: FinancialSummary = Field(default_factory=FinancialSummary)
    penalty_terms: Optional[PenaltyTerms] = None

    def to_prompt_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "document_type": self.document_type,
            "parties": self.parties,
            "amounts": self.amounts,
            "dates": self.dates,
            "identifiers": self.identifiers,
            "other": self.other,
            "financial": self.financial.model_dump(),
        }
        if self.penalty_terms is not None:
            payload["penalty_terms"] = self.penalty_terms.model_dump()
        return payload

    @classmethod
    def from_llm_dict(cls, raw: Any) -> "ExtractedFacts":
        if not isinstance(raw, dict):
            return cls()
        penalty_terms = None
        if isinstance(raw.get("penalty_terms"), dict):
            penalty_terms = PenaltyTerms.from_llm_dict(raw.get("penalty_terms"))
        return cls(
            document_type=str(raw.get("document_type") or ""),
            parties={str(k): str(v) for k, v in (raw.get("parties") or {}).items() if v},
            amounts={str(k): str(v) for k, v in (raw.get("amounts") or {}).items() if v},
            dates={str(k): str(v) for k, v in (raw.get("dates") or {}).items() if v},
            identifiers={str(k): str(v) for k, v in (raw.get("identifiers") or {}).items() if v},
            other={str(k): str(v) for k, v in (raw.get("other") or {}).items() if v},
            financial=FinancialSummary.from_llm_dict(raw.get("financial")),
            penalty_terms=penalty_terms,
        )


class BlueprintSection(BaseModel):
    """One generatable unit in the master plan."""

    section_id: str
    title: str
    sample_html: str = ""
    rag_query: str = ""
    rag_sources: List[Literal["case", "legal"]] = Field(default_factory=lambda: ["case"])
    section_index: int = 0

    @field_validator("rag_sources", mode="before")
    @classmethod
    def _coerce_rag_sources(cls, v: Any) -> List[str]:
        if not v:
            return ["case"]
        if isinstance(v, list):
            out = [str(x) for x in v if str(x) in ("case", "legal")]
            return out or ["case"]
        return ["case"]


class DraftPipelineMetadata(BaseModel):
    """Persisted on Document.document_metadata for refactor flows."""

    pipeline_version: str = "unified_v1"
    generation_mode: Literal["unified", "decomposed"] = "unified"
    strategy: Literal["template", "scratch"] = "scratch"
    template_id: Optional[str] = None
    template_key: Optional[str] = None
    template_html: Optional[str] = None
    document_title: str = ""
    task_plan: Dict[str, Any] = Field(default_factory=dict)
    triage: Dict[str, Any] = Field(default_factory=dict)
    extracted_facts: Dict[str, Any] = Field(default_factory=dict)
    case_retrieval: Dict[str, Any] = Field(default_factory=dict)
    extraction_records: List[Dict[str, Any]] = Field(default_factory=list)
    blueprint: List[Dict[str, Any]] = Field(default_factory=list)
    generated_sections: Dict[str, str] = Field(default_factory=dict)

    def to_document_metadata(self) -> Dict[str, Any]:
        return {"draft_pipeline": self.model_dump()}

    @classmethod
    def from_document_metadata(cls, meta: Any) -> Optional["DraftPipelineMetadata"]:
        if not isinstance(meta, dict):
            return None
        raw = meta.get("draft_pipeline")
        if not isinstance(raw, dict):
            return None
        try:
            return cls.model_validate(raw)
        except Exception:
            return None
