"""Self-Critique механизм для агентов - самопроверка результатов"""
from typing import Dict, Any, Optional, List
from app.services.llm_factory import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
import logging
import json

logger = logging.getLogger(__name__)


class SelfCritiqueService:
    """
    Сервис для самопроверки результатов агентов.
    
    Агент проверяет свой ответ на:
    1. Логичность
    2. Полноту извлечённых данных
    3. Противоречия внутри ответа
    """
    
    def __init__(self):
        """Initialize self-critique service"""
        try:
            self.llm = create_llm(temperature=0.1)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM for self-critique: {e}")
            self.llm = None
    
    def critique_agent_result(
        self,
        agent_name: str,
        agent_result: Dict[str, Any],
        original_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Критикует результат агента и выявляет проблемы
        
        Args:
            agent_name: Имя агента (timeline, key_facts, discrepancy, risk, summary)
            agent_result: Результат работы агента
            original_query: Исходный запрос пользователя (опционально)
            
        Returns:
            Dictionary with critique result:
            {
                "logical_issues": List[str],  # Логические проблемы
                "completeness_issues": List[str],  # Проблемы полноты
                "contradictions": List[str],  # Противоречия
                "overall_quality": float,  # Общая оценка качества (0.0-1.0)
                "should_retry": bool,  # Нужно ли повторить
                "suggestions": List[str]  # Предложения по улучшению
            }
        """
        if not self.llm:
            logger.warning("LLM not available for self-critique, skipping")
            return {
                "logical_issues": [],
                "completeness_issues": [],
                "contradictions": [],
                "overall_quality": 0.5,
                "should_retry": False,
                "suggestions": []
            }
        
        try:
            # Форматируем результат для анализа
            result_text = self._format_result_for_critique(agent_result)
            
            # Создаём промпт для самопроверки
            critique_prompt = self._create_critique_prompt(agent_name, result_text, original_query)
            
            # Выполняем самопроверку
            response = self.llm.invoke([HumanMessage(content=critique_prompt)])
            critique_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим результат
            critique_result = self._parse_critique_response(critique_text)
            
            logger.info(
                f"Self-critique for {agent_name}: quality={critique_result.get('overall_quality', 0.0):.2f}, "
                f"issues={len(critique_result.get('logical_issues', [])) + len(critique_result.get('completeness_issues', [])) + len(critique_result.get('contradictions', []))}"
            )
            
            return critique_result
            
        except Exception as e:
            logger.error(f"Error in self-critique for {agent_name}: {e}", exc_info=True)
            return {
                "logical_issues": [],
                "completeness_issues": [],
                "contradictions": [],
                "overall_quality": 0.5,
                "should_retry": False,
                "suggestions": [],
                "error": str(e)
            }
    
    def _format_result_for_critique(self, result: Dict[str, Any]) -> str:
        """Форматирует результат агента для анализа"""
        try:
            # Преобразуем результат в читаемый формат
            if isinstance(result, dict):
                # Пытаемся извлечь основные данные
                formatted_parts = []
                
                # Для timeline
                if "timeline" in result or "events" in result:
                    events = result.get("timeline") or result.get("events", [])
                    formatted_parts.append(f"События ({len(events) if isinstance(events, list) else 0}):")
                    if isinstance(events, list):
                        for i, event in enumerate(events[:10], 1):  # Первые 10
                            if isinstance(event, dict):
                                formatted_parts.append(f"{i}. {event.get('description', str(event))}")
                            else:
                                formatted_parts.append(f"{i}. {str(event)}")
                
                # Для key_facts
                if "facts" in result or "key_facts" in result:
                    facts = result.get("facts") or result.get("key_facts", [])
                    formatted_parts.append(f"Ключевые факты ({len(facts) if isinstance(facts, list) else 0}):")
                    if isinstance(facts, list):
                        for i, fact in enumerate(facts[:10], 1):
                            if isinstance(fact, dict):
                                formatted_parts.append(f"{i}. {fact.get('description', fact.get('value', str(fact)))}")
                            else:
                                formatted_parts.append(f"{i}. {str(fact)}")
                
                # Для discrepancy
                if "discrepancies" in result:
                    discrepancies = result.get("discrepancies", [])
                    formatted_parts.append(f"Противоречия ({len(discrepancies) if isinstance(discrepancies, list) else 0}):")
                    if isinstance(discrepancies, list):
                        for i, disc in enumerate(discrepancies[:10], 1):
                            if isinstance(disc, dict):
                                formatted_parts.append(f"{i}. {disc.get('description', str(disc))}")
                            else:
                                formatted_parts.append(f"{i}. {str(disc)}")
                
                # Для risk
                if "risks" in result:
                    risks = result.get("risks", [])
                    formatted_parts.append(f"Риски ({len(risks) if isinstance(risks, list) else 0}):")
                    if isinstance(risks, list):
                        for i, risk in enumerate(risks[:10], 1):
                            if isinstance(risk, dict):
                                formatted_parts.append(f"{i}. {risk.get('risk_name', risk.get('description', str(risk)))}")
                            else:
                                formatted_parts.append(f"{i}. {str(risk)}")
                
                # Для summary
                if "summary" in result or "summary_text" in result:
                    summary = result.get("summary") or result.get("summary_text", "")
                    formatted_parts.append(f"Резюме:\n{summary[:500]}")
                
                # Если ничего не найдено, используем JSON
                if not formatted_parts:
                    formatted_parts.append(json.dumps(result, ensure_ascii=False, indent=2)[:1000])
                
                return "\n\n".join(formatted_parts)
            else:
                return str(result)[:1000]
                
        except Exception as e:
            logger.warning(f"Error formatting result for critique: {e}")
            return str(result)[:1000]
    
    def _create_critique_prompt(
        self,
        agent_name: str,
        result_text: str,
        original_query: Optional[str] = None
    ) -> str:
        """Создаёт промпт для самопроверки"""
        
        agent_context = {
            "timeline": "анализ временной линии событий",
            "key_facts": "извлечение ключевых фактов",
            "discrepancy": "поиск противоречий между документами",
            "risk": "анализ рисков",
            "summary": "создание резюме"
        }
        
        task_description = agent_context.get(agent_name, "анализ")
        
        prompt = f"""Ты эксперт-аналитик, который проверяет результаты работы AI-агента.

Задача агента: {task_description}

Результат работы агента:
{result_text}

Проверь результат на следующие аспекты:

1. **Логичность**:
   - Логичны ли выводы?
   - Соответствуют ли выводы данным?
   - Есть ли логические ошибки?

2. **Полнота**:
   - Все ли важные данные извлечены?
   - Нет ли пропусков?
   - Достаточно ли деталей?

3. **Противоречия**:
   - Есть ли противоречия внутри результата?
   - Противоречат ли выводы друг другу?
   - Есть ли несогласованности?

Верни ответ в формате JSON:
{{
    "logical_issues": ["проблема 1", "проблема 2"],
    "completeness_issues": ["проблема 1", "проблема 2"],
    "contradictions": ["противоречие 1", "противоречие 2"],
    "overall_quality": 0.8,
    "should_retry": false,
    "suggestions": ["предложение 1", "предложение 2"]
}}

Где:
- logical_issues: список логических проблем (пустой список если проблем нет)
- completeness_issues: список проблем полноты (пустой список если проблем нет)
- contradictions: список противоречий (пустой список если противоречий нет)
- overall_quality: оценка качества от 0.0 до 1.0
- should_retry: true если нужна повторная попытка
- suggestions: список предложений по улучшению

Будь объективным и конструктивным. Если проблем нет, верни пустые списки и high quality."""
        
        if original_query:
            prompt = f"{prompt}\n\nИсходный запрос пользователя: {original_query}"
        
        return prompt
    
    def _parse_critique_response(self, response_text: str) -> Dict[str, Any]:
        """Парсит ответ от LLM в структурированный формат"""
        try:
            # Пытаемся извлечь JSON из ответа
            import re
            
            # Ищем JSON блок
            json_match = re.search(r'\{[^{}]*"logical_issues"[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                # Пытаемся найти JSON между ```json и ```
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = response_text
            
            # Парсим JSON
            critique_data = json.loads(json_str)
            
            # Валидация и нормализация
            result = {
                "logical_issues": critique_data.get("logical_issues", []),
                "completeness_issues": critique_data.get("completeness_issues", []),
                "contradictions": critique_data.get("contradictions", []),
                "overall_quality": float(critique_data.get("overall_quality", 0.5)),
                "should_retry": bool(critique_data.get("should_retry", False)),
                "suggestions": critique_data.get("suggestions", [])
            }
            
            # Ограничиваем overall_quality диапазоном [0, 1]
            result["overall_quality"] = max(0.0, min(1.0, result["overall_quality"]))
            
            return result
            
        except Exception as e:
            logger.warning(f"Error parsing critique response: {e}. Response: {response_text[:200]}")
            # Возвращаем дефолтный результат
            return {
                "logical_issues": [],
                "completeness_issues": [],
                "contradictions": [],
                "overall_quality": 0.5,
                "should_retry": False,
                "suggestions": [],
                "parse_error": str(e)
            }

