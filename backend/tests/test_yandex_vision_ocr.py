"""Парсинг ответа Yandex Vision OCR."""
from app.services.yandex_vision_ocr import extract_text_from_vision_response
from app.services.yandex_vision_ocr import normalize_image_for_yandex
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
