"""
Universal Tools - 12 универсальных инструментов для case assistant runtime

Агент САМ решает, какие инструменты вызвать на основе вопроса пользователя.
Каждый инструмент имеет подробное описание для LLM.

БЛОК 1: Работа с документами (4 инструмента)
- get_document: получить текст документа
- search_in_documents: поиск по документам
- extract_structured_data: извлечь даты/суммы/имена
- compare_documents: сравнить два документа

БЛОК 2: Законы (2 инструмента)
- search_legal_db: поиск НПА на pravo.gov.ru
- get_legal_document: получить полный текст НПА

БЛОК 3: Генерация документов (2 инструмента)
- generate_document: создать черновик
- list_templates: показать шаблоны

БЛОК 4: Playbook (2 инструмента)
- validate_with_playbook: проверить по правилам
- get_user_playbooks: список правил

БЛОК 5: Вспомогательные (2 инструмента)
- calculate: расчеты
- get_current_date: текущая дата
"""
from typing import List, Optional, Dict, Any
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from datetime import datetime
import logging
import re

from app.config import config

logger = logging.getLogger(__name__)

# Глобальные зависимости (инжектируются при создании tools)
_db: Optional[Session] = None
_rag_service = None
_case_id: Optional[str] = None
_user_id: Optional[str] = None
_attached_file_ids: Optional[List[str]] = None  # Фильтрация по прикреплённым файлам

# Флаг использования Pro-модели (GigaChat-Pro) для внутренних LLM-вызовов,
# когда в чате включён deep_think.
_use_pro_llm: bool = False

# Отслеживание использованных источников для citations
_used_sources: List[Dict[str, Any]] = []

# Lock flag: once the first direct-streamed answer is sent, don't let subsequent
# tool calls overwrite _used_sources (they correspond to already-streamed [N] markers).
_sources_locked: bool = False

# Pre-synthesised answer (with inline [N] markers) to stream directly,
# bypassing GigaChat's outer synthesis step.
_last_direct_result: Optional[str] = None


def get_used_sources() -> List[Dict[str, Any]]:
    """Получить список использованных источников (для отправки citations в SSE)"""
    return list(_used_sources)


def lock_used_sources():
    """Lock _used_sources so subsequent tool calls don't overwrite citations from the first stream."""
    global _sources_locked
    _sources_locked = True


def clear_used_sources():
    """Очистить список использованных источников и снять блокировку"""
    global _used_sources, _sources_locked
    _used_sources = []
    _sources_locked = False


def unlock_used_sources():
    """Снять блокировку _used_sources (для авто-поиска pravo.gov.ru после документального ответа)."""
    global _sources_locked
    _sources_locked = False


def set_used_sources(sources: List[Dict[str, Any]]):
    """Напрямую установить _used_sources (для объединения источников из разных инструментов)."""
    global _used_sources
    _used_sources = list(sources)


def get_last_direct_result() -> Optional[str]:
    """Get the pre-synthesised answer to stream directly (bypasses GigaChat synthesis)."""
    global _last_direct_result
    return _last_direct_result


def clear_last_direct_result() -> None:
    """Clear after direct-streaming."""
    global _last_direct_result
    _last_direct_result = None


def _extract_meaningful_excerpt(text: str, max_len: int = 200) -> Optional[str]:
    """Extract the first meaningful (non-header, non-empty) line from document text."""
    if not text:
        return None
    for line in text.split('\n'):
        line = line.strip()
        # Skip short lines (headers, titles, blank lines)
        if len(line) < 20:
            continue
        # Skip lines that look like metadata/headers (all caps, short)
        if len(line) < 50 and line.isupper():
            continue
        return line[:max_len]
    # Fallback: just use the beginning
    return text[:max_len].strip() or None


def _normalize_citation_positions(text: str) -> str:
    """Move [N] markers from the START of lines to the END of the sentence.

    Handles all forms GigaChat may produce:
      '[1] text.'                        → 'text. [1]'
      '[1][2] text.'                     → 'text. [1][2]'
      '[1] filename.pdf: sentence text.' → 'filename.pdf: sentence text. [1]'
      '**[1] filename.pdf:**'            → '**filename.pdf:**'  (strip from bold headers)
    """
    # 1. Strip [N] from bold headers: **[1] text:** → **text:**
    text = re.sub(r'(\*{1,3})((?:\[\d+\]\s*)+)', r'\1', text)

    lines = text.split('\n')
    result = []
    for line in lines:
        # Match one or more [N] at the very start of the line (with optional leading spaces)
        m = re.match(r'^(\s*)((?:\[\d+\]\s*)+)(.+)', line)
        if m:
            indent = m.group(1)
            citations = re.sub(r'\s+', '', m.group(2))  # '[1][2]' compact
            content = m.group(3).strip()

            # If content is ONLY a header marker (ends with : and no real sentence)
            # just drop the leading [N] entirely — the citation will appear on the next line
            if re.match(r'^[^:]+:\s*$', content):
                result.append(indent + content)
                continue

            # Don't double-append if content already ends with [N]
            if re.search(r'\[\d+\]\s*[.!?]?\s*$', content):
                result.append(indent + content)
                continue

            # Attach citations before trailing punctuation
            punc_m = re.search(r'([.!?])\s*$', content)
            if punc_m:
                content = content[:punc_m.start()] + punc_m.group(1) + ' ' + citations
            else:
                content = content + ' ' + citations
            result.append(indent + content)
        else:
            result.append(line)
    return '\n'.join(result)


_HEADER_SKIP_RE = re.compile(
    r'^(?:'
    r'[А-ЯЁ\s«»"\d\-/.,()]+$'          # ALL-CAPS lines (court names, titles)
    r'|АРБИТРАЖНЫЙ\b|ОПРЕДЕЛЕНИЕ\b|РЕШЕНИЕ\b|ПОСТАНОВЛЕНИЕ\b'
    r'|г\.\s+\w|«\d+»\s+\w'             # location "г. Ростов" or date "«11» марта"
    r'|\d+\s*/\s*\d+'                    # page numbers
    r'|(?:Дело\s+№|№\s*\d)'             # case numbers
    r')',
    re.IGNORECASE,
)


def _first_content_line(text: str, max_len: int = 150) -> Optional[str]:
    """Return the first verbatim line from text that is actual document content
    (not a court header, section title, or formatting artifact).
    Falls back to the first long line if all lines look like headers.
    """
    first_long: Optional[str] = None
    for line in text.split('\n'):
        line = line.strip()
        if len(line) < 25:
            continue
        if first_long is None:
            first_long = line[:max_len]
        if not _HEADER_SKIP_RE.match(line):
            return line[:max_len]
    return first_long[:max_len] if first_long else (text[:max_len] or None)


def _last_sentence_fragment(text: str, max_len: int = 300) -> str:
    """Return the sentence fragment preceding a [N] marker.

    Strips leading filename headers (e.g. "file.pdf: ") so that the returned
    hint contains the full annotated sentence like "Срок устранения: установлен судом."
    """
    text = text.rstrip()
    if not text:
        return ''
    # Strip markdown bold markers
    clean = re.sub(r'\*{1,3}', '', text).strip()
    # Strip leading filename header: "А53-..._Opredelenie.pdf: " or "...копия.pdf: "
    clean = re.sub(
        r'^[^\n]+?\.(?:pdf|PDF|docx?|DOCX|txt|TXT)(?:\s*[—–-]\s*\S+)?\s*:\s*',
        '', clean
    ).strip()
    # Find the last complete sentence boundary and take text after it
    m = re.search(r'[.!?]\s+(.+)$', clean, re.DOTALL)
    if m:
        fragment = m.group(1).strip()
        return fragment[-max_len:] if len(fragment) > max_len else fragment
    # No boundary — return everything (it's all one sentence)
    return clean[-max_len:] if len(clean) > max_len else clean


