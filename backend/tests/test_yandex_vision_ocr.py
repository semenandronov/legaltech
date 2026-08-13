"""Парсинг ответа Yandex Vision OCR."""
import pytest
from unittest.mock import Mock

from app.services.yandex_vision_ocr import (
    YandexOcrOperationFailedError,
    _async_max_pages_per_request,
    _raise_if_get_recognition_fatal,
    _yandex_api_error_fields,
    extract_text_from_vision_response,
    normalize_image_for_yandex,
)
from app.services.langchain_loaders import DocumentLoaderService
from langchain_core.documents import Document


def test_extract_text_from_vision_response_sample():
    sample = {
        "results": [
            {
                "results": [
                    {
                        "textDetection": {
                            "pages": [
                                {
                                    "blocks": [
                                        {
                                            "lines": [
                                                {
                                                    "words": [
                                                        {"text": "Hello"},
                                                        {"text": "world"},
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    assert extract_text_from_vision_response(sample) == "Hello world"


def test_normalize_image_for_yandex_passthrough_jpeg_extension():
    # Для JPEG/PNG функция не должна требовать Pillow и не должна менять bytes.
    payload = b"fake-jpeg-bytes"
    out = normalize_image_for_yandex(payload, "scan.jpg")
    assert out == payload


def test_yandex_api_error_fields_extracts_code_message_details():
    payload = {
        "error": {
            "code": 3,
            "message": "invalid argument",
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "X"}],
        }
    }
    fields = _yandex_api_error_fields(payload)
    assert fields["code"] == 3
    assert fields["message"] == "invalid argument"
    assert len(fields["details"]) == 1


def test_raise_if_get_recognition_fatal_non_ok():
    r = Mock()
    r.status_code = 400
    r.text = ""
    r.json.return_value = {
        "error": {
            "code": 13,
            "message": "Try get operation which execution finished with non-OK status code",
            "details": [{"reason": "INTERNAL"}],
        }
    }
    with pytest.raises(YandexOcrOperationFailedError, match="non-OK"):
        _raise_if_get_recognition_fatal(r, "op-dead", model="markdown")


def test_async_max_pages_per_request_defaults_to_200(monkeypatch):
    from app import config as cfg

    monkeypatch.delenv("YANDEX_OCR_ASYNC_MAX_PAGES_PER_REQUEST", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_OCR_ASYNC_MAX_PAGES_PER_REQUEST", 200, raising=False)
    assert _async_max_pages_per_request() == 200


def test_new_ocr_headers_omit_folder_id_for_api_key(monkeypatch):
    from app import config as cfg
    from app.services.yandex_privacy import HEADER_NAME
    from app.services.yandex_vision_ocr import _new_ocr_headers

    monkeypatch.setattr(cfg.config, "YANDEX_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_FOLDER_ID", "b1folder", raising=False)
    monkeypatch.setattr(cfg.config, "YANDEX_DATA_LOGGING_ENABLED", False, raising=False)

    headers = _new_ocr_headers()
    assert headers["Authorization"].startswith("Api-Key ")
    assert "x-folder-id" not in headers
    assert headers[HEADER_NAME] == "false"


def test_pdf_text_quality_ok_uses_chars_per_page_threshold():
    docs = [
        Document(page_content="коротко", metadata={}),
        Document(page_content="еще немного текста", metadata={}),
    ]
    assert DocumentLoaderService._pdf_text_quality_ok(docs) is False

    docs_ok = [
        Document(page_content=("x" * 60), metadata={}),
        Document(page_content=("y" * 60), metadata={}),
    ]
    assert DocumentLoaderService._pdf_text_quality_ok(docs_ok) is True
