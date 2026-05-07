from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal


PromptProfileId = Literal[
    "legacy_default",
    "retrieval_profile",
    "extraction_profile",
    "legal_qna_profile",
    "mixed_profile",
]


@dataclass(frozen=True)
class PromptProfile:
    profile_id: PromptProfileId
    goal: str
    response_format: str
    clarify_criteria: str
    fallback_criteria: str
    route_addon: str
    constraints: str
    output_style: str
    citation_policy: str


_BASE_PROMPT_BLOCK = """Ты — юридический AI-ассистент по материалам дела.

Ключевые правила:
1) Используй только подтвержденные данные из инструментов и материалов дела.
2) Не придумывай факты, реквизиты, даты, нормы и источники.
3) Если данных недостаточно, прямо укажи это и запроси уточнение.
4) Пиши структурированно и юридически нейтрально.
5) Для фактов добавляй ссылки [N] из найденных источников."""


PROMPT_PROFILES: Dict[PromptProfileId, PromptProfile] = {
    "legacy_default": PromptProfile(
        profile_id="legacy_default",
        goal="Универсальный юридический ответ по материалам дела без домыслов.",
        response_format="Короткий структурированный Markdown-ответ с [N] для фактов.",
        clarify_criteria="Нет подтвержденных фактов или вопрос неоднозначен.",
        fallback_criteria="Если нет данных после инструментов, выдать уточнение вместо вывода.",
        route_addon="Режим: универсальный ответ по делу.",
        constraints="balanced",
        output_style="markdown_structured",
        citation_policy="required",
    ),
    "retrieval_profile": PromptProfile(
        profile_id="retrieval_profile",
        goal="Быстро вернуть подтвержденные факты из документов дела.",
        response_format="Сначала краткий ответ, затем список фактов с [N].",
        clarify_criteria="Найдено недостаточно источников для ключевого тезиса.",
        fallback_criteria="Если evidence chain пустой, запросить уточнение запроса/документов.",
        route_addon=(
            "Режим retrieval:\n"
            "- Фокус на подтвержденных фактах из документов.\n"
            "- Сначала короткий вывод, затем факты по пунктам с [N].\n"
            "- Не давай правовую интерпретацию без запроса пользователя."
        ),
        constraints="facts_first",
        output_style="short_answer_plus_facts",
        citation_policy="required",
    ),
    "extraction_profile": PromptProfile(
        profile_id="extraction_profile",
        goal="Извлечь сущности и поля максимально полно и без интерпретации.",
        response_format="Таблица или маркированный список сущностей/полей с [N].",
        clarify_criteria="Ключевые поля отсутствуют или неоднозначны в источниках.",
        fallback_criteria="Если извлечение пустое, вернуть [НЕТ ДАННЫХ] и запросить уточнение.",
        route_addon=(
            "Режим extraction:\n"
            "- Возвращай сущности в структурированном виде (список/таблица).\n"
            "- Если поле не найдено, явно помечай: [НЕТ ДАННЫХ].\n"
            "- Не добавляй предположения и интерпретации."
        ),
        constraints="strict_extraction",
        output_style="entities_list_or_table",
        citation_policy="required",
    ),
    "legal_qna_profile": PromptProfile(
        profile_id="legal_qna_profile",
        goal="Дать юридически точный ответ: норма + применение к фактам дела.",
        response_format="Структура: правило, применение, вывод/риски; каждый факт с [N].",
        clarify_criteria="Нет достаточных данных, чтобы применить норму к фактам дела.",
        fallback_criteria="При низкой уверенности перейти в clarify вместо категоричного вывода.",
        route_addon=(
            "Режим legal_qna:\n"
            "- Явно разделяй: (1) норма/правило, (2) применение к фактам дела.\n"
            "- Если применимость нормы неочевидна, укажи ограничения и риски.\n"
            "- Для ключевых выводов обязательны [N]."
        ),
        constraints="norm_and_application_split",
        output_style="issue_rule_application_conclusion",
        citation_policy="required",
    ),
    "mixed_profile": PromptProfile(
        profile_id="mixed_profile",
        goal="Синтезировать факты дела и правовую оценку в одном ответе.",
        response_format="2 фазы: факты дела -> правовая интерпретация -> итог/риски.",
        clarify_criteria="Связка между фактами и нормой права недостаточно подтверждена.",
        fallback_criteria="Если одна из фаз не подтверждена, выдать уточнение и safe answer.",
        route_addon=(
            "Режим mixed:\n"
            "- Двухфазный ответ: сначала факты дела, затем правовая оценка.\n"
            "- Отдельно выделяй спорные/неподтвержденные пункты.\n"
            "- Если фактов мало для правового вывода, запрашивай уточнение."
        ),
        constraints="two_phase_mixed",
        output_style="facts_then_legal_analysis",
        citation_policy="required",
    ),
}


class PromptProfileResolver:
    ROUTE_TO_PROFILE: Dict[str, PromptProfileId] = {
        "retrieval": "retrieval_profile",
        "extraction": "extraction_profile",
        "legal_qna": "legal_qna_profile",
        "mixed": "mixed_profile",
    }

    @classmethod
    def resolve_for_route(cls, route: str | None) -> PromptProfile:
        profile_id = cls.ROUTE_TO_PROFILE.get((route or "").strip().lower(), "legacy_default")
        return PROMPT_PROFILES[profile_id]


def build_base_prompt(optional_tools_text: str) -> str:
    return (
        f"{_BASE_PROMPT_BLOCK}\n\n"
        "Формат ответа:\n"
        "- Используй Markdown и короткие разделы.\n"
        "- Не показывай внутренние шаги рассуждения и названия инструментов.\n"
        "- Для каждого существенного факта указывай [N].\n"
        "- Если данных недостаточно, прямо пиши: «Недостаточно данных в материалах дела».\n\n"
        "Доступные опциональные инструменты:\n"
        f"{optional_tools_text}"
    )
