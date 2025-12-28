# Models module
"""SQLAlchemy models for Legal AI Vault"""

from app.models.case import Base, Case, ChatMessage, File
from app.models.user import User
from app.models.analysis import (
    AnalysisResult,
    DocumentChunk,
    Discrepancy,
    TimelineEvent,
    DocumentClassification,
    ExtractedEntity,
    PrivilegeCheck,
    Risk,
    AnalysisPlan,
)
from app.models.tabular_review import (
    TabularReview,
    TabularColumn,
    TabularCell,
    TabularColumnTemplate,
    TabularDocumentStatus,
)
from app.models.agent_interaction import AgentInteraction, AgentExecutionLog
from app.models.prompt_library import PromptTemplate, PromptCategory
from app.models.workflow_template import WorkflowTemplate
from app.models.folder import Folder, FileTag, FileTagAssociation

__all__ = [
    # Base
    "Base",
    # Core models
    "Case",
    "ChatMessage",
    "File",
    "User",
    # Analysis models
    "AnalysisResult",
    "DocumentChunk",
    "Discrepancy",
    "TimelineEvent",
    "DocumentClassification",
    "ExtractedEntity",
    "PrivilegeCheck",
    "Risk",
    "AnalysisPlan",
    # Tabular review
    "TabularReview",
    "TabularColumn",
    "TabularCell",
    "TabularColumnTemplate",
    "TabularDocumentStatus",
    # Agent interactions (Human-in-the-loop)
    "AgentInteraction",
    "AgentExecutionLog",
    # Prompt library
    "PromptTemplate",
    "PromptCategory",
    # Workflows
    "WorkflowTemplate",
    # Folders and tags
    "Folder",
    "FileTag",
    "FileTagAssociation",
]
