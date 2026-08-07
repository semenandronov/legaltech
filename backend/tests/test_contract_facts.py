"""Tests for contract facts schema layer (phase 3)."""

from types import SimpleNamespace

from app.services.contract_extraction_schemas import (
    GroundedField,
    LeaseExtraction,
    extraction_model_to_fields,
)
from app.services.contract_facts_service import (
    build_contract_facts_payload,
    extract_contract_facts_rules,
    lookup_contract_fact,
    try_extraction_from_contract_facts,
)
from app.services.contract_field_catalog import (
    RU_DD_LEASE_TEMPLATE,
    field_id_from_column_config,
    normalize_field_id,
)
from app.services.tabular_column_type_contract import validate_column_config
import pytest


SAMPLE_LEASE = """
ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1
к Договору аренды движимого имущества с правом выкупа № 03/03-2022/1 от 03.03.2022г.

г. Москва                        «25» июля 2022г.
Общество с ограниченной ответственностью «СМАРТ СИТИ» (ИНН 9701032688)

1.Стороны решили внести изменения в пункт 5.1. Договора и изложить его в следующей редакции:
«5.1. Размер арендной платы за весь период аренды составляет 959 335 (девятьсот пятьдесят девять
тысяч триста тридцать пять) руб. 00 копеек, без НДС.
"""


def test_normalize_field_id_namespaced():
    assert normalize_field_id("lease.rent_amount") == "rent_amount"
    assert normalize_field_id("unknown_x") is None


def test_rules_extract_lease_core_fields():
    fields = extract_contract_facts_rules(
        SAMPLE_LEASE,
        filename="ds1_arenda.pdf",
        dd_doc_type="addendum",
    )
    assert fields["doc_number"]["value"] == "03/03-2022/1"
    assert fields["doc_date"]["value"] == "2022-07-25"
    assert fields["buyout_right"]["value"] == "Да"
    assert fields["rent_amount"]["value"] == "959 335 руб."
    # Generic title «движимого имущества» must NOT short-circuit as leased_object.
    assert "leased_object" not in fields


OCR_PREAMBLE_LEASE = """
Договор аренды движимого имущества
с правом выкупа № 20/01-2022/1
г. Москва
«20» января 2022г.
Общество с ограниченной ответственностью «СМАРТ СИТИ» (ИНН 9701032688, ОГРН
1167746181173) в лице Генерального директора Елизарова Данилы Михайловича, действующего на
основании устава, именуемое в дальнейшем «Арендодатель», с одной стороны
и Индивидуальный предприниматель Красноштанова Ольга Борисовна (ИНН 380503776092,
ОГРНИП 321385000042741) в собственном лице, действующий на основании свидетельства о
государственной регистрации физического лица в качестве индивидуального предпринимателя
ОГРНИП 321385000042741, именуемый в дальнейшем «Арендатор», с другой стороны, совместно
именуемые «Стороны», заключили настоящий договор (далее также именуемый «Договор») о
нижеследующем:
1. Предмет Договора
1.1. Арендодатель передаёт Арендатору электросамокаты в количестве 50 штук.
5.1. Размер арендной платы за весь период аренды составляет 1 894 705 (один миллион
восемьсот девяносто четыре тысячи семьсот пять) руб. 00 копеек.
"""


def test_rules_extract_parties_from_ocr_multiline_preamble():
    fields = extract_contract_facts_rules(
        OCR_PREAMBLE_LEASE,
        filename="lease_scan.pdf",
        dd_doc_type="lease_commercial",
    )
    assert "СМАРТ СИТИ" in fields["landlord"]["value"].upper().replace("«", "").replace("»", "")
    assert "Красноштанова" in fields["tenant"]["value"]
    assert "основании" not in fields["landlord"]["value"].lower()
    assert "огрнип" not in fields["tenant"]["value"].lower()
    assert fields["rent_amount"]["value"] == "1 894 705 руб."
    assert fields["doc_number"]["value"] == "20/01-2022/1"
    assert fields["doc_date"]["value"] == "2022-01-20"


def test_rules_reject_garbage_party_tail():
    from app.services.contract_facts_service import is_plausible_party_name

    assert not is_plausible_party_name("основании устава")
    assert not is_plausible_party_name("ОГРНИП 321385000042741")
    assert is_plausible_party_name(
        "Общество с ограниченной ответственностью «СМАРТ СИТИ»"
    )


