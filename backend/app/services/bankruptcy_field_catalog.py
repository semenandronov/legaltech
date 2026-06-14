"""
Каталог переменных docxtpl для банкротных заявлений.

Единый источник правды: имя переменной → атомарная инструкция для LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Type

from pydantic import BaseModel, Field, create_model

_DESC_COURT_NAME = (
    "Напиши только официальное наименование Арбитражного суда, в который подается заявление. "
    "Пример: Арбитражный суд города Москвы."
)
_DESC_STATE_DUTY = (
    "Напиши только сумму государственной пошлины цифрами в рублях, без букв и точек. "
    "Пример: 300 или 2000."
)
_DESC_DOC_CITY = (
    "Напиши только название города/населенного пункта, где подписывается документ. "
    "Пример: г. Москва."
)
_DESC_DOC_DATE = (
    "Напиши только текущую дату составления документа или дату подачи в формате ДД.ММ.ГГГГ. "
    "Пример: 14.06.2026."
)
_DESC_CREDITOR_NAME = (
    "Напиши полное наименование компании-кредитора (с ОПФ, например, ООО «Ромашка») "
    "или ФИО кредитора-гражданина."
)
_DESC_CREDITOR_INN = (
    "Напиши только ИНН Кредитора (10 или 12 цифр). "
    "Если это физлицо и ИНН нет, укажи его паспортные данные."
)
_DESC_CREDITOR_ADDRESS = (
    "Напиши полный адрес места нахождения или регистрации Кредитора с почтовым индексом."
)
_DESC_DEBTOR_NAME = (
    "Напиши полное наименование компании-должника или ФИО должника-гражданина."
)
_DESC_DEBTOR_INN = (
    "Напиши только ИНН Должника (10 цифр для ЮЛ, 12 цифр для ФЛ)."
)
_DESC_DEBTOR_ADDRESS = (
    "Напиши полный юридический адрес компании-должника или адрес прописки должника-гражданина."
)
_DESC_EFRSB_NUM = (
    "Напиши только цифровой номер сообщения (уведомления) о намерении обратиться в суд, "
    "опубликованного на ЕФРСБ."
)
_DESC_EFRSB_DATE = (
    "Напиши только дату публикации сообщения на ЕФРСБ в формате ДД.ММ.ГГГГ."
)
_DESC_SRO_NAME = (
    "Напиши полное официальное наименование Саморегулируемой организации (СРО) арбитражных "
    "управляющих, из числа членов которой должен быть утвержден управляющий."
)
_DESC_MANAGER_FIO = (
    "Напиши ФИО конкретного арбитражного (временного/финансового) управляющего, "
    "если он указан в документах. Если указано только СРО, оставь строку пустой."
)
_DESC_DEBT_EVIDENCE = (
    "Кратко перечисли судебные акты (решения, определения), подтверждающие долг, "
    "с указанием дат и номеров дел. "
    "Пример: Решение Арбитражного суда г. Москвы от 15.04.2026 по делу № А40-999/26."
)
_DESC_DEBT_TOTAL = (
    "Напиши общую итоговую сумму задолженности (включая основной долг, пени, штрафы) "
    "строго цифрами без пробелов и копеек. Пример: 2500000."
)
_DESC_DEBT_MAIN = (
    "Напиши только сумму основного долга (чистый долг без учета штрафных санкций) "
    "цифрами без пробелов. Пример: 2300000."
)
_DESC_DEBT_PENALTY = (
    "Напиши общую сумму начисленной неустойки, пени, штрафов или процентов "
    "цифрами без пробелов. Пример: 200000."
)
_DESC_DEBT_START_DATE = (
    "Напиши дату начала периода, за который начислялись пени/проценты, в формате ДД.ММ.ГГГГ."
)
_DESC_DEBT_END_DATE = (
    "Напиши дату окончания периода, за который начислялись пени/проценты, в формате ДД.ММ.ГГГГ."
)
_DESC_DEBT_CONFIRMED = (
    "Напиши сумму долга, которая уже подтверждена вступившими в силу решениями судов. Только цифры."
)
_DESC_DEBTOR_BIRTH = (
    "Напиши дату и место рождения гражданина. Пример: 20.11.1988 года рождения, гор. Ленинград."
)
_DESC_DEBTOR_PASSPORT = (
    "Напиши паспортные данные гражданина: серия, номер, кем и когда выдан, код подразделения."
)
_DESC_DEBTOR_SNILS = (
    "Напиши только номер СНИЛС гражданина в формате ХХХ-ХХХ-ХХХ ХХ."
)
_DESC_DEBTOR_INCOME_VALUE = (
    "Напиши среднемесячный доход гражданина цифрами в рублях. Пример: 45000."
)
_DESC_DEBTOR_INCOME_SOURCE = (
    "Напиши источник дохода гражданина (например: заработная плата в ООО «Вектор» или пенсия)."
)
_DESC_MARITAL_STATUS = (
    "Напиши семейное положение гражданина (строго одно из значений: "
    "состоит в браке, холост, не замужем, разведен, вдовец, вдова)."
)
_DESC_CHILDREN_STATUS = (
    "Напиши информацию о наличии несовершеннолетних детей. "
    "Пример: имеются несовершеннолетние дети (двое) или несовершеннолетних детей не имеет."
)
_DESC_ALIMONY = (
    "Напиши размер алиментных обязательств гражданина в месяц цифрами. "
    "Если алиментов нет, напиши: обязательства по уплате алиментов отсутствуют."
)
_DESC_DEBT_MONETARY = (
    "Выдели из баланса/документов долга сумму требований кредиторов по денежным обязательствам. "
    "Напиши только цифрами. Если данных нет — 0."
)
_DESC_DEBT_INJURY = (
    "Выдели сумму задолженности по возмещению вреда, причиненного жизни или здоровью граждан. "
    "Напиши только цифрами. Если данных нет — 0."
)
_DESC_DEBT_SALARY = (
    "Выдели сумму задолженности по оплате труда работников и выплате выходных пособий. "
    "Напиши только цифрами. Если данных нет — 0."
)
_DESC_DEBT_INTELLECTUAL = (
    "Выдели сумму вознаграждения авторов результатов интеллектуальной деятельности. "
    "Напиши только цифрами. Если данных нет — 0."
)
_DESC_DEBT_MANDATORY = (
    "Выдели сумму задолженности по обязательным платежам. "
    "Напиши только цифрами. Если данных нет — 0."
)
_DESC_ASSET_IMMOVABLE = (
    "Выдели стоимость недвижимого имущества должника. "
    "Напиши только цифрами. Если активов нет — 0."
)
_DESC_ASSET_MOVABLE = (
    "Выдели стоимость движимого имущества (включая транспорт). "
    "Напиши только цифрами. Если активов нет — 0."
)
_DESC_ASSET_INTANGIBLE = (
    "Выдели стоимость нематериальных активов (интеллектуальная собственность). "
    "Напиши только цифрами. Если активов нет — 0."
)
_DESC_ASSET_RECEIVABLE = (
    "Выдели сумму дебиторской задолженности должника. "
    "Напиши только цифрами. Если активов нет — 0."
)
_DESC_ASSET_TOTAL = (
    "Выдели итоговую стоимость всех активов должника. "
    "Напиши только цифрами. Если активов нет — 0."
)
_DESC_SIGNATORY_FIO = (
    "Напиши ФИО лица, которое будет подписывать документ "
    "(руководитель компании, представитель по доверенности или сам гражданин-должник). "
    "Пример: И.И. Иванов."
)
_DESC_SIGNATORY_POSITION = (
    "Напиши должность лица, подписывающего документ "
    "(например: Генеральный директор, Представитель по доверенности, Должник-гражданин)."
)

BANKRUPTCY_FIELD_CATALOG: Dict[str, Dict[str, Any]] = {
    "court_name": {"description": _DESC_COURT_NAME, "entity_role": "court", "data_type": "court_name"},
    "state_duty": {"description": _DESC_STATE_DUTY, "data_type": "amount"},
    "doc_city": {"description": _DESC_DOC_CITY, "data_type": "other"},
    "doc_date": {"description": _DESC_DOC_DATE, "data_type": "date"},
    "creditor_name": {"description": _DESC_CREDITOR_NAME, "entity_role": "creditor", "data_type": "party_name"},
    "creditor_inn": {"description": _DESC_CREDITOR_INN, "entity_role": "creditor", "data_type": "inn"},
    "creditor_address": {"description": _DESC_CREDITOR_ADDRESS, "entity_role": "creditor", "data_type": "address"},
    "debtor_name": {"description": _DESC_DEBTOR_NAME, "entity_role": "debtor", "data_type": "party_name"},
    "debtor_inn": {"description": _DESC_DEBTOR_INN, "entity_role": "debtor", "data_type": "inn"},
    "debtor_address": {"description": _DESC_DEBTOR_ADDRESS, "entity_role": "debtor", "data_type": "address"},
    "efrsb_num": {"description": _DESC_EFRSB_NUM, "data_type": "other"},
    "efrsb_date": {"description": _DESC_EFRSB_DATE, "data_type": "date"},
    "sro_name": {"description": _DESC_SRO_NAME, "data_type": "party_name"},
    "manager_fio": {"description": _DESC_MANAGER_FIO, "data_type": "party_name"},
    "debt_evidence": {"description": _DESC_DEBT_EVIDENCE, "data_type": "other"},
    "debt_total": {"description": _DESC_DEBT_TOTAL, "data_type": "amount"},
    "debt_main": {"description": _DESC_DEBT_MAIN, "data_type": "amount"},
    "debt_penalty": {"description": _DESC_DEBT_PENALTY, "data_type": "amount"},
    "debt_start_date": {"description": _DESC_DEBT_START_DATE, "data_type": "date"},
    "debt_end_date": {"description": _DESC_DEBT_END_DATE, "data_type": "date"},
    "debt_confirmed": {"description": _DESC_DEBT_CONFIRMED, "data_type": "amount"},
    "debtor_birth": {"description": _DESC_DEBTOR_BIRTH, "entity_role": "debtor", "data_type": "other"},
    "debtor_passport": {"description": _DESC_DEBTOR_PASSPORT, "entity_role": "debtor", "data_type": "other"},
    "debtor_snils": {"description": _DESC_DEBTOR_SNILS, "entity_role": "debtor", "data_type": "other"},
    "debtor_income_value": {"description": _DESC_DEBTOR_INCOME_VALUE, "entity_role": "debtor", "data_type": "amount"},
    "debtor_income_source": {"description": _DESC_DEBTOR_INCOME_SOURCE, "entity_role": "debtor", "data_type": "other"},
    "marital_status": {"description": _DESC_MARITAL_STATUS, "entity_role": "debtor", "data_type": "other"},
    "children_status": {"description": _DESC_CHILDREN_STATUS, "entity_role": "debtor", "data_type": "other"},
    "alimony_obligations": {"description": _DESC_ALIMONY, "entity_role": "debtor", "data_type": "amount"},
    "debt_monetary": {"description": _DESC_DEBT_MONETARY, "data_type": "amount"},
    "debt_injury": {"description": _DESC_DEBT_INJURY, "data_type": "amount"},
    "debt_salary": {"description": _DESC_DEBT_SALARY, "data_type": "amount"},
    "debt_intellectual": {"description": _DESC_DEBT_INTELLECTUAL, "data_type": "amount"},
    "debt_mandatory": {"description": _DESC_DEBT_MANDATORY, "data_type": "amount"},
    "asset_immovable": {"description": _DESC_ASSET_IMMOVABLE, "data_type": "amount"},
    "asset_movable": {"description": _DESC_ASSET_MOVABLE, "data_type": "amount"},
    "asset_intangible": {"description": _DESC_ASSET_INTANGIBLE, "data_type": "amount"},
    "asset_receivable": {"description": _DESC_ASSET_RECEIVABLE, "data_type": "amount"},
    "asset_total": {"description": _DESC_ASSET_TOTAL, "data_type": "amount"},
    "signatory_fio": {"description": _DESC_SIGNATORY_FIO, "data_type": "party_name"},
    "signatory_position": {"description": _DESC_SIGNATORY_POSITION, "data_type": "other"},
}

TEMPLATE_VARIABLES: Dict[str, List[str]] = {
    "creditor_ul_general": [
        "court_name", "creditor_name", "creditor_inn", "creditor_address",
        "debtor_name", "debtor_inn", "debtor_address", "state_duty",
        "doc_city", "doc_date", "debt_total", "debt_main", "debt_penalty",
        "debt_start_date", "debt_end_date", "debt_evidence",
        "efrsb_num", "efrsb_date", "sro_name", "manager_fio",
        "signatory_fio", "signatory_position",
    ],
    "debtor_ul_general": [
        "court_name", "debtor_name", "debtor_inn", "debtor_address",
        "state_duty", "doc_city", "doc_date", "efrsb_num", "efrsb_date",
        "sro_name", "debt_total", "debt_confirmed",
        "debt_monetary", "debt_injury", "debt_salary", "debt_intellectual",
        "debt_mandatory", "asset_immovable", "asset_movable", "asset_intangible",
        "asset_receivable", "asset_total", "signatory_fio", "signatory_position",
    ],
    "debtor_fl_general": [
        "court_name", "debtor_name", "debtor_birth", "debtor_passport",
        "debtor_inn", "debtor_snils", "debtor_address", "state_duty",
        "doc_city", "doc_date", "debt_total", "debtor_income_value",
        "debtor_income_source", "asset_total", "marital_status",
        "children_status", "alimony_obligations", "sro_name",
    ],
    "creditor_fl_general": [
        "court_name", "creditor_name", "creditor_inn", "creditor_address",
        "debtor_name", "debtor_inn", "debtor_address", "state_duty",
        "doc_city", "doc_date", "debt_total", "debt_main", "debt_penalty",
        "debt_start_date", "debt_end_date", "debt_evidence",
        "efrsb_num", "efrsb_date", "sro_name",
        "signatory_fio", "signatory_position",
    ],
}


def docxtpl_marker(variable: str) -> str:
    return f"{{{{ {variable} }}}}"


def get_field_description(variable: str) -> str:
    meta = BANKRUPTCY_FIELD_CATALOG.get(variable)
    if not meta:
        return f"Напиши значение для поля {variable}."
    return str(meta["description"])


def get_field_meta(variable: str) -> Dict[str, Any]:
    return BANKRUPTCY_FIELD_CATALOG.get(
        variable,
        {"description": get_field_description(variable)},
    )


def get_template_variables(template_id: str) -> List[str]:
    return list(TEMPLATE_VARIABLES.get(template_id, []))


def build_extraction_model(
    variable_keys: List[str],
    *,
    model_name: str = "BankruptcyTemplateExtract",
) -> Type[BaseModel]:
    """Динамическая Pydantic-модель для structured output."""
    fields: Dict[str, Any] = {}
    for key in variable_keys:
        desc = get_field_description(key)
        fields[key] = (str, Field(default="", description=desc))
    return create_model(model_name, **fields)  # type: ignore[call-overload]
