"""processing_progress is a merge-patched bag — stage updates must not wipe outline."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.file_document_outline import (
    OUTLINE_PAYLOAD_KEY,
    load_outline_payload_from_file,
    persist_outline_on_file,
)
from app.services.ingest_progress import apply_processing_progress, reset_processing_progress


def test_apply_processing_progress_preserves_outline_through_ready():
    file_model = SimpleNamespace(processing_progress={"stage": "store", "percent": 90})
    outline_payload = {
        "outline": [{"section_root_id": "s1", "section_title": "Definitions"}],
        "definition_section_roots": ["s1"],
        "index_fingerprint": "v2:1:abc",
    }
    persist_outline_on_file(file_model, outline_payload)

    apply_processing_progress(
        file_model,
        {"stage": "ready", "percent": 100, "message": "Готово"},
    )

    assert file_model.processing_progress["stage"] == "ready"
    assert file_model.processing_progress["percent"] == 100
    loaded = load_outline_payload_from_file(file_model)
    assert loaded == outline_payload
    assert OUTLINE_PAYLOAD_KEY in file_model.processing_progress


def test_progress_sink_style_patch_keeps_outline():
    file_model = SimpleNamespace(processing_progress=None)
    persist_outline_on_file(
        file_model,
        {"outline": [{"section_root_id": "a"}], "definition_section_roots": [], "index_fingerprint": "x"},
    )
    apply_processing_progress(
        file_model,
        {"stage": "store", "percent": 90, "message": "Запись в векторный индекс"},
    )
    assert load_outline_payload_from_file(file_model)["outline"][0]["section_root_id"] == "a"
    assert file_model.processing_progress["stage"] == "store"


def test_reset_processing_progress_clears_prior_artifacts():
    file_model = SimpleNamespace(
        processing_progress={
            "stage": "ready",
            OUTLINE_PAYLOAD_KEY: {"outline": [{"section_root_id": "old"}]},
        }
    )
    reset_processing_progress(
        file_model,
        {"stage": "load", "percent": 5, "message": "Чтение файла"},
    )
    assert load_outline_payload_from_file(file_model) is None
    assert file_model.processing_progress == {
        "stage": "load",
        "percent": 5,
        "message": "Чтение файла",
    }
