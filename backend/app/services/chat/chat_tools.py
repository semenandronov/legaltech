"""
Chat Tools - Инструменты для ReAct Chat Agent

Набор инструментов, которые агент выбирает САМ в зависимости от вопроса:
- search_documents: поиск по документам (k=5-100)
- list_case_files: список всех файлов в деле
- get_file_summary: краткое содержание файла
- summarize_all_documents: Map-Reduce суммаризация всех документов
- extract_entities: извлечь сущности (даты, имена, суммы)
- find_contradictions: найти противоречия
- analyze_risks: анализ рисков
- build_timeline: построить хронологию
- search_garant: поиск в GARANT (опционально)
- search_web: веб-поиск (опционально)
"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from sqlalchemy.orm import Session
import asyncio
import logging

logger = logging.getLogger(__name__)

# Глобальные зависимости (инжектируются при создании tools)
_db: Optional[Session] = None
_rag_service = None
_case_id: Optional[str] = None


def initialize_chat_tools(db: Session, rag_service, case_id: str):
    """Инициализировать глобальные зависимости для tools"""
    global _db, _rag_service, _case_id
    _db = db
    _rag_service = rag_service
    _case_id = case_id


# =============================================================================
# Основные инструменты поиска
# =============================================================================

@tool
def search_documents(query: str, k: int = 10) -> str:
    """
    Поиск по документам дела.
    
    Используй этот инструмент когда:
    - Нужно найти конкретную информацию в документах
    - Пользователь спрашивает о содержимом документов
    - Нужны факты, даты, суммы из документов
    
    Args:
        query: Поисковый запрос
        k: Количество документов для поиска (5-100, по умолчанию 10)
           Используй k=5 для простых вопросов
           Используй k=20-50 для сложных вопросов
           Используй k=100 для полного анализа
    
    Returns:
        Найденные фрагменты документов с источниками
    """
    global _rag_service, _case_id, _db
    
    if not _rag_service or not _case_id:
        return "Ошибка: сервис поиска не инициализирован"
    
    try:
        # Ограничиваем k разумными пределами
        k = max(5, min(100, k))
        
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query=query,
            k=k,
            retrieval_strategy="multi_query",
            db=_db
        )
        
        if not documents:
            return f"По запросу '{query}' документы не найдены."
        
        # Форматируем результаты
        formatted = _rag_service.format_sources_for_prompt(documents, max_context_chars=8000)
        logger.info(f"[ChatTools] search_documents: найдено {len(documents)} документов для '{query[:50]}...'")
        
        return formatted
        
    except Exception as e:
        logger.error(f"[ChatTools] search_documents error: {e}")
        return f"Ошибка поиска: {str(e)}"


@tool
def list_case_files() -> str:
    """
    Получить список всех файлов в деле.
    
    Используй этот инструмент когда:
    - Пользователь спрашивает "какие документы в деле?"
    - Нужно узнать, что загружено в дело
    - Перед обзором всех документов
    
    Returns:
        Список файлов с их типами и размерами
    """
    global _db, _case_id
    
    if not _db or not _case_id:
        return "Ошибка: база данных не инициализирована"
    
    try:
        from app.models.case import File as FileModel
        
        files = _db.query(FileModel).filter(
            FileModel.case_id == _case_id
        ).all()
        
        if not files:
            return "В деле нет загруженных документов."
        
        # Форматируем список файлов
        result_lines = [f"📁 **В деле {len(files)} документов:**\n"]
        
        for i, f in enumerate(files, 1):
            file_type = f.doc_type or "unknown"
            file_size = f.file_size or 0
            size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.1f} MB"
            
            result_lines.append(f"{i}. **{f.filename}**")
            result_lines.append(f"   - Тип: {file_type}")
            result_lines.append(f"   - Размер: {size_str}")
            if f.page_count:
                result_lines.append(f"   - Страниц: {f.page_count}")
        
        logger.info(f"[ChatTools] list_case_files: {len(files)} файлов")
        return "\n".join(result_lines)
        
    except Exception as e:
        logger.error(f"[ChatTools] list_case_files error: {e}")
        return f"Ошибка получения списка файлов: {str(e)}"


@tool
def get_file_summary(filename: str) -> str:
    """
    Получить краткое содержание конкретного файла.
    
    Используй этот инструмент когда:
    - Пользователь спрашивает о конкретном документе
    - Нужен обзор одного файла
    
    Args:
        filename: Имя файла (полное или частичное)
    
    Returns:
        Краткое содержание файла
    """
    global _db, _case_id, _rag_service
    
    if not _db or not _case_id:
        return "Ошибка: база данных не инициализирована"
    
    try:
        from app.models.case import File as FileModel
        
        # Ищем файл по имени (частичное совпадение)
        file = _db.query(FileModel).filter(
            FileModel.case_id == _case_id,
            FileModel.filename.ilike(f"%{filename}%")
        ).first()
        
        if not file:
            return f"Файл '{filename}' не найден в деле."
        
        # Получаем контент файла через RAG
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query=f"содержание документа {file.filename}",
            k=20,
            retrieval_strategy="multi_query",
            db=_db
        )
        
        if not documents:
            return f"Не удалось получить содержимое файла '{file.filename}'."
        
        # Фильтруем только документы из этого файла
        file_docs = [d for d in documents if d.metadata.get("source") == file.filename or d.metadata.get("file_id") == file.id]
        
        if not file_docs:
            file_docs = documents[:10]  # Fallback
        
        content = "\n".join([d.page_content for d in file_docs[:10]])
        
        result = f"📄 **{file.filename}**\n"
        result += f"Тип: {file.doc_type or 'не определён'}\n\n"
        result += f"**Содержание:**\n{content[:3000]}"
        
        if len(content) > 3000:
            result += "\n\n[... документ сокращён ...]"
        
        logger.info(f"[ChatTools] get_file_summary: {file.filename}")
        return result
        
    except Exception as e:
        logger.error(f"[ChatTools] get_file_summary error: {e}")
        return f"Ошибка получения содержимого файла: {str(e)}"


# =============================================================================
# Map-Reduce суммаризация
# =============================================================================

@tool
def summarize_all_documents() -> str:
    """
    Суммаризировать ВСЕ документы в деле (Map-Reduce).
    
    Используй этот инструмент когда:
    - Пользователь спрашивает "о чём все эти документы?"
    - Нужен общий обзор дела
    - Вопрос "что содержится в документах?"
    - Пользователь просит "расскажи о деле"
    
    ВАЖНО: Этот инструмент обрабатывает ВСЕ документы в деле,
    даже если их много (100+). Используй его для обзорных вопросов.
    
    Returns:
        Общий обзор всех документов в деле
    """
    global _db, _case_id, _rag_service
    
    if not _db or not _case_id:
        return "Ошибка: база данных не инициализирована"
    
    try:
        from app.models.case import File as FileModel
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # 1. Получаем все файлы
        files = _db.query(FileModel).filter(
            FileModel.case_id == _case_id
        ).all()
        
        if not files:
            return "В деле нет загруженных документов."
        
        logger.info(f"[ChatTools] summarize_all_documents: начинаем Map-Reduce для {len(files)} файлов")
        
        # 2. MAP: Суммаризируем каждый файл
        llm = create_legal_llm(temperature=0.1)
        file_summaries = []
        
        for file in files:
            try:
                # Получаем контент файла
                documents = _rag_service.retrieve_context(
                    case_id=_case_id,
                    query=f"полное содержание {file.filename}",
                    k=30,
                    retrieval_strategy="multi_query",
                    db=_db
                )
                
                # Фильтруем по файлу
                file_docs = [d for d in documents if 
                            d.metadata.get("source") == file.filename or 
                            d.metadata.get("file_id") == str(file.id)]
                
                if not file_docs:
                    file_docs = documents[:5]
                
                content = "\n".join([d.page_content for d in file_docs[:15]])[:4000]
                
                if not content.strip():
                    file_summaries.append({
                        "filename": file.filename,
                        "doc_type": file.doc_type or "unknown",
                        "summary": "Содержимое не извлечено"
                    })
                    continue
                
                # Суммаризируем файл
                summary_prompt = f"""Кратко опиши содержание документа (2-3 предложения):

