"""Legacy global lock removed — ingest serialization is per-case via file_ingest_scheduler."""
from __future__ import annotations

import pytest


def test_background_processing_lock_removed():
    from app.services import file_processor_bg as fpb

    assert not hasattr(fpb, "_background_processing_lock")
