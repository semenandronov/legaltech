"""
Функции обновления памяти через LLM.

Используют LLM для извлечения информации из текста
и обновления структурированных данных памяти.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
import json
import uuid

from app.services.langchain_agents.memory.schemas import (
    UserProfile,
    CaseMemory,
    QueryRecord,
    Insight,
    KeyFact,
    CaseParticipant,
    ImportantDate,
)

logger = logging.getLogger(__name__)


async def update_user_profile(
    profile: UserProfile,
    new_info: str,
    llm=None
) -> UserProfile:
    """
    Обновить профиль пользователя на основе новой информации.
    
    Использует LLM для извлечения релевантных данных из текста.
    
    Args:
        profile: Текущий профиль
        new_info: Новая информация (текст)
        llm: LLM instance (опционально)
    
    Returns:
        Обновлённый профиль
    
    # ПРИМЕР
    ```python
    profile = store.get_user_profile(user_id)
    updated = await update_user_profile(
        profile,
        "Я работаю юристом в IT-компании, специализируюсь на договорах"
    )
    store.put_user_profile(updated)
    ```
    """
    if not llm:
        from app.services.llm_factory import create_llm
        llm = create_llm()
    
    # Формируем промпт для извлечения информации
    prompt = f"""# ЗАДАЧА
Извлеки информацию о пользователе из текста и обнови профиль.

# ТЕКУЩИЙ ПРОФИЛЬ
{profile.model_dump_json(indent=2)}

# НОВАЯ ИНФОРМАЦИЯ
{new_info}

# ИНСТРУКЦИИ
1. Извлеки любую релевантную информацию о пользователе
2. Определи, какие поля профиля нужно обновить
3. НЕ удаляй существующую информацию, только дополняй
4. Если информация противоречит существующей - используй новую

# ФОРМАТ ОТВЕТА (JSON)
Верни ТОЛЬКО JSON с полями, которые нужно обновить:
{{
    "name": "если упомянуто имя",
    "role": "если упомянута роль/должность",
    "organization": "если упомянута организация",
    "legal_preferences": {{
        "primary_area": "если упомянута область права",
        "secondary_areas": ["если упомянуты доп. области"],
        "detail_level": "brief/standard/detailed"
    }},
    "expertise_level": "beginner/intermediate/expert",
    "recent_topics": ["если упомянуты темы"]
}}

Если поле не нужно обновлять - НЕ включай его в ответ."""

    try:
        response = llm.invoke(prompt)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Парсим JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            updates = json.loads(json_match.group())
            
            # Применяем обновления
            if "name" in updates:
                profile.name = updates["name"]
            if "role" in updates:
                profile.role = updates["role"]
            if "organization" in updates:
                profile.organization = updates["organization"]
            if "expertise_level" in updates:
                profile.expertise_level = updates["expertise_level"]
            
            # Обновляем legal_preferences
            if "legal_preferences" in updates:
                lp = updates["legal_preferences"]
                if "primary_area" in lp:
                    profile.legal_preferences.primary_area = lp["primary_area"]
                if "secondary_areas" in lp:
                    # Добавляем, не заменяем
                    existing = set(profile.legal_preferences.secondary_areas)
                    existing.update(lp["secondary_areas"])
                    profile.legal_preferences.secondary_areas = list(existing)
                if "detail_level" in lp:
                    profile.legal_preferences.detail_level = lp["detail_level"]
            
            # Обновляем recent_topics
            if "recent_topics" in updates:
                existing = profile.recent_topics[:5]  # Храним последние 5
                for topic in updates["recent_topics"]:
                    if topic not in existing:
                        existing.insert(0, topic)
                profile.recent_topics = existing[:10]
            
            profile.updated_at = datetime.utcnow()
            logger.info(f"[Memory] Updated user profile: {list(updates.keys())}")
        
    except Exception as e:
        logger.error(f"[Memory] Profile update error: {e}")
    
    return profile


async def update_case_memory(
    memory: CaseMemory,
    new_info: str,
    source: Optional[str] = None,
    llm=None
) -> CaseMemory:
    """
    Обновить память по делу на основе новой информации.
    
    Args:
        memory: Текущая память по делу
        new_info: Новая информация (текст)
        source: Источник информации (документ)
        llm: LLM instance
    
    Returns:
        Обновлённая память
    """
    if not llm:
        from app.services.llm_factory import create_llm
        llm = create_llm()
    
    prompt = f"""# ЗАДАЧА
Извлеки юридически значимую информацию из текста и обнови память по делу.

# ТЕКУЩАЯ ПАМЯТЬ ПО ДЕЛУ
{memory.model_dump_json(indent=2)}

# НОВАЯ ИНФОРМАЦИЯ
{new_info}

# ИСТОЧНИК
{source or "Не указан"}

# ИНСТРУКЦИИ
1. Извлеки ключевые факты, даты, участников
2. Определи правовые основания если упоминаются
3. Выдели риски и рекомендации
4. НЕ дублируй существующую информацию