def _expand_per_fact_citations(
    synthesized: str,
    file_order: list,
    doc_texts_map: dict,   # fname → text used for verbatim quote search
    source_meta_map: dict, # fname → {source_id, page, chunk_excerpt?}
) -> tuple:
    """Expand document-level [N] citations into unique per-fact [1],[2],[3]...

    GigaChat emits the same [docN] for every fact from document N. This function:
      1. Detects document sections by scanning for known filenames in each line.
      2. For each [N] occurrence assigns a unique sequential counter.
      3. Extracts a verbatim key phrase from the document text to use as `quote`.
      4. Builds a _used_sources list with one entry per badge.

    Returns: (expanded_text, per_fact_used_sources)
    """
    if not synthesized or not file_order:
        return synthesized, []

    lines = synthesized.split('\n')
    result_lines = []
    used_sources = []
    counter = 0
    current_fname: Optional[str] = None
    # Track quotes already assigned per document to avoid duplicate highlights
    used_quotes_per_doc: dict = {}  # fname → list[str]

    for line in lines:
        line_lower = line.lower()

        # GigaChat often puts [N] in the first column instead of the filename.
        # Detect "| [N] | fact... |" rows, resolve [N] → filename, and rewrite the
        # line so the filename appears in column 1 for correct display.
        first_col_num_m = re.match(r'^\|\s*\[(\d+)\]\s*\|(.+)$', line)
        if first_col_num_m:
            doc_num = int(first_col_num_m.group(1))
            if 1 <= doc_num <= len(file_order):
                current_fname = file_order[doc_num - 1]
                line = f'| {current_fname} |{first_col_num_m.group(2)}'
                line_lower = line.lower()

        # Detect document section header — filename must appear at the START of the
        # line (bold header "**file.pdf:**") OR in the FIRST COLUMN of a table row
        # "| file.pdf | fact |". Filenames embedded mid-sentence must NOT trigger switch.
        stripped = line_lower.lstrip('*# \t|')  # strip | too for table rows
        for fname in file_order:
            fname_lower = fname.lower()
            if stripped.startswith(fname_lower):
                current_fname = fname
                break

        if not re.search(r'\[\d+\]', line):
            result_lines.append(line)
            continue

        # Use capturing split to preserve the actual N value from each [N] marker.
        # parts alternates: text, N_str, text, N_str, ...
        parts = re.split(r'\[(\d+)\]', line)
        new_line = parts[0]

        for part_idx in range(1, len(parts), 2):
            n_str = parts[part_idx]
            seg = parts[part_idx + 1] if part_idx + 1 < len(parts) else ''
            n_val = int(n_str)

            # Resolve the document for this badge.
            # Priority: explicit filename header detected in the line (table format).
            # Fallback: use N directly as document index (prose/bullet format like extract_structured_data).
            effective_fname = current_fname
            if effective_fname is None and 1 <= n_val <= len(file_order):
                effective_fname = file_order[n_val - 1]

            doc_text = doc_texts_map.get(effective_fname, '') if effective_fname else ''
            meta = source_meta_map.get(effective_fname, {}) if effective_fname else {}
            doc_used = used_quotes_per_doc.setdefault(effective_fname or '_', [])

            counter += 1
            # The "hint" is the sentence fragment right before this [N]
            hint = _last_sentence_fragment(new_line)
            quote = _extract_key_search_phrase(hint, doc_text) if hint else None

            # Fallback 1: find longest n-gram from hint that appears verbatim in doc_text.
            # Handles cases where the hint has no date/amount but contains content words
            # that appear literally in the document.
            if quote is None and hint and doc_text:
                words = re.findall(r'[а-яёА-ЯЁ]{4,}', hint)
                doc_lower = doc_text.lower()
                for window in range(min(4, len(words)), 1, -1):
                    for i in range(len(words) - window + 1):
                        phrase = ' '.join(words[i:i + window])
                        if phrase.lower() in doc_lower:
                            quote = phrase
                            break
                    if quote:
                        break

            # Deduplication: if this quote is already used for this document,
            # try to find the NEXT occurrence of the phrase in the document text
            # so each badge highlights a different place.
            if quote is not None and quote in doc_used and doc_text:
                doc_lower = doc_text.lower()
                q_lower = quote.lower()
                # Skip past all known occurrences to find a new one
                search_start = 0
                for already in doc_used:
                    if already.lower() == q_lower:
                        pos = doc_lower.find(q_lower, search_start)
                        if pos >= 0:
                            search_start = pos + len(q_lower)
                next_pos = doc_lower.find(q_lower, search_start)
                if next_pos >= 0:
                    quote = doc_text[next_pos:next_pos + len(quote) + 30].strip()

            # Fallback 2 (insurance): use the verbatim chunk excerpt stored in meta.
            # This is always findable in the document and at least opens it at the
            # right area (the chunk most relevant to the query for this document).
            if quote is None:
                chunk_exc = meta.get("chunk_excerpt")
                # Use chunk_excerpt only if not already taken by another badge
                if chunk_exc and chunk_exc not in doc_used:
                    quote = chunk_exc

            if quote:
                doc_used.append(quote)

            used_sources.append({
                "source_id": meta.get("source_id"),
                "file_name": effective_fname,
                "page": meta.get("page"),
                "quote": quote,
                "source_type": "document",
            })
            new_line += f'[{counter}]{seg}'

        result_lines.append(new_line)

    return '\n'.join(result_lines), used_sources


def _find_verbatim_quote_in_chunk(entity_quote: str, chunk_text: str, max_len: int = 200) -> Optional[str]:
    """Find the sentence in chunk_text that best matches a paraphrased entity_quote.

    Extracts key tokens (numbers, dates, long words) from entity_quote and scores each
    sentence in chunk_text by overlap.  Returns the verbatim best-matching sentence so
    DocumentPreviewSheet can locate it precisely via text search within the chunk bounds.
    """
    if not entity_quote or not chunk_text:
        return None

    # Key tokens: numbers/dates (e.g. "5.11.2011", "500 000") and long content words
    tokens = set(re.findall(r'\b\d[\d.,\-/]*\d\b|\b[а-яёА-ЯЁa-zA-Z]{5,}\b', entity_quote.lower()))
    if not tokens:
        return None

    # Split chunk into sentence-like fragments
    sentences = re.split(r'(?<=[.!?])\s+|\n+', chunk_text)
    best_sentence: Optional[str] = None
    best_score = 0

    for sent in sentences:
        sent_stripped = sent.strip()
        if len(sent_stripped) < 10:
            continue
        score = sum(1 for t in tokens if t in sent_stripped.lower())
        if score > best_score:
            best_score = score
            best_sentence = sent_stripped

    # Require at least 2 matching tokens to avoid false positives
    if best_sentence and best_score >= 2:
        return best_sentence[:max_len]
    return None


# Russian month names for date extraction
_RU_MONTHS = (
    'января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря'
)
# Date patterns in order of specificity
_DATE_PATTERNS = [
    # «28» сентября 2011  or  «28» сентября 2011 года
    rf'«\s*\d{{1,2}}\s*»\s+(?:{_RU_MONTHS})\s+\d{{4}}(?:\s*г(?:ода)?\.?)?',
    # 28 сентября 2011 года
    rf'\d{{1,2}}\s+(?:{_RU_MONTHS})\s+\d{{4}}(?:\s*г(?:ода)?\.?)?',
    # 28.09.2011 or 28/09/2011
    r'\d{1,2}[./]\d{2}[./]\d{4}',
]
# Amount patterns: "500 000 руб.", "1 500 000,00 рублей"
_AMOUNT_PATTERN = r'\d[\d\s]*\d\s*(?:руб(?:лей|\.)?|тыс(?:\.|\s*руб)?|млн)'


def _extract_key_search_phrase(synthesis_sentence: str, chunk_text: str) -> Optional[str]:
    """Return the shortest VERBATIM phrase from synthesis_sentence that exists in chunk_text.

    Priority:
      1. Specific date expressions — almost always copied verbatim by the LLM
      2. Monetary amounts
      3. Best-matching sentence via token overlap (_find_verbatim_quote_in_chunk)

    For PDFs this short phrase is passed to PDF.js findController for text search,
    so it MUST appear literally in the extracted PDF text.
    """
    if not synthesis_sentence:
        return None

    chunk_lower = (chunk_text or '').lower()

    _NUM_TO_MONTH = {
        '01': 'января', '02': 'февраля', '03': 'марта', '04': 'апреля',
        '05': 'мая', '06': 'июня', '07': 'июля', '08': 'августа',
        '09': 'сентября', '10': 'октября', '11': 'ноября', '12': 'декабря',
    }

    # 1. Try date patterns — also generate Russian-month variants for numeric dates
    for pattern in _DATE_PATTERNS:
        for m in re.finditer(pattern, synthesis_sentence, re.IGNORECASE):
            candidate = m.group(0).strip()
            # Strip guillemets for direct match
            cand_plain = re.sub(r'[«»"]', '', candidate).strip()
            if cand_plain.lower() in chunk_lower or candidate.lower() in chunk_lower:
                return candidate

            # Numeric date "DD.MM.YYYY" → try Russian written forms in chunk
            num_m = re.match(r'(\d{1,2})[./](\d{2})[./](\d{4})', candidate)
            if num_m:
                day, mon, year = num_m.group(1), num_m.group(2).zfill(2), num_m.group(3)
                month_name = _NUM_TO_MONTH.get(mon)
                if month_name:
                    # Exact substring variants (fast path)
                    for variant in [
                        f"{day} {month_name} {year}",
                        f"«{day}» {month_name}",
                        f"{month_name} {year}",
                    ]:
                        if variant.lower() in chunk_lower:
                            idx = chunk_lower.find(variant.lower())
                            end = min(len(chunk_text), idx + len(variant) + 20)
                            return chunk_text[idx:end].strip()
                    # Regex variants — handle spaces inside guillemets (« 11 » марта)
                    # and multiple/non-breaking spaces (common in PDF extraction)
                    for pat in [
                        rf'«\s*{re.escape(day)}\s*»\s*{re.escape(month_name)}\s*{re.escape(year)}',
                        rf'«\s*{re.escape(day)}\s*»\s*{re.escape(month_name)}',
                        rf'{re.escape(day)}\s+{re.escape(month_name)}\s+{re.escape(year)}',
                    ]:
                        rm = re.search(pat, chunk_lower)
                        if rm:
                            end = min(len(chunk_text), rm.end() + 20)
                            return chunk_text[rm.start():end].strip()
            continue

    # 2. Try amount patterns
    for m in re.finditer(_AMOUNT_PATTERN, synthesis_sentence, re.IGNORECASE):
        candidate = m.group(0).strip()
        # Flexible whitespace match (non-breaking spaces in PDFs)
        pattern_flex = re.compile(
            re.escape(candidate.lower()).replace(r'\ ', r'[\s\u00a0]+'),
            re.IGNORECASE
        )
        if pattern_flex.search(chunk_lower):
            return candidate

    # 3. Fall back to verbatim sentence via keyword overlap
    return _find_verbatim_quote_in_chunk(synthesis_sentence, chunk_text, max_len=150)


def _parse_entity_quotes(result_text: str, n_sources: int) -> dict:
    """Parse LLM entity-extraction output to get per-source short quotes for highlighting.
    Matches lines like: '- Абумов Евгений Геннадьевич [1]: исполнитель'
    Returns {source_index: entity_text}.
    """
    quotes: dict = {}
    for line in result_text.split('\n'):
        m = re.search(r'[-•]\s+(.+?)\s*\[(\d+)\]', line)
        if m:
            entity = m.group(1).strip('- \u2022').strip()
            # Strip leading [label] markers like "[сумма]", "[стороны]" — they won't appear verbatim in the document
            entity = re.sub(r'^\[.*?\]\s*', '', entity).strip()
            idx = int(m.group(2))
            if 1 <= idx <= n_sources and entity and idx not in quotes:
                quotes[idx] = entity
    return quotes


_SAFETY_FILTER_PHRASES = [
    # Variant 1: "Генеративные языковые модели не обладают собственным мнением"
    "не обладают собственным мнением",
    # Variant 2: "GigaChat не обладает собственным мнением" (singular form)
    "не обладает собственным мнением",
    # Tail phrases common to both variants
    "неправильного толкования, разговоры",
    "темы временно ограничены",
    "чувствительные темы могут быть ограничены",
    # GigaChat-specific boilerplate (variant 2)
    "нейросетевой моделью, обученной на открытых данных",
    "не транслирует мнение своих разработчиков",
    # Generic disclaimers
    "не могу дать совет",
    "не могу высказать мнение",
    "как языковая модель, я не могу",
    "не могу предоставить юридическую консультацию",
    "за консультацией к специалисту",
    "я не в состоянии оценить",
]


