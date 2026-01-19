"""
Субагенты для архитектуры Supervisor.

Каждый субагент - специализированный инструмент с:
- Чёткой спецификацией (имя, описание, capabilities)
- Определённым input/output schema
- Методом execute для выполнения задачи
"""
from app.services.workflows.subagents.summarizer import SummarizerAgent
from app.services.workflows.subagents.entity_extractor import EntityExtractorAgent
from app.services.workflows.subagents.rag_searcher import RAGSearcherAgent
from app.services.workflows.subagents.playbook_checker import PlaybookCheckerAgent
from app.services.workflows.subagents.tabular_reviewer import TabularReviewerAgent
from app.services.workflows.subagents.legal_researcher import LegalResearcherAgent
from app.services.workflows.subagents.document_drafter import DocumentDrafterAgent

__all__ = [
    "SummarizerAgent",
    "EntityExtractorAgent",
    "RAGSearcherAgent",
    "PlaybookCheckerAgent",
    "TabularReviewerAgent",
    "LegalResearcherAgent",
    "DocumentDrafterAgent"
]


