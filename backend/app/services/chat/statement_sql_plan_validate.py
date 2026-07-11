"""
Structural validation of StatementSqlPlan before SQL execution.

Rejects description filters that are query-language noise (not counterparty /
payment-purpose tokens). Does not hardcode merchant names.
"""
from __future__ import annotations

import re
from typing import Tuple

from app.services.chat.statement_sql_amount_semantics import is_direction_description_noise
from app.services.chat.statement_sql_models import StatementSqlPlan

# Structural / interrogative Russian tokens for bank-statement questions.
# These are language scaffolding, not domain entity dictionaries.
_DESCRIPTION_FILTER_STOPWORDS = frozenset(
    {
        "сколько",
        "какая",
        "какой",
        "какие",
        "какое",
        "что",
        "где",
        "когда",
        "покажи",
        "покажите",
        "найди",
        "найдите",
        "выведи",
        "выведите",
        "перечисли",
        "перечислите",
        "список",
        "операций",
        "операции",
        "операция",
        "операцию",
        "платежей",
        "платежи",
        "платеж",
        "платежа",
        "транзакций",
        "транзакции",
        "транзакция",
        "сумма",
        "суммы",
        "сумму",
        "итого",
        "всего",
        "общая",
        "общий",
        "больше",
        "меньше",
        "равно",
        "период",
        "периода",
        "периоде",
        "выписка",
        "выписке",
        "выписки",
        "выписку",
        "файл",
        "файле",
        "таблице",
        "таблица",
        "строк",
        "строки",
        "дата",
        "даты",
        "дату",
        "время",
        "месяц",
        "месяца",
        "год",
        "года",
        "день",
        "дня",
        "сегодня",
        "вчера",
        "подробнее",
        "детальнее",
        "пожалуйста",
        "нужно",
        "надо",
        "хочу",
        "дай",
        "дайте",
        "есть",
        "было",
        "были",
        "был",
        "была",
        "это",
        "эти",
        "этот",
        "эта",
        "там",
        "тут",
        "здесь",
        "только",
        "также",
        "ещё",
        "еще",
        "или",
        "и",
        "а",
        "но",
        "по",
        "за",
        "на",
        "от",
        "до",
        "из",
        "со",
        "во",
        "об",
        "про",
        "с",
        "в",
        "у",
        "к",
        "о",
        # Short function words (same class as above — not merchant names).
        # Needed once content tokens may be length 2 (matches _TOKEN_RE / bank codes).
        "ли",
        "да",
        "то",
        "же",
        "бы",
        "ни",
        "ну",
        "уж",
        "не",
        "ты",
        "мы",
        "вы",
        "он",
        "она",
        "они",
        "их",
        "им",
        "ей",
        "его",
        "её",
        "ее",
        "мне",
        "нас",
        "вас",
        "если",
        "как",
        "чем",
        "кто",
        "чей",
        "чья",
        "чьё",
        "чье",
    }
)

# Same floor as _TOKEN_RE ({2,}): payment texts use short Latin codes (VK, OK, MB).
# Length-1 tokens never appear; length-2 content is valid unless it is a stopword.
_MIN_CONTENT_TOKEN_LEN = 2

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9*]{2,}", re.UNICODE)
_PURE_NUMBER_RE = re.compile(r"^\d+([.,]\d+)?$")
_DATE_LIKE_RE = re.compile(r"^\d{1,2}[./]\d{1,2}([./]\d{2,4})?$")
_TIME_LIKE_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def is_description_filter_noise(value: str) -> bool:
    """True when value must not be used as description_contains."""
    raw = (value or "").strip()
    if not raw:
        return False
    if is_direction_description_noise(raw):
        return True

    tokens = [t.lower() for t in _TOKEN_RE.findall(raw)]
    if not tokens:
        return True

    content = [
        t
        for t in tokens
        if t not in _DESCRIPTION_FILTER_STOPWORDS
        and not _PURE_NUMBER_RE.match(t)
        and not _DATE_LIKE_RE.match(t)
        and not _TIME_LIKE_RE.match(t)
        and len(t) >= _MIN_CONTENT_TOKEN_LEN
    ]
    return not content


def extract_content_tokens(text: str) -> Tuple[str, ...]:
    """
    Content-bearing tokens from free text for value grounding probes.

    Drops structural stopwords / dates / pure numbers. Does not map synonyms
    or merchant dictionaries — only tokenizes and filters language noise.
    """
    raw = (text or "").strip()
    if not raw:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.findall(raw):
        token = match.strip()
        key = token.lower()
        if key in seen:
            continue
        if key in _DESCRIPTION_FILTER_STOPWORDS:
            continue
        if _PURE_NUMBER_RE.match(token):
            continue
        if _DATE_LIKE_RE.match(token) or _TIME_LIKE_RE.match(token):
            continue
        if len(token) < _MIN_CONTENT_TOKEN_LEN:
            continue
        seen.add(key)
        out.append(token)
    return tuple(out)


def sanitize_description_contains(plan: StatementSqlPlan) -> StatementSqlPlan:
    needle = (plan.description_contains or "").strip()
    if not needle:
        return plan
    if is_description_filter_noise(needle):
        return plan.model_copy(update={"description_contains": ""})
    return plan