def _is_safety_filter_response(text: str) -> bool:
    """Detect if GigaChat returned a safety filter / disclaimer instead of an answer."""
    if not text:
        return False
    text_lower = text.lower()
    return any(phrase.lower() in text_lower for phrase in _SAFETY_FILTER_PHRASES)


def _neutralize_sensitive_query(query: str) -> Optional[str]:
    """If query contains words that trigger GigaChat's safety filter,
    return a semantically equivalent neutral phrasing. Returns None if no change needed."""
    q_lower = query.lower()
    triggers = ["риск", "опасност", "угроз", "нарушени", "проблем", "слабост"]
    if not any(t in q_lower for t in triggers):
        return None
    # Replace trigger phrases while preserving semantic intent
    neutral = re.sub(
        r'\b(?:риски|риск|опасности|угрозы|проблемы|слабости)\b',
        'неблагоприятные обстоятельства',
        query,
        flags=re.IGNORECASE
    )
    neutral = re.sub(
        r'\b(?:рискованн\w+|опасн\w+)\b',
        'проблемн',
        neutral,
        flags=re.IGNORECASE
    )
    return neutral if neutral != query else None


def initialize_universal_tools(
    db: Session,
    rag_service,
    case_id: str,
    user_id: Optional[str] = None,
    attached_file_ids: Optional[List[str]] = None,
    use_pro_llm: bool = False,
):
    """Инициализировать глобальные зависимости для tools"""
    global _db, _rag_service, _case_id, _user_id, _attached_file_ids, _last_direct_result, _use_pro_llm
    _db = db
    _rag_service = rag_service
    _case_id = case_id
    _user_id = user_id
    _attached_file_ids = attached_file_ids or None
    _last_direct_result = None
    _use_pro_llm = use_pro_llm
    clear_used_sources()


# =============================================================================
# БЛОК 1: РАБОТА С ДОКУМЕНТАМИ (4 инструмента)
# =============================================================================

@tool
def get_document(filename: str) -> str:
    """
    Получить полный текст документа по имени файла.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь просит показать конкретный документ
    - Нужен полный текст для детального анализа
    - Вопрос типа "покажи договор", "открой иск", "что в документе X"
    - Перед сравнением документов
    
    НЕ ИСПОЛЬЗОВАТЬ:
    - Для поиска конкретной информации (используй search_in_documents)
    - Если нужен только фрагмент (используй search_in_documents)
    
    Args:
        filename: Имя файла (полное или частичное, например "договор" или "договор.pdf")
    
    Returns:
        Полный текст документа (до 15000 символов) или сообщение об ошибке
    """
    global _db, _case_id
    
    if not _db or not _case_id:
        return "Ошибка: база данных не инициализирована"
    
    try:
        from app.models.case import File as FileModel
        
        # Ищем файл по частичному совпадению имени
        files = _db.query(FileModel).filter(
            FileModel.case_id == _case_id
        ).all()
        
        if not files:
            return "В деле нет загруженных документов."
        
        # Ищем файл по имени (частичное совпадение)
        filename_lower = filename.lower()
        matched_file = None
        
        for f in files:
            if filename_lower in f.filename.lower():
                matched_file = f
                break
        
        if not matched_file:
            # Если не нашли - показываем список доступных файлов
            file_list = "\n".join([f"- {f.filename}" for f in files])
            return f"Документ '{filename}' не найден.\n\nДоступные документы:\n{file_list}"
        
        # Получаем текст документа
        text = matched_file.original_text or ""
        
        if not text:
            return f"Документ '{matched_file.filename}' найден, но текст пуст."
        
        # Ограничиваем размер
        if len(text) > 15000:
            text = text[:15000] + "\n\n... [текст обрезан, используй search_in_documents для поиска конкретной информации]"
        
        logger.info(f"[UniversalTools] get_document: {matched_file.filename} ({len(text)} символов)")

        # Track source for citations
        global _used_sources
        _used_sources = [{
            "source_id": str(matched_file.id),
            "file_name": matched_file.filename,
            "page": 1,
            "quote": text[:300],
            "source_type": "document",
        }]

        return f"📄 **{matched_file.filename}**\n\n{text}"

    except Exception as e:
        logger.error(f"[UniversalTools] get_document error: {e}")
        return f"Ошибка получения документа: {str(e)}"


@tool
def search_in_documents(query: str, k: int = 20) -> str:
    """
    Поиск по документам дела. Возвращает релевантные фрагменты с источниками.
    
    Args:
        query: Поисковый запрос
        k: Количество результатов (5-100, по умолчанию 20)
    
    Returns:
        Найденные фрагменты документов с источниками
    """
    global _rag_service, _case_id, _db, _used_sources, _sources_locked, _attached_file_ids, _last_direct_result

    if not _rag_service or not _case_id:
        return "Ошибка: сервис поиска не инициализирован"

    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        # Ограничиваем k разумными пределами
        k = max(5, min(100, k))

        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query=query,
            k=k,
            retrieval_strategy="multi_query",
            db=_db,
            file_ids=_attached_file_ids  # Фильтр по прикреплённым файлам
        )

        if not documents:
            return f"По запросу '{query}' ничего не найдено в документах дела."

        # Очищаем предыдущие источники при новом поиске (только если ещё не заблокированы
        # первым прямым стримингом — иначе источники уже отправлены и перезаписывать их не нужно)
        if not _sources_locked:
            _used_sources = []

        # Group chunks by source file, preserving order of first appearance
        files_map: dict = {}  # fname -> list of docs
        for doc in documents:
            fname = doc.metadata.get("source_file", "Документ")
            files_map.setdefault(fname, []).append(doc)

        file_order = list(files_map.keys())

        # Build numbered per-file context: [N] filename:\n <all chunks>
        result_parts = []
        total_chars = 0
        max_chars = 25000

        for i, fname in enumerate(file_order, 1):
            if total_chars >= max_chars:
                break
            chunks = files_map[fname]
            file_text = "\n".join(c.page_content.strip() for c in chunks)[:3000]
            entry = f"[{i}] {fname}:\n{file_text}"
            if total_chars + len(entry) > max_chars:
                available = max_chars - total_chars - 100
                if available > 200:
                    entry = f"[{i}] {fname}:\n{file_text[:available]}..."
                else:
                    break
            result_parts.append(entry)
            total_chars += len(entry)

            # One _used_sources entry per file — first chunk is most relevant
            best = chunks[0]
            meta = best.metadata
            # Preserve None when there's no real page info — viewer then uses verbatim
            # text search instead of jumping to a wrong page (sourcePage + 1 offset).
            _page = meta.get("source_page")
            if _page is None:
                _page = meta.get("page")
            _used_sources.append({
                "source_id": str(meta.get("file_id", meta.get("doc_id", f"src-{i}"))),
                "file_name": fname,
                "page": _page,
                "quote": best.page_content[:300],
                "char_start": meta.get("char_start"),
                "char_end": meta.get("char_end"),
                "source_type": "document",
            })

        context = "\n\n".join(result_parts)
        logger.info(f"[UniversalTools] search_in_documents: {len(documents)} чанков, {len(result_parts)} файлов для '{query[:50]}'")

        # Inner LLM synthesis: documents go into SystemMessage (like global assistant),
        # which avoids GigaChat safety filter that triggers on user-turn document content.
        source_list = "\n".join(f"[{i}] {fn}" for i, fn in enumerate(file_order, 1))

        # В режиме deep_think используем Pro-модель (GigaChat-Pro), если флаг установлен.
        if _use_pro_llm:
            llm = create_legal_llm(model=config.GIGACHAT_PRO_MODEL, use_rate_limiting=False)
        else:
            llm = create_legal_llm()

        _system_msg = (
            "Ты ассистент по работе с текстом документов. "
            "Твоя задача — извлекать и излагать информацию из предоставленных текстов в виде таблицы Markdown. "
            "Строго следуй формату таблицы: каждая строка — один факт, в конце ячейки с фактом ставь [N] — номер документа-источника. "
            "Пиши только [1], [2], [3] и т.д. — никогда не пиши [документ 1], только [1]. "
            "ЗАПРЕЩЕНО добавлять заголовки или текст вне таблицы. "
            "ЗАПРЕЩЕНО изменять, округлять или перефразировать числа, даты и суммы — "
            "все цифры, даты и денежные суммы переписывай ДОСЛОВНО так, как они написаны в документе.\n\n"
            f"Документы из дела:\n{context}\n\n"
            f"Список документов:\n{source_list}"
        )
        ex1 = file_order[0] if file_order else "Договор_подряда.pdf"
        ex2 = file_order[1] if len(file_order) > 1 else "Дополнительное_соглашение.pdf"
        query_prompt = (
            f"На основе документов выше выполни следующий запрос: {query}\n\n"
            "ФОРМАТ — таблица Markdown. Каждая строка = один отдельный факт. [N] = номер документа из списка выше:\n"
            "| Документ | Факт |\n"
            "| --- | --- |\n"
            f"| {ex1} | Исполнитель — Иванов А.А. [1] |\n"
            f"| {ex1} | Сумма договора — 500 000 руб. [1] |\n"
            f"| {ex2} | Дата подачи заявления — 17.08.2011. [2] |\n"
            f"| {ex2} | Срок рассмотрения — до 13.07.2011. [2] |\n\n"
            "ПРАВИЛА: [N] ставь ТОЛЬКО в конце ячейки «Факт». В колонке «Документ» пиши ТОЛЬКО полное имя файла из списка — НЕЛЬЗЯ писать [1] или другие числа в скобках в колонке «Документ».\n"
            "Перечисли ВСЕ факты, даты и сроки, относящиеся к запросу. Документы без нужной информации не включай.\n"
            "ВАЖНО: числа, даты и суммы переписывай ДОСЛОВНО из документа — не округляй и не изменяй их.\n"
            "Отвечай строго по тексту документов:"
        )
        response = llm.invoke([
            SystemMessage(content=_system_msg),
            HumanMessage(content=query_prompt)
        ])
        synthesized = response.content if hasattr(response, 'content') else str(response)

        # Retry with neutral query if safety filter triggered
        if _is_safety_filter_response(synthesized):
            logger.warning(
                f"[UniversalTools] search_in_documents: safety filter hit at {datetime.now().isoformat()} "
                f"| query='{query[:100]}' | response='{synthesized[:120]}'"
            )
            neutral_query = _neutralize_sensitive_query(query)
            # Try 1: neutral query (риски → неблагоприятные обстоятельства)
            if neutral_query:
                logger.info(f"[UniversalTools] search_in_documents: retry 1 with neutral query")
                neutral_prompt = (
                    f"На основе документов выше выполни следующий запрос: {neutral_query}\n\n"
                    "ФОРМАТ — [N] в конце каждого предложения с фактом (N — номер документа):\n"
                    "Если документ не содержит нужной информации — пропусти его.\n"
                    "Отвечай строго по тексту документов:"
                )
                response2 = llm.invoke([
                    SystemMessage(content=_system_msg),
                    HumanMessage(content=neutral_prompt)
                ])
                retry_text = response2.content if hasattr(response2, 'content') else str(response2)
                if not _is_safety_filter_response(retry_text):
                    synthesized = retry_text
                    logger.info(f"[UniversalTools] search_in_documents: retry 1 succeeded ({len(synthesized)} chars)")
                else:
                    # Try 2: extraction-framed prompt (no mention of sensitive topics)
                    logger.info("[UniversalTools] search_in_documents: retry 2 with extraction framing")
                    extract_prompt = (
                        "Из каждого документа выпиши все упомянутые проблемы, отказы, замечания, "
                        "процессуальные нарушения, спорные условия и затруднения.\n\n"
                        "ФОРМАТ — [N] в конце каждого предложения с фактом (N — номер документа):\n"
                        "Если документ не содержит нужной информации — пропусти его."
                    )
                    response3 = llm.invoke([
                        SystemMessage(content=_system_msg),
                        HumanMessage(content=extract_prompt)
                    ])
                    retry_text2 = response3.content if hasattr(response3, 'content') else str(response3)
                    if not _is_safety_filter_response(retry_text2):
                        synthesized = retry_text2
                        logger.info(f"[UniversalTools] search_in_documents: retry 2 succeeded ({len(synthesized)} chars)")
                    else:
                        logger.warning("[UniversalTools] search_in_documents: all retries hit safety filter — using raw context")
                        synthesized = context
            else:
                logger.warning("[UniversalTools] search_in_documents: safety filter, no neutralization possible")

        # Build per-document text and metadata maps for per-fact quote extraction
        doc_texts_map: dict = {}
        source_meta_map: dict = {}
        for fn in file_order:
            chunks = files_map.get(fn, [])
            # Prefer full document text from DB for better date/number coverage
            full_text = ''
            try:
                from app.models.case import File as FileModel
                if _db is not None and _case_id is not None:
                    file_obj = _db.query(FileModel).filter(
                        FileModel.case_id == _case_id,
                        FileModel.filename == fn,
                    ).first()
                    if file_obj and file_obj.original_text:
                        full_text = file_obj.original_text
            except Exception as _e:
                logger.warning("[UniversalTools] Could not load full doc text for %s: %s", fn, _e)
            doc_texts_map[fn] = full_text or '\n'.join(c.page_content for c in chunks)
            if chunks:
                meta = chunks[0].metadata or {}
                # First meaningful sentence from best chunk — verbatim fallback quote
                chunk_text = chunks[0].page_content.strip()
                chunk_excerpt = _first_content_line(chunk_text)
                source_meta_map[fn] = {
                    "source_id": str(meta.get("file_id", meta.get("doc_id", ""))),
                    "page": meta.get("source_page") or meta.get("page"),
                    "chunk_excerpt": chunk_excerpt,
                }

        # Expand document-level [N] → unique per-fact [1],[2],[3]...
        # Each fact gets its own _used_sources entry with a verbatim quote.
        synthesized, per_fact_sources = _expand_per_fact_citations(
            synthesized, file_order, doc_texts_map, source_meta_map
        )
        if per_fact_sources and not _sources_locked:
            _used_sources.clear()
            _used_sources.extend(per_fact_sources)
            logger.info(f"[UniversalTools] search_in_documents: {len(per_fact_sources)} per-fact citations built")

        # Normalize: move any [N] markers that ended up at start of sentence to end
        synthesized = _normalize_citation_positions(synthesized)

        # Store for direct streaming (bypasses GigaChat's outer synthesis)
        _last_direct_result = synthesized
        logger.info(f"[UniversalTools] search_in_documents: inner synthesis done ({len(synthesized)} chars)")

        return synthesized

    except Exception as e:
        logger.error(f"[UniversalTools] search_in_documents error: {e}")
        return f"Ошибка поиска: {str(e)}"


