"""Component factory for centralized component creation with unified error handling"""
from typing import Dict, Any, Optional, TypeVar, Callable, Tuple
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.advanced_planning_agent import AdvancedPlanningAgent
from app.services.langchain_agents.human_feedback import get_feedback_service
from app.services.langchain_agents.fallback_handler import FallbackHandler
from app.services.langchain_agents.subagent_manager import SubAgentManager
from app.services.context_manager import ContextManager
from app.services.metrics.planning_metrics import MetricsCollector
from app.services.langchain_agents.learning_service import ContinuousLearningService
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ComponentFactory:
    """Centralized factory for creating agent system components with unified error handling"""
    
    @staticmethod
    def create_required_component(
        component_name: str,
        factory_func: Callable[[], T],
        error_message: str
    ) -> T:
        """
        Create a required component - fails fast if initialization fails
        
        Args:
            component_name: Name of component for logging
            factory_func: Function that creates the component
            error_message: Error message if creation fails
            
        Returns:
            Created component
            
        Raises:
            RuntimeError: If component creation fails
        """
        try:
            logger.info(f"Initializing required component: {component_name}")
            component = factory_func()
            logger.info(f"✅ {component_name} initialized successfully")
            return component
        except Exception as e:
            logger.error(f"❌ Failed to initialize required component {component_name}: {e}")
            raise RuntimeError(f"{error_message}: {str(e)}") from e
    
    @staticmethod
    def create_optional_component(
        component_name: str,
        factory_func: Callable[[], T],
        default_value: Optional[T] = None
    ) -> Optional[T]:
        """
        Create an optional component - returns None if initialization fails
        
        Args:
            component_name: Name of component for logging
            factory_func: Function that creates the component
            default_value: Default value if creation fails (default: None)
            
        Returns:
            Created component or default_value if creation fails
        """
        try:
            logger.info(f"Initializing optional component: {component_name}")
            component = factory_func()
            logger.info(f"✅ {component_name} initialized successfully")
            return component
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize optional component {component_name}: {e}, continuing without it")
            return default_value
    
    @staticmethod
    def create_planning_agent(
        rag_service: Optional[RAGService],
        document_processor: Optional[DocumentProcessor]
    ) -> Tuple[Optional[AdvancedPlanningAgent], Optional[PlanningAgent]]:
        """
        Create planning agent - tries AdvancedPlanningAgent first, falls back to PlanningAgent
        
        Args:
            rag_service: RAG service instance
            document_processor: Document processor instance
            
        Returns:
            Tuple of (advanced_planning_agent, planning_agent)
            - If AdvancedPlanningAgent succeeds: (agent, agent.base_planning_agent)
            - If only PlanningAgent succeeds: (None, agent)
            - If both fail: (None, None)
        """
        # Try AdvancedPlanningAgent first
        advanced_agent = ComponentFactory.create_optional_component(
            "AdvancedPlanningAgent",
            lambda: AdvancedPlanningAgent(
                rag_service=rag_service,
                document_processor=document_processor
            )
        )
        
        if advanced_agent:
            return advanced_agent, advanced_agent.base_planning_agent
        
        # Fallback to base PlanningAgent
        base_agent = ComponentFactory.create_optional_component(
            "PlanningAgent",
            lambda: PlanningAgent(
                rag_service=rag_service,
                document_processor=document_processor
            )
        )
        
        return None, base_agent
    
    @staticmethod
    def create_all_components(
        db: Session,
        rag_service: Optional[RAGService],
        document_processor: Optional[DocumentProcessor]
    ) -> Dict[str, Any]:
        """
        Create all components for AgentCoordinator
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
            
        Returns:
            Dictionary with all created components
        """
        components = {}
        
        # Required components (will raise if fail)
        # Note: Graph is created separately in coordinator as it needs other components
        
        # Optional components
        advanced_agent, planning_agent = ComponentFactory.create_planning_agent(
            rag_service, document_processor
        )
        components['advanced_planning_agent'] = advanced_agent
        components['planning_agent'] = planning_agent
        
        components['feedback_service'] = ComponentFactory.create_optional_component(
            "HumanFeedbackService",
            lambda: get_feedback_service(db)
        )
        
        components['fallback_handler'] = ComponentFactory.create_optional_component(
            "FallbackHandler",
            lambda: FallbackHandler()
        )
        
        components['metrics_collector'] = ComponentFactory.create_optional_component(
            "MetricsCollector",
            lambda: MetricsCollector(db)
        )
        
        components['subagent_manager'] = ComponentFactory.create_optional_component(
            "SubAgentManager",
            lambda: SubAgentManager(
                rag_service=rag_service,
                document_processor=document_processor
            )
        )
        
        components['context_manager'] = ComponentFactory.create_optional_component(
            "ContextManager",
            lambda: ContextManager()
        )
        
        components['learning_service'] = ComponentFactory.create_optional_component(
            "ContinuousLearningService",
            lambda: ContinuousLearningService(db)
        )
        
        return components