Документ: {file.filename}
Тип: {file.doc_type or 'не определён'}

Содержание:
{content}

Краткое описание:"""
                
                response = llm.invoke([
                    SystemMessage(content="Ты юридический ассистент. Кратко описывай документы."),
                    HumanMessage(content=summary_prompt)
                ])
                
                summary_text = response.content if hasattr(response, 'content') else str(response)
                
                file_summaries.append({
                    "filename": file.filename,
                    "doc_type": file.doc_type or "unknown",
                    "summary": summary_text.strip()
                })
                
            except Exception as e:
                logger.warning(f"[ChatTools] Ошибка суммаризации {file.filename}: {e}")
                file_summaries.append({
                    "filename": file.filename,
                    "doc_type": file.doc_type or "unknown",
                    "summary": f"Ошибка обработки: {str(e)[:50]}"
                })
        
        # 3. REDUCE: Объединяем в общий обзор
        summaries_text = "\n\n".join([
            f"**{s['filename']}** ({s['doc_type']}): {s['summary']}"
            for s in file_summaries
        ])
        
        reduce_prompt = f"""На основе описаний всех документов дела, составь общий обзор:

{summaries_text}

Составь структурированный обзор дела:
1. О чём это дело (1-2 предложения)
2. Какие документы есть (перечисли основные)
3. Ключевые факты из документов
4. Общий вывод

