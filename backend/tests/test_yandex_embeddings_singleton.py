"""Shared YandexEmbeddings: doc/query models and single-string OpenAI-compat calls."""
from unittest.mock import MagicMock, patch

import app.services.yandex_embeddings as emb_mod
from app.services.yandex_embeddings import YandexEmbeddings, get_yandex_embeddings


def test_get_yandex_embeddings_singleton():
    emb_mod._yandex_embeddings_singleton = None
    with patch.object(YandexEmbeddings, "__init__", return_value=None) as init:
        a = get_yandex_embeddings()
        b = get_yandex_embeddings()
    assert a is b
    init.assert_called_once()


def test_openai_compat_one_string_per_request():
    inst = YandexEmbeddings.__new__(YandexEmbeddings)
    inst.sdk = MagicMock()
    inst.folder_id = "fld"
    inst.api_key = "k"
    inst.iam_token = None
    inst._dns_ok = True

    texts = [f"chunk {i}" for i in range(5)]

    with patch("app.services.yandex_openai_llm.yandex_openai_sdk_client") as client_fn:
        client = MagicMock()
        client_fn.return_value = client

        def _create(*, model, input, encoding_format):
            assert isinstance(input, str)
            resp = MagicMock()
            resp.data = [MagicMock(embedding=[0.1] * 256)]
            return resp

        client.embeddings.create.side_effect = _create

        with patch.object(emb_mod.config, "YANDEX_EMBEDDINGS_TRANSPORT", "openai"):
            with patch.object(emb_mod.config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 5):
                with patch.object(emb_mod.config, "YANDEX_EMBEDDING_MIN_REQUEST_INTERVAL_SEC", 0):
                    with patch(
                        "app.services.yandex_embeddings.split_text_for_embedding_api",
                        side_effect=lambda t: [t],
                    ):
                        with patch.object(
                            emb_mod,
                            "_resolve_embedding_model_uri",
                            return_value="emb://fld/text-search-doc/latest",
                        ) as resolve:
                            out = inst.embed_documents(texts)

    assert len(out) == 5
    assert client.embeddings.create.call_count == 5
    resolve.assert_called()
    assert resolve.call_args.kwargs.get("for_query") is False


def test_embed_query_uses_query_model():
    inst = YandexEmbeddings.__new__(YandexEmbeddings)
    inst.sdk = MagicMock()
    inst.folder_id = "fld"
    inst._dns_ok = True

    with patch.object(inst, "_embed_texts", return_value=[[0.2] * 256]) as embed:
        vec = inst.embed_query("вопрос юриста")
    assert len(vec) == 256
    embed.assert_called_once()
    assert embed.call_args.kwargs.get("for_query") is True
