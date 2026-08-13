"""Tests for DD rules-first document classifier + auto-catalog helpers."""

from types import SimpleNamespace

from app.services.contract_field_catalog import field_applies_to_dd_doc_type
from app.services.dd_document_classifier import (
    apply_user_dd_doc_type,
    classify_dd_document,
    dd_classification_needs_review,
    filename_looks_generic,
    reclassify_file_from_text,
    save_dd_classification_on_file,
)
from app.services.dd_auto_catalog import build_catalog_filename


def test_classify_lease_from_text():
    text = (
        "ДОГОВОР АРЕНДЫ № 03/03-2022/1\n"
        "Арендодатель передаёт Арендатору имущество. Арендная плата составляет..."
    )
    r = classify_dd_document(text=text, filename="dogovor_arendy.pdf")
    assert r.doc_type == "lease_commercial"
    assert r.confidence >= 0.55


def test_classify_lease_not_appendix_when_appendix_only_in_body():
    """Mid-document «приложение №» must not win over a lease title in the head."""
    text = (
        "ДОГОВОР АРЕНДЫ ДВИЖИМОГО ИМУЩЕСТВА С ПРАВОМ ВЫКУПА № 20/01-2022/1\n"
        "Арендодатель ООО СМАРТ СИТИ. Арендатор ИП.\n"
        + ("условия " * 80)
        + "\nПриложение № 1 к настоящему Договору. Спецификация.\n"
    )
    r = classify_dd_document(text=text, filename="06. dogovor arendy 20-01-22 9l.pdf")
    assert r.doc_type == "lease_commercial"


def test_classify_generic_contract_not_appendix_from_body_refs():
    """Diverse commercial contract → contract_other, not appendix."""
    text = (
        "Производство и строительство\n"
        "ДОГОВОР № 98/2024\n"
        "«16» апреля 2024 г.\n"
        "г. Москва\n"
        "Заказчик ... Подрядчик ...\n"
        + ("условия выполнения " * 40)
        + "\nв сроки, установленные в приложении №3 к настоящему договору.\n"
    )
    r = classify_dd_document(text=text, filename="03. договор от 16.04.2024 на 14л.pdf")
    assert r.doc_type in {"contract_other", "works"}
    assert r.doc_type != "appendix_spec"


def test_classify_addendum_still_wins():
    text = (
        "ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1\n"
        "к Договору аренды движимого имущества № 03/03-2022/1\n"
        "Арендная плата составляет 959 335 руб."
    )
    r = classify_dd_document(text=text, filename="ds1_arenda.pdf")
    assert r.doc_type == "addendum"


def test_classify_payment_order():
    text = "Платежное поручение № 123\nПлательщик ... Получатель ..."
    r = classify_dd_document(text=text, filename="pp_2024.pdf")
    assert r.doc_type == "payment_order"


def test_classify_unknown_on_empty():
    r = classify_dd_document(text="короткий текст", filename="x.dat")
    assert r.doc_type == "unknown"


def test_lease_fields_not_applicable_on_litigation():
    assert field_applies_to_dd_doc_type("landlord", "litigation") is False
    assert field_applies_to_dd_doc_type("rent_amount", "litigation") is False
    assert field_applies_to_dd_doc_type("doc_date", "litigation") is True
    assert field_applies_to_dd_doc_type("landlord", "lease_commercial") is True


def test_needs_review_for_unknown_and_user_override():
    assert dd_classification_needs_review("unknown", 0.9, "rules") is True
    assert dd_classification_needs_review("lease_commercial", 0.9, "rules") is False
    assert dd_classification_needs_review("lease_commercial", 0.4, "rules") is True
    assert dd_classification_needs_review("lease_commercial", 1.0, "user") is False

    file_model = SimpleNamespace(
        dd_doc_type=None,
        dd_doc_type_confidence=None,
        dd_doc_type_source=None,
        processing_progress=None,
        original_text="ДОГОВОР АРЕНДЫ\nАрендодатель передаёт имущество",
        filename="lease.pdf",
    )
    auto = classify_dd_document(text=file_model.original_text, filename=file_model.filename)
    save_dd_classification_on_file(file_model, auto)
    assert file_model.dd_doc_type == "lease_commercial"

    apply_user_dd_doc_type(file_model, "addendum")
    assert file_model.dd_doc_type == "addendum"
    assert file_model.dd_doc_type_source == "user"

    kept = reclassify_file_from_text(file_model)
    assert kept.doc_type == "addendum"
    assert kept.source == "user"


def test_taxonomy_serialize_has_all_types():
    from app.services.dd_document_taxonomy import DD_DOC_TYPES, serialize_dd_taxonomy

    payload = serialize_dd_taxonomy()
    ids = {t["id"] for t in payload["types"]}
    assert set(DD_DOC_TYPES) == ids
    assert payload["version"]
    assert "contract_other" in ids
    assert "data_room" in payload
    room_ids = {f["id"] for f in payload["data_room"]["folders"]}
    assert "lease" in room_ids
    assert "inbox" in room_ids
    assert any(f["label"] == "Аренда" for f in payload["data_room"]["folders"])


def test_data_room_bucket_mapping():
    from app.services.dd_data_room import resolve_data_room_bucket

    assert resolve_data_room_bucket("lease_commercial") == "lease"
    assert resolve_data_room_bucket("supply") == "supply"
    assert resolve_data_room_bucket("services") == "services_works"
    assert resolve_data_room_bucket("works") == "services_works"
    assert resolve_data_room_bucket("payment_order") == "finance"
    assert resolve_data_room_bucket("bank_statement") == "finance"
    assert resolve_data_room_bucket("litigation") == "disputes"
    assert resolve_data_room_bucket("correspondence") == "disputes"
    assert resolve_data_room_bucket("contract_other") == "contracts_other"
    assert resolve_data_room_bucket("unknown") == "inbox"
    assert resolve_data_room_bucket("other") == "inbox"

    # Addendum / appendix follow subject hints from filename + head.
    assert (
        resolve_data_room_bucket(
            "addendum",
            filename="ds1_arenda.pdf",
            text="ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ к Договору аренды № 1",
        )
        == "lease"
    )
    assert (
        resolve_data_room_bucket(
            "appendix_spec",
            filename="spec_postavka.pdf",
            text="Приложение №1 к договору поставки",
        )
        == "supply"
    )
    assert (
        resolve_data_room_bucket(
            "addendum",
            filename="ds_bez_temy.pdf",
            text="ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 2 к Договору № 5",
        )
        == "contracts_other"
    )


def test_filename_looks_generic():
    assert filename_looks_generic("Скан_1.pdf") is True
    assert filename_looks_generic("Безымянный_4.pdf") is True
    assert filename_looks_generic("Scan 12.pdf") is True
    assert filename_looks_generic("Dogovor arendy 03-03.pdf") is False


def test_build_catalog_filename():
    name = build_catalog_filename(
        doc_type="lease_commercial",
        text="ДОГОВОР АРЕНДЫ № 03/03-2022/1 г. Москва",
        original_filename="Scan_1.pdf",
    )
    assert name.endswith(".pdf")
    assert "Аренда" in name or "ДОГОВОР" in name.upper() or "договор" in name.lower()
