"""
Общие фикстуры для pytest (SQLite in-memory).

Интеграционные тесты импортируют `db_session`, `test_user`, `test_case` из этого модуля.
Тесты, требующие реальный PostgreSQL (например health check), могут падать без БД — их помечают отдельно или пропускают локально.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.case import Base, Case
from app.models.case_file_transaction import CaseFileTransaction  # noqa: F401
from app.models.user import User


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def test_user(db_session):
    user = User(
        email="pytest-user@example.com",
        password="test-password-hash",
        name="Pytest User",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_case(db_session, test_user):
    case = Case(
        user_id=test_user.id,
        title="Pytest case",
        description="",
        full_text="",
        file_names=[],
        num_documents=0,
    )
    db_session.add(case)
    db_session.commit()
    db_session.refresh(case)
    return case
