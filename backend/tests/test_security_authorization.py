import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routes.auth import router as auth_router
from app.services.cell_history_service import CellHistoryService
from app.config import config, validate_production_security
from app.utils.auth import (
    create_access_token,
    create_websocket_ticket,
    decode_websocket_ticket,
)
from app.utils.authorization import (
    require_case_access,
    require_case_manage,
    require_case_write,
    require_review_write,
)
from app.utils.auth import get_current_user
from app.utils.database import get_db
from app.models.case_sharing import CASE_ROLE_EDITOR, CASE_ROLE_OWNER, CASE_ROLE_VIEWER


def test_websocket_ticket_is_short_lived_and_resource_scoped():
    ticket = create_websocket_ticket(
        user_id="user-1",
        resource_type="tabular_review",
        resource_id="review-1",
        expires_seconds=60,
    )

    payload = decode_websocket_ticket(
        ticket,
        resource_type="tabular_review",
        resource_id="review-1",
    )

    assert payload is not None
    assert payload["sub"] == "user-1"
    assert decode_websocket_ticket(
        ticket,
        resource_type="tabular_review",
        resource_id="review-2",
    ) is None
    assert decode_websocket_ticket(
        ticket,
        resource_type="case",
        resource_id="review-1",
    ) is None


def test_access_token_cannot_be_used_as_websocket_ticket():
    access_token = create_access_token({"sub": "user-1"})

    assert decode_websocket_ticket(
        access_token,
        resource_type="tabular_review",
        resource_id="review-1",
    ) is None


def _mock_db_for_case(*, case=None, membership=None):
    """Build a db mock for case ACL helpers (Case then CaseMember queries)."""
    db = Mock()

    def query(model):
        q = Mock()
        name = getattr(model, "__name__", str(model))
        if name == "Case" or getattr(model, "__tablename__", None) == "cases":
            q.filter.return_value.first.return_value = case
        elif name == "CaseMember" or getattr(model, "__tablename__", None) == "case_members":
            q.filter.return_value.first.return_value = membership
        elif name == "TabularReview" or getattr(model, "__tablename__", None) == "tabular_reviews":
            q.filter.return_value.first.return_value = None
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    return db


def test_require_case_access_hides_foreign_case():
    db = _mock_db_for_case(case=None, membership=None)
    with pytest.raises(HTTPException) as exc_info:
        require_case_access(db, "case-1", "user-1")
    assert exc_info.value.status_code == 404


def test_require_case_access_allows_member():
    case = SimpleNamespace(id="case-1", user_id="owner-1")
    membership = SimpleNamespace(role=CASE_ROLE_VIEWER, case_id="case-1", user_id="user-1")
    db = _mock_db_for_case(case=case, membership=membership)
    assert require_case_access(db, "case-1", "user-1") is case


def test_require_case_write_forbids_viewer():
    case = SimpleNamespace(id="case-1", user_id="owner-1")
    membership = SimpleNamespace(role=CASE_ROLE_VIEWER, case_id="case-1", user_id="user-1")
    db = _mock_db_for_case(case=case, membership=membership)
    with pytest.raises(HTTPException) as exc_info:
        require_case_write(db, "case-1", "user-1")
    assert exc_info.value.status_code == 403


def test_require_case_manage_requires_owner():
    case = SimpleNamespace(id="case-1", user_id="owner-1")
    membership = SimpleNamespace(role=CASE_ROLE_EDITOR, case_id="case-1", user_id="user-1")
    db = _mock_db_for_case(case=case, membership=membership)
    with pytest.raises(HTTPException) as exc_info:
        require_case_manage(db, "case-1", "user-1")
    assert exc_info.value.status_code == 403


def test_legacy_owner_without_membership_row():
    case = SimpleNamespace(id="case-1", user_id="user-1")
    db = _mock_db_for_case(case=case, membership=None)
    assert require_case_manage(db, "case-1", "user-1") is case


def test_require_review_access_via_case():
    review = SimpleNamespace(id="review-1", case_id="case-1", user_id="owner-1")
    case = SimpleNamespace(id="case-1", user_id="owner-1")
    membership = SimpleNamespace(role=CASE_ROLE_EDITOR, case_id="case-1", user_id="user-1")

    db = Mock()

    def query(model):
        q = Mock()
        name = getattr(model, "__name__", str(model))
        tablename = getattr(model, "__tablename__", None)
        if name == "TabularReview" or tablename == "tabular_reviews":
            q.filter.return_value.first.return_value = review
        elif name == "Case" or tablename == "cases":
            q.filter.return_value.first.return_value = case
        elif name == "CaseMember" or tablename == "case_members":
            q.filter.return_value.first.return_value = membership
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    assert require_review_write(db, "review-1", "user-1") is review


def test_require_review_write_forbids_viewer():
    review = SimpleNamespace(id="review-1", case_id="case-1", user_id="owner-1")
    case = SimpleNamespace(id="case-1", user_id="owner-1")
    membership = SimpleNamespace(role=CASE_ROLE_VIEWER, case_id="case-1", user_id="user-1")

    db = Mock()

    def query(model):
        q = Mock()
        name = getattr(model, "__name__", str(model))
        tablename = getattr(model, "__tablename__", None)
        if name == "TabularReview" or tablename == "tabular_reviews":
            q.filter.return_value.first.return_value = review
        elif name == "Case" or tablename == "cases":
            q.filter.return_value.first.return_value = case
        elif name == "CaseMember" or tablename == "case_members":
            q.filter.return_value.first.return_value = membership
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    with pytest.raises(HTTPException) as exc_info:
        require_review_write(db, "review-1", "user-1")
    assert exc_info.value.status_code == 403