def test_try_extraction_skips_garbage_cached_fact(monkeypatch):
    monkeypatch.setattr(
        "app.services.contract_facts_service.config.CONTRACT_FACTS_ENABLED",
        True,
        raising=False,
    )
    file_model = SimpleNamespace(
        id="f1",
        filename="bad.txt",
        original_text="x",
        contract_facts={
            "fields": {
                "landlord": {
                    "value": "основании устава",
                    "verbatim": "основании устава, именуемое Арендодатель",
                    "confidence": 0.9,
                }
            }
        },
        dd_doc_type="lease_commercial",
        processing_progress=None,
    )
    column = SimpleNamespace(
        column_type="text",
        column_config={"field_id": "landlord"},
        column_label="Арендодатель",
        prompt="Кто арендодатель?",
    )
    assert try_extraction_from_contract_facts(file_model, column, allow_lazy=False) is None


def test_rules_extract_money_with_broken_ocr_spacing():
    text = SAMPLE_LEASE.replace("959 335", "959 3 35")
    fields = extract_contract_facts_rules(text, dd_doc_type="addendum")
    assert fields["rent_amount"]["value"] == "959 335 руб."


def test_rules_extract_glued_ot_in_number():
    text = SAMPLE_LEASE.replace("03/03-2022/1 от", "03/03-2022/1от")
    fields = extract_contract_facts_rules(text, dd_doc_type="addendum")
    assert fields["doc_number"]["value"] == "03/03-2022/1"


def test_build_payload_rules_only(monkeypatch):
    monkeypatch.setattr(
        "app.services.contract_facts_service.config.CONTRACT_FACTS_LLM_ENABLED",
        False,
        raising=False,
    )
    payload = build_contract_facts_payload(
        text=SAMPLE_LEASE,
        filename="ds1.pdf",
        dd_doc_type="addendum",
        allow_llm=True,
    )
    assert payload["source"] == "rules"
    assert payload["field_count"] >= 3
    assert lookup_contract_fact(payload, "doc_date")["value"] == "2022-07-25"


def test_extraction_model_to_fields_aliases():
    model = LeaseExtraction(
        rent_amount=GroundedField(
            value="100000 руб.",
            verbatim_quote="арендная плата 100000 руб.",
            confidence=0.9,
        ),
        landlord=GroundedField(
            value="ООО Альфа",
            verbatim_quote="ООО Альфа именуемое Арендодатель",
            confidence=0.9,
        ),
    )
    fields = extraction_model_to_fields(model)
    assert "rent_amount" in fields
    assert "price_total" in fields
    assert fields["party_a"]["value"] == "ООО Альфа"


def test_try_extraction_from_contract_facts_hits_without_rag(monkeypatch):
    monkeypatch.setattr(
        "app.services.contract_facts_service.config.CONTRACT_FACTS_ENABLED",
        True,
        raising=False,
    )
    payload = build_contract_facts_payload(
        text=SAMPLE_LEASE,
        dd_doc_type="addendum",
        allow_llm=False,
    )
    file_model = SimpleNamespace(
        id="f1",
        filename="ds1.txt",
        original_text=SAMPLE_LEASE,
        contract_facts=payload,
        dd_doc_type="addendum",
        processing_progress=None,
    )
    column = SimpleNamespace(
        column_type="currency",
        column_config={"field_id": "rent_amount"},
        column_label="Арендная плата",
        prompt="Сумма",
    )
    hit = try_extraction_from_contract_facts(file_model, column, allow_lazy=False)
    assert hit is not None
    extraction, docs, meta = hit
    assert extraction.extraction_method == "contract_facts"
    assert "959" in extraction.cell_value
    assert meta["status"] == "contract_facts_hit"
    assert docs[0].metadata["retrieval_channel"] == "contract_facts"


def test_try_extraction_skips_without_field_id():
    file_model = SimpleNamespace(contract_facts={"fields": {}}, original_text="x")
    column = SimpleNamespace(column_type="text", column_config={})
    assert try_extraction_from_contract_facts(file_model, column) is None


def test_validate_field_id_in_column_config():
    validate_column_config("text", {"field_id": "doc_number"})
    with pytest.raises(ValueError, match="field_id"):
        validate_column_config("text", {"field_id": "not_a_real_field"})


def test_lease_template_has_field_ids():
    cols = RU_DD_LEASE_TEMPLATE["columns"]
    assert len(cols) >= 8
    assert field_id_from_column_config(cols[0]["column_config"]) is not None
