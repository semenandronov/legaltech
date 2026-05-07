"""
Reflection Service - Сервис самопроверки ответов агента

Реализует Reflection Pattern:
1. Агент генерирует ответ
2. ReflectionService проверяет ответ на:
   - Логическую корректность
   - Соответствие вопросу
   - Наличие и корректность цитат
   - Полноту ответа
3. Если есть проблемы — возвращает критику для улучшения
4. Выдаёт confidence score

Используется в quality pipeline ассистента для повышения качества ответов.
"""
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage
from app.services.llm_factory import create_legal_llm

logger = logging.getLogger(__name__)


class ReflectionIssueType(Enum):
    """Типы проблем, выявляемых при рефлексии"""
    INCOMPLETE_ANSWER = "incomplete"          # Неполный ответ
    OFF_TOPIC = "off_topic"                   # Не по теме
    MISSING_SOURCES = "missing_sources"       # Нет источников
    INVALID_CITATION = "invalid_citation"     # Неверная цитата
    LOGICAL_ERROR = "logical_error"           # Логическая ошибка
    OUTDATED_INFO = "outdated_info"           # Устаревшая информация
    HALLUCINATION = "hallucination"           # Галлюцинация (выдуманные факты)
    UNCLEAR = "unclear"                       # Непонятный ответ


@dataclass
class ReflectionIssue:
    """Проблема, выявленная при рефлексии"""
    issue_type: ReflectionIssueType
    description: str
    severity: str  # "high", "medium", "low"
    suggestion: Optional[str] = None


@dataclass
class ReflectionResult:
    """Результат рефлексии"""
    is_valid: bool                           # Ответ валиден?
    confidence_score: float                  # Оценка уверенности (0.0 - 1.0)
    issues: List[ReflectionIssue]            # Список проблем
    improved_answer: Optional[str] = None    # Улучшенный ответ (если нужно)
    critique: Optional[str] = None           # Текстовая критика
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "confidence_score": self.confidence_score,
            "confidence_level": self._get_confidence_level(),
            "issues": [
                {
                    "type": issue.issue_type.value,
                    "description": issue.description,
                    "severity": issue.severity,
                    "suggestion": issue.suggestion
                }
                for issue in self.issues
            ],
            "critique": self.critique
        }
    
    def _get_confidence_level(self) -> str:
        """Получить уровень уверенности"""
        if self.confidence_score >= 0.9:
            return "high"
        elif self.confidence_score >= 0.7:
            return "medium"
        elif self.confidence_score >= 0.5:
            return "low"
        else:
            return "very_low"


