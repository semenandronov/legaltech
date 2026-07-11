"""Deterministic document-number → file_id scope."""
from app.services.chat.document_ref_scope import (
    extract_document_refs,
    match_catalog_by_document_refs,
    normalize_doc_ref,
)
from app.services.chat.retrieval_router import CaseFileCatalogEntry, _try_document_ref_scope
from app.services.chat.scoped_file_expand import score_chunk_for_question


def test_extract_document_refs_contract_numbers():
    refs = extract_document_refs(
        "Какая стоимость по договору №51 от 02.02.2024 и кадастр в №98/2024?"
    )
    assert normalize_doc_ref("51") in refs
    assert "98/2024" in refs


def test_match_catalog_by_document_refs_exact():
    catalog = [
        CaseFileCatalogEntry(
            file_id="f54",
            filename="04. договор от 16.04.2024 на 5л.pdf",
            summary="Договор поставки №54 между Технион и Кочкин",
        ),
        CaseFileCatalogEntry(
            file_id="f51",
            filename="05. договор от 02.02.2024 на 5л.pdf",
            summary="Договор поставки №51 от 02.02.2024",
        ),
        CaseFileCatalogEntry(
            file_id="f98",
            filename="06. договор купли-продажи от 15.04.2024.pdf",
            summary="Договор №98/2024, участок кадастр",
            key_points=["кадастровый номер"],
        ),
    ]
    assert match_catalog_by_document_refs(catalog, "срок по договору №54") == ["f54"]
    assert match_catalog_by_document_refs(
        catalog, "стоимость оборудования по договору №51"
    ) == ["f51"]
    assert match_catalog_by_document_refs(
        catalog, "кадастровый номер в договоре №98/2024"
    ) == ["f98"]


def test_try_document_ref_scope_sets_expand_flag():
    catalog = [
        CaseFileCatalogEntry(
            file_id="f51",
            filename="05. договор.pdf",
            summary="Договор №51",
        )
    ]
    task = _try_document_ref_scope(catalog, "Какая стоимость по договору №51?")
    assert task is not None
    assert task.file_ids == ["f51"]
    assert task.scope_mode == "resolved"
    assert task.within_file_expand is True
    assert task.rationale == "document_ref_catalog_match"


def test_lexical_score_prefers_price_clause():
    q = "Какая стоимость оборудования по договору №51 от 02.02.2024?"
    price = score_chunk_for_question(
        q,
        "2.1. Стоимость оборудования составляет-3 400 000 рублей.",
        suppress_doc_refs=["51"],
    )
    header = score_chunk_for_question(
        q,
        "ДОГОВОР ПОСТАВКИ №51 от 02 февраля 2024 г. Москва",
        suppress_doc_refs=["51"],
    )
    unrelated = score_chunk_for_question(
        q,
        "Стороны обязуются соблюдать конфиденциальность условий договора.",
        suppress_doc_refs=["51"],
    )
    assert price > header
    assert price > unrelated
    assert price > 0


def test_bm25_in_file_ranks_signature_and_amount():
    from langchain_core.documents import Document

    from app.services.chat.scoped_file_expand import _rank_chunks_in_file

    chunks = [
        Document(page_content="ПРЕТЕНЗИЯ ООО «Смарт Сити» к ИП Красноштанова"),
        Document(
            page_content=(
                "Общая сумма задолженности составляет 6 392 533 рубля 00 копеек."
            )
        ),
        Document(page_content="Срок погашения — 10 рабочих дней с даты получения."),
        Document(page_content="Контактный телефон и реквизиты сторон указаны ниже."),
    ]
    # Signature only in original_text tail (simulates micro-chunk truncation).
    original = (
        "ПРЕТЕНЗИЯ ООО «Смарт Сити». "
        + ("текст " * 200)
        + "Приложения: карточка с реквизитами. "
        "Генеральный директор Стеблин А.Е. ООО «Смарт Сити»"
    )
    sig = _rank_chunks_in_file(
        question="Кто подписал претензию от имени ООО «Смарт Сити»?",
        chunks=chunks,
        file_id="f1",
        suppress_doc_refs=[],
        per_file_cap=6,
        original_text=original,
    )
    assert sig
    assert any("Стеблин" in (d.page_content or "") for _, d in sig)

    amt = _rank_chunks_in_file(
        question="Какая общая сумма задолженности указана в претензии?",
        chunks=chunks,
        file_id="f1",
        suppress_doc_refs=[],
        per_file_cap=3,
    )
    assert amt
    assert "6 392 533" in (amt[0][1].page_content or "")


def test_resolve_includes_related_objections_file():
    from app.services.chat.document_ref_scope import resolve_document_ref_file_ids

    catalog = [
        CaseFileCatalogEntry(
            file_id="f54",
            filename="04. договор.pdf",
            summary="Договор поставки №54",
        ),
        CaseFileCatalogEntry(
            file_id="fobj",
            filename="00. возражения ШАК и ШЭР.pdf",
            summary="Возражения должников по делу",
        ),
    ]
    ids = resolve_document_ref_file_ids(
        catalog,
        "Как договор №54 связан с возражениями должников?",
    )
    assert "f54" in ids
    assert "fobj" in ids