@tool
def analyze_all_documents(question: str, task_type: str = "answer") -> str:
    """
    Глубокий анализ ВСЕХ документов дела с использованием Map-Reduce.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Вопрос требует анализа ВСЕХ документов ("о чём все документы?")
    - Нужен полный обзор дела
    - Много документов (>10) и нужен комплексный ответ
    - Сравнение или извлечение из множества документов
    
    НЕ ИСПОЛЬЗОВАТЬ:
    - Для простых вопросов (используй search_in_documents)
    - Когда нужен конкретный фрагмент
    
    Args:
        question: Вопрос или задача для анализа
        task_type: Тип задачи:
            - "answer" - ответить на вопрос по всем документам
            - "summarize" - сделать обзор всех документов
            - "extract" - извлечь факты из всех документов
    
    Returns:
        Комплексный ответ на основе анализа всех документов
    """
    global _rag_service, _case_id, _db, _used_sources, _sources_locked, _last_direct_result

    if not _rag_service or not _case_id:
        return "Ошибка: сервис не инициализирован"
    
    try:
        import asyncio
        from app.services.map_reduce_service import MapReduceService
        from app.models.case import File as FileModel
        from langchain_core.documents import Document
        
        # Получаем все документы дела
        files = _db.query(FileModel).filter(
            FileModel.case_id == _case_id
        ).all()
        
        if not files:
            return "В деле нет загруженных документов."
        
        # Collect files with text (ordered — [N] numbering must match _used_sources)
        files_with_text = [f for f in files if f.original_text]

        if not files_with_text:
            return "Документы найдены, но текст не извлечён."

        logger.info(f"[UniversalTools] analyze_all_documents: {len(files_with_text)} документов для анализа")

        # Build numbered context [N] for reliable citation markers.
        # Each document gets a capped excerpt; for very large sets use MapReduce.
        MAX_CHARS_PER_DOC = 4000
        MAX_TOTAL_CHARS = 30000
        file_order = []  # [(index, filename)]
        context_parts = []
        total_chars = 0

        for i, f in enumerate(files_with_text, 1):
            excerpt = f.original_text[:MAX_CHARS_PER_DOC]
            entry = f"[{i}] {f.filename}:\n{excerpt}"
            if total_chars + len(entry) > MAX_TOTAL_CHARS:
                available = MAX_TOTAL_CHARS - total_chars - 50
                if available > 200:
                    entry = f"[{i}] {f.filename}:\n{f.original_text[:available]}..."
                else:
                    break
            context_parts.append(entry)
            file_order.append((i, f.filename))
            total_chars += len(entry)

        if not context_parts:
            # Fallback: MapReduce for very large documents
            from app.services.map_reduce_service import MapReduceService
            from langchain_core.documents import Document
            from app.utils.async_utils import run_async_safe
            documents = [
                Document(page_content=f.original_text, metadata={"source_file": f.filename, "file_id": str(f.id)})
                for f in files_with_text
            ]
            service = MapReduceService()
            result = run_async_safe(service.process(documents, question, task_type))
            response = result.answer
        else:
            context = "\n\n".join(context_parts)
            source_list = "\n".join(f"[{i}] {fn}" for i, fn in file_order)

            from langchain_core.messages import HumanMessage, SystemMessage
            from app.services.llm_factory import create_legal_llm
            # При включённом deep_think используем Pro-модель для глубокого анализа.
            if _use_pro_llm:
                llm = create_legal_llm(model=config.GIGACHAT_PRO_MODEL, use_rate_limiting=False)
            else:
                llm = create_legal_llm()

            # Documents go into SystemMessage (mirrors global assistant) to avoid safety filter
            # that triggers on user-turn content with legal/sensitive document text.
            _sys_content = (
                "Ты — профессиональный юридический ассистент. "
                "Отвечай на вопрос пользователя на основе предоставленных документов. "
                "После КАЖДОГО факта, имени, даты, суммы или вывода ставь [N] — номер документа-источника из списка. "
                "Пиши только [1], [2], [3] и т.д. "
                "Используй Markdown: заголовки ## для разделов, маркированные списки для перечислений, **жирный** для важного. "
                "НЕ упоминай названия файлов в тексте — только [N].\n\n"
                f"Документы из дела:\n{context}\n\n"
                f"Список документов:\n{source_list}"
            )
            query_prompt = (
                f"Вопрос: {question}\n\n"
                "Ответь структурированно с заголовками Markdown. "
                "После каждого факта ставь [N]. "
                "Отвечай строго по тексту документов."
            )
            llm_response = llm.invoke([
                SystemMessage(content=_sys_content),
                HumanMessage(content=query_prompt)
            ])
            response = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)

            # Retry with neutral query if safety filter triggered
            if _is_safety_filter_response(response):
                logger.warning(
                    f"[UniversalTools] analyze_all_documents: safety filter hit at {datetime.now().isoformat()} "
                    f"| question='{question[:100]}' | response='{response[:120]}'"
                )
                neutral_question = _neutralize_sensitive_query(question)
                # Try 1: neutral query (риски → неблагоприятные обстоятельства)
                if neutral_question:
                    logger.info("[UniversalTools] analyze_all_documents: retry 1 with neutral query")
                    neutral_prompt = (
                        f"На основе документов выше выполни следующий запрос: {neutral_question}\n\n"
                        "Правила:\n"
                        "- После каждого факта, числа, имени или даты добавляй [N]\n"
                        "- Документы без нужной информации не упоминай\n"
                        "Отвечай строго по тексту документов:"
                    )
                    retry_resp = llm.invoke([
                        SystemMessage(content=_sys_content),
                        HumanMessage(content=neutral_prompt)
                    ])
                    retry_text = retry_resp.content if hasattr(retry_resp, 'content') else str(retry_resp)
                    if not _is_safety_filter_response(retry_text):
                        response = retry_text
                        logger.info(f"[UniversalTools] analyze_all_documents: retry 1 succeeded ({len(response)} chars)")
                    else:
                        # Try 2: extraction-framed prompt
                        logger.info("[UniversalTools] analyze_all_documents: retry 2 with extraction framing")
                        extract_prompt = (
                            "Из каждого документа выпиши все упомянутые проблемы, отказы, замечания, "
                            "процессуальные нарушения и затруднения.\n\n"
                            "Правила:\n"
                            "- После каждого факта добавляй [N] — номер документа-источника\n"
                            "Отвечай строго по тексту документов:"
                        )
                        retry_resp2 = llm.invoke([
                            SystemMessage(content=_sys_content),
                            HumanMessage(content=extract_prompt)
                        ])
                        retry_text2 = retry_resp2.content if hasattr(retry_resp2, 'content') else str(retry_resp2)
                        if not _is_safety_filter_response(retry_text2):
                            response = retry_text2
                            logger.info(f"[UniversalTools] analyze_all_documents: retry 2 succeeded ({len(response)} chars)")
                        else:
                            logger.warning("[UniversalTools] analyze_all_documents: all retries hit safety filter — using raw context")
                            response = context
                else:
                    logger.warning("[UniversalTools] analyze_all_documents: safety filter, no neutralization possible")

        # Build per-document text and metadata maps for per-fact quote extraction
        analyze_doc_texts: dict = {}
        analyze_meta: dict = {}
        for f in files_with_text:
            analyze_doc_texts[f.filename] = f.original_text or ''
            chunk_excerpt_a = _first_content_line(f.original_text or '')
            analyze_meta[f.filename] = {
                "source_id": str(f.id),
                "page": None,
                "chunk_excerpt": chunk_excerpt_a,
            }

        # Expand document-level [N] → unique per-fact [1],[2],[3]...
        an_file_order = [f.filename for f in files_with_text]
        response, per_fact_sources = _expand_per_fact_citations(
            response, an_file_order, analyze_doc_texts, analyze_meta
        )
        if per_fact_sources and not _sources_locked:
            _used_sources.clear()
            _used_sources.extend(per_fact_sources)
            logger.info(f"[UniversalTools] analyze_all_documents: {len(per_fact_sources)} per-fact citations built")
        elif not _sources_locked:
            # Fallback: populate one entry per file if expansion produced nothing
            _used_sources.clear()
            for f in files_with_text:
                _used_sources.append({
                    "source_id": str(f.id),
                    "file_name": f.filename,
                    "page": None,
                    "quote": None,
                    "source_type": "document",
                })

        # Normalize: move any [N] markers that ended up at start of sentence to end
        response = _normalize_citation_positions(response)

        # Store as direct result so orchestrator can stream deterministic output
        global _last_direct_result
        _last_direct_result = response

        logger.info(f"[UniversalTools] analyze_all_documents: завершено, {len(files_with_text)} документов")

        return response
        
    except Exception as e:
        logger.error(f"[UniversalTools] analyze_all_documents error: {e}", exc_info=True)
        return f"Ошибка анализа документов: {str(e)}"


