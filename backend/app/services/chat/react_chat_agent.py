"""
ReAct Chat Agent v3.0 - Адаптивный агент для чата с Reflection и Citation Verification

Использует ReAct цикл (Reason + Act) для:
- Анализа вопроса пользователя
- Выбора нужных инструментов
- Итеративного получения информации
- Синтеза ответа

Ключевые особенности v3.0:
- 11+ универсальных инструментов (universal_tools)
- Сам решает, какие инструменты использовать
- Адаптируется под тип вопроса (обзорный, конкретный, аналитический)
- Поддерживает пользовательские переключатели (GARANT, deep_think, web_search)
- Интегрирован с ThinkingService для глубокого анализа
- **NEW: Reflection Pattern** - самопроверка ответов (снижает ошибки на 30%)
- **NEW: Citation Verification** - проверка цитат через ГАРАНТ
- **NEW: Confidence Scores** - оценка уверенности в ответе
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import asyncio
import logging
import json
import re

from app.services.chat.events import SSESerializer
from app.services.chat.universal_tools import get_universal_tools
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)

# Tool names used for stripping echoed tool calls from GigaChat responses
_TOOL_NAMES = [
    "search_in_documents", "get_document", "analyze_all_documents",
    "extract_structured_data", "compare_documents", "search_legal_db",
    "get_legal_document", "generate_document", "list_templates",
    "validate_with_playbook", "get_user_playbooks", "calculate",
    "get_current_date", "web_research",
]

# Pre-compiled regex patterns for cleaning GigaChat response artifacts
_TOOL_CALL_PATTERN = re.compile(
    r'^[ \t]*(?:' + '|'.join(re.escape(t) for t in _TOOL_NAMES) + r')\s*\(.*?\)\s*$',
    re.MULTILINE
)
# Code fences (```...```) that contain a tool function call — GigaChat reasoning leak
_CODE_BLOCK_TOOL_RE = re.compile(
    r'```[^\n]*\n(?:[^`]*?(?:' + '|'.join(re.escape(t) for t in _TOOL_NAMES) + r')[^`]*?)```',
    re.DOTALL
)
_RESULT_PREFIX_PATTERN = re.compile(
    r'^\s*\[Результат (?:анализа|поиска|извлечения)\]\s*:\s*',
    re.MULTILINE
)
_SEARCH_RESULTS_HEADER = re.compile(
    r'^\s*Результаты поиска:\s*$',
    re.MULTILINE
)
# Chain-of-thought section headers: [# Header], # Header, ## Header, ### Header, **Header**,
# numbered steps like "1. Выбор Подходящего Инструмента", "2. Применение Инструмента"
_SECTION_HEADER_RE = re.compile(
    r'^\s*(?:'
    r'\[#[^\]]+\]'  # [# ...] bracket format
    r'|#{1,3}\s*(?:Анализ вопроса|Выбор инструмента|Применение инструмента|Вызов инструмента|'
    r'Ответ|Шаг \d+|Итог|Размышление|Рассуждение|Мышление|Thinking|Analysis|Tool|'
    r'Источники|Заключение|Результаты?\s*поиска|Поиск[^\n]*|Ключевые\s+[^\n]*|'
    r'Обзор|Выводы?|Резюме|Итоги|Анализ[^\n]*|Ответ на вопрос|'
    r'Решение[^\n]*|Результат[^\n]*|Обработка результата[^\n]*|'
    r'Извлечение[^\n]*|Полученные\s+результаты)(?:[^\n]*)?'  # # / ## / ### headers
    r'|\*{2}(?:Анализ вопроса|Применение инструмента|Вызов инструмента|Выбор инструментов?|Размышление|'
    r'Источники|Заключение|Результаты?\s*поиска|Ключевые\s+[^\n]*|Выводы?|'
    r'Решение|Результат|Обработка результата|Шаг \d+|Ответ|Итог|Вывод|'
    r'Полный ответ|Анализ запроса|Анализ вопроса|Процесс поиска|Найдено)\*{2}[:\s]*'  # **bold** headers
    r'|\d+\.\s*(?:Выбор\s+(?:подходящего\s+)?инструмента|Применение\s+инструмента|'
    r'Полученные\s+результаты|Анализ\s+[^\n]*|Результаты?\s*[^\n]*|'
    r'Извлечение\s+[^\n]*|Шаг\s+\d+|Обработка результата|'
    r'Данный инструмент позволяет|Используем инструмент|После обработки инструментом)[^\n]*'  # numbered steps: "1. Выбор Инструмента"
    r')\s*$',
    re.MULTILINE | re.IGNORECASE
)
# Lines that look like agent internal reasoning (e.g. "Пользователь запрашивает ... из дела с ID ...")
_INTERNAL_REASONING_RE = re.compile(
    r'^\s*(?:Пользователь (?:запрашивает|спрашивает|просит|хочет)|'
    r'Мне нужно|Я должен|Необходимо(?:сть)?\s+(?:использовать|вызвать|найти|выполнить|проанализировать)|'
    r'Нужно (?:использовать|вызвать|найти)|'
    r'Для (?:ответа|этого|извлечения|анализа|поиска)[^\n]{0,20}(?:мне |)(?:нужно|необходимо|требуется)|'
    r'Давайте|Буду использовать|Вызываю|'
    r'Эти данные получены путем|'
    r'Данный инструмент позволяет|Используем инструмент|Применяем инструмент|'
    r'Инструмент (?:позволяет|вернул|возвращает|предоставляет)|После обработки инструментом|'
    r'После выполнения функции|Обработка результата|Получим релевантные)[^\n]*$',
    re.MULTILINE | re.IGNORECASE
)
# [Single-line bracket notes] like [Приветствие удалено из вопроса пользователя]
_BRACKET_NOTE_RE = re.compile(r'^\s*\[[^\]#\n]{8,}\]\s*$', re.MULTILINE)
# Sentences/phrases that mention internal tool function names in user-facing text
# e.g. "Подробный обзор можно найти в выводе функции `analyze_all_documents`."
_TOOL_NAME_MENTION_RE = re.compile(
    r'[^\n.!?]*(?:' + '|'.join(re.escape(t) for t in _TOOL_NAMES) + r')[^\n.!?]*[.!?]?\n?',
    re.IGNORECASE,
)
# GigaChat auto-citation artifacts like "Фрагмент 1 из documents" or "Фрагмент 2 из search_results"
_FRAGMENT_CITE_RE = re.compile(r'\s*Фрагмент\s+\d+\s+из\s+\S+\.?', re.IGNORECASE)
# "Источники:" / "Источники" section at the end of responses (GigaChat appends source lists)
_SOURCES_SECTION_RE = re.compile(
    r'\n\s*(?:#{1,3}\s*)?(?:\*{2})?(?:Источники|Sources)(?:\*{2})?:?\s*\n.*',
    re.DOTALL | re.IGNORECASE
)


# Задержка между «словами» при эффекте печати (секунды)
_STREAM_TYPING_DELAY_SEC = 0.032  # ~32 ms на слово — создаёт впечатление набора текста


async def _stream_text_with_typing_effect(
    text: str, delay_sec: float = _STREAM_TYPING_DELAY_SEC
) -> AsyncGenerator[str, None]:
    """
    Отдаёт текст по словам с небольшой задержкой, чтобы создавалось впечатление печати.
    """
    if not text:
        return
    parts = text.split(" ")
    for i, part in enumerate(parts):
        chunk = part + (" " if i < len(parts) - 1 else "")
        if chunk:
            yield SSESerializer.text_delta(chunk)
            await asyncio.sleep(delay_sec)


def _clean_response_text(text: str) -> str:
    """Strip GigaChat artifacts: echoed tool calls, [Результат анализа]: prefixes, etc."""
    # Strip code fences that contain tool function calls (GigaChat reasoning leak)
    cleaned = _CODE_BLOCK_TOOL_RE.sub('', text)
    cleaned = _TOOL_CALL_PATTERN.sub('', cleaned)
    cleaned = _RESULT_PREFIX_PATTERN.sub('', cleaned)
    cleaned = _SEARCH_RESULTS_HEADER.sub('', cleaned)
    # Remove chain-of-thought section header lines
    cleaned = _SECTION_HEADER_RE.sub('', cleaned)
    # Remove internal reasoning lines ("Пользователь запрашивает...", "Мне нужно...")
    cleaned = _INTERNAL_REASONING_RE.sub('', cleaned)
    # Remove [bracket note] lines (preprocessing notes like [Приветствие удалено...])
    cleaned = _BRACKET_NOTE_RE.sub('', cleaned)
    # Remove sentences that mention internal tool function names
    # (e.g. "Подробный обзор можно найти в выводе функции analyze_all_documents.")
    cleaned = _TOOL_NAME_MENTION_RE.sub('', cleaned)
    # Remove GigaChat auto-citation artifacts: "Фрагмент N из documents" etc.
    cleaned = _FRAGMENT_CITE_RE.sub('', cleaned)
    # Remove "Источники:" trailing section (GigaChat appends its own source list)
    cleaned = _SOURCES_SECTION_RE.sub('', cleaned)
    # Remove "Улучшенный ответ:" prefix from reflection
    cleaned = re.sub(r'^\s*Улучшенный ответ:\s*', '', cleaned, flags=re.MULTILINE)
    # Remove lines that are ONLY "N." or "N. " (empty numbered list items left after stripping)
    cleaned = re.sub(r'^\s*\d+\.\s*$', '', cleaned, flags=re.MULTILINE)
    # Collapse excessive blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


_SOURCES_LINE_RE = re.compile(
    r'^\s*(?:#{1,3}\s*)?(?:\*{2})?(?:Источники|Sources)(?:\*{2})?:?\s*$',
    re.IGNORECASE
)


def _filter_section_headers_streaming(token: str, line_buf: str, in_sources_section: bool = False) -> tuple:
    """
    Buffer tokens line-by-line and filter out [# ...] section header lines during streaming.
    Returns (text_to_emit, remaining_line_buf, in_sources_section).
    """
    combined = line_buf + token
    parts = combined.split('\n')
    emit_parts = []
    # All parts except the last are complete lines (they ended with \n)
    for part in parts[:-1]:
        # Once we hit "Источники:" section, suppress everything after it
        if _SOURCES_LINE_RE.match(part):
            in_sources_section = True
            continue
        if in_sources_section:
            continue
        if _SECTION_HEADER_RE.match(part) or _BRACKET_NOTE_RE.match(part):
            continue
        # Suppress internal reasoning lines (agent thinking leaked into output)
        if _INTERNAL_REASONING_RE.match(part):
            continue
        # Suppress lines that mention internal tool names (GigaChat reasoning leakage)
        if _TOOL_NAME_MENTION_RE.search(part):
            continue
        # Strip GigaChat "Фрагмент N из ..." inline citations from the line
        cleaned_part = _FRAGMENT_CITE_RE.sub('', part)
        emit_parts.append(cleaned_part + '\n')
    # Last part is an incomplete line — buffer it
    return ''.join(emit_parts), parts[-1], in_sources_section


class ReActChatAgent:
    """
    Адаптивный агент для чата v2.0, использующий ReAct цикл.
    
    Сам анализирует вопрос и решает:
    - Какие инструменты вызвать
    - Сколько документов нужно (k=5 или k=100)
    - Нужен ли Map-Reduce для обзора всех документов
    - Нужен ли поиск в ГАРАНТ
    """
    
    # Системный промпт для агента
    SYSTEM_PROMPT = """Ты - юридический AI-ассистент высшего уровня, который помогает анализировать документы дела и отвечать на вопросы.

ТВОЯ ЗАДАЧА: Понять вопрос пользователя и ВЫБРАТЬ ПРАВИЛЬНЫЕ ИНСТРУМЕНТЫ для ответа.

═══════════════════════════════════════════════════════════════════════════════
                         ДОСТУПНЫЕ ИНСТРУМЕНТЫ
═══════════════════════════════════════════════════════════════════════════════

📁 РАБОТА С ДОКУМЕНТАМИ:

1. **search_in_documents(query, k)** - Поиск по документам дела
   - Используй для конкретных вопросов ("какая сумма в договоре?", "что сказано о сроках?")
   - k=10-20 для простых вопросов, k=30-50 для сложных

2. **get_document(filename)** - Получить полный текст документа
   - Используй когда нужен весь документ ("покажи договор", "открой иск")

3. **analyze_all_documents(question, task_type)** - Глубокий анализ ВСЕХ документов (Map-Reduce)
   - ВАЖНО: Используй когда пользователь спрашивает:
     * "О чём все эти документы?"
     * "Расскажи о деле"
     * "Дай общий обзор"
   - task_type: "answer", "summarize", "extract"

4. **extract_structured_data(entity_types)** - Извлечь сущности
   - Используй для "какие даты?", "какие суммы?", "кто участники?"
   - entity_types: "dates,amounts,persons,organizations"

5. **compare_documents(doc1_name, doc2_name)** - Сравнить два документа
   - Используй для поиска противоречий и различий

═══════════════════════════════════════════════════════════════════════════════

📝 СОЗДАНИЕ ДОКУМЕНТОВ:

6. **generate_document(doc_type, variables)** - Создать черновик документа
   - doc_type: contract, claim, pretension, letter, memo, power_of_attorney
   - variables: "истец=ООО Ромашка; сумма=100000"

7. **list_templates()** - Показать доступные шаблоны документов

═══════════════════════════════════════════════════════════════════════════════

✅ PLAYBOOK (проверка по правилам):

8. **validate_with_playbook(document_name, playbook_name)** - Проверить документ
   - Используй когда просят проверить документ на соответствие

9. **get_user_playbooks()** - Список доступных Playbooks

═══════════════════════════════════════════════════════════════════════════════

🧮 ВСПОМОГАТЕЛЬНЫЕ:

10. **calculate(expression)** - Юридические расчёты
    - Проценты: "percent(100000, 10)"
    - Пени по ставке ЦБ: "penalty_cb(100000, 30)"
    - Дни между датами: "days_between(01.01.2024, 31.01.2024)"

11. **get_current_date()** - Текущая дата

{optional_tools}

═══════════════════════════════════════════════════════════════════════════════
                              ПРАВИЛА РАБОТЫ
═══════════════════════════════════════════════════════════════════════════════

1. На приветствия и светские реплики ("привет", "здравствуйте", "как дела?") отвечай коротко и дружелюбно — без использования инструментов. Например: "Здравствуйте! Чем могу помочь?"
2. ВСЕГДА используй инструменты для получения информации по документам
3. НЕ придумывай информацию - только то, что нашёл в документах
4. Для обзорных вопросов ("о чём дело?", "расскажи о деле") используй analyze_all_documents
5. Для вопросов "все X из ВСЕХ документов" ("все фамилии", "все даты", "все суммы", "все участники дела") — используй analyze_all_documents(task_type="extract"). ТОЛЬКО этот инструмент гарантирует 100% охват всех документов. search_in_documents и extract_structured_data просматривают только часть документов и могут пропустить данные.
6. Для конкретных вопросов по содержанию ("какая сумма в договоре?", "что написано о сроках?") используй search_in_documents
7. Можешь вызывать несколько инструментов для полного ответа
8. КРИТИЧЕСКИ ВАЖНО — СНОСКИ ПОСЛЕ КАЖДОГО ПУНКТА:
   - КАЖДЫЙ пункт списка, КАЖДОЕ предложение с фактом ОБЯЗАНЫ заканчиваться [N]
   - НЕТ НИ ОДНОГО исключения. Если у "Иванов" источник [1] — пиши "Иванов [1]"
   - Номера соответствуют номерам источников из результатов инструментов
   - Каждый номер в ОТДЕЛЬНЫХ скобках: [1][2] — НЕ [1, 2] или [1,2]
   - НЕ пиши "(из файла.pdf)" текстом — только [N], система сама покажет документ
9. Если информация не найдена - честно скажи об этом

═══════════════════════════════════════════════════════════════════════════════
                              ФОРМАТ ОТВЕТА
═══════════════════════════════════════════════════════════════════════════════

- Используй Markdown для форматирования
- Для списков используй маркеры
- Для важного используй **жирный** текст
- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО включать в ответ заголовки разделов, нумерованные шаги или секции. Запрещены: «Анализ вопроса», «Применение инструмента», «Вызов инструмента», «Выбор инструмента», «Заключение», «Результаты поиска», «Полученные результаты», «Источники», «Извлечение», «Шаг N», «Итог», «Обзор», «Выводы». Запрещены конструкции вида "1. Выбор...", "2. Применение...", "3. Результаты...". НЕ используй # ## ### ** или нумерацию для таких заголовков. Пиши ответ пользователю СРАЗУ — без структуры «анализ→инструмент→результат→заключение». Пользователь НЕ должен видеть внутренний процесс мышления.
- НЕ упоминай названия инструментов/функций (analyze_all_documents, search_in_documents и т.д.) в тексте ответа пользователю. Пользователь не видит и не должен видеть эти названия.
- НЕ добавляй раздел "Источники:", "Сноски:" или отдельный список вида "[1] Описание источника" в конце ответа. Маркеры [N] используй ТОЛЬКО встроенно сразу после каждого факта, НИКОГДА не выносить в отдельный список или строку в конце.
- НЕ пиши "Фрагмент N из ..." — это внутренний формат системы, недопустимый в ответе пользователю. Для ссылки на источник используй только [N].

ПРИМЕР ПРАВИЛЬНОГО ОТВЕТА на вопрос "какие фамилии в документах?":
• Иванов Иван Иванович [1]
• Петров Пётр Петрович [2][3]
• Сидоров Сидор Сидорович [4]

ПРИМЕР НЕПРАВИЛЬНОГО ОТВЕТА (так делать ЗАПРЕЩЕНО):
• Иванов Иван Иванович
• Петров Пётр Петрович (из договора.pdf)
• Сидоров
[1] [2] [3] [4]"""
    
    def __init__(
        self,
        case_id: str,
        db: Session,
        rag_service: RAGService,
        current_user: Optional[User] = None,
        # Пользовательские переключатели
        legal_research: bool = False,
        deep_think: bool = False,
        web_search: bool = False,
        chat_history: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        # NEW v3.0: Reflection и Citation Verification
        enable_reflection: bool = True,
        enable_citation_verification: bool = True,
        # Прикреплённые файлы (для фильтрации RAG)
        attached_file_ids: Optional[List[str]] = None
    ):
        """
        Инициализация агента
        
        Args:
            case_id: ID дела
            db: SQLAlchemy сессия
            rag_service: RAG сервис
            current_user: Текущий пользователь
            legal_research: Включить поиск в GARANT
            deep_think: Включить глубокое мышление (GigaChat Pro)
            web_search: Включить веб-поиск
            chat_history: История чата
            session_id: ID сессии чата
            enable_reflection: Включить самопроверку ответов (Reflection Pattern)
            enable_citation_verification: Включить проверку цитат
        """
        self.case_id = case_id
        self.db = db
        self.rag_service = rag_service
        self.current_user = current_user
        self.legal_research = legal_research
        self.deep_think = deep_think
        self.web_search = web_search
        self.chat_history = chat_history or []
        self.session_id = session_id
        
        # NEW v3.0: Reflection и Citation Verification
        self.enable_reflection = enable_reflection
        self.enable_citation_verification = enable_citation_verification and legal_research
        
        # Получаем user_id для playbooks
        user_id = str(current_user.id) if current_user else None
        
        # Инициализируем инструменты из universal_tools
        # Если включён deep_think, передаём флаг use_pro_llm=True, чтобы
        # внутренние LLM-вызовы (analyze_all_documents, search_in_documents и др.)
        # также использовали GigaChat-Pro.
        self.tools = get_universal_tools(
            db=db,
            rag_service=rag_service,
            case_id=case_id,
            user_id=user_id,
            legal_research=legal_research,
            web_search=web_search,
            attached_file_ids=attached_file_ids,
            use_pro_llm=deep_think,
        )
        
        # Создаём LLM и агента
        self.llm = self._create_llm()
        self.agent = self._create_agent()
        
        # NEW v3.0: Инициализируем сервисы проверки
        self._reflection_service = None
        self._citation_verifier = None
        
        logger.info(
            f"[ReActChatAgent] Initialized for case {case_id} "
            f"(tools={len(self.tools)}, deep_think={deep_think}, "
            f"legal_research={legal_research}, web_search={web_search}, "
            f"reflection={enable_reflection}, citation_verification={self.enable_citation_verification})"
        )
    
    def _create_llm(self):
        """Создать LLM в зависимости от режима"""
        from app.services.llm_factory import create_legal_llm
        from app.config import config
        
        if self.deep_think:
            # Используем GigaChat Pro для глубокого анализа
            model = config.GIGACHAT_PRO_MODEL or "GigaChat-Pro"
            logger.info(f"[ReActChatAgent] Using deep_think mode with {model}")
            return create_legal_llm(model=model, temperature=0.2)
        else:
            # Стандартная модель
            return create_legal_llm(temperature=0.1)
    
    def _get_reflection_service(self):
        """Lazy initialization of ReflectionService"""
        if self._reflection_service is None and self.enable_reflection:
            try:
                from app.services.reflection_service import get_reflection_service
                self._reflection_service = get_reflection_service(deep_think=self.deep_think)
            except ImportError as e:
                logger.warning(f"[ReActChatAgent] ReflectionService not available: {e}")
        return self._reflection_service
    
    def _get_citation_verifier(self):
        """Lazy initialization of CitationVerifier"""
        if self._citation_verifier is None and self.enable_citation_verification:
            try:
                from app.services.citation_verifier import get_citation_verifier
                self._citation_verifier = get_citation_verifier(garant_enabled=self.legal_research)
            except ImportError as e:
                logger.warning(f"[ReActChatAgent] CitationVerifier not available: {e}")
        return self._citation_verifier
    
    def _create_agent(self):
        """Создать ReAct агента с инструментами"""
        try:
            # Пробуем создать агента через langgraph
            try:
                from langgraph.prebuilt import create_react_agent
                
                agent = create_react_agent(
                    self.llm,
                    self.tools
                )
                logger.info("[ReActChatAgent] Created agent via langgraph.prebuilt.create_react_agent")
                return agent
                
            except (ImportError, TypeError) as e:
                logger.warning(f"[ReActChatAgent] LangGraph create_react_agent failed: {e}, trying fallback")
                
                # Fallback на agent_factory
                try:
                    from app.services.langchain_agents.agent_factory import create_legal_agent
                    
                    system_prompt = self._build_system_prompt()
                    agent = create_legal_agent(
                        llm=self.llm,
                        tools=self.tools,
                        system_prompt=system_prompt
                    )
                    logger.info("[ReActChatAgent] Created agent via agent_factory")
                    return agent
                except Exception as factory_error:
                    logger.warning(f"[ReActChatAgent] agent_factory failed: {factory_error}")
                    return None
                
        except Exception as e:
            logger.error(f"[ReActChatAgent] Failed to create agent: {e}", exc_info=True)
            return None
    
    def _build_system_prompt(self) -> str:
        """Построить системный промпт с учётом включённых инструментов"""
        optional_tools_text = ""
        
        if self.legal_research:
            optional_tools_text += """
═══════════════════════════════════════════════════════════════════════════════

⚖️ ПРАВОВАЯ БАЗА (pravo.gov.ru):

12. **search_legal_db(query, max_results)** - Поиск НПА на официальном портале pravo.gov.ru
    - Используй для вопросов о законах, постановлениях, приказах, судебной практике
    - Пример: search_legal_db("несостоятельность банкротство требования кредиторов", 5)

13. **get_legal_document(eo_number)** - Полный текст НПА (из PDF)
    - Используй после search_legal_db для загрузки текста нужного НПА
    - eo_number — номер электронного опубликования из результатов search_legal_db
    - Пример: get_legal_document("2600202104190001")
"""
        
        if self.web_search:
            optional_tools_text += """
═══════════════════════════════════════════════════════════════════════════════

🌐 ВЕБ-ПОИСК:

14. **web_research_tool(query)** - Поиск в интернете
    - Используй для актуальной информации, которой нет в документах
"""
        
        if not optional_tools_text:
            optional_tools_text = "\n(Дополнительные инструменты не включены)"
        
        return self.SYSTEM_PROMPT.format(optional_tools=optional_tools_text)
    
    async def handle(
        self,
        question: str,
        stream: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Обработать вопрос пользователя
        
        Args:
            question: Вопрос пользователя
            stream: Стримить ответ (по умолчанию True)
            
        Yields:
            SSE события
        """
        try:
            logger.info(f"[ReActChatAgent] Processing: {question[:100]}...")
            
            # Определяем количество шагов
            total_steps = 2  # agent + generate
            if self.deep_think:
                total_steps = 3  # thinking + agent + generate
            
            current_step = 0
            
            # Если включен deep_think, сначала запускаем thinking
            if self.deep_think:
                current_step += 1
                yield SSESerializer.reasoning(
                    phase="thinking",
                    step=current_step,
                    total_steps=total_steps,
                    content="Запускаю глубокий анализ вопроса..."
                )
                
                async for event in self._run_thinking(question):
                    yield event
            
            # Запускаем агента
            current_step += 1
            yield SSESerializer.reasoning(
                phase="agent",
                step=current_step,
                total_steps=total_steps,
                content="Анализирую вопрос и выбираю инструменты..."
            )
            
            async for event in self._run_agent(question):
                yield event
                
        except Exception as e:
            logger.error(f"[ReActChatAgent] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка обработки запроса: {str(e)}")
    
    async def _run_thinking(self, question: str) -> AsyncGenerator[str, None]:
        """Запустить thinking (пошаговое мышление)"""
        try:
            from app.services.thinking_service import get_thinking_service
            
            thinking_service = get_thinking_service(deep_think=True)
            logger.info("[ReActChatAgent] Starting deep thinking process")
            
            # Получаем контекст для thinking
            context = ""
            try:
                docs = self.rag_service.retrieve_context(
                    case_id=self.case_id,
                    query=question,
                    k=15,
                    db=self.db
                )
                if docs:
                    context = self.rag_service.format_sources_for_prompt(docs, max_context_chars=5000)
            except Exception as e:
                logger.warning(f"[ReActChatAgent] Failed to get context for thinking: {e}")
            
            async for step in thinking_service.think(
                question=question,
                context=context,
                stream_steps=True
            ):
                yield SSESerializer.reasoning(
                    phase=step.phase.value,
                    step=step.step_number,
                    total_steps=step.total_steps,
                    content=step.content
                )
                
        except Exception as e:
            logger.warning(f"[ReActChatAgent] Thinking error: {e}, continuing without thinking")
    
    async def _run_reflection(
        self,
        question: str,
        answer: str,
        context: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Запустить Reflection (самопроверку ответа)
        
        Yields:
            SSE события с результатами рефлексии
        """
        reflection_service = self._get_reflection_service()
        if not reflection_service:
            return
        
        try:
            logger.info("[ReActChatAgent] Starting reflection on answer")
            
            yield SSESerializer.reasoning(
                phase="reflection",
                step=1,
                total_steps=2,
                content="Проверяю качество ответа..."
            )
            
            # Проводим рефлексию
            result = await reflection_service.reflect(
                question=question,
                answer=answer,
                context=context,
                auto_improve=True
            )
            
            # Отправляем результат рефлексии
            yield SSESerializer.agent_step(
                step_type="reflection_result",
                content=json.dumps({
                    "is_valid": result.is_valid,
                    "confidence_score": result.confidence_score,
                    "confidence_level": result._get_confidence_level(),
                    "issues_count": len(result.issues),
                    "has_improvement": result.improved_answer is not None
                }, ensure_ascii=False)
            )
            
            # Если есть проблемы высокой серьёзности
            high_severity_issues = [i for i in result.issues if i.severity == "high"]
            if high_severity_issues:
                yield SSESerializer.reasoning(
                    phase="reflection",
                    step=2,
                    total_steps=2,
                    content=f"Обнаружено {len(high_severity_issues)} важных проблем, улучшаю ответ..."
                )
            
            # Если есть улучшенный ответ с реальным содержимым, добавляем его без заголовка
            if (result.improved_answer and not result.is_valid
                    and result.improved_answer.strip()
                    and len(result.improved_answer.strip()) > 50
                    and result.confidence_score < 0.6):
                cleaned_improvement = _clean_response_text(result.improved_answer)
                if cleaned_improvement and len(cleaned_improvement) > 50:
                    logger.info(f"[ReActChatAgent] Reflection improved answer (confidence: {result.confidence_score:.2f})")
                    yield SSESerializer.text_delta("\n\n" + cleaned_improvement)
            
            # Отправляем confidence score
            yield SSESerializer.agent_step(
                step_type="confidence_score",
                content=json.dumps({
                    "score": result.confidence_score,
                    "level": result._get_confidence_level()
                })
            )
            
            logger.info(
                f"[ReActChatAgent] Reflection complete: "
                f"valid={result.is_valid}, confidence={result.confidence_score:.2f}"
            )
            
        except Exception as e:
            logger.warning(f"[ReActChatAgent] Reflection error: {e}")
    
    async def _run_citation_verification(
        self,
        answer: str
    ) -> AsyncGenerator[str, None]:
        """
        Запустить проверку цитат в ответе
        
        Yields:
            SSE события с результатами проверки
        """
        verifier = self._get_citation_verifier()
        if not verifier:
            return
        
        try:
            logger.info("[ReActChatAgent] Starting citation verification")
            
            yield SSESerializer.reasoning(
                phase="citation_verification",
                step=1,
                total_steps=1,
                content="Проверяю цитаты через ГАРАНТ..."
            )
            
            # Проверяем цитаты
            result = await verifier.verify_answer(answer)
            
            if result.total_citations == 0:
                logger.info("[ReActChatAgent] No citations found in answer")
                return
            
            # Отправляем результат проверки
            yield SSESerializer.agent_step(
                step_type="citation_verification",
                content=json.dumps({
                    "total_citations": result.total_citations,
                    "verified_count": result.verified_count,
                    "not_found_count": result.not_found_count,
                    "overall_confidence": result.overall_confidence,
                    "citations": [
                        {
                            "text": c.normalized,
                            "status": c.status.value,
                            "url": c.garant_url
                        }
                        for c in result.citations[:5]  # Первые 5 цитат
                    ]
                }, ensure_ascii=False)
            )
            
            # Если есть непроверенные цитаты, предупреждаем
            if result.not_found_count > 0:
                warning = f"\n\n⚠️ *{result.not_found_count} из {result.total_citations} цитат не подтверждены в ГАРАНТ*"
                yield SSESerializer.text_delta(warning)
            
            logger.info(
                f"[ReActChatAgent] Citation verification complete: "
                f"total={result.total_citations}, verified={result.verified_count}, "
                f"not_found={result.not_found_count}"
            )
            
        except Exception as e:
            logger.warning(f"[ReActChatAgent] Citation verification error: {e}")

    async def _stream_agent_tokens(
        self,
        input_data: dict,
        config: dict,
        tool_calls_made: list,
    ) -> AsyncGenerator[tuple, None]:
        """
        Стриминг по токенам через astream_events (ответ по слову/токену).
        Yields: (sse_string, delta_text) для накопления response_text наверх.
        """
        seen_tool_names = set()
        async for event in self.agent.astream_events(
            input_data, config=config, version="v2"
        ):
            event_type = event.get("event") or event.get("event_type")
            data = event.get("data") or {}

            # Токены от LLM — стримим по кусочкам
            if event_type in ("on_chat_model_stream", "on_llm_stream"):
                chunk = data.get("chunk")
                if not chunk:
                    continue
                content = getattr(chunk, "content", None)
                if content is None and isinstance(chunk, str):
                    content = chunk
                elif content is not None and not isinstance(content, str):
                    content = str(content) if content else ""
                if content:
                    yield (SSESerializer.text_delta(content), content)

            # Вызов инструмента — одно событие на инструмент
            elif event_type == "on_tool_start":
                name = event.get("name") or data.get("name") or "unknown"
                if name not in seen_tool_names:
                    seen_tool_names.add(name)
                    tool_calls_made.append(name)
                    logger.info("[ReActChatAgent] Tool call: %s", name)
                    yield (
                        SSESerializer.reasoning(
                            phase="tool_call",
                            step=len(tool_calls_made),
                            total_steps=0,
                            content=f"Использую инструмент: {name}",
                        ),
                        "",
                    )

    async def _stream_agent_messages(
        self, input_data: dict, tool_calls_made: list
    ) -> AsyncGenerator[tuple, None]:
        """
        Стриминг по сообщениям (целыми кусками). Fallback при отсутствии astream_events.
        Yields: (sse_string, delta_text).
        """
        response_text = ""
        async for event in self.agent.astream(input_data):
            if not isinstance(event, dict):
                continue
            if "messages" in event:
                for msg in event["messages"]:
                    if hasattr(msg, "content") and msg.content:
                        delta = msg.content
                        if delta and delta != response_text:
                            if response_text and delta.startswith(response_text):
                                delta = delta[len(response_text) :]
                            elif response_text:
                                delta = msg.content
                            if delta:
                                yield (SSESerializer.text_delta(delta), delta)
                                response_text += delta
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            name = tc.get("name", "unknown")
                            tool_calls_made.append(name)
                            logger.info("[ReActChatAgent] Tool call: %s", name)
                            yield (
                                SSESerializer.reasoning(
                                    phase="tool_call",
                                    step=len(tool_calls_made),
                                    total_steps=0,
                                    content=f"Использую инструмент: {name}",
                                ),
                                "",
                            )
            elif "output" in event:
                output = event["output"]
                if output and output not in response_text:
                    delta = output[len(response_text) :] if response_text and output.startswith(response_text) else output
                    if delta:
                        yield (SSESerializer.text_delta(delta), delta)
                        response_text += delta
    
    _GREETING_PHRASES = frozenset([
        "привет", "здравствуйте", "здравствуй", "добрый день", "добрый вечер",
        "доброе утро", "добрый", "хай", "hi", "hello", "салют", "как дела",
        "как дела?", "как вы?", "как ты?", "приветствую",
    ])

    def _is_greeting(self, question: str) -> bool:
        """Проверяет, является ли вопрос приветствием/светской репликой."""
        q = question.strip().lower().rstrip("!?,.")
        return q in self._GREETING_PHRASES or len(q) <= 20 and any(
            q.startswith(p) for p in self._GREETING_PHRASES
        )

    async def _run_agent(self, question: str) -> AsyncGenerator[str, None]:
        """Запустить ReAct агента с Reflection и Citation Verification"""
        try:
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

            # Shortcut: greetings don't need tools — reply directly
            if self._is_greeting(question):
                logger.info("[ReActChatAgent] Greeting detected, skipping agent")
                async for chunk in _stream_text_with_typing_effect(
                    "Здравствуйте! Чем могу помочь?"
                ):
                    yield chunk
                return

            # Формируем системный промпт
            system_prompt = self._build_system_prompt()
            
            # Формируем входные данные
            messages = [SystemMessage(content=system_prompt)]
            
            # Добавляем историю чата (последние 10 сообщений)
            for msg in self.chat_history[-10:]:
                if msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg.get("content", "")))
            
            # Добавляем текущий вопрос с контекстом
            enhanced_question = f"""Вопрос пользователя: {question}

ID дела: {self.case_id}

Проанализируй вопрос и используй подходящие инструменты для ответа.
- Если вопрос об обзоре всех документов — используй analyze_all_documents
- Если конкретный вопрос — используй search_in_documents
- Если нужна статья закона — используй search_garant (если доступен)"""
            
            messages.append(HumanMessage(content=enhanced_question))
            
            # Запускаем агента
            input_data = {"messages": messages}
            
            # Проверяем, создан ли агент
            if self.agent is None:
                logger.warning("[ReActChatAgent] Agent not created, using fallback")
                fallback_response = await self._fallback_response(question)
                yield SSESerializer.text_delta(fallback_response)
                
                # Всё равно запускаем проверки на fallback ответ
                if self.enable_reflection or self.enable_citation_verification:
                    async for event in self._post_process_answer(question, fallback_response):
                        yield event
                return
            
            # Пробуем стриминг (сначала по токенам для качественного UX)
            try:
                response_text = ""
                tool_calls_made = []
                context_used = ""  # Сохраняем контекст для reflection
                # Flag: whether a tool already produced a synthesized answer and it was streamed.
                # Defined here (before if/elif/else) so it's always accessible in except blocks.
                direct_result_streamed = False

                # Token-level streaming via astream_events (v2)
                if hasattr(self.agent, 'astream_events'):
                    logger.info("[ReActChatAgent] Using astream_events for token-level streaming")
                    active_tool_calls = set()  # Track tool calls we've already emitted "running" for

                    # STRATEGY: Buffer ALL GigaChat tokens. Never stream them directly.
                    # The actual answer comes from _last_direct_result (set by tools).
                    # Buffer is only flushed at end of loop if no tool produced a direct result.
                    text_buffer = ""
                    has_tool_call_in_current_step = False

                    async for event in self.agent.astream_events(input_data, version="v2"):
                        kind = event.get("event", "")

                        # Token-by-token streaming from LLM
                        # STRATEGY: NEVER stream GigaChat's outer tokens directly.
                        # Only buffer them. The actual answer comes from _last_direct_result
                        # (set by tools). If no tool was called, we flush the buffer at the end.
                        if kind == "on_chat_model_stream":
                            chunk = event.get("data", {}).get("chunk")
                            if chunk:
                                # Buffer text content (never stream GigaChat tokens directly)
                                token = getattr(chunk, 'content', '') or ''
                                if token:
                                    text_buffer += token

                                # Tool call chunks — emit "running" on first appearance
                                tool_call_chunks = getattr(chunk, 'tool_call_chunks', None)
                                if tool_call_chunks:
                                    for tc_chunk in tool_call_chunks:
                                        tc_name = tc_chunk.get('name', '')
                                        if tc_name and tc_name not in active_tool_calls:
                                            has_tool_call_in_current_step = True
                                            active_tool_calls.add(tc_name)
                                            tool_calls_made.append(tc_name)
                                            logger.info(f"[ReActChatAgent] Tool call: {tc_name}")
                                            tc_input = tc_chunk.get('args', '')
                                            if tc_input and not isinstance(tc_input, str):
                                                tc_input = json.dumps(tc_input, ensure_ascii=False)[:200]
                                            yield SSESerializer.tool_call(
                                                name=tc_name,
                                                status="running",
                                                input=tc_input if tc_input else None
                                            )

                        # LLM call ended
                        elif kind == "on_chat_model_end":
                            # GigaChat may not stream tool_call_chunks during on_chat_model_stream
                            # but still include tool_calls in the final output message.
                            # Detect this here so we don't accidentally leak pre-tool reasoning text.
                            end_output = event.get("data", {}).get("output")
                            if end_output and not has_tool_call_in_current_step:
                                end_tool_calls = (
                                    getattr(end_output, "tool_calls", None)
                                    or (getattr(end_output, "additional_kwargs", {}) or {}).get("tool_calls")
                                )
                                if end_tool_calls:
                                    has_tool_call_in_current_step = True

                            # If this LLM step had tool calls, discard buffered text (it's reasoning)
                            if has_tool_call_in_current_step:
                                if text_buffer:
                                    logger.info(
                                        f"[ReActChatAgent] Discarding pre-tool-call reasoning "
                                        f"({len(text_buffer)} chars)"
                                    )
                                text_buffer = ""
                            # Otherwise keep buffer — it will be flushed at end of loop
                            # (only if no direct result was streamed from a tool)

                            has_tool_call_in_current_step = False

                        # Tool execution completed
                        elif kind == "on_tool_end":
                            tool_name = event.get("name", "unknown")
                            output_data = event.get("data", {}).get("output", "")
                            from app.services.chat.universal_tools import get_last_direct_result as _gdr
                            logger.info(f"[ReActChatAgent] on_tool_end: tool={tool_name!r}, direct_result_streamed={direct_result_streamed}, last_direct_set={bool(_gdr())}")
                            output_preview = str(output_data)[:300] if output_data else ''
                            yield SSESerializer.tool_call(
                                name=tool_name,
                                status="completed",
                                output=output_preview
                            )
                            # If validate_with_playbook finished, emit rich playbook result card
                            if tool_name == "validate_with_playbook":
                                try:
                                    from app.services.chat.universal_tools import (
                                        get_last_playbook_check,
                                        clear_last_playbook_check,
                                    )
                                    check_data = get_last_playbook_check()
                                    if check_data:
                                        yield SSESerializer.playbook_check_result(check_data)
                                        clear_last_playbook_check()
                                        logger.info("[ReActChatAgent] Emitted playbook_check_result SSE event")
                                except Exception as pb_err:
                                    logger.warning(f"[ReActChatAgent] Failed to emit playbook result: {pb_err}")

                            # For any tool that stored a synthesized answer: stream it directly
                            # and skip GigaChat's outer synthesis (which drops [N] markers).
                            # We check _last_direct_result for ALL tools, not just a hardcoded list,
                            # because LangChain event names may differ from function names.
                            try:
                                from app.services.chat.universal_tools import (
                                    get_last_direct_result,
                                    clear_last_direct_result,
                                )
                                direct = get_last_direct_result()
                                if direct and not direct_result_streamed:
                                    cleaned = _clean_response_text(direct)
                                    # Use original `direct` as fallback if cleaning stripped everything
                                    text_to_stream = cleaned if cleaned else direct.strip()
                                    if text_to_stream:
                                        yield SSESerializer.text_delta(text_to_stream)
                                        response_text += text_to_stream
                                        direct_result_streamed = True
                                        # Lock _used_sources so subsequent tools don't overwrite
                                        # the sources that correspond to already-streamed [N] markers.
                                        from app.services.chat.universal_tools import lock_used_sources
                                        lock_used_sources()
                                        logger.info(f"[ReActChatAgent] Direct-streamed {tool_name} result ({len(text_to_stream)} chars)")
                                clear_last_direct_result()
                            except Exception as dr_err:
                                logger.warning(f"[ReActChatAgent] Failed to direct-stream result: {dr_err}")

                    # Flush any remaining buffered text (only if no direct result
                    # was already streamed from a tool)
                    if text_buffer and not direct_result_streamed:
                        # Detect GigaChat hallucination: it imagines calling a tool
                        # instead of actually calling it, producing fabricated [N] citations.
                        # Signs: text_buffer contains reasoning headers but no tool was called.
                        _hallucination_indicators = (
                            _SECTION_HEADER_RE.search(text_buffer)
                            or _INTERNAL_REASONING_RE.search(text_buffer)
                        )
                        strip_citations = False
                        if _hallucination_indicators and not tool_calls_made:
                            # GigaChat hallucinated a tool call — discard the hallucinated text
                            # and run search_in_documents directly so the user gets real citations.
                            logger.warning(
                                f"[ReActChatAgent] Detected hallucinated tool response "
                                f"({len(text_buffer)} chars, no real tool calls) — running fallback search"
                            )
                            strip_citations = True
                            # Find search_in_documents tool and call it directly
                            search_tool = next(
                                (t for t in self.tools if getattr(t, 'name', '') == 'search_in_documents'),
                                None
                            )
                            # Pick the best fallback tool:
                            # - analyze_all_documents for broad/overview questions ("какие сроки", "расскажи о деле")
                            # - search_in_documents for specific targeted questions
                            _overview_kw = ('какие', 'все', 'перечисли', 'расскажи', 'обзор', 'итог', 'суть', 'краткое')
                            _q_lower = question.lower()
                            _use_analyze = any(kw in _q_lower for kw in _overview_kw)
                            fallback_tool = None
                            if _use_analyze:
                                fallback_tool = next(
                                    (t for t in self.tools if getattr(t, 'name', '') == 'analyze_all_documents'),
                                    None
                                )
                            if fallback_tool is None:
                                fallback_tool = search_tool  # search_in_documents as default

                            if fallback_tool:
                                try:
                                    from app.services.chat.universal_tools import (
                                        get_last_direct_result as _fb_gdr,
                                        clear_last_direct_result as _fb_clr,
                                        get_used_sources as _fb_sources,
                                    )
                                    if _use_analyze and getattr(fallback_tool, 'name', '') == 'analyze_all_documents':
                                        await fallback_tool.ainvoke(
                                            {"question": question, "task_type": "analyze"}
                                        )
                                    else:
                                        await fallback_tool.ainvoke(
                                            {"query": question, "k": 8}
                                        )
                                    direct = _fb_gdr()
                                    if direct:
                                        cleaned_direct = _clean_response_text(direct)
                                        text_to_stream = cleaned_direct if cleaned_direct else direct.strip()
                                        if text_to_stream:
                                            async for sse_chunk in _stream_text_with_typing_effect(text_to_stream):
                                                yield sse_chunk
                                            response_text += text_to_stream
                                            direct_result_streamed = True
                                            strip_citations = False
                                    _fb_clr()
                                    sources = _fb_sources()
                                    if sources:
                                        yield SSESerializer.citations(sources)
                                except Exception as fb_err:
                                    logger.warning(f"[ReActChatAgent] Fallback search failed: {fb_err}")
                        if not direct_result_streamed:
                            cleaned = _clean_response_text(text_buffer)
                            # If no tools were called there are no real sources — always strip [N]
                            # markers to prevent broken citation badges in the UI.
                            if strip_citations or not tool_calls_made:
                                cleaned = re.sub(r'\s*\[\d+\]', '', cleaned)
                            if cleaned:
                                async for sse_chunk in _stream_text_with_typing_effect(cleaned):
                                    yield sse_chunk
                                response_text += cleaned

                # Fallback: step-level streaming (old behavior)
                elif hasattr(self.agent, 'astream'):
                    logger.info("[ReActChatAgent] Falling back to astream (step-level streaming)")
                    last_processed = 0

                    async for event in self.agent.astream(input_data):
                        if isinstance(event, dict):
                            if "messages" in event:
                                all_msgs = event["messages"]
                                new_msgs = all_msgs[last_processed:]
                                last_processed = len(all_msgs)

                                for msg in new_msgs:
                                    msg_type = getattr(msg, 'type', '')

                                    if msg_type == 'tool':
                                        tool_name = getattr(msg, 'name', 'unknown')
                                        output_preview = str(msg.content)[:300] if hasattr(msg, 'content') and msg.content else ''
                                        yield SSESerializer.tool_call(
                                            name=tool_name,
                                            status="completed",
                                            output=output_preview
                                        )
                                        # Check for direct result after tool completion
                                        try:
                                            from app.services.chat.universal_tools import (
                                                get_last_direct_result,
                                                clear_last_direct_result,
                                            )
                                            direct = get_last_direct_result()
                                            if direct and not direct_result_streamed:
                                                cleaned = _clean_response_text(direct)
                                                text_to_stream = cleaned if cleaned else direct.strip()
                                                if text_to_stream:
                                                    yield SSESerializer.text_delta(text_to_stream)
                                                    response_text += text_to_stream
                                                    direct_result_streamed = True
                                                    from app.services.chat.universal_tools import lock_used_sources
                                                    lock_used_sources()
                                                    logger.info(f"[ReActChatAgent] astream: Direct-streamed {tool_name} result ({len(text_to_stream)} chars)")
                                            clear_last_direct_result()
                                        except Exception as dr_err:
                                            logger.warning(f"[ReActChatAgent] astream: Failed to direct-stream result: {dr_err}")
                                        continue

                                    if msg_type in ('system', 'human'):
                                        continue

                                    # Skip AI synthesis when a tool already produced the answer
                                    if direct_result_streamed:
                                        logger.debug(f"[ReActChatAgent] astream: Skipping AI message (direct already streamed)")
                                        # Still track tool calls from AI messages
                                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                            for tc in msg.tool_calls:
                                                tool_name = tc.get('name', 'unknown')
                                                tool_calls_made.append(tool_name)
                                                logger.info(f"[ReActChatAgent] Tool call: {tool_name}")
                                                tool_input = json.dumps(tc.get('args', {}), ensure_ascii=False)[:200] if tc.get('args') else None
                                                yield SSESerializer.tool_call(
                                                    name=tool_name,
                                                    status="running",
                                                    input=tool_input
                                                )
                                        continue

                                    # Check tool_calls FIRST: if the AI message has tool_calls,
                                    # its content is reasoning/chain-of-thought — skip it
                                    has_tool_calls = hasattr(msg, 'tool_calls') and msg.tool_calls
                                    if has_tool_calls:
                                        for tc in msg.tool_calls:
                                            tool_name = tc.get('name', 'unknown')
                                            tool_calls_made.append(tool_name)
                                            logger.info(f"[ReActChatAgent] Tool call: {tool_name}")
                                            tool_input = json.dumps(tc.get('args', {}), ensure_ascii=False)[:200] if tc.get('args') else None
                                            yield SSESerializer.tool_call(
                                                name=tool_name,
                                                status="running",
                                                input=tool_input
                                            )
                                        # Skip content of AI messages with tool calls (it's reasoning)
                                        continue

                                    # AI message without tool calls — this is the final answer
                                    if hasattr(msg, 'content') and msg.content:
                                        cleaned_msg = _clean_response_text(msg.content)
                                        if cleaned_msg:
                                            async for sse_chunk in _stream_text_with_typing_effect(cleaned_msg):
                                                yield sse_chunk
                                            response_text += cleaned_msg

                            elif "output" in event:
                                # Skip output if direct result already streamed
                                if direct_result_streamed:
                                    continue
                                output = event["output"]
                                if output and output not in response_text:
                                    cleaned_output = _clean_response_text(output)
                                    if cleaned_output:
                                        async for sse_chunk in _stream_text_with_typing_effect(cleaned_output):
                                            yield sse_chunk
                                        response_text += cleaned_output
                else:
                    # Синхронный вызов с fallback
                    result = await self._invoke_agent_sync(input_data)
                    if result:
                        yield SSESerializer.text_delta(result)
                        response_text = result
                
                # Если ответ пустой, пробуем fallback (только если прямой результат не был стримирован)
                if not response_text.strip() and not direct_result_streamed:
                    logger.warning("[ReActChatAgent] Empty response, trying fallback")
                    fallback_response = await self._fallback_response(question)
                    yield SSESerializer.text_delta(fallback_response)
                    response_text = fallback_response
                
                logger.info(f"[ReActChatAgent] Completed. Tools used: {tool_calls_made}")

                # Отправляем citations из использованных источников
                from app.services.chat.universal_tools import get_used_sources, clear_used_sources
                used_sources = get_used_sources()
                if used_sources:
                    try:
                        # Fallback: если LLM не включил [1] маркеры — добавляем их
                        # Append inline to last sentence instead of as separate block
                        if not re.search(r"\[\d+\]", response_text):
                            refs = " ".join(f"[{i+1}]" for i in range(len(used_sources)))
                            suffix = f" {refs}"
                            yield SSESerializer.text_delta(suffix)
                            response_text += suffix
                            logger.info(f"[ReActChatAgent] Added inline citation markers: {refs}")
                        yield SSESerializer.citations(used_sources)
                        logger.info(f"[ReActChatAgent] Sent {len(used_sources)} citations")
                    except Exception as cite_err:
                        logger.warning(f"[ReActChatAgent] Failed to send citations: {cite_err}")
                    finally:
                        clear_used_sources()

                # === NEW v3.0: Post-processing с Reflection и Citation Verification ===
                # Skip reflection when tool already provided a direct synthesized answer:
                # the inner LLM already produced a high-quality per-document response,
                # and reflection would duplicate or overwrite it.
                if response_text and not direct_result_streamed and (self.enable_reflection or self.enable_citation_verification):
                    async for event in self._post_process_answer(question, response_text, context_used):
                        yield event
                
            except Exception as stream_error:
                logger.warning(f"[ReActChatAgent] Stream error: {stream_error}, trying sync invoke")
                # If direct result was already streamed, don't append a fallback error on top
                if direct_result_streamed:
                    logger.info("[ReActChatAgent] Direct result already streamed — skipping fallback after stream error")
                    return
                result = await self._invoke_agent_sync(input_data)
                if result:
                    yield SSESerializer.text_delta(result)

                    # Post-processing
                    if self.enable_reflection or self.enable_citation_verification:
                        async for event in self._post_process_answer(question, result):
                            yield event
                else:
                    fallback_response = await self._fallback_response(question)
                    yield SSESerializer.text_delta(fallback_response)
                    
        except Exception as e:
            logger.error(f"[ReActChatAgent] Agent error: {e}", exc_info=True)
            if direct_result_streamed:
                logger.info("[ReActChatAgent] Direct result already streamed — skipping fallback")
                return
            fallback_response = await self._fallback_response(question)
            yield SSESerializer.text_delta(fallback_response)
    
    async def _post_process_answer(
        self,
        question: str,
        answer: str,
        context: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Post-processing ответа: Reflection + Citation Verification
        
        Args:
            question: Исходный вопрос
            answer: Ответ агента
            context: Использованный контекст (опционально)
            
        Yields:
            SSE события с результатами проверок
        """
        # 1. Citation Verification (быстрее, запускаем первым)
        if self.enable_citation_verification:
            async for event in self._run_citation_verification(answer):
                yield event
        
        # 2. Reflection (самопроверка)
        if self.enable_reflection:
            async for event in self._run_reflection(question, answer, context):
                yield event
    
    async def _invoke_agent_sync(self, input_data: Dict[str, Any]) -> str:
        """Синхронный вызов агента"""
        try:
            if self.agent is None:
                return ""
                
            if hasattr(self.agent, 'ainvoke'):
                result = await self.agent.ainvoke(input_data)
            elif hasattr(self.agent, 'invoke'):
                import asyncio
                result = await asyncio.to_thread(self.agent.invoke, input_data)
            else:
                return ""
            
            # Извлекаем текст из результата
            if isinstance(result, dict):
                if "messages" in result:
                    messages = result["messages"]
                    if messages:
                        last_msg = messages[-1]
                        if hasattr(last_msg, 'content'):
                            return last_msg.content
                elif "output" in result:
                    return result["output"]
            elif hasattr(result, 'content'):
                return result.content
            
            return str(result) if result else ""
            
        except Exception as e:
            logger.error(f"[ReActChatAgent] Sync invoke error: {e}")
            return ""
    
    async def _fallback_response(self, question: str) -> str:
        """Fallback ответ через простой RAG + ГАРАНТ (если включен)"""
        try:
            logger.info("[ReActChatAgent] Using fallback RAG response")
            
            # Определяем тип вопроса
            question_lower = question.lower()
            is_overview = any(phrase in question_lower for phrase in [
                "о чём", "о чем", "обзор", "все документы", "что в деле",
                "расскажи о", "содержится", "какие документы"
            ])
            
            is_legal_question = any(phrase in question_lower for phrase in [
                "статья", "статьи", "закон", "кодекс", "гк рф", "гпк", "апк",
                "ук рф", "нк рф", "фз", "постановлен"
            ])
            
            combined_context = ""
            
            # Если включен ГАРАНТ и это правовой вопрос
            if self.legal_research and is_legal_question:
                try:
                    from app.services.external_sources.garant_source import get_garant_source
                    
                    garant_source = get_garant_source()
                    if garant_source and garant_source.api_key:
                        results = await garant_source.search(query=question, max_results=5)
                        
                        if results:
                            garant_parts = []
                            for i, result in enumerate(results, 1):
                                title = result.title or "Без названия"
                                content = result.content[:1500] if result.content else ""
                                url = result.url or ""
                                
                                part = f"[{i}] {title}"
                                if url:
                                    part += f"\nСсылка: {url}"
                                if content:
                                    part += f"\n\n{content}"
                                garant_parts.append(part)
                            
                            combined_context += "=== РЕЗУЛЬТАТЫ ИЗ ПРАВОВОЙ БАЗЫ ГАРАНТ ===\n\n"
                            combined_context += "\n\n---\n\n".join(garant_parts)
                            combined_context += "\n\n"
                            
                except Exception as e:
                    logger.warning(f"[ReActChatAgent] ГАРАНТ fallback error: {e}")
            
            if is_overview:
                # Для обзорных вопросов используем analyze_all_documents напрямую
                from app.services.chat.universal_tools import analyze_all_documents, initialize_universal_tools
                initialize_universal_tools(self.db, self.rag_service, self.case_id)
                return analyze_all_documents.invoke({"question": question, "task_type": "summarize"})
            else:
                # Для конкретных вопросов используем RAG
                docs = self.rag_service.retrieve_context(
                    case_id=self.case_id,
                    query=question,
                    k=15,
                    db=self.db
                )
                
                if docs:
                    context = self.rag_service.format_sources_for_prompt(docs, max_context_chars=6000)
                    combined_context += "=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ДЕЛА ===\n\n"
                    combined_context += context
                
                if not combined_context:
                    return "К сожалению, не удалось найти релевантную информацию в документах дела."
                
                # Генерируем ответ
                from langchain_core.messages import HumanMessage, SystemMessage
                
                response = self.llm.invoke([
                    SystemMessage(content="""Ты юридический ассистент. Отвечай на основе предоставленного контекста.
                    
Правила:
- Используй информацию ТОЛЬКО из контекста
- Указывай источники информации
- Если информация из ГАРАНТ - цитируй с указанием нормы
- Структурируй ответ с помощью Markdown"""),
                    HumanMessage(content=f"Контекст:\n{combined_context}\n\nВопрос: {question}")
                ])
                
                return response.content if hasattr(response, 'content') else str(response)
                
        except Exception as e:
            logger.error(f"[ReActChatAgent] Fallback error: {e}")
            return f"Произошла ошибка при обработке запроса. Пожалуйста, попробуйте переформулировать вопрос."
