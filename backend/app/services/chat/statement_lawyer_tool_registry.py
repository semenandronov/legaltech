"""Tool name registry and workflow hints for the statement lawyer agent."""

STATEMENT_LAWYER_TOOL_NAMES = frozenset(
    {
        "statement_context",
        "resolve_entity",
        "transactions_query",
        "flow_profile",
        "legal_calendar",
        "risk_scan",
        "counterparty_dossier",
        "evidence_bundle",
    }
)

ANALYTICAL_LAWYER_TOOL_NAMES = frozenset(
    {
        "statement_context",
        "flow_profile",
        "legal_calendar",
        "risk_scan",
        "counterparty_dossier",
        "evidence_bundle",
    }
)

ENTITY_LAWYER_TOOL_NAMES = frozenset({"resolve_entity", "counterparty_dossier"})

QUERY_LAWYER_TOOL_NAMES = frozenset({"transactions_query"})

INSIGHT_TOOL_NAMES = ANALYTICAL_LAWYER_TOOL_NAMES

LAWYER_TOOL_WORKFLOWS = """
Цепочки (следуй им, не смешивай «обзор всей выписки» с вопросом про одного контрагента):

1) Открытый разбор / «что подозрительного»:
   statement_context → flow_profile → risk_scan → (если банкротство и есть дата) legal_calendar

2) Контрагент / «были ли операции с X»:
   resolve_entity → counterparty_dossier → при необходимости transactions_query (list) → evidence_bundle

3) Точный факт (сколько, топ-N, дата/время, сумма):
   resolve_entity (если в вопросе имя) → transactions_query

4) Периоды 61.2/61.3:
   legal_calendar → risk_scan в выбранном окне → counterparty_dossier по топам

5) Список под приложение / процесс:
   evidence_bundle (или transactions_query list + evidence_bundle)
"""

# Canonical spec: role of each tool (for docs / prompts).
LAWYER_TOOL_SPEC: tuple[tuple[str, str], ...] = (
    (
        "statement_context",
        "Контекст: файл, период, число операций в области (UI), примеры описаний.",
    ),
    (
        "resolve_entity",
        "Как в выписке пишется контрагент: grounded token, autocomplete, примеры строк.",
    ),
    (
        "transactions_query",
        "Скальpel: count/sum/list/find/top/group — любой точный факт по таблице.",
    ),
    (
        "flow_profile",
        "Картина денег: приток/отток/сальdo, топы, крупные операции, помесячная динамика.",
    ),
    (
        "legal_calendar",
        "Окна 61.2/61.3 от даты заявления + контраст оттока с периодом «до окна».",
    ),
    (
        "risk_scan",
        "Паттерны риска (эвристики) + структура по типам операций за период.",
    ),
    (
        "counterparty_dossier",
        "Досье контрагента: суммы, период, список ключевых операций.",
    ),
    (
        "evidence_bundle",
        "Пакет строк под процесс: дата, сумма, назначение, страница PDF.",
    ),
)
