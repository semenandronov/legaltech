#!/usr/bin/env python3
"""Convert bankruptcy DOCX templates to HTML with semantic placeholders."""
from __future__ import annotations

import html
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Callable, List, Tuple

import mammoth

ROOT = Path(__file__).resolve().parent.parent
SRC = Path("/Users/semyon_andronov04/Downloads/01. заявления о банкротстве")
OUT = ROOT / "app" / "templates" / "draft"

ReplaceFn = Callable[[str], str]

SRO_CANDIDATE = "[наименование СРО кандидата арбитражного управляющего]"
SRO_LIST = "[перечень СРО арбитражных управляющих]"


def _replace_nth(text: str, pattern: str, repl: str, n: int = 1) -> str:
    count = 0

    def sub(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return repl if count == n else m.group(0)

    return re.sub(pattern, sub, text, flags=re.IGNORECASE)


def _replace_all_nth(text: str, pairs: List[Tuple[str, str]]) -> str:
    for pattern, repl in pairs:
        text = _replace_nth(text, pattern, repl, 1)
    return text


def _docx_html(path: Path) -> str:
    with path.open("rb") as f:
        result = mammoth.convert_to_html(f)
    body = (result.value or "").strip()
    if not body:
        raise ValueError(f"empty conversion: {path}")
    return (
        '<article class="legal-draft">\n'
        + body
        + '\n</article>'
    )


def _common_header_creditor(text: str) -> str:
    text = text.replace(
        "В АРБИТРАЖНЫЙ СУД [вставить данные]",
        "В АРБИТРАЖНЫЙ СУД [наименование суда]",
    )
    text = _replace_nth(text, r"\[Наименование\]", "[наименование кредитора]", 1)
    text = text.replace("[ИНН или паспортные данные]", "[ИНН кредитора]")
    text = _replace_nth(text, r"\[адрес\]", "[адрес кредитора]", 1)
    text = _replace_nth(text, r"\[Наименование\]", "[наименование должника]", 1)
    text = text.replace("[ИНН]", "[ИНН должника]")
    text = _replace_nth(text, r"\[адрес\]", "[адрес должника]", 1)
    text = text.replace("[размер]", "[госпошлина]")
    text = text.replace("[место]", "[место подписания]")
    text = text.replace("[дата]", "[дата составления]")
    return text


def _common_header_debtor_ul(text: str) -> str:
    text = text.replace(
        "В АРБИТРАЖНЫЙ СУД [вставить данные]",
        "В АРБИТРАЖНЫЙ СУД [наименование суда]",
    )
    text = _replace_nth(text, r"\[Наименование\]", "[наименование должника]", 1)
    text = text.replace("[ИНН]", "[ИНН должника]")
    text = _replace_nth(text, r"\[адрес\]", "[адрес должника]", 1)
    text = text.replace("[размер]", "[госпошлина]")
    text = text.replace("[место]", "[место подписания]")
    text = text.replace("[дата]", "[дата составления]")
    return text


def _creditor_claim_amounts(text: str) -> str:
    text = re.sub(
        r"составлять \[вставить данные\] рублей",
        "составлять [сумма требований всего] рублей",
        text,
        count=1,
    )
    text = re.sub(
        r"\[вставить данные\] рублей – основной долг",
        "[сумма основного долга] рублей – основной долг",
        text,
        count=1,
    )
    text = re.sub(
        r"\[вставить данные\] рублей – неустойка",
        "[сумма неустойки] рублей – неустойка",
        text,
        count=1,
    )
    text = re.sub(
        r"за период с \[вставить данные\] по \[вставить данные\]",
        "за период с [дата начала неустойки] по [дата окончания неустойки]",
        text,
        count=1,
    )
    text = re.sub(
        r"подтверждаются следующим \[вставить данные\]",
        "подтверждаются следующим [документы основания задолженности]",
        text,
        count=1,
    )
    text = re.sub(
        r"сообщение № \[вставить данные\] от \[вставить данные\]",
        "сообщение № [номер сообщения ЕФРСБ] от [дата сообщения ЕФРСБ]",
        text,
    )
    text = re.sub(
        r"членов СРО \[вставить данные\]",
        f"членов СРО {SRO_LIST}",
        text,
        count=1,
    )
    text = re.sub(
        r"требования Кредитора в размере \[вставить данные\]",
        "требования Кредитора в размере [сумма требований всего]",
        text,
    )
    text = text.replace(
        "[доказательства наличия задолженности]",
        "[перечень доказательств задолженности]",
    )
    text = text.replace("[И.О. Фамилия]", "[ФИО подписанта]")
    text = text.replace("[должность]", "[должность подписанта]")
    return text


def _replace_creditor_names_in_body(text: str) -> str:
    text = text.replace(
        "Кредитор [Наименование]",
        "Кредитор [наименование кредитора]",
    )
    text = text.replace(
        "должника [Наименование]",
        "должника [наименование должника]",
    )
    text = text.replace(
        "должника [Наименование]",
        "должника [наименование должника]",
    )
    text = re.sub(
        r"кредитора \[Наименование\]",
        "кредитора [наименование кредитора]",
        text,
    )
    text = re.sub(
        r"Должника \[Наименование\]",
        "Должника [наименование должника]",
        text,
    )
    text = re.sub(
        r"должника \[Наименование\]",
        "должника [наименование должника]",
        text,
    )
    text = re.sub(
        r"члена СРО \[Наименование\] – \[Фамилия Имя Отчество\]",
        f"члена СРО {SRO_CANDIDATE} – [ФИО кандидата арбитражного управляющего]",
        text,
    )
    text = text.replace("[Фамилия Имя Отчество]", "[ФИО кандидата арбитражного управляющего]")
    # remaining generic names
    text = text.replace("[Наименование]", "[наименование должника]")
    text = text.replace(
        "требования кредитора [наименование кредитора] в размере [вставить данные]",
        "требования кредитора [наименование кредитора] в размере [сумма требований всего]",
    )
    return text


def transform_creditor_ul_general(raw: str) -> str:
    t = _common_header_creditor(raw)
    t = _creditor_claim_amounts(t)
    t = _replace_creditor_names_in_body(t)
    return t


def transform_creditor_ul_absent(raw: str) -> str:
    t = transform_creditor_ul_general(raw)
    t = t.replace(
        "[генерального директора | участника | юридического адреса]",
        "[предмет записи о недостоверности в ЕГРЮЛ]",
    )
    t = t.replace(
        "[не всегда имеет место]",
        "[сведения о неподаче бухгалтерской отчётности]",
    )
    return t


def transform_creditor_ul_liquidation(raw: str) -> str:
    return transform_creditor_ul_general(raw)


def transform_creditor_fl(raw: str) -> str:
    t = _common_header_creditor(raw)
    t = t.replace(
        "Кредитор [Наименование | Фамилия Имя Отчество]",
        "Кредитор [наименование или ФИО кредитора]",
    )
    t = t.replace(
        "должника [Фамилия Имя Отчество]",
        "должника [ФИО должника]",
    )
    t = _creditor_claim_amounts(t)
    t = re.sub(
        r"Кредитора \[Наименование \| Фамилия Имя Отчество\]",
        "Кредитора [наименование или ФИО кредитора]",
        t,
    )
    t = re.sub(
        r"должника \[Фамилия Имя Отчество\]",
        "должника [ФИО должника]",
        t,
    )
    t = re.sub(
        r"члена СРО \[вставить данные\]",
        f"члена СРО {SRO_CANDIDATE}",
        t,
    )
    t = t.replace(
        "Кредитора Наименование | Фамилия Имя Отчество]",
        "Кредитора [наименование или ФИО кредитора]",
    )
    t = re.sub(
        r"требования кредитора \[наименование кредитора\] в размере \[вставить данные\]",
        "требования кредитора [наименование или ФИО кредитора] в размере [сумма требований всего]",
        t,
    )
    t = t.replace(
        "<strong>Кредитор:</strong></p></th><th><p><strong>[наименование кредитора]</strong>",
        "<strong>Кредитор:</strong></p></th><th><p><strong>[наименование или ФИО кредитора]</strong>",
    )
    t = t.replace(
        "<strong>Должник:</strong></p></th><th><p><strong>[наименование должника]</strong>",
        "<strong>Должник:</strong></p></th><th><p><strong>[ФИО должника]</strong>",
    )
    t = t.replace("[Фамилия Имя Отчество]", "[ФИО должника]")
    return t


def _debtor_ul_tables(text: str) -> str:
    html_pairs = [
        (r"денежным обязательствам</p></th><th><p>\[вставить данные\]", "денежным обязательствам</p></th><th><p>[сумма денежных обязательств перед кредиторами]"),
        (r"возмещения вреда</p></th><th><p>\[вставить данные\]", "возмещения вреда</p></th><th><p>[сумма задолженности по вреду жизни и здоровью]"),
        (r"выходных пособий</p></th><th><p>\[вставить данные\]", "выходных пособий</p></th><th><p>[сумма задолженности по оплате труда]"),
        (r"интеллектуальной деятельности\s*</p></th><th><p>\[вставить данные\]", "интеллектуальной деятельности</p></th><th><p>[сумма задолженности по вознаграждению авторов]"),
        (r"обязательным платежам</p></th><th><p>\[вставить данные\]", "обязательным платежам</p></th><th><p>[сумма задолженности по обязательным платежам]"),
        (r"<strong>ИТОГО:</strong></p></th><th><p><strong>\[вставить данные\]</strong>", "<strong>ИТОГО:</strong></p></th><th><p><strong>[итого требования кредиторов]</strong>"),
        (r"недвижимое имущество</p></th><th><p>\[вставить данные\]", "недвижимое имущество</p></th><th><p>[стоимость недвижимого имущества]"),
        (r"транспортные средства\)</p></th><th><p>\[вставить данные\]", "транспортные средства)</p></th><th><p>[стоимость движимого имущества]"),
        (r"интеллектуальная собственность\)</p></th><th><p>\[вставить данные\]", "интеллектуальная собственность)</p></th><th><p>[стоимость нематериальных активов]"),
        (r"дебиторская задолженность</p></th><th><p>\[вставить данные\]", "дебиторская задолженность</p></th><th><p>[сумма дебиторской задолженности]"),
        (r"активов Должника составляет \[вставить данные\] рублей", "активов Должника составляет [стоимость активов всего] рублей"),
        (r"кредиторов к Должнику составляет \[вставить данные\] рублей", "кредиторов к Должнику составляет [итого требования кредиторов] рублей"),
        (r"кредиторов составляет \[вставить данные\] рублей", "кредиторов составляет [общая сумма требований кредиторов] рублей"),
        (r"в законную силу на сумму \[вставить данные\] рублей", "в законную силу на сумму [сумма подтверждённых судом требований] рублей"),
        (r"Таким СРО являются \[вставить данные\]", f"Таким СРО являются {SRO_LIST}"),
        (r"членов СРО \[вставить данные\]", f"членов СРО {SRO_LIST}"),
        (r"сообщение № \[вставить данные\] от \[вставить данные\]", "сообщение № [номер сообщения ЕФРСБ] от [дата сообщения ЕФРСБ]"),
        (r"кредитора \[наименование кредитора\] в размере \[вставить данные\]", "кредитора [наименование кредитора] в размере [сумма требований всего]"),
        (r"ИТОГО:</strong></p></th><th><p><strong>\[вставить данные\]</strong></p></th></tr></thead></table><p>Должник прикладывает к настоящему заявлению список кредиторов",
         "ИТОГО:</strong></p></th><th><p><strong>[итого стоимость имущества]</strong></p></th></tr></thead></table><p>Должник прикладывает к настоящему заявлению список кредиторов"),
    ]
    for pat, repl in html_pairs:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    # Second ИТОГО block — имущество должника
    text = re.sub(
        r"(Сведения об имуществе Должника.*?<strong>ИТОГО:</strong></p></th><th><p><strong>)\[итого требования кредиторов\]",
        r"\1[итого стоимость имущества]",
        text,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return text


def transform_debtor_ul_general(raw: str) -> str:
    t = _common_header_debtor_ul(raw)
    t = _debtor_ul_tables(t)
    t = t.replace("ООО [Наименование]", "ООО [наименование должника]")
    t = t.replace("ООО “Кванта”", "ООО [наименование должника]")
    t = re.sub(
        r"членов СРО \[Наименование\]",
        f"членов СРО {SRO_LIST}",
        t,
    )
    t = t.replace("[Наименование]", "[наименование должника]")
    t = t.replace("[И.О. Фамилия]", "[ФИО подписанта]")
    t = t.replace("[должность]", "[должность подписанта]")
    return t


def transform_debtor_ul_liquidation(raw: str) -> str:
    t = transform_debtor_ul_general(raw)
    t = t.replace(
        "конкусрного управляющего",
        "конкурсного управляющего",
    )
    return t


def transform_debtor_fl(raw: str) -> str:
    t = raw.replace(
        "В АРБИТРАЖНЫЙ СУД [вставить данные]",
        "В АРБИТРАЖНЫЙ СУД [наименование суда]",
    )
    t = t.replace("[Фамилия Имя Отчество]", "[ФИО должника]")
    t = t.replace("[год и место рождения]", "[год и место рождения должника]")
    t = t.replace("[паспортные данные]", "[паспортные данные должника]")
    t = t.replace("[ИНН]", "[ИНН должника]")
    t = t.replace("[СНИЛС]", "[СНИЛС должника]")
    t = t.replace("[адрес]", "[адрес должника]")
    t = t.replace("[размер]", "[госпошлина]")
    t = t.replace("[место]", "[место подписания]")
    t = t.replace("[дата]", "[дата составления]")

    # creditors table rows (5 rows x 2 cols)
    creditor_row = 0
    def creditor_cell(m):
        nonlocal creditor_row
        creditor_row += 1
        if creditor_row % 2 == 1:
            return "[кредитор " + str((creditor_row + 1) // 2) + "]"
        return "[сумма требования кредитора " + str(creditor_row // 2) + "]"

    # simpler: sequential replacement for table
    for i in range(1, 6):
        t = _replace_nth(t, r"\[вставить данные\]", f"[кредитор {i}]", 1)
        t = _replace_nth(t, r"\[вставить данные\]", f"[сумма требования кредитора {i}]", 1)
    t = _replace_nth(t, r"\[вставить данные\]", "[итого требования кредиторов]", 1)
    t = _replace_nth(t, r"\[вставить данные\]", "[среднемесячный доход должника]", 1)
    t = _replace_nth(t, r"\[вставить данные\]", "[источник дохода должника]", 1)

    fl_asset_pairs = [
        (r"недвижимое имущество</p></th><th><p>\[вставить данные\]", "недвижимое имущество</p></th><th><p>[стоимость недвижимого имущества]"),
        (r"транспортные средства\)</p></th><th><p>\[вставить данные\]", "транспортные средства)</p></th><th><p>[стоимость движимого имущества]"),
        (r"интеллектуальная собственность\)</p></th><th><p>\[вставить данные\]", "интеллектуальная собственность)</p></th><th><p>[стоимость нематериальных активов]"),
        (r"дебиторская задолженность</p></th><th><p>\[вставить данные\]", "дебиторская задолженность</p></th><th><p>[сумма дебиторской задолженности]"),
        (r"уставных капиталах или акции</p></th><th><p>\[вставить данные\]", "уставных капиталах или акции</p></th><th><p>[стоимость долей и акций]"),
        (r"<strong>ИТОГО:</strong></p></th><th><p><strong>\[вставить данные\]</strong>", "<strong>ИТОГО:</strong></p></th><th><p><strong>[итого стоимость имущества]</strong>"),
        (r"членов СРО \[вставить данные\]", f"членов СРО {SRO_LIST}"),
        (r"алиментные обязательства в размере \[вставить данные\]", "алиментные обязательства в размере [размер алиментных обязательств]"),
    ]
    for pat, repl in fl_asset_pairs:
        t = re.sub(pat, repl, t, flags=re.IGNORECASE)

    t = t.replace(
        "[состоит в браке | не состоит в браке | разведен]",
        "[семейное положение должника]",
    )
    t = t.replace(
        "[имеются несовершеннолетние дети | не имеется детей]",
        "[сведения о детях должника]",
    )
    t = re.sub(
        r"имеются \[не имеется\] текущие алиментные обязательства",
        "[наличие алиментных обязательств]",
        t,
        flags=re.IGNORECASE,
    )
    t = t.replace(
        "[имеются / не имеются] текущие алиментные обязательства",
        "[наличие алиментных обязательств]",
    )
    t = t.replace("[И.О. Фамилия]", "[ФИО подписанта]")
    return t


TEMPLATES: List[dict] = [
    {
        "id": "creditor_ul_general",
        "file": "creditor_ul_general.html",
        "title": "Заявление кредитора о банкротстве ЮЛ (общие правила)",
        "description": "Заявление конкурсного кредитора о признании юридического лица банкротом по общим правилам (наблюдение).",
        "priority": 100,
        "intent_keywords": [
            "заявление кредитора о банкротстве",
            "кредитор о банкротстве юл",
            "признании должника несостоятельным",
            "банкротство юридического лица",
            "общие правила банкротства",
        ],
        "src": "01. общие правила/01. шаблон заявление кредитора о банкротстве ЮЛ (общие правила).docx",
        "transform": transform_creditor_ul_general,
    },
    {
        "id": "debtor_ul_general",
        "file": "debtor_ul_general.html",
        "title": "Заявление должника ЮЛ о банкротстве (общие правила)",
        "description": "Заявление юридического лица о собственном банкротстве по общим правилам (наблюдение).",
        "priority": 95,
        "intent_keywords": [
            "заявление должника о банкротстве",
            "собственное банкротство юл",
            "должник юл банкротство",
            "наблюдение",
        ],
        "src": "01. общие правила/02. шаблон заявление должника ЮЛ о банкротстве (общие правила).docx",
        "transform": transform_debtor_ul_general,
    },
    {
        "id": "debtor_fl_general",
        "file": "debtor_fl_general.html",
        "title": "Заявление должника-гражданина о банкротстве",
        "description": "Заявление физического лица о собственном банкротстве (реализация имущества).",
        "priority": 90,
        "intent_keywords": [
            "банкротство гражданина",
            "должник гражданин",
            "личное банкротство",
            "заявление должника фл",
        ],
        "src": "01. общие правила/03. заявление должника ФЛ о банкротстве.docx",
        "transform": transform_debtor_fl,
    },
    {
        "id": "creditor_fl_general",
        "file": "creditor_fl_general.html",
        "title": "Заявление кредитора о банкротстве должника ФЛ",
        "description": "Заявление кредитора о признании гражданина банкротом (реализация имущества).",
        "priority": 85,
        "intent_keywords": [
            "банкротство физического лица",
            "кредитор банкротство гражданина",
            "должник фл банкротство",
        ],
        "src": "01. общие правила/04. заявление кредитора о банкротстве должника ФЛ.docx",
        "transform": transform_creditor_fl,
    },
    {
        "id": "creditor_ul_absent",
        "file": "creditor_ul_absent.html",
        "title": "Заявление кредитора о банкротстве отсутствующего должника ЮЛ",
        "description": "Упрощённая процедура: кредитор о банкротстве отсутствующего юридического лица.",
        "priority": 80,
        "intent_keywords": [
            "отсутствующий должник",
            "упрощенная процедура отсутствующего",
            "банкротство отсутствующего",
        ],
        "src": "02. упрощенные процедуры/01. шаблон заявление кредитора о банкротстве должника ЮЛ (упрощенная процедура отсутствующего должника).docx",
        "transform": transform_creditor_ul_absent,
    },
    {
        "id": "creditor_ul_liquidation",
        "file": "creditor_ul_liquidation.html",
        "title": "Заявление кредитора о банкротстве ликвидируемого должника ЮЛ",
        "description": "Упрощённая процедура: кредитор о банкротстве ликвидируемого юридического лица.",
        "priority": 75,
        "intent_keywords": [
            "ликвидируемый должник",
            "упрощенная процедура ликвидируемого",
            "предстоящая ликвидация",
        ],
        "src": "02. упрощенные процедуры/02. заявление кредитора о банкротстве должника ЮЛ (ликвидиуремый должник).docx",
        "transform": transform_creditor_ul_liquidation,
    },
    {
        "id": "debtor_ul_liquidation",
        "file": "debtor_ul_liquidation.html",
        "title": "Заявление должника ЮЛ о банкротстве (ликвидируемый должник)",
        "description": "Заявление ликвидируемого юридического лица о собственном банкротстве (конкурсное производство).",
        "priority": 70,
        "intent_keywords": [
            "банкротство ликвидируемого должника",
            "должник в ликвидации",
            "ликвидатор банкротство",
        ],
        "src": "02. упрощенные процедуры/03. заявление должника ЮЛ о банкротстве (ликвидируемый должник).docx",
        "transform": transform_debtor_ul_liquidation,
    },
]


def _audit_placeholders(text: str) -> List[str]:
    bad = []
    if "[вставить данные]" in text.lower():
        bad.append("[вставить данные]")
    for m in re.findall(r"\[(?:Наименование|адрес|размер|место)\]", text, re.I):
        bad.append(m)
    for marker in (
        "не всегда имеет место",
        "не имеется",
        "наименование СРО",
        "наименование СРО арбитражных управляющих",
        "наименования СРО арбитражных управляющих",
    ):
        if f"[{marker}]" in text:
            bad.append(f"[{marker}]")
    return sorted(set(bad))


def main() -> int:
    if not SRC.is_dir():
        print(f"Source folder not found: {SRC}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    manifest = []
    errors = 0
    for spec in TEMPLATES:
        src_path = SRC / spec["src"]
        if not src_path.is_file():
            print(f"MISSING: {src_path}", file=sys.stderr)
            errors += 1
            continue
        raw = _docx_html(src_path)
        html_out = spec["transform"](raw)
        leftover = _audit_placeholders(html_out)
        if leftover:
            print(f"WARN {spec['id']}: unresolved placeholders: {leftover}", file=sys.stderr)
            errors += 1
        out_path = OUT / spec["file"]
        out_path.write_text(html_out, encoding="utf-8")
        print(f"OK {spec['id']} -> {out_path.name} ({len(html_out)} chars)")
        manifest.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "description": spec["description"],
                "file": spec["file"],
                "priority": spec["priority"],
                "intent_keywords": spec["intent_keywords"],
            }
        )

    import json

    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"manifest: {len(manifest)} templates")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
