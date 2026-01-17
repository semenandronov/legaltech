"""Redline Generator Service - генерация предложений по исправлению контрактов"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from langchain_core.prompts import ChatPromptTemplate
from app.services.llm_factory import create_llm
from app.services.clause_extractor import ExtractedClause
from app.models.playbook import PlaybookRule
import logging
import json
import re

logger = logging.getLogger(__name__)


@dataclass
class Redline:
    """A single redline (suggested change)"""
    rule_id: str
    rule_name: str
    rule_type: str  # red_line, fallback, no_go
    change_type: str  # replace, add, remove
    original_text: str
    suggested_text: str
    location: Dict[str, Any] = field(default_factory=dict)
    issue_description: str = ""
    priority: str = "medium"  # low, medium, high, critical
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class RedlineDocument:
    """Document with all redlines"""
    document_id: str
    document_name: str
    redlines: List[Redline]
    summary: str = ""
    total_changes: int = 0
    critical_changes: int = 0
    

# Промпт для генерации исправления
REDLINE_GENERATION_PROMPT = """Ты - эксперт по юридическим документам. Твоя задача - предложить исправление пункта контракта.

ИСХОДНЫЙ ПУНКТ:
{original_text}

ПРОБЛЕМА:
{issue_description}

ТРЕБОВАНИЕ ПРАВИЛА:
- Название: {rule_name}
- Описание: {rule_description}
- Тип правила: {rule_type}

ШАБЛОН ИСПРАВЛЕНИЯ (если есть):
{suggested_template}

ЗАДАЧА:
1. Предложи исправленный текст пункта, который:
   - Устраняет указанную проблему
   - Соответствует требованию правила
   - Сохраняет юридическую корректность
   - Использует профессиональный юридический язык

2. Объясни, какие изменения были внесены

Верни результат в формате JSON:
{{
    "suggested_text": "полный текст исправленного пункта",
    "changes_summary": "краткое описание изменений",
    "reasoning": "обоснование предложенных изменений",
    "confidence": 0.0-1.0
}}