class ReflectionService:
    """
    Сервис рефлексии (самопроверки) ответов агента.
    
    Проверяет ответ на:
    1. Соответствие вопросу
    2. Логическую корректность
    3. Наличие и валидность источников
    4. Полноту ответа
    5. Отсутствие галлюцинаций
    
    Возвращает:
    - Оценку уверенности (confidence score)
    - Список проблем (если есть)
    - Улучшенный ответ (опционально)
    """
    
    REFLECTION_PROMPT = """Ты — критический рецензент юридических ответов. Твоя задача — проверить качество ответа AI-ассистента.

ВОПРОС ПОЛЬЗОВАТЕЛЯ:
{question}

ОТВЕТ АССИСТЕНТА:
{answer}

КОНТЕКСТ ИЗ ДОКУМЕНТОВ (если есть):
{context}

═══════════════════════════════════════════════════════════════════════════════
                         КРИТЕРИИ ОЦЕНКИ
═══════════════════════════════════════════════════════════════════════════════

Оцени ответ по следующим критериям:

1. **РЕЛЕВАНТНОСТЬ** (отвечает ли на вопрос?)
   - Ответ должен напрямую отвечать на заданный вопрос
   - Не должен уходить в сторону

2. **ПОЛНОТА** (достаточно ли информации?)
   - Все аспекты вопроса рассмотрены
   - Нет важных пропусков

3. **ТОЧНОСТЬ** (верна ли информация?)
   - Факты соответствуют контексту
   - Нет противоречий

4. **ИСТОЧНИКИ** (указаны ли источники?)
   - Ссылки на документы/статьи законов
   - Источники реальны и проверяемы

5. **ЛОГИКА** (логичны ли выводы?)
   - Рассуждения последовательны
   - Нет логических ошибок

6. **ГАЛЛЮЦИНАЦИИ** (есть ли выдуманные факты?)
   - Нет информации, которой нет в контексте
   - Нет "придуманных" статей законов

═══════════════════════════════════════════════════════════════════════════════
                         ФОРМАТ ОТВЕТА
═══════════════════════════════════════════════════════════════════════════════

Ответь в формате JSON:
```json
{{
    "is_valid": true/false,
    "confidence_score": 0.0-1.0,
    "issues": [
        {{
            "type": "incomplete/off_topic/missing_sources/invalid_citation/logical_error/hallucination/unclear",
            "description": "Описание проблемы",
            "severity": "high/medium/low",
            "suggestion": "Как исправить"
        }}
    ],
    "critique": "Общая критика ответа (1-2 предложения)",
    "should_improve": true/false
}}
```

Если ответ хороший — issues = [] и is_valid = true.
Если есть проблемы — укажи их и предложи исправления.

Оценка:"""

    IMPROVEMENT_PROMPT = """Улучши ответ на основе критики.

ВОПРОС:
{question}

ИСХОДНЫЙ ОТВЕТ:
{answer}

КРИТИКА:
{critique}

ПРОБЛЕМЫ:
{issues}

═══════════════════════════════════════════════════════════════════════════════

Напиши УЛУЧШЕННЫЙ ответ, который:
1. Исправляет указанные проблемы
2. Сохраняет хорошие части исходного ответа
3. Добавляет недостающую информацию
4. Убирает ошибки и галлюцинации

Улучшенный ответ:"""

    def __init__(self, deep_think: bool = False):
        """
        Инициализация сервиса рефлексии
        
        Args:
            deep_think: Использовать более мощную модель для рефлексии
        """
        self.deep_think = deep_think
        self.llm = self._create_llm()
        
        logger.info(f"[ReflectionService] Initialized (deep_think={deep_think})")
    
    def _create_llm(self):
        """Создать LLM для рефлексии"""
        from app.services.llm_factory import legal_deep_extra_kwargs

        if self.deep_think:
            return create_legal_llm(
                temperature=0.1,
                **legal_deep_extra_kwargs(),
            )
        return create_legal_llm(temperature=0.1)
    
    async def reflect(
        self,
        question: str,
        answer: str,
        context: Optional[str] = None,
        auto_improve: bool = True
    ) -> ReflectionResult:
        """
        Провести рефлексию (самопроверку) ответа
        
        Args:
            question: Вопрос пользователя
            answer: Ответ ассистента
            context: Контекст из документов (опционально)
            auto_improve: Автоматически улучшить ответ если есть проблемы
            
        Returns:
            ReflectionResult с оценкой и возможными улучшениями
        """
        try:
            logger.info(f"[ReflectionService] Reflecting on answer (length={len(answer)})")
            
            # Шаг 1: Получаем критику
            critique_result = await self._get_critique(question, answer, context)
            
            # Шаг 2: Если нужно улучшение и auto_improve=True
            improved_answer = None
            if auto_improve and critique_result.get("should_improve", False):
                improved_answer = await self._improve_answer(
                    question=question,
                    answer=answer,
                    critique=critique_result.get("critique", ""),
                    issues=critique_result.get("issues", [])
                )
            
            # Шаг 3: Формируем результат
            issues = [
                ReflectionIssue(
                    issue_type=ReflectionIssueType(issue.get("type", "unclear")),
                    description=issue.get("description", ""),
                    severity=issue.get("severity", "medium"),
                    suggestion=issue.get("suggestion")
                )
                for issue in critique_result.get("issues", [])
            ]
            
            result = ReflectionResult(
                is_valid=critique_result.get("is_valid", True),
                confidence_score=critique_result.get("confidence_score", 0.8),
                issues=issues,
                improved_answer=improved_answer,
                critique=critique_result.get("critique")
            )
            
            logger.info(
                f"[ReflectionService] Reflection complete: "
                f"valid={result.is_valid}, confidence={result.confidence_score:.2f}, "
                f"issues={len(issues)}, improved={improved_answer is not None}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ReflectionService] Error: {e}", exc_info=True)
            # В случае ошибки возвращаем нейтральный результат
            return ReflectionResult(
                is_valid=True,
                confidence_score=0.7,
                issues=[],
                critique="Не удалось провести рефлексию"
            )
    
    async def _get_critique(
        self,
        question: str,
        answer: str,
        context: Optional[str]
    ) -> Dict[str, Any]:
        """Получить критику ответа"""
        import json
        
        prompt = self.REFLECTION_PROMPT.format(
            question=question,
            answer=answer,
            context=context or "Контекст не предоставлен"
        )
        
        try:
            response = self.llm.invoke([
                SystemMessage(content="Ты критический рецензент юридических текстов. Отвечай только в формате JSON."),
                HumanMessage(content=prompt)
            ])
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Извлекаем JSON из ответа
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Пробуем найти JSON напрямую
                start = response_text.find('{')
                end = response_text.rfind('}')
                if start != -1 and end != -1:
                    json_str = response_text[start:end + 1]
                else:
                    raise ValueError("JSON не найден в ответе")
            
            result = json.loads(json_str)
            return result
            
        except json.JSONDecodeError as e:
            logger.warning(f"[ReflectionService] JSON parse error: {e}")
            return {
                "is_valid": True,
                "confidence_score": 0.75,
                "issues": [],
                "critique": "Не удалось распарсить критику",
                "should_improve": False
            }
        except Exception as e:
            logger.error(f"[ReflectionService] Critique error: {e}")
            return {
                "is_valid": True,
                "confidence_score": 0.7,
                "issues": [],
                "critique": str(e),
                "should_improve": False
            }
    
    async def _improve_answer(
        self,
        question: str,
        answer: str,
        critique: str,
        issues: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Улучшить ответ на основе критики"""
        try:
            issues_text = "\n".join([
                f"- [{issue.get('severity', 'medium')}] {issue.get('type', '')}: {issue.get('description', '')}"
                for issue in issues
            ])
            
            prompt = self.IMPROVEMENT_PROMPT.format(
                question=question,
                answer=answer,
                critique=critique,
                issues=issues_text if issues_text else "Нет конкретных проблем"
            )
            
            response = self.llm.invoke([
                SystemMessage(content="Ты юридический ассистент. Улучши ответ на основе критики."),
                HumanMessage(content=prompt)
            ])
            
            improved = response.content if hasattr(response, 'content') else str(response)
            
            # Проверяем, что улучшенный ответ не пустой и отличается от исходного
            if improved and len(improved) > 50 and improved != answer:
                logger.info(f"[ReflectionService] Answer improved (length: {len(answer)} → {len(improved)})")
                return improved
            
            return None
            
        except Exception as e:
            logger.error(f"[ReflectionService] Improvement error: {e}")
            return None
    
    def quick_validate(self, answer: str) -> Tuple[bool, float]:
        """
        Быстрая валидация ответа без LLM (эвристики)
        
        Returns:
            (is_valid, confidence_score)
        """
        issues_count = 0
        confidence = 1.0
        
        # Проверка 1: Ответ не пустой
        if not answer or len(answer) < 20:
            return False, 0.1
        
        # Проверка 2: Есть структура (абзацы, списки)
        if '\n' not in answer:
            confidence -= 0.1
            issues_count += 1
        
        # Проверка 3: Не слишком короткий
        if len(answer) < 100:
            confidence -= 0.15
            issues_count += 1
        
        # Проверка 4: Есть ссылки на источники
        has_sources = bool(re.search(r'\[.*?\]|ст\.\s*\d+|статья\s*\d+|п\.\s*\d+', answer, re.IGNORECASE))
        if not has_sources:
            confidence -= 0.1
            issues_count += 1
        
        # Проверка 5: Нет явных признаков галлюцинаций
        hallucination_patterns = [
            r'я не знаю',
            r'к сожалению.*не могу',
            r'информация.*отсутствует',
            r'данные.*недоступны'
        ]
        for pattern in hallucination_patterns:
            if re.search(pattern, answer, re.IGNORECASE):
                confidence -= 0.2
                issues_count += 1
                break
        
        # Проверка 6: Нет повторений
        sentences = answer.split('.')
        unique_sentences = set(s.strip().lower() for s in sentences if len(s.strip()) > 20)
        if len(sentences) > 3 and len(unique_sentences) < len(sentences) * 0.7:
            confidence -= 0.15
            issues_count += 1
        
        confidence = max(0.3, min(1.0, confidence))
        is_valid = issues_count < 3 and confidence >= 0.5
        
        return is_valid, confidence


# Factory function
def get_reflection_service(deep_think: bool = False) -> ReflectionService:
    """
    Получить экземпляр ReflectionService
    
    Args:
        deep_think: Использовать более мощную модель
        
    Returns:
        ReflectionService instance
    """
    return ReflectionService(deep_think=deep_think)

