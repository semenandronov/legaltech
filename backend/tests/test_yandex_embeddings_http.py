"""HTTP JSON parsing for Yandex OpenAI-compat embeddings."""
from app.services.yandex_embeddings import _parse_openai_embeddings_json


def test_parse_openai_embeddings_json_accepts_standard_shape():
    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.5] + [0.0] * 255, "index": 0}],
        "model": "emb://fld/text-search-query/latest",
    }
    vec = _parse_openai_embeddings_json(payload)
    assert len(vec) == 256
    assert vec[0] == 0.5