ВАЖНО:
- Если шаблон предоставлен, используй его как основу
- Сохраняй структуру и нумерацию оригинального пункта
- Используй точные юридические формулировки"""


class RedlineGenerator:
    """
    Генератор redlines (предложений по исправлению) для контрактов.
    
    Поддерживает:
    - Генерация исправлений на основе правил Playbook
    - Использование LLM для сложных случаев
    - Форматирование redlines для экспорта
    """
    
    def __init__(self):
        """Initialize redline generator"""
        self.llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            self.llm = create_llm(temperature=0.3)
            logger.info("RedlineGenerator: LLM initialized")
        except Exception as e:
            logger.warning(f"RedlineGenerator: Failed to initialize LLM: {e}")
            self.llm = None
    
    async def generate_redline(
        self,
        rule: PlaybookRule,
        original_clause: Optional[ExtractedClause],
        issue_description: str
    ) -> Redline:
        """
        Generate a redline for a rule violation
        
        Args:
            rule: The violated rule
            original_clause: The original clause (if found)
            issue_description: Description of the issue
            
        Returns:
            Generated Redline
        """
        original_text = original_clause.text if original_clause else ""
        location = original_clause.location if original_clause else {}
        
        # Determine change type
        if not original_text:
            change_type = "add"
        elif rule.condition_type == "must_not_exist":
            change_type = "remove"
        else:
            change_type = "replace"
        
        # If we have a template and no LLM needed
        if rule.suggested_clause_template and (not original_text or change_type == "add"):
            return Redline(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                change_type=change_type,
                original_text=original_text,
                suggested_text=rule.suggested_clause_template,
                location=location,
                issue_description=issue_description,
                priority=self._get_priority(rule),
                confidence=0.9,
                reasoning="Использован шаблон из правила"
            )
        
        # For remove - suggest deletion
        if change_type == "remove":
            return Redline(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                change_type=change_type,
                original_text=original_text,
                suggested_text="[УДАЛИТЬ ДАННЫЙ ПУНКТ]",
                location=location,
                issue_description=issue_description,
                priority=self._get_priority(rule),
                confidence=0.85,
                reasoning="Пункт содержит запрещённые положения"
            )
        
        # Use LLM to generate redline
        if self.llm and original_text:
            try:
                return await self._generate_with_llm(
                    rule=rule,
                    original_text=original_text,
                    issue_description=issue_description,
                    location=location
                )
            except Exception as e:
                logger.error(f"LLM redline generation error: {e}")
        
        # Fallback: use template or generic message
        suggested = rule.suggested_clause_template or f"[Требуется ручная доработка согласно правилу: {rule.rule_name}]"
        
        return Redline(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            change_type=change_type,
            original_text=original_text,
            suggested_text=suggested,
            location=location,
            issue_description=issue_description,
            priority=self._get_priority(rule),
            confidence=0.6,
            reasoning="Автоматическая генерация недоступна, требуется ручная доработка"
        )
    
    async def _generate_with_llm(
        self,
        rule: PlaybookRule,
        original_text: str,
        issue_description: str,
        location: Dict[str, Any]
    ) -> Redline:
        """Generate redline using LLM"""
        prompt = ChatPromptTemplate.from_template(REDLINE_GENERATION_PROMPT)
        chain = prompt | self.llm
        
        response = await chain.ainvoke({
            "original_text": original_text,
            "issue_description": issue_description,
            "rule_name": rule.rule_name,
            "rule_description": rule.description or "",
            "rule_type": rule.rule_type,
            "suggested_template": rule.suggested_clause_template or "Шаблон не предоставлен"
        })
        
        # Parse response
        json_match = re.search(r'\{[\s\S]*\}', response.content)
        if json_match:
            data = json.loads(json_match.group())
            
            return Redline(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                change_type="replace",
                original_text=original_text,
                suggested_text=data.get("suggested_text", ""),
                location=location,
                issue_description=issue_description,
                priority=self._get_priority(rule),
                confidence=data.get("confidence", 0.8),
                reasoning=data.get("reasoning", "")
            )
        
        raise ValueError("Failed to parse LLM response")
    
    def _get_priority(self, rule: PlaybookRule) -> str:
        """Get priority based on rule type and severity"""
        if rule.rule_type == "no_go":
            return "critical"
        elif rule.rule_type == "red_line":
            if rule.severity == "critical":
                return "critical"
            elif rule.severity == "high":
                return "high"
            return "medium"
        else:  # fallback
            return "low"
    
    def generate_redline_document(
        self,
        document_id: str,
        document_name: str,
        redlines: List[Redline]
    ) -> RedlineDocument:
        """
        Create a RedlineDocument from a list of redlines
        
        Args:
            document_id: Document ID
            document_name: Document name
            redlines: List of redlines
            
        Returns:
            RedlineDocument
        """
        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_redlines = sorted(
            redlines,
            key=lambda r: priority_order.get(r.priority, 2)
        )
        
        # Count critical changes
        critical_changes = sum(1 for r in redlines if r.priority == "critical")
        
        # Generate summary
        summary_parts = []
        
        if critical_changes > 0:
            summary_parts.append(f"⚠️ {critical_changes} критических изменений требуется")
        
        change_types = {
            "replace": 0,
            "add": 0,
            "remove": 0
        }
        for r in redlines:
            change_types[r.change_type] = change_types.get(r.change_type, 0) + 1
        
        if change_types["replace"] > 0:
            summary_parts.append(f"Заменить: {change_types['replace']} пунктов")
        if change_types["add"] > 0:
            summary_parts.append(f"Добавить: {change_types['add']} пунктов")
        if change_types["remove"] > 0:
            summary_parts.append(f"Удалить: {change_types['remove']} пунктов")
        
        return RedlineDocument(
            document_id=document_id,
            document_name=document_name,
            redlines=sorted_redlines,
            summary=". ".join(summary_parts),
            total_changes=len(redlines),
            critical_changes=critical_changes
        )
    
    def format_redlines_as_text(
        self,
        redline_doc: RedlineDocument
    ) -> str:
        """
        Format redlines as readable text
        
        Args:
            redline_doc: RedlineDocument
            
        Returns:
            Formatted text
        """
        lines = [
            f"ОТЧЁТ О РЕДАКТИРОВАНИИ ДОКУМЕНТА",
            f"Документ: {redline_doc.document_name}",
            f"Всего изменений: {redline_doc.total_changes}",
            f"Критических: {redline_doc.critical_changes}",
            "",
            redline_doc.summary,
            "",
            "=" * 60,
            ""
        ]
        
        for i, redline in enumerate(redline_doc.redlines, 1):
            lines.extend([
                f"ИЗМЕНЕНИЕ #{i} [{redline.priority.upper()}]",
                f"Правило: {redline.rule_name}",
                f"Тип: {self._translate_change_type(redline.change_type)}",
                f"Проблема: {redline.issue_description}",
                "",
            ])
            
            if redline.original_text:
                lines.extend([
                    "ИСХОДНЫЙ ТЕКСТ:",
                    "-" * 40,
                    redline.original_text[:1000],
                    "-" * 40,
                    ""
                ])
            
            lines.extend([
                "ПРЕДЛАГАЕМЫЙ ТЕКСТ:",
                "-" * 40,
                redline.suggested_text[:1000],
                "-" * 40,
                ""
            ])
            
            if redline.reasoning:
                lines.extend([
                    f"Обоснование: {redline.reasoning}",
                    ""
                ])
            
            lines.append("=" * 60)
            lines.append("")
        
        return "\n".join(lines)
    
    def format_redlines_as_html(
        self,
        redline_doc: RedlineDocument
    ) -> str:
        """
        Format redlines as HTML with visual diff
        
        Args:
            redline_doc: RedlineDocument
            
        Returns:
            HTML string
        """
        priority_colors = {
            "critical": "#dc3545",
            "high": "#fd7e14",
            "medium": "#ffc107",
            "low": "#28a745"
        }
        
        html_parts = [
            "<!DOCTYPE html>",
            "<html><head>",
            "<meta charset='utf-8'>",
            "<style>",
            "body { font-family: Arial, sans-serif; margin: 20px; }",
            ".redline { border: 1px solid #ddd; margin: 20px 0; padding: 15px; border-radius: 8px; }",
            ".header { display: flex; justify-content: space-between; margin-bottom: 10px; }",
            ".priority { padding: 4px 8px; border-radius: 4px; color: white; font-weight: bold; }",
            ".original { background: #ffebee; padding: 10px; margin: 10px 0; border-left: 4px solid #f44336; }",
            ".suggested { background: #e8f5e9; padding: 10px; margin: 10px 0; border-left: 4px solid #4caf50; }",
            ".issue { color: #666; font-style: italic; }",
            "</style>",
            "</head><body>",
            f"<h1>Отчёт о редактировании: {redline_doc.document_name}</h1>",
            f"<p><strong>Всего изменений:</strong> {redline_doc.total_changes}</p>",
            f"<p><strong>{redline_doc.summary}</strong></p>",
            "<hr>"
        ]
        
        for i, redline in enumerate(redline_doc.redlines, 1):
            color = priority_colors.get(redline.priority, "#6c757d")
            
            html_parts.extend([
                "<div class='redline'>",
                "<div class='header'>",
                f"<h3>Изменение #{i}: {redline.rule_name}</h3>",
                f"<span class='priority' style='background: {color}'>{redline.priority.upper()}</span>",
                "</div>",
                f"<p class='issue'>Проблема: {redline.issue_description}</p>",
            ])
            
            if redline.original_text:
                html_parts.extend([
                    "<div class='original'>",
                    "<strong>Исходный текст:</strong>",
                    f"<p>{self._escape_html(redline.original_text[:1000])}</p>",
                    "</div>"
                ])
            
            html_parts.extend([
                "<div class='suggested'>",
                "<strong>Предлагаемый текст:</strong>",
                f"<p>{self._escape_html(redline.suggested_text[:1000])}</p>",
                "</div>",
                "</div>"
            ])
        
        html_parts.extend([
            "</body></html>"
        ])
        
        return "\n".join(html_parts)
    
    def _translate_change_type(self, change_type: str) -> str:
        """Translate change type to Russian"""
        translations = {
            "replace": "Замена",
            "add": "Добавление",
            "remove": "Удаление"
        }
        return translations.get(change_type, change_type)
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters"""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
            .replace("\n", "<br>")
        )
    
    def redline_to_dict(self, redline: Redline) -> Dict[str, Any]:
        """Convert Redline to dictionary"""
        return {
            "rule_id": redline.rule_id,
            "rule_name": redline.rule_name,
            "rule_type": redline.rule_type,
            "change_type": redline.change_type,
            "original_text": redline.original_text,
            "suggested_text": redline.suggested_text,
            "location": redline.location,
            "issue_description": redline.issue_description,
            "priority": redline.priority,
            "confidence": redline.confidence,
            "reasoning": redline.reasoning
        }

