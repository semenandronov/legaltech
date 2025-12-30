"""Workflow Service for managing analysis workflows"""
from typing import List, Dict, Any, Optional, AsyncIterator
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.workflow_template import WorkflowTemplate, DEFAULT_WORKFLOWS
from app.services.workflow_nl_parser import WorkflowNLParser
from app.services.workflow_executor import WorkflowExecutor, WorkflowExecutionEvent
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class WorkflowService:
    """
    Service for managing workflow templates.
    Similar to Harvey's Workflows feature.
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Initialize service
        
        Args:
            db: Database session
            rag_service: Optional RAG service for workflow execution
            document_processor: Optional document processor for workflow execution
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        self.nl_parser = WorkflowNLParser()
    
    def get_workflows(
        self,
        user_id: str,
        category: str = None,
        include_system: bool = True,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get available workflows for a user
        
        Args:
            user_id: User ID
            category: Filter by category
            include_system: Include system workflows
            limit: Max results
            
        Returns:
            List of workflow dictionaries
        """
        query = self.db.query(WorkflowTemplate)
        
        # Visibility filter
        visibility_filters = [WorkflowTemplate.user_id == user_id]
        if include_system:
            visibility_filters.append(WorkflowTemplate.is_system == True)
        visibility_filters.append(WorkflowTemplate.is_public == True)
        
        query = query.filter(or_(*visibility_filters))
        
        # Category filter
        if category:
            query = query.filter(WorkflowTemplate.category == category)
        
        # Order
        query = query.order_by(
            WorkflowTemplate.is_system.desc(),
            WorkflowTemplate.usage_count.desc()
        )
        
        workflows = query.limit(limit).all()
        return [w.to_dict() for w in workflows]
    
    def get_workflow(self, workflow_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific workflow
        
        Args:
            workflow_id: Workflow ID
            user_id: User ID for access check
            
        Returns:
            Workflow dictionary or None
        """
        workflow = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.id == workflow_id
        ).first()
        
        if not workflow:
            return None
        
        # Check access
        if not self._can_access(workflow, user_id):
            return None
        
        return workflow.to_dict()
    
    def get_workflow_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a workflow by name (for system workflows)
        
        Args:
            name: Workflow name
            
        Returns:
            Workflow dictionary or None
        """
        workflow = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.name == name,
            WorkflowTemplate.is_system == True
        ).first()
        
        if not workflow:
            return None
        
        return workflow.to_dict()
    
    def create_workflow(
        self,
        user_id: str,
        name: str,
        display_name: str,
        category: str,
        steps: List[Dict],
        description: str = None,
        review_columns: List[Dict] = None,
        is_public: bool = False
    ) -> Dict[str, Any]:
        """
        Create a custom workflow
        
        Args:
            user_id: User ID
            name: Unique name
            display_name: Display name
            category: Category
            steps: Workflow steps
            description: Optional description
            review_columns: Optional review table columns
            is_public: Whether to share publicly
            
        Returns:
            Created workflow dictionary
        """
        workflow = WorkflowTemplate(
            user_id=user_id,
            name=name,
            display_name=display_name,
            description=description,
            category=category,
            steps=steps,
            review_columns=review_columns or [],
            is_system=False,
            is_public=is_public,
        )
        
        self.db.add(workflow)
        self.db.commit()
        
        logger.info(f"Created workflow: {workflow.id}")
        return workflow.to_dict()
    
    def update_workflow(
        self,
        workflow_id: str,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a workflow
        
        Args:
            workflow_id: Workflow ID
            user_id: User ID for access check
            updates: Fields to update
            
        Returns:
            Updated workflow or None
        """
        workflow = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.id == workflow_id,
            WorkflowTemplate.user_id == user_id  # Only owner can update
        ).first()
        
        if not workflow:
            return None
        
        # Can't update system workflows
        if workflow.is_system:
            return None
        
        # Update fields
        allowed_fields = [
            "display_name", "description", "category",
            "steps", "review_columns", "is_public"
        ]
        
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(workflow, field, value)
        
        workflow.updated_at = datetime.utcnow()
        self.db.commit()
        
        return workflow.to_dict()
    
    def delete_workflow(self, workflow_id: str, user_id: str) -> bool:
        """
        Delete a workflow
        
        Args:
            workflow_id: Workflow ID
            user_id: User ID for access check
            
        Returns:
            True if deleted
        """
        workflow = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.id == workflow_id,
            WorkflowTemplate.user_id == user_id  # Only owner can delete
        ).first()
        
        if not workflow:
            return False
        
        # Can't delete system workflows
        if workflow.is_system:
            return False
        
        self.db.delete(workflow)
        self.db.commit()
        
        return True
    
    def use_workflow(self, workflow_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get workflow for use (increments usage counter)
        
        Args:
            workflow_id: Workflow ID
            user_id: User ID
            
        Returns:
            Workflow dictionary or None
        """
        workflow = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.id == workflow_id
        ).first()
        
        if not workflow:
            return None
        
        if not self._can_access(workflow, user_id):
            return None
        
        workflow.increment_usage()
        self.db.commit()
        
        return workflow.to_dict()
    
    def duplicate_workflow(
        self,
        workflow_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Duplicate a workflow to user's library
        
        Args:
            workflow_id: Workflow to duplicate
            user_id: User ID for new workflow
            
        Returns:
            New workflow or None
        """
        original = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.id == workflow_id
        ).first()
        
        if not original:
            return None
        
        if not self._can_access(original, user_id):
            return None
        
        copy = WorkflowTemplate(
            user_id=user_id,
            name=f"{original.name}_copy",
            display_name=f"{original.display_name} (копия)",
            description=original.description,
            category=original.category,
            steps=original.steps,
            review_columns=original.review_columns,
            is_system=False,
            is_public=False,
        )
        
        self.db.add(copy)
        self.db.commit()
        
        return copy.to_dict()
    
    def _can_access(self, workflow: WorkflowTemplate, user_id: str) -> bool:
        """Check if user can access workflow"""
        return (
            workflow.user_id == user_id or
            workflow.is_public or
            workflow.is_system
        )
    
    def init_system_workflows(self):
        """Initialize system workflow templates"""
        # Check if already initialized
        existing = self.db.query(WorkflowTemplate).filter(
            WorkflowTemplate.is_system == True
        ).first()
        
        if existing:
            logger.info("System workflows already initialized")
            return
        
        for workflow_data in DEFAULT_WORKFLOWS:
            workflow = WorkflowTemplate(
                user_id=None,
                is_system=True,
                is_public=True,
                **workflow_data
            )
            self.db.add(workflow)
        
        try:
            self.db.commit()
            logger.info(f"Initialized {len(DEFAULT_WORKFLOWS)} system workflows")
        except Exception as e:
            logger.error(f"Error initializing system workflows: {e}")
            self.db.rollback()
    
    def get_categories(self) -> List[Dict[str, str]]:
        """Get workflow categories"""
        return [
            {"name": "due_diligence", "display_name": "Due Diligence"},
            {"name": "litigation", "display_name": "Судебные дела"},
            {"name": "contract", "display_name": "Договоры"},
            {"name": "compliance", "display_name": "Compliance"},
            {"name": "research", "display_name": "Исследование"},
            {"name": "custom", "display_name": "Кастомные"},
        ]
    
    def create_workflow_from_nl(
        self,
        user_id: str,
        description: str,
        display_name: str = None,
        category: str = "custom"
    ) -> Dict[str, Any]:
        """
        Создает workflow из natural language описания
        
        Args:
            user_id: User ID
            description: Natural language описание workflow
            display_name: Display name (опционально)
            category: Category для workflow
            
        Returns:
            Created workflow dictionary
        """
        try:
            # Parse NL description to WorkflowTemplate
            workflow = self.nl_parser.parse_workflow_description(
                description=description,
                user_id=user_id,
                display_name=display_name,
                category=category
            )
            
            # Save to database
            self.db.add(workflow)
            self.db.commit()
            self.db.refresh(workflow)
            
            logger.info(f"Created workflow from NL: {workflow.id} - {workflow.display_name}")
            return workflow.to_dict()
            
        except Exception as e:
            logger.error(f"Error creating workflow from NL: {e}", exc_info=True)
            self.db.rollback()
            raise
    
    async def execute_workflow(
        self,
        workflow_id: str,
        case_id: str,
        user_input: str,
        user_id: str
    ) -> AsyncIterator[WorkflowExecutionEvent]:
        """
        Выполняет workflow и возвращает streaming events
        
        Args:
            workflow_id: Workflow template ID
            case_id: Case ID to analyze
            user_input: User input/query
            user_id: User ID
            
        Yields:
            WorkflowExecutionEvent objects
        """
        executor = WorkflowExecutor(
            db=self.db,
            rag_service=self.rag_service,
            document_processor=self.document_processor
        )
        
        async for event in executor.execute_workflow(
            workflow_id=workflow_id,
            case_id=case_id,
            user_input=user_input,
            user_id=user_id
        ):
            yield event