@tool
def extract_structured_data(entity_types: str = "dates,amounts,persons,organizations") -> str:
    """
    Извлечь структурированные данные из документов дела.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь спрашивает "какие даты", "какие суммы", "кто участники"
    - Нужен список всех дат/сумм/имён/организаций
    - Для построения обзора ключевых фактов
    
    Args:
        entity_types: Типы сущностей через запятую:
            - dates: даты (договоры, сроки, события)
            - amounts: суммы (цены, штрафы, пени)
            - persons: имена людей (стороны, представители)
            - organizations: организации (компании, суды)
    
    Returns:
        Структурированный список найденных сущностей по категориям
    """
    global _rag_service, _case_id, _db, _used_sources, _sources_locked, _last_direct_result

    if not _rag_service or not _case_id:
        return "Ошибка: сервис не инициализирован"
    
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Load ALL files directly from DB — guarantees 100% coverage of every document.
        # Vector search (k=50) was previously used but could miss documents with low
        # query similarity, causing incomplete entity lists.
        from app.models.case import File as FileModel
        all_files = _db.query(FileModel).filter(FileModel.case_id == _case_id).all()
        files_with_text = [f for f in all_files if f.original_text]

        if not files_with_text:
            return "Документы не найдены для извлечения данных."

        file_order = [f.filename for f in files_with_text]

        # Build numbered per-file context: [N] filename:\n <text>
        context_parts = []
        for i, f in enumerate(files_with_text, 1):
            context_parts.append(f"[{i}] {f.filename}:\n{f.original_text[:1500]}")
        context = "\n\n".join(context_parts)[:12000]

        # Парсим типы сущностей
        types_list = [t.strip() for t in entity_types.split(",")]

        prompt = f"""Извлеки из текста следующие сущности: {', '.join(types_list)}

Текст документов (каждый помечен [N] — номером источника):
{context}

ВАЖНО: После каждого найденного факта указывай [N] — номер документа-источника прямо в тексте.
Пример: "Абумов Евгений Геннадьевич [1]: исполнитель" или "26 января 2026 года [2]: дата подачи КП"

Формат ответа (только запрошенные категории):
"""
        if "dates" in types_list:
            prompt += "\n📅 ДАТЫ:\n- [дата] [N]: [контекст/событие]"
        if "amounts" in types_list:
            prompt += "\n\n💰 СУММЫ:\n- [сумма] [N]: [контекст]"
        if "persons" in types_list:
            prompt += "\n\n👤 ЛИЦА:\n- [имя] [N]: [роль]"
        if "organizations" in types_list:
            prompt += "\n\n🏢 ОРГАНИЗАЦИИ:\n- [название] [N]: [роль]"

        prompt += "\n\nЕсли сущность не найдена — напиши 'не найдено'."

        llm = create_legal_llm()
        response = llm.invoke([
            SystemMessage(content="Ты извлекаешь структурированную информацию из юридических документов. Будь точен."),
            HumanMessage(content=prompt)
        ])

        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[UniversalTools] extract_structured_data: извлечены {entity_types}")

        # Build per-document text and metadata maps (same pattern as search_in_documents)
        doc_texts_map_esd: dict = {f.filename: f.original_text or '' for f in files_with_text}
        source_meta_map_esd: dict = {
            f.filename: {
                "source_id": str(f.id),
                "page": None,
                "chunk_excerpt": _first_content_line(f.original_text or ''),
            }
            for f in files_with_text
        }

        # Expand per-fact citations — each [N] badge gets its own unique highlight
        result, per_fact_sources = _expand_per_fact_citations(
            result, file_order, doc_texts_map_esd, source_meta_map_esd
        )
        if not _sources_locked:
            _used_sources = []
            _used_sources.extend(per_fact_sources)
            logger.info(f"[UniversalTools] extract_structured_data: {len(per_fact_sources)} per-fact citations built")

        # Store for direct streaming (bypasses GigaChat's outer synthesis)
        _last_direct_result = result

        return result

    except Exception as e:
        logger.error(f"[UniversalTools] extract_structured_data error: {e}")
        return f"Ошибка извлечения данных: {str(e)}"


@tool
def compare_documents(doc1_name: str, doc2_name: str) -> str:
    """
    Сравнить два документа и найти различия/противоречия.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь просит сравнить документы
    - Нужно найти противоречия между документами
    - Вопросы типа "чем отличается договор от акта"
    
    Args:
        doc1_name: Имя первого документа (или часть имени)
        doc2_name: Имя второго документа (или часть имени)
    
    Returns:
        Сравнительный анализ двух документов с указанием различий
    """
    global _db, _case_id, _rag_service
    
    if not _db or not _case_id:
        return "Ошибка: база данных не инициализирована"
    
    try:
        from app.models.case import File as FileModel
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Получаем все файлы
        files = _db.query(FileModel).filter(FileModel.case_id == _case_id).all()
        
        if not files:
            return "В деле нет документов для сравнения."
        
        # Ищем первый документ
        doc1 = None
        doc1_name_lower = doc1_name.lower()
        for f in files:
            if doc1_name_lower in f.filename.lower():
                doc1 = f
                break
        
        # Ищем второй документ
        doc2 = None
        doc2_name_lower = doc2_name.lower()
        for f in files:
            if doc2_name_lower in f.filename.lower():
                doc2 = f
                break
        
        if not doc1:
            return f"Документ '{doc1_name}' не найден."
        if not doc2:
            return f"Документ '{doc2_name}' не найден."
        
        # Получаем тексты (ограничиваем размер)
        text1 = (doc1.original_text or "")[:6000]
        text2 = (doc2.original_text or "")[:6000]
        
        prompt = f"""Сравни два документа и найди:
1. Ключевые различия
2. Противоречия (если есть)
3. Общие элементы

ДОКУМЕНТ 1: {doc1.filename}
{text1}

ДОКУМЕНТ 2: {doc2.filename}
{text2}

Дай структурированный сравнительный анализ."""

        llm = create_legal_llm()
        response = llm.invoke([
            SystemMessage(content="Ты юридический аналитик. Сравниваешь документы и находишь различия."),
            HumanMessage(content=prompt)
        ])
        
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[UniversalTools] compare_documents: {doc1.filename} vs {doc2.filename}")
        
        return f"📊 **Сравнение документов**\n\n{result}"
        
    except Exception as e:
        logger.error(f"[UniversalTools] compare_documents error: {e}")
        return f"Ошибка сравнения: {str(e)}"


# =============================================================================
# БЛОК 2: ЗАКОНЫ (2 инструмента)
# =============================================================================

