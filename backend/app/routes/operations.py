"""Operations registry API — bank statement transactions per case."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.models.case import Case
from app.models.user import User
from app.schemas.operations import (
    OperationsAvailableFile,
    OperationsAvailableFilesResponse,
    OperationsAnalysisInsightsResponse,
    OperationsChatHistoryResponse,
    OperationsChatMessage,
    OperationsChatRequest,
    OperationsCounterpartyGroup,
    OperationsCounterpartyGroupsResponse,
    OperationsExportRequest,
    OperationsPeriodInsight,
    OperationsSessionResponse,
    OperationsSessionSaveRequest,
    OperationsSessionSummary,
    OperationsSessionsListResponse,
    OperationsSessionUiState,
    OperationsTransactionsResponse,
    build_summary,
    collect_column_headers,
    serialize_transaction,
)
from app.services.operations_bankruptcy_periods import all_bankruptcy_period_windows
from app.services.operations_noise_filter import sql_operational_noise_match_expression
from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    feature_enabled,
    parse_user_date,
)
from app.services.chat.events import SSESerializer
from app.services.operations_chat_service import OperationsChatService
from app.services.operations_export_service import (
    export_transactions_csv,
    export_transactions_excel,
)
from app.services.operations_registry_service import resolve_statement_file_id
from app.services.operations_session_service import (
    get_session,
    list_sessions_for_case,
    save_ui_state,
    touch_session,
)
from app.utils.auth import get_current_user
from app.utils.content_disposition import content_disposition_attachment
from app.utils.database import SessionLocal, get_db
from app.utils.authorization import require_case_access, require_case_write

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_feature() -> None:
    if not feature_enabled():
        raise HTTPException(status_code=503, detail="Реестр операций отключён")


def _get_user_case(db: Session, case_id: str, user_id: str) -> Case:
    return require_case_access(db, case_id, user_id)


def _get_user_case_write(db: Session, case_id: str, user_id: str) -> Case:
    return require_case_write(db, case_id, user_id)


def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
    if value is None or not str(value).strip():
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", "."))
    except InvalidOperation:
        raise HTTPException(status_code=400, detail=f"Некорректная сумма: {value}")


@router.get("/{case_id}/operations/available-files", response_model=OperationsAvailableFilesResponse)
async def list_available_files(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    summaries = CaseFileTransactionService.list_available_files(db, case_id)
    return OperationsAvailableFilesResponse(
        files=[
            OperationsAvailableFile(
                file_id=item.file_id,
                filename=item.filename,
                transaction_count=item.transaction_count,
                date_min=item.date_min.isoformat() if item.date_min else None,
                date_max=item.date_max.isoformat() if item.date_max else None,
            )
            for item in summaries
        ]
    )


@router.get("/{case_id}/operations/transactions", response_model=OperationsTransactionsResponse)
async def list_transactions(
    case_id: str,
    file_id: str = Query(..., min_length=1, description="ID оцифрованной выписки"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    min_amount: Optional[str] = Query(None),
    max_amount: Optional[str] = Query(None),
    flow: Optional[str] = Query(None, pattern="^(debit|credit)$"),
    exclude_operational_noise: bool = Query(False),
    description_exact: Optional[str] = Query(None),
    limit: int = Query(5000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)

    page = CaseFileTransactionService.query_page(
        db,
        case_id=case_id,
        file_id=resolved_file_id,
        date_from=parse_user_date(date_from) if date_from else None,
        date_to=parse_user_date(date_to) if date_to else None,
        search=search,
        min_amount=_parse_decimal(min_amount),
        max_amount=_parse_decimal(max_amount),
        flow=flow,
        exclude_operational_noise=exclude_operational_noise,
        description_exact=description_exact,
        limit=limit,
        offset=offset,
    )

    column_headers = collect_column_headers(page.rows, single_file=True)
    serialized = [
        serialize_transaction(row, column_headers=column_headers) for row in page.rows
    ]
    return OperationsTransactionsResponse(
        transactions=serialized,
        summary=build_summary(page.rows, total=page.total, file_id=resolved_file_id),
        column_headers=column_headers,
    )


def _count_operational_noise_rows(
    db: Session,
    *,
    case_id: str,
    file_id: str,
    date_from=None,
    date_to=None,
    search: Optional[str] = None,
) -> int:
    base = db.query(func.count(CaseFileTransaction.id))
    filtered = CaseFileTransactionService._apply_query_filters(
        base,
        case_id=case_id,
        file_id=file_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    filtered = filtered.filter(sql_operational_noise_match_expression())
    return int(filtered.scalar() or 0)


@router.get("/{case_id}/operations/analysis-insights", response_model=OperationsAnalysisInsightsResponse)
async def get_operations_analysis_insights(
    case_id: str,
    file_id: str = Query(..., min_length=1),
    petition_date: Optional[str] = Query(None),
    exclude_operational_noise: bool = Query(False),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)

    totals = CaseFileTransactionService.aggregate_totals(
        db,
        case_id=case_id,
        file_id=resolved_file_id,
        search=search,
    )
    noise_count = _count_operational_noise_rows(
        db,
        case_id=case_id,
        file_id=resolved_file_id,
        search=search,
    )
    filtered_totals = CaseFileTransactionService.aggregate_totals(
        db,
        case_id=case_id,
        file_id=resolved_file_id,
        search=search,
        exclude_operational_noise=exclude_operational_noise,
    )

    parsed_petition = parse_user_date(petition_date) if petition_date else None
    periods: list[OperationsPeriodInsight] = []
    if parsed_petition is not None:
        for window in all_bankruptcy_period_windows(parsed_petition):
            period_totals = CaseFileTransactionService.aggregate_totals(
                db,
                case_id=case_id,
                file_id=resolved_file_id,
                date_from=window.date_from,
                date_to=window.date_to,
                search=search,
                exclude_operational_noise=exclude_operational_noise,
            )
            periods.append(
                OperationsPeriodInsight(
                    period_id=window.period_id,
                    label=window.label,
                    date_from=window.date_from.isoformat(),
                    date_to=window.date_to.isoformat(),
                    count=period_totals.count,
                )
            )

    return OperationsAnalysisInsightsResponse(
        petition_date=parsed_petition.isoformat() if parsed_petition else None,
        total_operations=totals.count,
        operational_noise_count=noise_count,
        filtered_count=filtered_totals.count,
        periods=periods,
    )


@router.get("/{case_id}/operations/counterparty-groups", response_model=OperationsCounterpartyGroupsResponse)
async def list_counterparty_groups(
    case_id: str,
    file_id: str = Query(..., min_length=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    exclude_operational_noise: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)

    groups = CaseFileTransactionService.aggregate_by_description(
        db,
        case_id=case_id,
        file_id=resolved_file_id,
        date_from=parse_user_date(date_from) if date_from else None,
        date_to=parse_user_date(date_to) if date_to else None,
        search=search,
        exclude_operational_noise=exclude_operational_noise,
        limit=limit,
    )
    desc_expr = func.coalesce(CaseFileTransaction.description, "")
    total_groups_query = db.query(func.count(func.distinct(desc_expr)))
    total_groups_filtered = CaseFileTransactionService._apply_query_filters(
        total_groups_query,
        case_id=case_id,
        file_id=resolved_file_id,
        date_from=parse_user_date(date_from) if date_from else None,
        date_to=parse_user_date(date_to) if date_to else None,
        search=search,
        exclude_operational_noise=exclude_operational_noise,
    )
    total_groups = int(total_groups_filtered.scalar() or 0)

    serialized = [
        OperationsCounterpartyGroup(
            description=group.description,
            op_count=group.op_count,
            amount_sum_rub=float(group.amount_sum),
            abs_amount_sum_rub=float(group.abs_amount_sum),
        )
        for group in groups
    ]
    return OperationsCounterpartyGroupsResponse(
        groups=serialized,
        returned=len(serialized),
        total_groups=total_groups,
    )


@router.get("/{case_id}/operations/export")
async def export_transactions_get(
    case_id: str,
    file_id: str = Query(..., min_length=1, description="ID оцифрованной выписки"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    min_amount: Optional[str] = Query(None),
    max_amount: Optional[str] = Query(None),
    flow: Optional[str] = Query(None, pattern="^(debit|credit)$"),
    format: str = Query("excel", pattern="^(excel|csv)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full-statement export (server-side filters only). Prefer POST for UI filters."""
    _require_feature()
    case = _get_user_case(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)

    page = CaseFileTransactionService.query_page(
        db,
        case_id=case_id,
        file_id=resolved_file_id,
        date_from=parse_user_date(date_from) if date_from else None,
        date_to=parse_user_date(date_to) if date_to else None,
        search=search,
        min_amount=_parse_decimal(min_amount),
        max_amount=_parse_decimal(max_amount),
        flow=flow,
        limit=10_000,
        offset=0,
    )
    return _operations_export_response(
        case_title=case.title or "operations",
        rows=page.rows,
        format=format,
    )


