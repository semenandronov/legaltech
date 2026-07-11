from decimal import Decimal

from sqlalchemy import select

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService


def test_apply_query_filters_uses_absolute_amount_comparison():
    query = select(CaseFileTransaction)
    filtered = CaseFileTransactionService._apply_query_filters(
        query,
        case_id="case-1",
        file_id="stmt-1",
        abs_amount_compare="gt",
        abs_amount_min=Decimal("10000"),
    )

    compiled = str(filtered.compile(compile_kwargs={"literal_binds": True}))

    assert "abs(case_file_transactions.amount_rub)" in compiled.lower()
    assert "> 10000" in compiled
