"""Tests for DD rules-first document classifier."""

from app.services.contract_field_catalog import field_applies_to_dd_doc_type
from app.services.dd_document_classifier import classify_dd_document


def test_classify_lease_from_text():
    text = (
        "ДОГОВОР АРЕНДЫ № 03/03-2022/1\n"
        "Арендодатель передаёт Арендатору имущество. Арендная плата составляет..."
    )
    r = classify_dd_document(text=text, filename="dogovor_arendy.pdf")
    assert r.doc_type == "lease_commercial"
    assert r.confidence >= 0.55


def test_classify_lease_not_appendix_when_appendix_only_in_body():
    text = (
        "ДОГОВОР АРЕНДЫ ДВИЖИМОГО ИМУЩЕСТВА С ПРАВОМ ВЫКУПА № 20/01-2022/1\n"
        "Арендодатель ООО СМАРТ СИТИ. Арендатор ИП.\n"
        + ("условия " * 80)
        + "\nПриложение № 1 к настоящему Договору. Спецификация.\n"
    )
    r = classify_dd_document(text=text, filename="06. dogovor arendy 20-01-22 9l.pdf")
    assert r.doc_type == "lease_commercial"


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