@router.post("/{case_id}/operations/export")
async def export_transactions_post(
    case_id: str,
    body: OperationsExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """WYSIWYG export: when transaction_ids is set, export exactly the filtered UI rows."""
    _require_feature()
    case = _get_user_case_write(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=body.file_id)

    ids = [str(x).strip() for x in (body.transaction_ids or []) if str(x).strip()]
    if ids:
        rows = CaseFileTransactionService.fetch_ordered_by_ids(
            db,
            case_id=case_id,
            file_id=resolved_file_id,
            transaction_ids=ids,
        )
        if not rows:
            raise HTTPException(
                status_code=400,
                detail="Нет операций для экспорта по текущим фильтрам",
            )
    else:
        page = CaseFileTransactionService.query_page(
            db,
            case_id=case_id,
            file_id=resolved_file_id,
            limit=10_000,
            offset=0,
        )
        rows = page.rows

    return _operations_export_response(
        case_title=case.title or "operations",
        rows=rows,
        format=body.format,
    )


def _operations_export_response(*, case_title: str, rows, format: str) -> Response:
    safe_title = case_title.replace("/", "-")[:80]

    if format == "csv":
        content = export_transactions_csv(rows, single_file=True)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": content_disposition_attachment(
                    f"{safe_title}_operations.csv"
                )
            },
        )

    try:
        content = export_transactions_excel(rows, single_file=True)
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Экспорт Excel недоступен: не установлен openpyxl",
        )
    if content[:2] != b"PK":
        raise HTTPException(
            status_code=500,
            detail="Экспорт Excel вернул некорректный файл",
        )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition_attachment(
                f"{safe_title}_operations.xlsx"
            )
        },
    )