def _run_async(coro, timeout: int = 40):
    """Run an async coroutine from sync context (handles running event loops)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, coro).result(timeout=timeout)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@tool
def search_legal_db(query: str, max_results: int = 5) -> str:
    """
    Поиск НПА на pravo.gov.ru с синтезом ответа из реального текста закона.

    КОГДА ИСПОЛЬЗОВАТЬ:
    - Нужен закон, постановление, приказ, кодекс или иной НПА
    - Пользователь просит проверить соответствие документа законодательству
    - Нужно сравнить положения документа с официальными нормами права

    НЕ ИСПОЛЬЗОВАТЬ:
    - Для поиска в документах пользователя (используй search_in_documents)

    ВАЖНО — стратегия поиска:
    - Если знаешь номер закона — ОБЯЗАТЕЛЬНО укажи его в query (например "127-ФЗ", "44-ФЗ")
    - Без номера — поиск по тематическому блоку (суд, правительство, банкротство и т.д.)

    Args:
        query: Запрос. Примеры: "127-ФЗ несостоятельность", "44-ФЗ контрактная система"
        max_results: Количество НПА для поиска (1-10)

    Returns:
        Ответ на основе текста найденных НПА с реальными ссылками
    """
    from app.services.external_sources.pravo_source import PravoSource
    from app.services.llm_factory import create_legal_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    global _used_sources, _sources_locked, _last_direct_result

    logger.info("[UniversalTools] search_legal_db: %s...", query[:60])

    source = PravoSource()

    # 1. Search pravo.gov.ru
    results = _run_async(
        source.search(query=query, max_results=min(10, max(1, max_results))),
        timeout=25,
    )
    if not results:
        return (
            f"На портале publication.pravo.gov.ru по запросу «{query}» документов не найдено.\n\n"
            f"Портал содержит официально опубликованные нормативные акты с 2011 года. "
            f"Если вас интересует полный текст кодекса или более раннего закона, "
            f"воспользуйтесь КонсультантПлюс (consultant.ru) или Гарант (garant.ru).\n\n"
            f"При необходимости вы также можете задать этот же вопрос ассистенту без режима Pravo.gov.ru — "
            f"он ответит на основе своих знаний о российском законодательстве."
        )

    logger.info(
        "[UniversalTools] search_legal_db: ✅ found %d results on pravo.gov.ru for %r",
        len(results), query[:60],
    )
    for i, r in enumerate(results[:3], 1):
        eo = r.metadata.get("eo_number", "")
        logger.info(
            "[UniversalTools] search_legal_db:   [%d] %s | eo=%s | url=%s",
            i, (r.metadata.get("complex_name") or r.title)[:80], eo, r.url,
        )

    # 2. Download document text for top 2 documents (PDF → HTML fallback inside get_document_text)
    async def _fetch_texts():
        tasks = [source.get_document_text(r.metadata["eo_number"]) for r in results[:2] if r.metadata.get("eo_number")]
        import asyncio
        return await asyncio.gather(*tasks, return_exceptions=True)

    texts = _run_async(_fetch_texts(), timeout=70)

    # 3. Build numbered context
    context_parts = []
    valid_results = []
    text_idx = 0
    for r in results[:2]:
        eo = r.metadata.get("eo_number", "")
        if not eo:
            continue
        doc_text = texts[text_idx] if text_idx < len(texts) else None
        text_idx += 1
        title = r.metadata.get("complex_name") or r.title
        if isinstance(doc_text, Exception) or not doc_text:
            # Fallback: use metadata from search result (title + dates) so the inner LLM
            # can produce a useful answer instead of "информация отсутствует"
            doc_date = r.metadata.get("doc_date", "")
            view_date = r.metadata.get("view_date", "")
            doc_text = (
                f"{title}\n"
                f"Дата подписания: {doc_date}\n"
                f"Дата официального опубликования: {view_date}\n"
                f"Источник: http://publication.pravo.gov.ru/Document/View/{eo}"
            )
            logger.info(
                "[UniversalTools] search_legal_db: ⚠️ no text for %s, using metadata as context", eo
            )
        else:
            logger.info(
                "[UniversalTools] search_legal_db: 📄 got text for %s: %d chars", eo, len(doc_text)
            )
        context_parts.append(f"[{len(valid_results)+1}] {title}:\n{doc_text[:4000]}")
        valid_results.append((r, doc_text))

    if not valid_results:
        # Fallback: return list without synthesis
        parts = [f"[{i}] {r.title} — {r.url}" for i, r in enumerate(results[:5], 1)]
        return "Найдено на pravo.gov.ru:\n" + "\n".join(parts)

    context = "\n\n---\n\n".join(context_parts)
    file_order = [r.metadata.get("complex_name") or r.title for r, _ in valid_results]

    # 4. Inner LLM synthesis
    system_msg = (
        "Ты юридический ассистент. Отвечай ТОЛЬКО на основе данных из документов ниже. "
        "Если есть полный текст — цитируй конкретные положения. "
        "Если есть только метаданные — сообщи название, дату и ссылку документа. "
        "Каждый факт или упоминание документа заканчивай [N] — номером источника. "
        "ВАЖНО: если в ПРИМЕЧАНИИ указано, что полный текст кодекса недоступен на портале — "
        "сообщи об этом честно: укажи, что портал publication.pravo.gov.ru содержит только поправки к данному кодексу, "
        "а полный актуальный текст можно найти на КонсультантПлюс или Гарант. "
        "Перечисли найденные поправки с датами [N]. Не отвечай на вопрос из собственных знаний."
    )
    user_msg = (
        f"Найденные документы на pravo.gov.ru (каждый помечен [N]):\n\n{context}\n\n"
        f"Запрос пользователя: {query}\n\n"
        f"Ответь по существу. После каждого упоминания документа или факта ставь [N]. "
        f"Пример: «Федеральный закон №273-ФЗ «Об образовании» принят 29.12.2012 [1]»."
    )

    try:
        llm = create_legal_llm()
        resp = llm.invoke([SystemMessage(content=system_msg), HumanMessage(content=user_msg)])
        synthesized = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        logger.error("[UniversalTools] search_legal_db synthesis error: %s", exc)
        synthesized = "\n".join(f"[{i+1}] {r.title}" for i, (r, _) in enumerate(valid_results))

    # 5. Build _used_sources with real pravo.gov.ru URLs (one per document, external type)
    if not _sources_locked:
        _used_sources = []
        for i, (r, _) in enumerate(valid_results):
            eo = r.metadata.get("eo_number", "")
            url = f"http://publication.pravo.gov.ru/Document/View/{eo}"
            _used_sources.append({
                "source_id": eo,
                "file_name": r.metadata.get("complex_name") or r.title,
                "page": None,
                "quote": None,
                "url": url,
                "source_type": "external",
            })
        logger.info("[UniversalTools] search_legal_db: %d external sources set", len(_used_sources))

    # 6. Re-number [N] markers to match _used_sources indices (1-based)
    # For external sources we keep the mapping simple: [1] → source 0, [2] → source 1
    _last_direct_result = synthesized
    return synthesized


@tool
def get_legal_document(eo_number: str) -> str:
    """
    Получить полный текст нормативного акта с портала pravo.gov.ru.

    КОГДА ИСПОЛЬЗОВАТЬ:
    - После search_legal_db, когда нужен полный текст конкретного НПА
    - Для детального анализа конкретной статьи закона

    Args:
        eo_number: Номер электронного опубликования из результатов search_legal_db

    Returns:
        Полный текст НПА (из PDF)
    """
    from app.services.external_sources.pravo_source import PravoSource
    global _used_sources, _sources_locked, _last_direct_result

    logger.info("[UniversalTools] get_legal_document: %s", eo_number)

    source = PravoSource()

    async def _fetch():
        import asyncio
        meta, text = await asyncio.gather(
            source.get_document_metadata(eo_number),
            source.get_document_text(eo_number),
        )
        return meta, text

    try:
        meta, text = _run_async(_fetch(), timeout=45)
    except Exception as exc:
        logger.error("[UniversalTools] get_legal_document error: %s", exc)
        return f"Ошибка получения документа: {exc}"

    if not meta and not text:
        logger.warning("[UniversalTools] get_legal_document: ⚠️ not found: %s", eo_number)
        return f"Документ с номером {eo_number} не найден."

    title = (meta or {}).get("complexName") or (meta or {}).get("name") or eo_number
    url = f"https://publication.pravo.gov.ru/Document/View/{eo_number}"

    logger.info(
        "[UniversalTools] get_legal_document: ✅ %s | title=%s | text=%d chars",
        eo_number, title[:80], len(text) if text else 0,
    )

    if not _sources_locked:
        _used_sources = [{
            "source_id": eo_number,
            "file_name": title,
            "page": None,
            "quote": None,
            "url": url,
            "source_type": "external",
        }]
        logger.info("[UniversalTools] get_legal_document: external source set → %s", url)

    if text:
        result = f"**{title}**\n{url}\n\n{text}"
    else:
        # No text — return metadata so the agent can still report the document was found
        doc_date = (meta or {}).get("documentDate", "")[:10]
        result = (
            f"**{title}**\n"
            f"Дата: {doc_date}\n"
            f"Ссылка: {url}\n\n"
            f"(Полный текст документа доступен по ссылке выше. "
            f"Автоматическое извлечение текста недоступно — документ является сканом.)"
        )
    _last_direct_result = result
    return result


# =============================================================================
# БЛОК 3: ГЕНЕРАЦИЯ ДОКУМЕНТОВ (2 инструмента)
# =============================================================================

@tool
def generate_document(doc_type: str, variables: str = "") -> str:
    """
    Создать черновик юридического документа.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь просит создать/составить документ
    - Нужен черновик договора, иска, претензии
    - Вопросы типа "составь", "напиши", "создай"
    
    Args:
        doc_type: Тип документа:
            - contract: договор
            - claim: исковое заявление
            - pretension: претензия
            - letter: деловое письмо
            - memo: служебная записка
            - power_of_attorney: доверенность
            - agreement: соглашение
            - protocol: протокол
            - act: акт
        variables: Переменные для документа в формате "ключ=значение; ключ2=значение2"
            Например: "истец=ООО Ромашка; ответчик=ИП Иванов; сумма=100000"
    
    Returns:
        Черновик документа в формате Markdown
    """
    global _db, _case_id, _rag_service
    
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Парсим переменные
        vars_dict = {}
        if variables:
            for pair in variables.split(";"):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    vars_dict[key.strip()] = value.strip()
        
        # Получаем контекст из документов дела (если есть)
        context = ""
        if _rag_service and _case_id and _db:
            try:
                docs = _rag_service.retrieve_context(
                    case_id=_case_id,
                    query=f"информация для {doc_type}",
                    k=10,
                    db=_db
                )
                if docs:
                    context = "\n".join([d.page_content for d in docs])[:4000]
            except:
                pass
        
        # Шаблоны разделов для разных типов
        templates = {
            "contract": ["Преамбула", "Предмет договора", "Права и обязанности", "Цена и расчёты", "Ответственность", "Срок действия", "Реквизиты"],
            "claim": ["Наименование суда", "Истец", "Ответчик", "Цена иска", "Обстоятельства", "Правовое обоснование", "Просительная часть", "Приложения"],
            "pretension": ["Адресат", "От кого", "Обстоятельства", "Требования", "Срок ответа", "Последствия"],
            "letter": ["Адресат", "Тема", "Вступление", "Основная часть", "Заключение"],
            "memo": ["Адресат", "От кого", "Тема", "Содержание", "Предложения"],
            "power_of_attorney": ["Доверитель", "Представитель", "Полномочия", "Срок действия"],
            "agreement": ["Стороны", "Предмет", "Условия", "Ответственность", "Заключительные положения"],
            "protocol": ["Дата и место", "Присутствующие", "Повестка дня", "Слушали", "Решили"],
            "act": ["Наименование", "Дата", "Комиссия", "Установлено", "Заключение"]
        }
        
        sections = templates.get(doc_type, ["Введение", "Основная часть", "Заключение"])
        
        prompt = f"""Создай профессиональный юридический документ.

