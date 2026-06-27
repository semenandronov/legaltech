"""Unit tests for async Yandex embedding HTTP engine."""
from unittest.mock import MagicMock, patch

import app.services.yandex_embedding_http as http_mod
from app.services.yandex_embedding_http import (
    YandexEmbeddingHttpEngine,
    parse_openai_embeddings_json,
    reset_embedding_http_engine_for_tests,
)


def test_parse_openai_embeddings_json_accepts_standard_shape():
    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.5] + [0.0] * 255, "index": 0}],
        "model": "emb://fld/text-search-doc/latest",
    }
    vec = parse_openai_embeddings_json(payload)
    assert len(vec) == 256
    assert vec[0] == 0.5


def test_embed_texts_delegates_to_engine_queue():
    reset_embedding_http_engine_for_tests()
    engine = YandexEmbeddingHttpEngine()

    with patch.object(engine, "embed_texts", return_value=[[0.1] * 256, [0.2] * 256]) as embed:
        with patch.object(http_mod, "_engine_singleton", engine):
            from app.services.yandex_embedding_http import get_embedding_http_engine

            out = get_embedding_http_engine().embed_texts(
                model="emb://fld/text-search-doc/latest",
                texts=["a", "b"],
            )
    assert len(out) == 2
    embed.assert_called_once()


def test_yandex_embeddings_uses_http_engine():
    from app.services.yandex_embeddings import YandexEmbeddings
    import app.services.yandex_embeddings as emb_mod

    inst = YandexEmbeddings.__new__(YandexEmbeddings)
    inst.sdk = MagicMock()
    inst.folder_id = "fld"
    inst._dns_ok = True

    texts = [f"chunk {i}" for i in range(5)]
    mock_engine = MagicMock()
    mock_engine.embed_texts.return_value = [[0.1] * 256 for _ in texts]

    with patch.object(emb_mod, "get_embedding_http_engine", return_value=mock_engine):
        with patch.object(emb_mod.config, "YANDEX_EMBEDDINGS_TRANSPORT", "openai"):
            with patch(
                "app.services.yandex_embeddings.split_text_for_embedding_api",
                side_effect=lambda t: [t],
            ):
                with patch.object(
                    emb_mod,
                    "_resolve_embedding_model_uri",
                    return_value="emb://fld/text-search-doc/latest",
                ):
                    out = inst.embed_documents(texts)

    assert len(out) == 5
    mock_engine.embed_texts.assert_called_once()
    assert mock_engine.embed_texts.call_args.kwargs.get("priority") is False


def test_priority_embed_processed_when_first_job():
    """embed_query uses priority=True; must not deadlock on empty regular queue."""
    reset_embedding_http_engine_for_tests()
    engine = YandexEmbeddingHttpEngine()
    model = "emb://fld/text-search-query/latest"
    vector = [0.3] + [0.0] * 255

    async def _fake_fetch(_client, _url, *, model, text, attempt=0):
        return vector

    with patch.object(engine, "_fetch_embedding", side_effect=_fake_fetch):
        engine._ensure_started()
        fut = engine._submit(model=model, text="query first", priority=True)
        result = fut.result(timeout=5.0)

    assert len(result) == 256
    assert result[0] == 0.3
