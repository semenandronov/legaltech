"""Workflow Graph Builder - builds LangGraph from WorkflowTemplate"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from app.models.workflow_template import WorkflowTemplate
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.graph import create_analysis_graph
from app.config import config
import logging
import os

logger = logging.getLogger(__name__)


class WorkflowGraphBuilder:
    """
    Строит LangGraph из WorkflowTemplate
    
    Преобразует статические шаги workflow в динамический исполняемый граф.
    """
    
    def __init__(
        self,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Initialize WorkflowGraphBuilder
        
        Args:
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.rag_service = rag_service
        self.document_processor = document_processor
    
    def build_graph(
        self,
        template: WorkflowTemplate,
        db: Session = None
    ):
        """
        Создает LangGraph из WorkflowTemplate
        
        Args:
            template: WorkflowTemplate instance
            db: Database session
            
        Returns:
            Compiled LangGraph graph
        """
        # Если есть graph_config, используем его
        if template.graph_config and template.node_mapping:
            logger.info(f"Using pre-built graph config for workflow {template.id}")
            return self._build_from_config(template, db)
        
        # Иначе строим граф из steps
        logger.info(f"Building graph from steps for workflow {template.id}")
        return self._build_from_steps(template, db)
    
    def _build_from_config(
        self,
        template: WorkflowTemplate,
        db: Session = None
    ):
        """Build graph from pre-configured graph_config"""
        # TODO: Implement building from graph_config
        # For now, fallback to build_from_steps
        return self._build_from_steps(template, db)
    
    def _build_from_steps(
        self,
        template: WorkflowTemplate,
        db: Session = None
    ):
        """Build graph from workflow steps"""
        # Extract analysis types from steps
        analysis_types = self._extract_analysis_types(template)
        
        # Use existing create_analysis_graph - it already supports all agents
        graph = create_analysis_graph(
            db=db,
            rag_service=self.rag_service,
            document_processor=self.document_processor,
            use_legora_workflow=True  # Use LEGORA workflow for better orchestration
        )
        
        logger.info(f"Built graph from workflow template {template.id} with {len(analysis_types)} analysis types")
        return graph
    
    def _extract_analysis_types(self, template: WorkflowTemplate) -> List[str]:
        """Extract analysis types from workflow steps"""
        analysis_types = []
        agent_mapping = {
            "classification": "document_classifier",
            "entity_extraction": "entity_extraction",
            "timeline": "timeline",
            "key_facts": "key_facts",
            "discrepancy": "discrepancy",
            "risk": "risk",
            "summary": "summary",
            "privilege_check": "privilege_check",
            "relationship": "relationship"
        }
        
        for step in template.steps or []:
            agent_name = step.get("agent", "")
            if agent_name in agent_mapping:
                analysis_type = agent_mapping[agent_name]
                if analysis_type not in analysis_types:
                    analysis_types.append(analysis_type)
        
        return analysis_types if analysis_types else ["key_facts"]  # Default fallback