def _serialize_session(row) -> OperationsSessionResponse:
    raw = row.ui_state if isinstance(row.ui_state, dict) else {}
    view_mode_raw = raw.get("view_mode") or raw.get("viewMode") or "operations"
    if view_mode_raw not in ("operations", "counterparties"):
        view_mode_raw = "operations"
    ui = OperationsSessionUiState(
        value_filters=list(raw.get("value_filters") or raw.get("valueFilters") or []),
        row_search=str(raw.get("row_search") or raw.get("rowSearch") or ""),
        petition_date=raw.get("petition_date") or raw.get("petitionDate"),
        active_period=raw.get("active_period") or raw.get("activePeriod"),
        hide_operational_noise=bool(
            raw.get("hide_operational_noise") or raw.get("hideOperationalNoise") or False
        ),
        view_mode=view_mode_raw,
        basket_ids=list(raw.get("basket_ids") or raw.get("basketIds") or []),
    )
    return OperationsSessionResponse(
        file_id=str(row.file_id),
        filename=row.filename,
        ui_state=ui,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/{case_id}/operations/sessions", response_model=OperationsSessionsListResponse)
async def list_operations_sessions(
    case_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    rows = list_sessions_for_case(
        db,
        user_id=str(current_user.id),
        case_id=case_id,
        limit=limit,
    )
    file_meta = {
        item.file_id: item
        for item in CaseFileTransactionService.list_available_files(db, case_id)
    }
    sessions: list[OperationsSessionSummary] = []
    for row in rows:
        meta = file_meta.get(str(row.file_id))
        sessions.append(
            OperationsSessionSummary(
                file_id=str(row.file_id),
                filename=row.filename or (meta.filename if meta else None),
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
                transaction_count=meta.transaction_count if meta else None,
                date_min=meta.date_min.isoformat() if meta and meta.date_min else None,
                date_max=meta.date_max.isoformat() if meta and meta.date_max else None,
            )
        )
    return OperationsSessionsListResponse(sessions=sessions)


@router.get("/{case_id}/operations/session", response_model=OperationsSessionResponse)
async def get_operations_session(
    case_id: str,
    file_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)
    row = get_session(
        db,
        user_id=str(current_user.id),
        case_id=case_id,
        file_id=resolved_file_id,
    )
    if row is None:
        return OperationsSessionResponse(file_id=resolved_file_id)
    return _serialize_session(row)


@router.put("/{case_id}/operations/session", response_model=OperationsSessionResponse)
async def save_operations_session(
    case_id: str,
    body: OperationsSessionSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case_write(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=body.file_id)
    ui_payload = {
        "value_filters": body.ui_state.value_filters,
        "row_search": body.ui_state.row_search,
        "petition_date": body.ui_state.petition_date,
        "active_period": body.ui_state.active_period,
        "hide_operational_noise": body.ui_state.hide_operational_noise,
        "view_mode": body.ui_state.view_mode,
        "basket_ids": body.ui_state.basket_ids,
    }
    row = save_ui_state(
        db,
        user_id=str(current_user.id),
        case_id=case_id,
        file_id=resolved_file_id,
        ui_state=ui_payload,
        filename=body.filename,
    )
    return _serialize_session(row)


@router.post("/{case_id}/operations/session/touch", response_model=OperationsSessionResponse)
async def touch_operations_session(
    case_id: str,
    file_id: str = Query(..., min_length=1),
    filename: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case_write(db, case_id, str(current_user.id))
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)
    row = touch_session(
        db,
        user_id=str(current_user.id),
        case_id=case_id,
        file_id=resolved_file_id,
        filename=filename,
    )
    return _serialize_session(row)


@router.get("/{case_id}/operations/chat/history", response_model=OperationsChatHistoryResponse)
async def get_operations_chat_history(
    case_id: str,
    file_id: str = Query(..., min_length=1, description="ID оцифрованной выписки"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case(db, case_id, str(current_user.id))
    service = OperationsChatService(db)
    resolved_file_id = resolve_statement_file_id(db, case_id=case_id, file_id=file_id)
    messages = service.get_chat_history(case_id, str(current_user.id), resolved_file_id)
    return OperationsChatHistoryResponse(
        messages=[OperationsChatMessage(**msg) for msg in messages]
    )


@router.post("/{case_id}/operations/chat/stream")
async def operations_chat_stream(
    case_id: str,
    request: OperationsChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_feature()
    _get_user_case_write(db, case_id, str(current_user.id))
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    user_id = str(current_user.id)
    file_id = resolve_statement_file_id(db, case_id=case_id, file_id=request.file_id)

    async def event_generator():
        stream_db = SessionLocal()
        try:
            yield ": stream-open\n\n"
            service = OperationsChatService(stream_db)
            async for event in service.stream_analyze(
                case_id,
                user_id,
                question,
                file_id,
                request.ui_state,
            ):
                event_type = event.get("type")
                if event_type == "text_delta":
                    text = event.get("text") or ""
                    if text:
                        yield SSESerializer.text_delta(text)
                elif event_type == "assistant_activity":
                    raw_status = str(event.get("status") or "running")
                    if raw_status in ("active", "done"):
                        raw_status = "running" if raw_status == "active" else "completed"
                    yield SSESerializer.assistant_activity(
                        step_id=str(event.get("step_id") or "react"),
                        phase=str(event.get("phase") or "statement"),
                        step=int(event.get("step") or 1),
                        total_steps=int(event.get("totalSteps") or 6),
                        label=str(event.get("label") or ""),
                        content=str(event.get("content") or event.get("label") or ""),
                        detail=event.get("detail"),
                        status=raw_status,
                    )
                elif event_type == "done":
                    yield SSESerializer.tabular_chat_done(
                        answer=str(event.get("answer") or ""),
                        citations=list(event.get("citations") or []),
                        table_stats=dict(event.get("table_stats") or {}),
                    )
                elif event_type == "error":
                    yield SSESerializer.error(str(event.get("message") or "Operations chat failed"))
        except Exception as exc:
            logger.error("Operations chat stream error: %s", exc, exc_info=True)
            yield SSESerializer.error("Не удалось обработать запрос")
        finally:
            stream_db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
