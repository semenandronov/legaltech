"""
Prompt Improver Service - Magic Prompt functionality.

Similar to Harvey's "Improve" feature that enhances user queries
to be more effective for legal research and analysis.
"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.config import config
from langchain_core.messages import SystemMessage, HumanMessage
import logging
import json
import re

logger = logging.getLogger(__name__)


class PromptImprover:
    """
    Service for improving user prompts to be more effective.
    
    Features:
    - Adds legal context and precision
    - Suggests structure for complex queries
    - Identifies missing specifications
    - Provides explanation of improvements
    """
    
    IMPROVEMENT_SYSTEM_PROMPT = """Ты — эксперт по юридическим запросам и промпт-инжинирингу.
Твоя задача — улучшить запрос пользователя для юридического ИИ-ассистента.

При улучшении запроса:
1. Добавь конкретику и структуру
2. Укажи формат желаемого ответа
3. Добавь релевантный юридический контекст
4. Сохрани исходное намерение пользователя
5. Сделай запрос более точным и полным

Отвечай в формате JSON:
{
    "improved_prompt": "Улучшенный запрос",
    "suggestions": ["Совет 1", "Совет 2"],
    "reasoning": "Объяснение изменений",
    "improvements_made": ["Изменение 1", "Изменение 2"]
}