Обзор:"""
        
        final_response = llm.invoke([
            SystemMessage(content="Ты юридический ассистент. Составляй структурированные обзоры дел."),
            HumanMessage(content=reduce_prompt)
        ])
        
        overview = final_response.content if hasattr(final_response, 'content') else str(final_response)
        
        result = f"📋 **Обзор дела ({len(files)} документов)**\n\n"
        result += overview
        result += f"\n\n---\n*Обработано документов: {len(file_summaries)}*"
        
        logger.info(f"[ChatTools] summarize_all_documents: завершено, {len(file_summaries)} файлов")
        return result
        
    except Exception as e:
        logger.error(f"[ChatTools] summarize_all_documents error: {e}", exc_info=True)
        return f"Ошибка создания обзора: {str(e)}"


# =============================================================================
# Аналитические инструменты
# =============================================================================

@tool
def extract_entities(entity_types: str = "all") -> str:
    """
    Извлечь сущности из документов (даты, имена, суммы, организации).
    
    Используй этот инструмент когда:
    - Пользователь спрашивает "какие даты в документах?"
    - Нужно найти все суммы или имена
    - Вопрос о конкретных фактах
    
    Args:
        entity_types: Типы сущностей через запятую: dates, persons, organizations, amounts, all
    
    Returns:
        Список извлечённых сущностей по типам
    """
    global _db, _case_id, _rag_service
    
    if not _rag_service or not _case_id:
        return "Ошибка: сервис не инициализирован"
    
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Получаем документы
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query="ключевые факты даты суммы имена организации",
            k=50,
            retrieval_strategy="multi_query",
            db=_db
        )
        
        if not documents:
            return "Документы не найдены для извлечения сущностей."
        
        content = "\n".join([d.page_content for d in documents])[:8000]
        
        llm = create_legal_llm(temperature=0.0)
        
        prompt = f"""Извлеки из текста следующие сущности:
- Даты (все упоминаемые даты)
- Суммы (денежные суммы)
- Лица (имена людей)
- Организации (названия компаний, органов)