ТИП: {doc_type}
РАЗДЕЛЫ: {', '.join(sections)}

ПЕРЕМЕННЫЕ:
{chr(10).join([f'- {k}: {v}' for k, v in vars_dict.items()]) if vars_dict else 'Не указаны'}

КОНТЕКСТ ИЗ ДЕЛА:
{context if context else 'Нет контекста'}

Требования:
1. Официальный юридический стиль
2. Все обязательные разделы
3. Корректная терминология
4. Места для подписей и дат
5. Формат Markdown

Создай полный текст документа:"""

        llm = create_legal_llm()
        response = llm.invoke([
            SystemMessage(content="Ты опытный юрист, составляющий юридические документы."),
            HumanMessage(content=prompt)
        ])
        
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[UniversalTools] generate_document: {doc_type}")
        
        return f"📝 **Черновик документа: {doc_type}**\n\n{result}\n\n---\n⚠️ *Это черновик. Проверьте и отредактируйте перед использованием.*"
        
    except Exception as e:
        logger.error(f"[UniversalTools] generate_document error: {e}")
        return f"Ошибка создания документа: {str(e)}"


@tool
def list_templates() -> str:
    """
    Показать доступные шаблоны документов.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь спрашивает "какие шаблоны есть"
    - Перед созданием документа (чтобы выбрать тип)
    - Нужен список доступных типов документов
    
    Returns:
        Список доступных шаблонов с описаниями
    """
    templates = """
📋 **Доступные шаблоны документов:**

**Договоры и соглашения:**
- `contract` — Договор (купли-продажи, поставки, услуг и др.)
- `agreement` — Соглашение (мировое, о сотрудничестве и др.)

**Судебные документы:**
- `claim` — Исковое заявление
- `pretension` — Претензия (досудебная)

**Деловая переписка:**
- `letter` — Деловое письмо
- `memo` — Служебная записка

**Прочие документы:**
- `power_of_attorney` — Доверенность
- `protocol` — Протокол (собрания, заседания)
- `act` — Акт (приёма-передачи, сверки и др.)

---
💡 Для создания документа используй: `generate_document(doc_type, variables)`

Пример: `generate_document("claim", "истец=ООО Ромашка; ответчик=ИП Иванов; сумма=100000")`
"""
    logger.info("[UniversalTools] list_templates called")
    return templates


# =============================================================================
# БЛОК 4: PLAYBOOK (2 инструмента)
# =============================================================================

# Global to store last playbook check result for SSE emission by assistant runtime
_last_playbook_check: Optional[Dict] = None


def get_last_playbook_check() -> Optional[Dict]:
    """Get and return the last playbook check result (for SSE emission)."""
    global _last_playbook_check
    return _last_playbook_check


def clear_last_playbook_check() -> None:
    """Clear the stored playbook check result after it's been emitted."""
    global _last_playbook_check
    _last_playbook_check = None


def _run_async_in_new_loop(coro):
    """Run an async coroutine in a new thread with its own event loop (sync wrapper)."""
    import concurrent.futures

    def _run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(_run).result(timeout=120)


def _format_playbook_check_markdown(result, doc_name: str, playbook_name: str) -> str:
    """Format a PlaybookCheckResult as rich markdown for chat display."""
    score = result.compliance_score

    if score >= 80:
        score_label = "✅ Соответствует"
    elif score >= 50:
        score_label = "⚠️ Требует доработки"
    else:
        score_label = "❌ Критичные нарушения"

    lines = [
        f"## 📋 Проверка: {doc_name}",
        f"**Playbook:** {playbook_name} | **Соответствие: {score:.0f}%** — {score_label}",
        "",
        f"🟢 Прошло: **{result.passed_rules}** | "
        f"🔴 Нарушения: **{result.red_line_violations}** | "
        f"🟡 Замечания: **{result.fallback_issues}** | "
        f"🚫 Запреты: **{result.no_go_violations}**",
        "",
        "---",
    ]

    # Red line violations (must fix)
    violations = [
        r for r in result.results
        if r.status in ('violation', 'not_found') and r.rule_type in ('red_line', 'standard')
    ]
    if violations:
        lines.append("### 🔴 Нарушения (обязательно исправить)")
        lines.append("")
        for i, r in enumerate(violations, 1):
            lines.append(f"**{i}. {r.rule_name}**")
            if r.found_text:
                preview = r.found_text[:200].replace('\n', ' ')
                lines.append(f"> _{preview}_")
            else:
                lines.append("> _(Не найдено в документе)_")
            if r.issue_description:
                lines.append(f"- ❌ {r.issue_description}")
            if r.suggested_fix:
                fix = r.suggested_fix[:300].replace('\n', ' ')
                lines.append(f"- ✅ **Рекомендация:** _{fix}_")
            lines.append("")

    # No-go violations
    no_go = [
        r for r in result.results
        if r.rule_type == 'no_go' and r.status in ('violation', 'not_found')
    ]
    if no_go:
        lines.append("### 🚫 Недопустимые условия")
        lines.append("")
        for i, r in enumerate(no_go, 1):
            lines.append(f"**{i}. {r.rule_name}**")
            if r.found_text:
                preview = r.found_text[:200].replace('\n', ' ')
                lines.append(f"> _{preview}_")
            if r.issue_description:
                lines.append(f"- ❌ {r.issue_description}")
            lines.append("")

    # Fallback issues (negotiable)
    fallbacks = [
        r for r in result.results
        if r.rule_type == 'fallback' and r.status not in ('passed',)
    ]
    if fallbacks:
        lines.append("### 🟡 Рекомендации (можно доработать)")
        lines.append("")
        for i, r in enumerate(fallbacks, 1):
            lines.append(f"**{i}. {r.rule_name}**")
            if r.found_text:
                preview = r.found_text[:200].replace('\n', ' ')
                lines.append(f"> _{preview}_")
            if r.issue_description:
                lines.append(f"- ⚠️ {r.issue_description}")
            if r.suggested_fix:
                fix = r.suggested_fix[:300].replace('\n', ' ')
                lines.append(f"- 💡 **Вариант:** _{fix}_")
            lines.append("")

    # Passed rules
    passed = [r for r in result.results if r.status == 'passed']
    if passed:
        lines.append(f"### 🟢 Выполнено ({len(passed)})")
        for r in passed:
            lines.append(f"- ✅ {r.rule_name}")
        lines.append("")

    return "\n".join(lines)


@tool
def validate_with_playbook(document_name: str, playbook_name: str = "") -> str:
    """
    Проверить документ на соответствие правилам Playbook.

    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь просит проверить документ по правилам
    - Нужен compliance check
    - Вопросы типа "проверь договор", "соответствует ли..."

    Args:
        document_name: Имя документа для проверки
        playbook_name: Имя playbook (опционально, если не указано - используется первый доступный)

    Returns:
        Результат проверки с указанием нарушений и рекомендаций
    """
    global _db, _case_id, _user_id, _last_playbook_check

    if not _db or not _case_id:
        return "Ошибка: база данных не инициализирована"

    try:
        from app.models.case import File as FileModel
        from app.services.playbook_service import PlaybookService
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        # Find document in the case
        files = _db.query(FileModel).filter(FileModel.case_id == _case_id).all()
        doc = None
        doc_name_lower = document_name.lower()
        for f in files:
            if doc_name_lower in f.filename.lower():
                doc = f
                break
        if not doc:
            # Try word-by-word partial match
            for f in files:
                if any(w in f.filename.lower() for w in doc_name_lower.split() if len(w) > 3):
                    doc = f
                    break

        if not doc:
            available = ", ".join(f.filename for f in files[:5]) if files else "нет документов"
            return f"Документ '{document_name}' не найден. Доступны: {available}"

        # Get available playbooks
        playbook_service = PlaybookService(_db)
        playbooks = playbook_service.get_playbooks(
            user_id=_user_id or "system",
            include_system=True,
            include_public=True,
            limit=20
        )

        if not playbooks:
            # Fall back to LLM-based check when no playbooks exist
            text = (doc.original_text or "")[:8000]
            llm = create_legal_llm()
            response = llm.invoke([
                SystemMessage(content="Ты юридический аудитор. Проверяешь документы на типичные юридические проблемы."),
                HumanMessage(content=f"Проверь документ:\n\nДОКУМЕНТ: {doc.filename}\n{text}\n\n"
                             "Проверь: 1) Полноту обязательных разделов 2) Корректность формулировок "
                             "3) Наличие существенных условий 4) Потенциальные риски.\n\n"
                             "Дай структурированный отчёт с конкретными рекомендациями.")
            ])
            result = response.content if hasattr(response, 'content') else str(response)
            return f"✅ **Проверка документа: {doc.filename}**\n\n{result}"

        # Select playbook by name or use the first available
        selected = None
        if playbook_name:
            for p in playbooks:
                if (playbook_name.lower() in p.get('name', '').lower() or
                        playbook_name.lower() in p.get('display_name', '').lower()):
                    selected = p
                    break
        if not selected:
            selected = playbooks[0]

        playbook_display = selected.get('display_name') or selected.get('name', 'Playbook')
        logger.info(f"[UniversalTools] Running PlaybookChecker: doc={doc.filename}, playbook={playbook_display}")

        # Run the full PlaybookChecker (async, executed in a new thread)
        try:
            from app.services.playbook_checker import PlaybookChecker
            checker = PlaybookChecker(_db)
            check_result = _run_async_in_new_loop(
                checker.check_document(
                    document_id=doc.id,
                    playbook_id=selected['id'],
                    user_id=_user_id or 'system',
                    case_id=_case_id
                )
            )

            # Store structured result for SSE emission by assistant runtime
            _last_playbook_check = {
                'check_id': check_result.check_id,
                'playbook_id': check_result.playbook_id,
                'playbook_name': playbook_display,
                'document_id': check_result.document_id,
                'document_name': doc.filename,
                'overall_status': check_result.overall_status,
                'compliance_score': float(check_result.compliance_score),
                'red_line_violations': check_result.red_line_violations,
                'fallback_issues': check_result.fallback_issues,
                'no_go_violations': check_result.no_go_violations,
                'passed_rules': check_result.passed_rules,
                'results': [
                    {
                        'rule_id': r.rule_id,
                        'rule_name': r.rule_name,
                        'rule_type': r.rule_type,
                        'status': r.status,
                        'issue_description': r.issue_description,
                        'suggested_fix': r.suggested_fix,
                        'found_text': (r.found_text or '')[:300],
                        'confidence': r.confidence,
                    }
                    for r in check_result.results
                ],
            }

            logger.info(
                f"[UniversalTools] PlaybookChecker done: score={check_result.compliance_score:.0f}%, "
                f"violations={check_result.red_line_violations}, issues={check_result.fallback_issues}"
            )
            return _format_playbook_check_markdown(check_result, doc.filename, playbook_display)

        except Exception as checker_error:
            logger.warning(f"[UniversalTools] PlaybookChecker failed ({checker_error}), falling back to LLM check")
            # Fallback to LLM-based check
            text = (doc.original_text or "")[:8000]
            llm = create_legal_llm()
            response = llm.invoke([
                SystemMessage(content="Ты юридический аудитор."),
                HumanMessage(content=f"Проверь документ '{doc.filename}' по правилам playbook '{playbook_display}':\n{text}")
            ])
            return f"✅ **Проверка документа: {doc.filename}**\n\n" + (
                response.content if hasattr(response, 'content') else str(response)
            )

    except Exception as e:
        logger.error(f"[UniversalTools] validate_with_playbook error: {e}", exc_info=True)
        return f"Ошибка проверки: {str(e)}"


