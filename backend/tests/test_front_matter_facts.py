"""Unit tests for front-matter facts channel (no live LLM)."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.documents import Document

from app.services.front_matter_facts import (
    FrontMatterExtractLLMItem,
    FrontMatterFact,
    FrontMatterMatchLLMOutput,
    FrontMatterPayload,
    FrontMatterRouteLLMOutput,
    facts_to_documents,
    format_front_matter_context,
    ground_extracted_facts,
    locate_quote_span,
    payload_from_storage,
    payload_to_storage,
    resolve_front_matter_evidence,
    select_front_matter_zone,
)


PREAMBLE = (
    "г. Москва\n\n"
    "Общество с ограниченной ответственностью «Управляющая компания «КЕМБРИДЖ Сервис» "
    "именуемое в дальнейшем «Заказчик», с одной стороны, и ООО «Технион» "
    "именуемое в дальнейшем «Подрядчик», с другой стороны,\n\n"
    "1. ПРЕДМЕТ ДОГОВОРА\n"
    "1.1. По настоящему Договору Подрядчик обязуется по заданию Заказчика выполнить работы.\n"
)


def test_select_front_matter_zone_stops_before_section():
    zone, end = select_front_matter_zone(PREAMBLE, max_chars=5000)
    assert "КЕМБРИДЖ" in zone
    assert "именуемое в дальнейшем «Заказчик»" in zone
    assert "обязуется по заданию" not in zone
    assert end <= PREAMBLE.find("1.1.") or "1.1." not in zone


def test_locate_quote_span_exact_and_ws():
    text = "AAA\n\nименуемое   в дальнейшем «Заказчик»\n\nBBB"
    q = "именуемое в дальнейшем «Заказчик»"
    span = locate_quote_span(text, q)
    assert span is not None
    cs, ce = span
    assert "Заказчик" in text[cs:ce]


def test_ground_extracted_facts_drops_ungrounded():
    items = [
        FrontMatterExtractLLMItem(
            kind="party_role",
            label="Заказчик",
            value="ООО КЕМБРИДЖ",
            quote="именуемое в дальнейшем «Заказчик»",
            confidence=0.9,
        ),
        FrontMatterExtractLLMItem(
            kind="party_role",
            label="Фейк",
            value="Нет такого",
            quote="этой цитаты нет в тексте совсем",
            confidence=0.9,
        ),
    ]
    facts = ground_extracted_facts(PREAMBLE, items)
    assert len(facts) == 1
    assert facts[0].label == "Заказчик"
    assert facts[0].char_start >= 0
    assert facts[0].char_end > facts[0].char_start


def test_facts_to_documents_are_geometry_leaves():
    facts = [
        FrontMatterFact(
            kind="party_role",
            label="Заказчик",
            value="КЕМБРИДЖ",
            quote="именуемое в дальнейшем «Заказчик»",
            char_start=10,
            char_end=40,
            confidence=0.9,
        )
    ]
    docs = facts_to_documents(facts, file_id="f1", filename="d.pdf", indices=[0])
    assert len(docs) == 1
    md = docs[0].metadata
    assert md["chunk_level"] == "micro"
    assert md["char_start"] == 10
    assert md["retrieval_channel"] == "front_matter"
    assert md["front_matter_value"] == "КЕМБРИДЖ"
    assert "КЕМБРИДЖ" in format_front_matter_context(docs)


def test_extraction_dict_from_front_matter_uses_matched_value_only():
    from app.services.front_matter_facts import extraction_dict_from_front_matter_docs

    facts = [
        FrontMatterFact(
            kind="party_role",
            label="Заказчик",
            value="ООО КЕМБРИДЖ Сервис",
            quote="именуемое в дальнейшем «Заказчик»",
            char_start=10,
            char_end=40,
            confidence=0.95,
        ),
        FrontMatterFact(
            kind="party_role",
            label="Подрядчик",
            value="ООО Технион",
            quote="именуемое в дальнейшем «Подрядчик»",
            char_start=50,
            char_end=80,
            confidence=0.95,
        ),
    ]
    # Only index 0 matched (customer question)
    docs = facts_to_documents(facts, file_id="f1", filename="d.pdf", indices=[0])
    payload = extraction_dict_from_front_matter_docs(docs)
    assert payload is not None
    assert payload["cell_value"] == "ООО КЕМБРИДЖ Сервис"
    assert "Технион" not in payload["cell_value"]
    assert payload["extraction_method"] == "front_matter"
    assert payload["source_references"][0]["char_start"] == 10


def test_extraction_dict_rejects_non_front_matter_docs():
    from app.services.front_matter_facts import extraction_dict_from_front_matter_docs
    from langchain_core.documents import Document

    docs = [Document(page_content="1.1 текст", metadata={"chunk_level": "micro", "char_start": 1})]
    assert extraction_dict_from_front_matter_docs(docs) is None


def test_payload_roundtrip():
    payload = FrontMatterPayload(
        content_hash="abc",
        zone_end=100,
        facts=[
            FrontMatterFact(
                kind="party_role",
                label="Истец",
                value="ООО Ромашка",
                quote="ООО Ромашка",
                char_start=0,
                char_end=11,
                confidence=0.8,
            )
        ],
    )
    raw = payload_to_storage(payload)
    back = payload_from_storage(raw)
    assert back is not None
    assert len(back.facts) == 1
    assert back.facts[0].label == "Истец"


def test_resolve_uses_front_matter_when_routed(monkeypatch):
    facts = [
        FrontMatterFact(
            kind="party_role",
            label="Заказчик",
            value="ООО КЕМБРИДЖ Сервис",
            quote="именуемое в дальнейшем «Заказчик»",
            char_start=PREAMBLE.find("именуемое"),
            char_end=PREAMBLE.find("именуемое") + len("именуемое в дальнейшем «Заказчик»"),
            confidence=0.95,
        )
    ]
    payload = FrontMatterPayload(content_hash="", zone_end=200, facts=facts)

    monkeypatch.setattr(
        "app.services.front_matter_facts.front_matter_facts_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.front_matter_facts.ensure_front_matter_payload",
        lambda *a, **k: payload,
    )
    monkeypatch.setattr(
        "app.services.front_matter_facts.route_front_matter_question",
        lambda *a, **k: FrontMatterRouteLLMOutput(
            use_front_matter=True,
            confidence=0.9,
            reason="identity",
            information_need="кто заказчик",
        ),
    )
    monkeypatch.setattr(
        "app.services.front_matter_facts.match_front_matter_facts",
        lambda *a, **k: FrontMatterMatchLLMOutput(
            fact_indices=[0],
            confidence=0.95,
            reason="label match",
        ),
    )

    db = SimpleNamespace()
    result = resolve_front_matter_evidence(
        db,  # type: ignore[arg-type]
        file_id="file-1",
        question="кто заказчик по договору",
        column_label="Заказчик",
        filename="dogovor.pdf",
        original_text=PREAMBLE,
        allow_llm=True,
    )
    assert result.used is True
    assert "КЕМБРИДЖ" in result.context_text or "Заказчик" in result.context_text
    assert len(result.documents) == 1
    assert isinstance(result.documents[0], Document)


def test_resolve_falls_back_when_not_identity(monkeypatch):
    facts = [
        FrontMatterFact(
            kind="party_role",
            label="Заказчик",
            value="X",
            quote="именуемое в дальнейшем «Заказчик»",
            char_start=10,
            char_end=40,
            confidence=0.9,
        )
    ]
    payload = FrontMatterPayload(facts=facts)
    monkeypatch.setattr(
        "app.services.front_matter_facts.front_matter_facts_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.front_matter_facts.ensure_front_matter_payload",
        lambda *a, **k: payload,
    )
    monkeypatch.setattr(
        "app.services.front_matter_facts.route_front_matter_question",
        lambda *a, **k: FrontMatterRouteLLMOutput(
            use_front_matter=False,
            confidence=0.9,
            reason="content",
        ),
    )
    result = resolve_front_matter_evidence(
        SimpleNamespace(),  # type: ignore[arg-type]
        file_id="f",
        question="какие обязанности у заказчика в пункте 4.1",
        original_text=PREAMBLE,
    )
    assert result.used is False
    assert result.meta.get("skipped") == "not_front_matter_intent"