Текст:
{content}

Формат ответа:
📅 ДАТЫ:
- дата1
- дата2

💰 СУММЫ:
- сумма1
- сумма2

👤 ЛИЦА:
- имя1
- имя2

🏢 ОРГАНИЗАЦИИ:
- организация1
- организация2

Извлечённые сущности:"""
        
        response = llm.invoke([
            SystemMessage(content="Ты извлекаешь структурированную информацию из юридических документов."),
            HumanMessage(content=prompt)
        ])
        
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[ChatTools] extract_entities: завершено")
        
        return result
        
    except Exception as e:
        logger.error(f"[ChatTools] extract_entities error: {e}")
        return f"Ошибка извлечения сущностей: {str(e)}"


@tool
def find_contradictions() -> str:
    """
    Найти противоречия между документами в деле.
    
    Используй этот инструмент когда:
    - Пользователь спрашивает о противоречиях
    - Нужно сравнить документы
    - Вопрос о несоответствиях
    
    Returns:
        Список найденных противоречий с указанием источников
    """
    global _db, _case_id, _rag_service
    
    if not _rag_service or not _case_id:
        return "Ошибка: сервис не инициализирован"
    
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Получаем документы с большим k для полного анализа
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query="факты даты суммы условия обязательства",
            k=100,
            retrieval_strategy="multi_query",
            db=_db
        )
        
        if not documents:
            return "Документы не найдены для анализа противоречий."
        
        content = "\n\n".join([
            f"[{d.metadata.get('source', 'unknown')}]: {d.page_content}"
            for d in documents
        ])[:12000]
        
        llm = create_legal_llm(temperature=0.1)
        
        prompt = f"""Проанализируй документы и найди противоречия:

{content}

Найди:
1. Противоречия в датах между документами
2. Противоречия в суммах
3. Противоречия в фактах
4. Несоответствия в условиях

Для каждого противоречия укажи:
- Что противоречит
- В каких документах
- Суть противоречия

Если противоречий нет, напиши "Явных противоречий не обнаружено".

Результат анализа:"""
        
        response = llm.invoke([
            SystemMessage(content="Ты юридический аналитик. Находишь противоречия в документах."),
            HumanMessage(content=prompt)
        ])
        
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[ChatTools] find_contradictions: завершено")
        
        return f"🔍 **Анализ противоречий**\n\n{result}"
        
    except Exception as e:
        logger.error(f"[ChatTools] find_contradictions error: {e}")
        return f"Ошибка анализа противоречий: {str(e)}"


@tool
def analyze_risks() -> str:
    """
    Проанализировать юридические риски в деле.
    
    Используй этот инструмент когда:
    - Пользователь спрашивает о рисках
    - Нужна оценка правовых рисков
    - Вопрос "какие риски?"
    
    Returns:
        Анализ рисков с оценкой серьёзности
    """
    global _db, _case_id, _rag_service
    
    if not _rag_service or not _case_id:
        return "Ошибка: сервис не инициализирован"
    
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Получаем документы
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query="условия обязательства ответственность сроки штрафы риски",
            k=50,
            retrieval_strategy="multi_query",
            db=_db
        )
        
        if not documents:
            return "Документы не найдены для анализа рисков."
        
        content = "\n".join([d.page_content for d in documents])[:8000]
        
        llm = create_legal_llm(temperature=0.1)
        
        prompt = f"""Проанализируй юридические риски на основе документов:

{content}

Оцени риски по категориям:
1. 🔴 Высокие риски (критичные)
2. 🟡 Средние риски (требуют внимания)
3. 🟢 Низкие риски (незначительные)

Для каждого риска укажи:
- Описание риска
- Возможные последствия
- Рекомендации по минимизации