def test_every_tabular_review_route_with_review_id_has_boundary_guard():
    route_path = Path(__file__).parents[1] / "app" / "routes" / "tabular_review.py"
    source = route_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    missing = []
    allowed_guards = (
        "require_owned_review(db, review_id, current_user.id)",
        "require_review_access(db, review_id, current_user.id)",
        "require_review_write(db, review_id, current_user.id)",
    )

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [ast.unparse(decorator) for decorator in node.decorator_list]
        if not any("router." in decorator for decorator in decorators):
            continue
        argument_names = {argument.arg for argument in node.args.args}
        if "review_id" not in argument_names:
            continue
        function_source = ast.get_source_segment(source, node) or ""
        if not any(guard in function_source for guard in allowed_guards):
            missing.append(node.name)

    assert missing == []


def test_websocket_ticket_endpoint_checks_ownership():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/auth")
    review = SimpleNamespace(id="review-1", case_id="case-1", user_id="user-1")
    case = SimpleNamespace(id="case-1", user_id="user-1")
    membership = SimpleNamespace(role=CASE_ROLE_OWNER, case_id="case-1", user_id="user-1")

    db = Mock()

    def query(model):
        q = Mock()
        name = getattr(model, "__name__", str(model))
        tablename = getattr(model, "__tablename__", None)
        if name == "TabularReview" or tablename == "tabular_reviews":
            q.filter.return_value.first.return_value = review
        elif name == "Case" or tablename == "cases":
            q.filter.return_value.first.return_value = case
        elif name == "CaseMember" or tablename == "case_members":
            q.filter.return_value.first.return_value = membership
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")

    response = TestClient(app).post(
        "/api/auth/ws-ticket",
        json={"resource_type": "tabular_review", "resource_id": "review-1"},
    )

    assert response.status_code == 200
    assert decode_websocket_ticket(
        response.json()["ticket"],
        resource_type="tabular_review",
        resource_id="review-1",
    ) is not None


def test_websocket_ticket_endpoint_hides_foreign_review():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/auth")
    db = Mock()

    def query(model):
        q = Mock()
        q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-1")

    response = TestClient(app).post(
        "/api/auth/ws-ticket",
        json={"resource_type": "tabular_review", "resource_id": "foreign-review"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Resource not found"


def test_history_diff_queries_both_versions_with_full_cell_scope():
    record = SimpleNamespace(
        cell_value="value",
        verbatim_extract="quote",
        reasoning="reason",
        confidence_score=None,
        source_page=1,
        source_section="section",
        status="completed",
    )
    db = Mock()
    filtered_query = db.query.return_value.filter.return_value
    filtered_query.first.side_effect = [record, record]

    CellHistoryService(db).get_diff(
        history_id_1="history-1",
        history_id_2="history-2",
        review_id="review-1",
        file_id="file-1",
        column_id="column-1",
    )

    assert len(db.query.return_value.filter.call_args_list) == 2
    for call in db.query.return_value.filter.call_args_list:
        assert len(call.args) == 4
        predicates = " ".join(str(predicate) for predicate in call.args)
        assert "tabular_review_id" in predicates
        assert "file_id" in predicates
        assert "column_id" in predicates


def test_comment_mutations_require_path_review_scope():
    service = __import__(
        "app.services.cell_comment_service",
        fromlist=["CellCommentService"],
    ).CellCommentService
    db = Mock()
    db.query.return_value.filter.return_value.first.side_effect = [
        SimpleNamespace(id="review-1", user_id="user-1"),
        None,
    ]

    with pytest.raises(ValueError, match="Comment comment-1 not found"):
        service(db)._require_comment(
            review_id="review-1",
            comment_id="comment-1",
        )


def test_template_apply_filter_requires_owner_or_shared_access():
    source = Path(__file__).parents[1].joinpath("app", "routes", "tabular_review.py").read_text(
        encoding="utf-8"
    )
    assert "TabularColumnTemplate.user_id == current_user.id" in source
    assert "TabularColumnTemplate.id == template_id," in source
    assert "TabularColumnTemplate.id == template_id,\n                and_(" not in source


def test_production_security_accepts_hardened_configuration(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setattr(config, "GIGACHAT_VERIFY_SSL", True)
    monkeypatch.setattr(config, "TABULAR_ONLY_MODE", True)
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://legal.example"])

    validate_production_security()


@pytest.mark.parametrize(
    ("attribute", "unsafe_value"),
    [
        ("JWT_SECRET_KEY", "short"),
        ("CORS_ORIGINS", ["*"]),
        ("CORS_ORIGINS", ["http://legal.example"]),
    ],
)
def test_production_security_rejects_unsafe_configuration(monkeypatch, attribute, unsafe_value):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setattr(config, "GIGACHAT_VERIFY_SSL", True)
    monkeypatch.setattr(config, "TABULAR_ONLY_MODE", True)
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://legal.example"])
    monkeypatch.setattr(config, attribute, unsafe_value)

    with pytest.raises(RuntimeError):
        validate_production_security()


def test_production_security_warns_when_hardening_flags_are_off(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(config, "JWT_SECRET_KEY", "a" * 48)
    monkeypatch.setattr(config, "GIGACHAT_VERIFY_SSL", False)
    monkeypatch.setattr(config, "TABULAR_ONLY_MODE", False)
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://legal.example"])

    validate_production_security()
    assert "GIGACHAT_VERIFY_SSL is false" in caplog.text
    assert "TABULAR_ONLY_MODE is false" in caplog.text