# ФОРМАТ ОТВЕТА (JSON)
{{
    "case_name": "если можно определить название",
    "case_type": "если можно определить тип",
    "summary": "краткое описание если нужно обновить",
    "new_participants": [
        {{"name": "ИП Иванов", "role": "ответчик", "details": "..."}}
    ],
    "new_dates": [
        {{"date": "2024-03-15", "description": "срок ответа", "is_deadline": true}}
    ],
    "new_facts": [
        {{"fact": "описание факта", "importance": "high", "verified": false}}
    ],
    "new_legal_basis": ["ст. 395 ГК РФ"],
    "new_risks": ["описание риска"],
    "new_recommendations": ["рекомендация"]
}}"""

    try:
        response = llm.invoke(prompt)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            updates = json.loads(json_match.group())
            
            # Применяем обновления
            if "case_name" in updates and updates["case_name"]:
                memory.case_name = updates["case_name"]
            if "case_type" in updates and updates["case_type"]:
                memory.case_type = updates["case_type"]
            if "summary" in updates and updates["summary"]:
                memory.summary = updates["summary"]
            
            # Добавляем участников
            for p in updates.get("new_participants", []):
                try:
                    participant = CaseParticipant(**p)
                    # Проверяем на дубликаты
                    existing_names = {ep.name.lower() for ep in memory.participants}
                    if participant.name.lower() not in existing_names:
                        memory.participants.append(participant)
                except Exception:
                    pass
            
            # Добавляем даты
            for d in updates.get("new_dates", []):
                try:
                    date = ImportantDate(**d)
                    # Проверяем на дубликаты
                    existing_dates = {(ed.date, ed.description) for ed in memory.important_dates}
                    if (date.date, date.description) not in existing_dates:
                        memory.important_dates.append(date)
                except Exception:
                    pass
            
            # Добавляем факты
            for f in updates.get("new_facts", []):
                try:
                    fact = KeyFact(source=source, **f)
                    # Проверяем на дубликаты (по содержанию)
                    existing_facts = {ef.fact.lower() for ef in memory.key_facts}
                    if fact.fact.lower() not in existing_facts:
                        memory.key_facts.append(fact)
                except Exception:
                    pass
            
            # Добавляем правовые основания
            for lb in updates.get("new_legal_basis", []):
                if lb and lb not in memory.legal_basis:
                    memory.legal_basis.append(lb)
            
            # Добавляем риски
            for r in updates.get("new_risks", []):
                if r and r not in memory.risks:
                    memory.risks.append(r)
            
            # Добавляем рекомендации
            for rec in updates.get("new_recommendations", []):
                if rec and rec not in memory.recommendations:
                    memory.recommendations.append(rec)
            
            memory.updated_at = datetime.utcnow()
            logger.info(f"[Memory] Updated case memory: {list(updates.keys())}")
        
    except Exception as e:
        logger.error(f"[Memory] Case memory update error: {e}")
    
    return memory


async def extract_insights(
    scope: str,
    scope_id: str,
    context: str,
    existing_insights: List[Insight] = None,
    llm=None
) -> List[Insight]:
    """
    Извлечь инсайты из контекста.
    
    Args:
        scope: "user" или "case"
        scope_id: ID пользователя или дела
        context: Контекст для анализа
        existing_insights: Существующие инсайты (для дедупликации)
        llm: LLM instance
    
    Returns:
        Список новых инсайтов
    """
    if not llm:
        from app.services.llm_factory import create_llm
        llm = create_llm()
    
    existing_titles = {i.title for i in (existing_insights or [])}
    
    prompt = f"""# ЗАДАЧА
Извлеки инсайты и паттерны из контекста.

# КОНТЕКСТ
{context[:5000]}

# СУЩЕСТВУЮЩИЕ ИНСАЙТЫ (не дублируй)
{json.dumps([i.title for i in (existing_insights or [])], ensure_ascii=False)}

# ИНСТРУКЦИИ
1. Выдели паттерны поведения или запросов
2. Определи потенциальные риски
3. Сформулируй рекомендации
4. НЕ дублируй существующие инсайты

# ФОРМАТ ОТВЕТА (JSON)
{{
    "insights": [
        {{
            "title": "Краткий заголовок",
            "description": "Описание инсайта",
            "category": "pattern/risk/recommendation",
            "priority": "low/medium/high",
            "confidence": 0.8,
            "is_actionable": true
        }}
    ]
}}"""

    try:
        response = llm.invoke(prompt)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            result = json.loads(json_match.group())
            
            new_insights = []
            for i in result.get("insights", []):
                if i.get("title") not in existing_titles:
                    try:
                        insight = Insight(
                            insight_id=str(uuid.uuid4()),
                            scope=scope,
                            scope_id=scope_id,
                            **i
                        )
                        new_insights.append(insight)
                    except Exception as e:
                        logger.warning(f"[Memory] Invalid insight: {e}")
            
            logger.info(f"[Memory] Extracted {len(new_insights)} new insights")
            return new_insights
        
    except Exception as e:
        logger.error(f"[Memory] Insight extraction error: {e}")
    
    return []


async def create_query_record(
    user_id: str,
    question: str,
    mode: str = "normal",
    case_id: Optional[str] = None,
    answer: Optional[str] = None,
    sources: List[str] = None,
    duration: Optional[float] = None
) -> QueryRecord:
    """
    Создать запись о запросе.
    
    Args:
        user_id: ID пользователя
        question: Текст вопроса
        mode: Режим работы
        case_id: ID дела
        answer: Текст ответа
        sources: Использованные источники
        duration: Время выполнения
    
    Returns:
        QueryRecord
    """
    # Создаём краткое содержание ответа если есть
    answer_summary = None
    if answer:
        # Берём первые 200 символов
        answer_summary = answer[:200] + "..." if len(answer) > 200 else answer
    
    return QueryRecord(
        query_id=str(uuid.uuid4()),
        user_id=user_id,
        case_id=case_id,
        question=question,
        mode=mode,
        answer_summary=answer_summary,
        sources_used=sources or [],
        timestamp=datetime.utcnow(),
        duration_seconds=duration
    )