Анализ рисков:"""
        
        response = llm.invoke([
            SystemMessage(content="Ты юридический аналитик. Оцениваешь правовые риски."),
            HumanMessage(content=prompt)
        ])
        
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[ChatTools] analyze_risks: завершено")
        
        return f"⚠️ **Анализ рисков**\n\n{result}"
        
    except Exception as e:
        logger.error(f"[ChatTools] analyze_risks error: {e}")
        return f"Ошибка анализа рисков: {str(e)}"


@tool
def build_timeline() -> str:
    """
    Построить хронологию событий из документов.
    
    Используй этот инструмент когда:
    - Пользователь спрашивает о хронологии
    - Нужно восстановить последовательность событий
    - Вопрос "когда что произошло?"
    
    Returns:
        Хронология событий с датами
    """
    global _db, _case_id, _rag_service
    
    if not _rag_service or not _case_id:
        return "Ошибка: сервис не инициализирован"
    
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        
        # Получаем документы с фокусом на даты
        documents = _rag_service.retrieve_context(
            case_id=_case_id,
            query="дата событие произошло заключен подписан направлен получен",
            k=50,
            retrieval_strategy="multi_query",
            db=_db
        )
        
        if not documents:
            return "Документы не найдены для построения хронологии."
        
        content = "\n".join([d.page_content for d in documents])[:8000]
        
        llm = create_legal_llm(temperature=0.0)
        
        prompt = f"""Построй хронологию событий на основе документов:

{content}

Формат:
📅 ДАТА — Событие (источник)

Отсортируй события по дате от ранних к поздним.
Если точная дата неизвестна, укажи примерный период.

Хронология:"""
        
        response = llm.invoke([
            SystemMessage(content="Ты юридический аналитик. Строишь хронологии событий."),
            HumanMessage(content=prompt)
        ])
        
        result = response.content if hasattr(response, 'content') else str(response)
        logger.info(f"[ChatTools] build_timeline: завершено")
        
        return f"📅 **Хронология событий**\n\n{result}"
        
    except Exception as e:
        logger.error(f"[ChatTools] build_timeline error: {e}")
        return f"Ошибка построения хронологии: {str(e)}"


# =============================================================================
# Опциональные инструменты (добавляются по переключателям)
# =============================================================================

def get_garant_tools():
    """Получить инструменты GARANT (если legal_research=True)"""
    try:
        from app.services.langchain_agents.garant_tools import search_garant, get_garant_full_text
        return [search_garant, get_garant_full_text]
    except ImportError:
        logger.warning("[ChatTools] GARANT tools not available")
        return []


def get_web_search_tool():
    """Получить инструмент веб-поиска (если web_search=True)"""
    try:
        from app.services.langchain_agents.web_research_tool import web_research_tool
        return [web_research_tool]
    except ImportError:
        logger.warning("[ChatTools] Web search tool not available")
        return []


# =============================================================================
# Фабрика инструментов
# =============================================================================

def get_chat_tools(
    db: Session,
    rag_service,
    case_id: str,
    legal_research: bool = False,
    web_search: bool = False
) -> List:
    """
    Получить набор инструментов для чата.
    
    Args:
        db: SQLAlchemy сессия
        rag_service: RAG сервис
        case_id: ID дела
        legal_research: Включить GARANT
        web_search: Включить веб-поиск
    
    Returns:
        Список инструментов
    """
    # Инициализируем глобальные зависимости
    initialize_chat_tools(db, rag_service, case_id)
    
    # Базовые инструменты (всегда доступны)
    tools = [
        search_documents,
        list_case_files,
        get_file_summary,
        summarize_all_documents,
        extract_entities,
        find_contradictions,
        analyze_risks,
        build_timeline,
    ]
    
    # Опциональные инструменты
    if legal_research:
        tools.extend(get_garant_tools())
        logger.info("[ChatTools] GARANT tools enabled")
    
    if web_search:
        tools.extend(get_web_search_tool())
        logger.info("[ChatTools] Web search tool enabled")
    
    logger.info(f"[ChatTools] Initialized {len(tools)} tools for case {case_id}")
    return tools

