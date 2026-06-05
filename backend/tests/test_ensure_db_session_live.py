"""Tests for stale-session recovery before DB writes after long LLM calls."""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from app.utils.database import ensure_db_session_live


def test_ensure_db_session_live_noop_when_select_ok():
    db = MagicMock()
    ensure_db_session_live(db)
    db.execute.assert_called_once()
    db.connection().invalidate.assert_not_called()
    db.rollback.assert_not_called()


def test_ensure_db_session_live_invalidates_on_stale_connection():
    db = MagicMock()
    db.execute.side_effect = OperationalError("stmt", {}, Exception("SSL closed"))
    ensure_db_session_live(db)
    db.connection().invalidate.assert_called_once()
    db.rollback.assert_called_once()
