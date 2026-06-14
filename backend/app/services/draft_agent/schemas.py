"""Pydantic schemas for draft agent tools."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class DraftCaseSearchInput(BaseModel):
    query: str = Field(..., min_length=2, description="Поисковый запрос по материалам дела")
    k: int = Field(default=8, ge=3, le=20)
    file_ids: Optional[List[str]] = Field(default=None, description="Ограничить поиск файлами")


class DraftLegalSearchInput(BaseModel):
    query: str = Field(..., min_length=2, description="Запрос к правовому справочнику")
    k: int = Field(default=6, ge=2, le=12)


class DraftCourtPracticeSearchInput(BaseModel):
    query: str = Field(
        ...,
        min_length=4,
        description="Суть спора или тип документа для поиска судебной практики",
    )
    k: int = Field(default=6, ge=2, le=12)


class DraftPartialPayment(BaseModel):
    amount: str = Field(..., description="Сумма оплаты")
    date: Optional[str] = Field(default=None, description="Дата оплаты YYYY-MM-DD")
    note: Optional[str] = Field(default=None, description="Источник/назначение")


class DraftCalculatorInput(BaseModel):
    principal_amount: str = Field(..., description="Основной долг (руб.)")
    event_date: str = Field(..., description="Дата акта/договора (YYYY-MM-DD или DD.MM.YYYY)")
    payment_term_business_days: int = Field(..., ge=1, le=365, description="Срок оплаты в рабочих днях")
    penalty_rate_percent_per_day: float = Field(..., gt=0, le=10, description="Ставка неустойки % за день")
    penalty_end_date: Optional[str] = Field(default=None, description="Конец периода неустойки")
    partial_payments: Optional[List[DraftPartialPayment]] = Field(default=None)
    reason: str = Field(default="", description="Зачем нужен расчёт")


class DraftWriteDocumentInput(BaseModel):
    document_instruction: str = Field(
        ...,
        min_length=40,
        description="Полная спецификация документа: тип, стороны, факты, нормы, расчёты, пробелы",
    )
    document_title: Optional[str] = Field(default=None, max_length=255)