@tool
def get_user_playbooks() -> str:
    """
    Получить список доступных Playbooks (наборов правил).
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Пользователь спрашивает "какие правила есть"
    - Перед проверкой документа
    - Нужен список доступных playbooks
    
    Returns:
        Список playbooks с описаниями
    """
    global _db, _user_id
    
    if not _db:
        return "Ошибка: база данных не инициализирована"
    
    try:
        from app.services.playbook_service import PlaybookService
        
        playbook_service = PlaybookService(_db)
        playbooks = playbook_service.get_playbooks(
            user_id=_user_id or "system",
            include_system=True,
            include_public=True,
            limit=20
        )
        
        if not playbooks:
            return "📋 Playbooks не найдены.\n\nСоздайте Playbook в разделе настроек для автоматической проверки документов."
        
        result = "📋 **Доступные Playbooks:**\n\n"
        for p in playbooks:
            name = p.get("name", "Без названия")
            desc = p.get("description", "")[:100]
            doc_type = p.get("document_type", "all")
            rules_count = p.get("rules_count", 0)
            
            result += f"**{name}**\n"
            if desc:
                result += f"  {desc}\n"
            result += f"  Тип: {doc_type} | Правил: {rules_count}\n\n"
        
        logger.info(f"[UniversalTools] get_user_playbooks: {len(playbooks)} найдено")
        return result
        
    except Exception as e:
        logger.error(f"[UniversalTools] get_user_playbooks error: {e}")
        return f"Ошибка получения playbooks: {str(e)}"


# =============================================================================
# БЛОК 5: ВСПОМОГАТЕЛЬНЫЕ (2 инструмента)
# =============================================================================

@tool
def calculate(expression: str) -> str:
    """
    Выполнить юридические расчёты.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Расчёт процентов, пеней, неустоек
    - Расчёт сроков исковой давности
    - Арифметические операции с суммами
    - Вопросы типа "посчитай", "сколько будет", "какая сумма"
    
    Args:
        expression: Выражение для расчёта. Поддерживается:
            - Арифметика: "100000 * 0.1" (10% от 100000)
            - Проценты: "percent(100000, 10)" = 10000
            - Пени по ставке ЦБ: "penalty_cb(100000, 30)" = пени за 30 дней
            - Дни между датами: "days_between(01.01.2024, 31.01.2024)"
    
    Returns:
        Результат расчёта с пояснением
    """
    try:
        result_text = ""
        
        # Простая арифметика
        if re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expression.replace(',', '.')):
            expr = expression.replace(',', '.').replace(' ', '')
            result = eval(expr)
            result_text = f"🧮 **Результат:** {result:,.2f}".replace(',', ' ')
        
        # Расчёт процентов: percent(сумма, процент)
        elif expression.startswith("percent("):
            match = re.match(r'percent\((\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\)', expression)
            if match:
                amount = float(match.group(1))
                percent = float(match.group(2))
                result = amount * percent / 100
                result_text = f"🧮 **{percent}% от {amount:,.0f}** = {result:,.2f}".replace(',', ' ')
        
        # Пени по ставке ЦБ: penalty_cb(сумма, дни)
        elif expression.startswith("penalty_cb("):
            match = re.match(r'penalty_cb\((\d+(?:\.\d+)?),\s*(\d+)\)', expression)
            if match:
                amount = float(match.group(1))
                days = int(match.group(2))
                # Примерная ставка ЦБ (16% годовых)
                cb_rate = 16.0
                daily_rate = cb_rate / 365 / 100
                penalty = amount * daily_rate * days
                result_text = f"""🧮 **Расчёт пени по ставке ЦБ:**
- Сумма долга: {amount:,.0f} руб.
- Период: {days} дней
- Ставка ЦБ: {cb_rate}% годовых
- Дневная ставка: {daily_rate*100:.4f}%
- **Пени: {penalty:,.2f} руб.**""".replace(',', ' ')
        
        # Дни между датами: days_between(дата1, дата2)
        elif expression.startswith("days_between("):
            match = re.match(r'days_between\((\d{2}\.\d{2}\.\d{4}),\s*(\d{2}\.\d{2}\.\d{4})\)', expression)
            if match:
                date1 = datetime.strptime(match.group(1), "%d.%m.%Y")
                date2 = datetime.strptime(match.group(2), "%d.%m.%Y")
                days = abs((date2 - date1).days)
                result_text = f"🧮 **Дней между {match.group(1)} и {match.group(2)}:** {days}"
        
        if not result_text:
            result_text = f"""🧮 **Калькулятор**

Не удалось распознать выражение: `{expression}`

**Поддерживаемые форматы:**
- Арифметика: `100000 * 0.1`
- Проценты: `percent(100000, 10)` = 10% от 100000
- Пени по ставке ЦБ: `penalty_cb(100000, 30)` = пени за 30 дней
- Дни между датами: `days_between(01.01.2024, 31.01.2024)`"""
        
        logger.info(f"[UniversalTools] calculate: {expression[:50]}")
        return result_text
        
    except Exception as e:
        logger.error(f"[UniversalTools] calculate error: {e}")
        return f"Ошибка расчёта: {str(e)}\n\nПроверьте формат выражения."


@tool
def get_current_date() -> str:
    """
    Получить текущую дату и время.
    
    КОГДА ИСПОЛЬЗОВАТЬ:
    - Нужна текущая дата для документа
    - Расчёт сроков от текущей даты
    - Проверка сроков исковой давности
    
    Returns:
        Текущая дата в разных форматах
    """
    now = datetime.now()
    
    result = f"""📅 **Текущая дата и время:**

- Полная: {now.strftime('%d.%m.%Y %H:%M:%S')}
- Дата: {now.strftime('%d.%m.%Y')}
- Для документов: «{now.strftime('%d')}» {_month_name(now.month)} {now.strftime('%Y')} г.
- ISO формат: {now.strftime('%Y-%m-%d')}
- День недели: {_weekday_name(now.weekday())}
"""
    
    logger.info("[UniversalTools] get_current_date called")
    return result


def _month_name(month: int) -> str:
    """Название месяца в родительном падеже"""
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    return months.get(month, "")


def _weekday_name(weekday: int) -> str:
    """Название дня недели"""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[weekday] if 0 <= weekday < 7 else ""


# =============================================================================
# ФАБРИКА ИНСТРУМЕНТОВ
# =============================================================================

def get_universal_tools(
    db: Session,
    rag_service,
    case_id: str,
    user_id: Optional[str] = None,
    legal_research: bool = False,
    web_search: bool = False,
    attached_file_ids: Optional[List[str]] = None,
    use_pro_llm: bool = False,
) -> List:
    """
    Получить набор из 12 универсальных инструментов.
    
    Args:
        db: SQLAlchemy сессия
        rag_service: RAG сервис
        case_id: ID дела
        user_id: ID пользователя (опционально)
        legal_research: Включить инструменты справочного правового поиска
        web_search: Включить веб-поиск (пока не реализован)
    
    Returns:
        Список из 12 инструментов
    """
    # Инициализируем глобальные зависимости
    initialize_universal_tools(
        db=db,
        rag_service=rag_service,
        case_id=case_id,
        user_id=user_id,
        attached_file_ids=attached_file_ids,
        use_pro_llm=use_pro_llm,
    )
    
    # Базовые инструменты (всегда доступны)
    tools = [
        # Блок 1: Документы
        get_document,
        search_in_documents,
        analyze_all_documents,  # Map-Reduce для глубокого анализа
        extract_structured_data,
        compare_documents,
        
        # Блок 3: Генерация
        generate_document,
        list_templates,
        
        # Блок 4: Playbook
        validate_with_playbook,
        get_user_playbooks,
        
        # Блок 5: Вспомогательные
        calculate,
        get_current_date,
    ]
    
    # Блок 2: Законы (опционально)
    if legal_research:
        tools.extend([
            search_legal_db,
            get_legal_document,
        ])
        logger.info("[UniversalTools] GARANT tools enabled")
    
    # Веб-поиск (опционально)
    if web_search:
        try:
            from app.services.langchain_agents.web_research_tool import web_research_tool
            tools.append(web_research_tool)
            logger.info("[UniversalTools] Web search tool enabled")
        except ImportError:
            logger.warning("[UniversalTools] Web search tool not available")
    
    logger.info(f"[UniversalTools] Initialized {len(tools)} tools for case {case_id}")
    return tools