Не добавляй ничего лишнего. Улучшай только то, что необходимо."""

    ANALYSIS_PATTERNS = [
        {
            "pattern": r"(анализ|проанализир)",
            "enhancement": "Для каждого найденного пункта укажи: описание, источник (документ и страница), юридическую значимость.",
        },
        {
            "pattern": r"(риск|опасност)",
            "enhancement": "Классифицируй риски по категориям (высокий/средний/низкий) с обоснованием и рекомендациями по минимизации.",
        },
        {
            "pattern": r"(сравн|отличи|разниц)",
            "enhancement": "Представь сравнение в табличном формате с указанием ключевых различий и совпадений.",
        },
        {
            "pattern": r"(хронолог|таймлайн|события)",
            "enhancement": "Для каждого события укажи дату, участников, источник документа и связь с другими событиями.",
        },
        {
            "pattern": r"(противореч|несоответств)",
            "enhancement": "Для каждого противоречия укажи: суть, источники, юридические последствия.",
        },
    ]

    def __init__(self):
        """Initialize prompt improver"""
        if config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN:
            self.llm = create_llm(temperature=0.3)
        else:
            self.llm = None
            logger.warning("Prompt Improver: LLM not configured")
    
    async def improve(
        self, 
        original_prompt: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Improve a user prompt
        
        Args:
            original_prompt: Original user query
            context: Optional context (case info, document types, etc.)
            
        Returns:
            Dictionary with improved_prompt, suggestions, reasoning
        """
        if not original_prompt.strip():
            return {
                "improved_prompt": original_prompt,
                "suggestions": [],
                "reasoning": "Пустой запрос",
                "improvements_made": [],
            }
        
        # First, apply rule-based improvements
        rule_improved, rule_suggestions = self._apply_rules(original_prompt)
        
        # If LLM is available, use it for more sophisticated improvement
        if self.llm:
            try:
                llm_result = await self._improve_with_llm(original_prompt, context)
                
                # Merge rule-based and LLM improvements
                if llm_result["improved_prompt"] != original_prompt:
                    # LLM made changes
                    result = llm_result
                    result["suggestions"] = list(set(rule_suggestions + llm_result.get("suggestions", [])))
                else:
                    # LLM didn't change much, use rule-based
                    result = {
                        "improved_prompt": rule_improved,
                        "suggestions": rule_suggestions,
                        "reasoning": "Применены стандартные улучшения",
                        "improvements_made": [],
                    }
                
                return result
                
            except Exception as e:
                logger.error(f"LLM improvement failed: {e}")
                # Fall back to rule-based
        
        return {
            "improved_prompt": rule_improved,
            "suggestions": rule_suggestions,
            "reasoning": "Применены стандартные улучшения структуры запроса",
            "improvements_made": ["Добавлена структура запроса"],
        }
    
    def _apply_rules(self, prompt: str) -> tuple:
        """
        Apply rule-based improvements
        
        Args:
            prompt: Original prompt
            
        Returns:
            Tuple of (improved_prompt, suggestions)
        """
        improved = prompt
        suggestions = []
        enhancements = []
        
        # Check for known patterns
        for pattern_info in self.ANALYSIS_PATTERNS:
            if re.search(pattern_info["pattern"], prompt.lower()):
                enhancements.append(pattern_info["enhancement"])
        
        # Add enhancements if found
        if enhancements:
            improved = prompt + "\n\n" + "\n".join(enhancements)
        
        # Check for missing elements and add suggestions
        if "документ" not in prompt.lower() and "файл" not in prompt.lower():
            suggestions.append("Уточните, какие документы анализировать")
        
        if not re.search(r"\?|укажи|опиши|найди|выдели|проанализируй", prompt.lower()):
            suggestions.append("Добавьте конкретный вопрос или действие")
        
        if len(prompt.split()) < 5:
            suggestions.append("Добавьте больше контекста для точного ответа")
        
        return improved, suggestions
    
    async def _improve_with_llm(
        self, 
        prompt: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Use LLM to improve prompt
        
        Args:
            prompt: Original prompt
            context: Optional context
            
        Returns:
            Improvement result
        """
        # Build context string
        context_str = ""
        if context:
            if context.get("case_name"):
                context_str += f"Название дела: {context['case_name']}\n"
            if context.get("document_count"):
                context_str += f"Количество документов: {context['document_count']}\n"
            if context.get("document_types"):
                context_str += f"Типы документов: {', '.join(context['document_types'])}\n"
        
        user_message = f"""Улучши следующий запрос для юридического ИИ-ассистента:

Исходный запрос: "{prompt}"
{f'Контекст: {context_str}' if context_str else ''}

Верни результат в формате JSON."""
        
        messages = [
            SystemMessage(content=self.IMPROVEMENT_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]
        
        response = self.llm.invoke(messages)
        content = response.content
        
        # Parse JSON from response
        try:
            # Try to extract JSON
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "improved_prompt": result.get("improved_prompt", prompt),
                    "suggestions": result.get("suggestions", []),
                    "reasoning": result.get("reasoning", ""),
                    "improvements_made": result.get("improvements_made", []),
                }
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response")
        
        # If JSON parsing failed, return original
        return {
            "improved_prompt": prompt,
            "suggestions": [],
            "reasoning": "Не удалось обработать ответ",
            "improvements_made": [],
        }
    
    def get_quick_suggestions(self, prompt: str) -> List[str]:
        """
        Get quick suggestions without LLM call
        
        Args:
            prompt: User prompt
            
        Returns:
            List of suggestions
        """
        suggestions = []
        prompt_lower = prompt.lower()
        
        # Very short prompts
        if len(prompt.split()) < 3:
            suggestions.append("Добавьте больше деталей к запросу")
        
        # Missing action verb
        action_verbs = ["найди", "проанализируй", "сравни", "выдели", "укажи", "опиши", "составь"]
        if not any(verb in prompt_lower for verb in action_verbs):
            suggestions.append("Укажите действие (найди, проанализируй, сравни)")
        
        # Missing specificity
        if "все" in prompt_lower or "любые" in prompt_lower:
            suggestions.append("Уточните критерии — слишком широкий запрос")
        
        # Missing output format
        format_words = ["таблиц", "списк", "кратко", "подробно", "по пунктам"]
        if not any(word in prompt_lower for word in format_words):
            suggestions.append("Укажите формат ответа (таблица, список)")
        
        return suggestions[:3]  # Return max 3 suggestions


# API function for quick access
async def improve_prompt(
    prompt: str, 
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Improve a prompt (convenience function)
    
    Args:
        prompt: Original prompt
        context: Optional context
        
    Returns:
        Improvement result
    """
    improver = PromptImprover()
    return await improver.improve(prompt, context)

