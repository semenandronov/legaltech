"""Shared YandexEmbeddings: doc/query models and HTTP engine integration."""
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
