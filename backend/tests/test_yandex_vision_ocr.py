"""Парсинг ответа Yandex Vision OCR."""
from app.services.yandex_vision_ocr import extract_text_from_vision_response


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
