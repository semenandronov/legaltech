"""Production document issuance-date resolver."""

from app.services.document_date_resolver import (
    resolve_document_issuance_date,
    select_document_date_zone,
)
from app.services.contract_facts_service import extract_contract_facts_rules


PODRYAD_14L = """
Производство и строительство быстровозводимых зданий

ТЕХНИОН
г. Москва, пр-т Маршала Жукова, 78
+7 (499) 302-3231  www.tg-sk.ru

ДОГОВОР № 98/2024

«16 » апреля 2024 г.

г. Москва

Общество с ограниченной ответственностью «Управляющая компания «КЕМБРИДЖ
Сервис» именуемое в дальнейшем «Заказчик», в лице генерального директора Климанова Дениса
Юрьевича, действующего на основании Устава, с одной стороны, и

ООО «Технион Групп», именуемое в дальнейшем «Подрядчик», …

1. ПРЕДМЕТ ДОГОВОРА

1.1. По настоящему Договору Подрядчик обязуется выполнить работы.
1.3.3. Результатом Работ не является здание в том виде, в каком предусмотрено статьей 2
федерального закона от 30.12.2009 N 384-ФЗ (ред. от 02.07.2013)
"Технический регламент о безопасности зданий и сооружений".
"""


ADDENDUM = """
ДОПОЛНИТЕЛЬНОЕ СОГЛАШЕНИЕ № 1
к Договору аренды движимого имущества с правом выкупа № 03/03-2022/1 от 03.03.2022г.

г. Москва                        «25» июля 2022г.
Общество с ограниченной ответственностью «СМАРТ СИТИ» (ИНН 9701032688)

1.Стороны решили внести изменения в пункт 5.1. Договора
"""


COURT_LIKE = """
АРБИТРАЖНЫЙ СУД ГОРОДА МОСКВЫ

РЕШЕНИЕ

г. Москва                                                12.03.2024

Дело № А40-12345/2024

Арбитражный суд города Москвы в составе судьи Иванова И.И. рассмотрел дело.

1. УСТАНОВИЛ
В соответствии с федеральным законом от 26.10.2002 N 127-ФЗ …
"""


LETTER_LIKE = """
ООО «Альфа»
Исх. № 44/2023
от 05 мая 2023 г.

Уважаемый Иван Иванович!

Настоящим уведомляем Вас о готовности акта.
В соответствии со ст. 309 ГК РФ …
"""


def test_podryad_ocr_date_not_statute_date():
    hit = resolve_document_issuance_date(PODRYAD_14L, filename="03_dogovor_16-04-2024_14l.pdf")
    assert hit is not None
    assert hit.iso_date == "2024-04-16"
    assert "2009" not in hit.iso_date


def test_addendum_prefers_signing_over_base_contract_ref():
    hit = resolve_document_issuance_date(ADDENDUM, filename="ds1.pdf")
    assert hit is not None
    assert hit.iso_date == "2022-07-25"


def test_court_decision_date():
    hit = resolve_document_issuance_date(COURT_LIKE, filename="decision.pdf")
    assert hit is not None
    assert hit.iso_date == "2024-03-12"


def test_letter_ru_month_date():
    hit = resolve_document_issuance_date(LETTER_LIKE, filename="letter.pdf")
    assert hit is not None
    assert hit.iso_date == "2023-05-05"


def test_zone_excludes_statute_body():
    zone, end = select_document_date_zone(PODRYAD_14L)
    assert "384-ФЗ" not in zone
    assert end < 2000
    assert "апреля 2024" in zone.replace("\n", " ")


def test_only_statute_dates_returns_none_or_not_statute():
    text = """
Документ без даты в шапке.

1. Предмет
Согласно федеральному закону от 30.12.2009 N 384-ФЗ (ред. от 02.07.2013) ...
"""
    hit = resolve_document_issuance_date(text)
    assert hit is None or hit.iso_date not in {"2009-12-30", "2013-07-02"}


def test_contract_facts_rules_use_resolver():
    fields = extract_contract_facts_rules(
        PODRYAD_14L,
        filename="03_dogovor.pdf",
        dd_doc_type="works",
    )
    assert fields["doc_date"]["value"] == "2024-04-16"

    fields2 = extract_contract_facts_rules(
        ADDENDUM,
        filename="ds.pdf",
        dd_doc_type="addendum",
    )
    assert fields2["doc_date"]["value"] == "2022-07-25"
