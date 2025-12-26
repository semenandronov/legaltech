"""Prompt Library Service for managing reusable prompts"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models.prompt_library import (
    PromptTemplate, 
    PromptCategory,
    DEFAULT_CATEGORIES,
    DEFAULT_PROMPTS
)
from datetime import datetime
import logging
import uuid

logger = logging.getLogger(__name__)


class PromptLibraryService:
    """
    Service for managing prompt templates.
    Similar to Harvey's Prompts feature.
    """
    
    def __init__(self, db: Session):
        """
        Initialize service
        
        Args:
            db: Database session
        """
        self.db = db
    
    def get_templates(
        self,
        user_id: str,
        category: str = None,
        search: str = None,
        include_public: bool = True,
        include_system: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get prompt templates for a user
        
        Args:
            user_id: User ID
            category: Filter by category
            search: Search in title and description
            include_public: Include public templates
            include_system: Include system templates
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of template dictionaries
        """
        query = self.db.query(PromptTemplate)
        
        # Build visibility filter
        visibility_filters = [PromptTemplate.user_id == user_id]
        if include_public:
            visibility_filters.append(PromptTemplate.is_public == True)
        if include_system:
            visibility_filters.append(PromptTemplate.is_system == True)
        
        query = query.filter(or_(*visibility_filters))
        
        # Category filter
        if category:
            query = query.filter(PromptTemplate.category == category)
        
        # Search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    PromptTemplate.title.ilike(search_term),
                    PromptTemplate.description.ilike(search_term),
                )
            )
        
        # Order by usage and creation
        query = query.order_by(
            PromptTemplate.is_system.desc(),
            PromptTemplate.usage_count.desc(),
            PromptTemplate.created_at.desc()
        )
        
        # Pagination
        templates = query.offset(offset).limit(limit).all()
        
        return [t.to_dict() for t in templates]
    
    def get_template(self, template_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific template
        
        Args:
            template_id: Template ID
            user_id: User ID for access check
            
        Returns:
            Template dictionary or None
        """
        template = self.db.query(PromptTemplate).filter(
            PromptTemplate.id == template_id
        ).first()
        
        if not template:
            return None
        
        # Check access
        if not self._can_access(template, user_id):
            return None
        
        return template.to_dict()
    
    def create_template(
        self,
        user_id: str,
        title: str,
        prompt_text: str,
        category: str = "custom",
        description: str = None,
        variables: List[Dict] = None,
        tags: List[str] = None,
        is_public: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new prompt template
        
        Args:
            user_id: User ID
            title: Template title
            prompt_text: Prompt text with optional {{variables}}
            category: Category name
            description: Optional description
            variables: Variable definitions
            tags: Tags for search
            is_public: Whether to share publicly
            
        Returns:
            Created template dictionary
        """
        template = PromptTemplate(
            user_id=user_id,
            title=title,
            prompt_text=prompt_text,
            category=category,
            description=description,
            variables=variables or [],
            tags=tags or [],
            is_public=is_public,
            is_system=False,
        )
        
        self.db.add(template)
        self.db.commit()
        
        logger.info(f"Created prompt template: {template.id}")
        return template.to_dict()
    
    def update_template(
        self,
        template_id: str,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a prompt template
        
        Args:
            template_id: Template ID
            user_id: User ID for access check
            updates: Fields to update
            
        Returns:
            Updated template or None
        """
        template = self.db.query(PromptTemplate).filter(
            PromptTemplate.id == template_id,
            PromptTemplate.user_id == user_id  # Only owner can update
        ).first()
        
        if not template:
            return None
        
        # Can't update system templates
        if template.is_system:
            logger.warning(f"Attempt to update system template: {template_id}")
            return None
        
        # Update fields
        allowed_fields = [
            "title", "description", "prompt_text", "category",
            "subcategory", "variables", "tags", "is_public"
        ]
        
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(template, field, value)
        
        template.updated_at = datetime.utcnow()
        self.db.commit()
        
        logger.info(f"Updated prompt template: {template_id}")
        return template.to_dict()
    
    def delete_template(self, template_id: str, user_id: str) -> bool:
        """
        Delete a prompt template
        
        Args:
            template_id: Template ID
            user_id: User ID for access check
            
        Returns:
            True if deleted
        """
        template = self.db.query(PromptTemplate).filter(
            PromptTemplate.id == template_id,
            PromptTemplate.user_id == user_id  # Only owner can delete
        ).first()
        
        if not template:
            return False
        
        # Can't delete system templates
        if template.is_system:
            logger.warning(f"Attempt to delete system template: {template_id}")
            return False
        
        self.db.delete(template)
        self.db.commit()
        
        logger.info(f"Deleted prompt template: {template_id}")
        return True
    
    def use_template(
        self,
        template_id: str,
        user_id: str,
        variables: Dict[str, str] = None
    ) -> Optional[str]:
        """
        Use a template - renders it and tracks usage
        
        Args:
            template_id: Template ID
            user_id: User ID
            variables: Values for template variables
            
        Returns:
            Rendered prompt text or None
        """
        template = self.db.query(PromptTemplate).filter(
            PromptTemplate.id == template_id
        ).first()
        
        if not template:
            return None
        
        if not self._can_access(template, user_id):
            return None
        
        # Render template
        rendered = template.render(variables or {})
        
        # Track usage
        template.increment_usage()
        self.db.commit()
        
        logger.info(f"Used prompt template: {template_id}")
        return rendered
    
    def get_categories(self) -> List[Dict[str, Any]]:
        """Get all prompt categories"""
        categories = self.db.query(PromptCategory).order_by(
            PromptCategory.order_index
        ).all()
        
        if not categories:
            # Initialize default categories
            self._init_default_categories()
            categories = self.db.query(PromptCategory).order_by(
                PromptCategory.order_index
            ).all()
        
        return [c.to_dict() for c in categories]
    
    def get_popular_templates(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get most popular templates"""
        return self.get_templates(
            user_id=user_id,
            limit=limit,
            include_public=True,
            include_system=True
        )
    
    def get_recent_templates(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recently used templates by user"""
        templates = self.db.query(PromptTemplate).filter(
            PromptTemplate.user_id == user_id,
            PromptTemplate.last_used_at.isnot(None)
        ).order_by(
            PromptTemplate.last_used_at.desc()
        ).limit(limit).all()
        
        return [t.to_dict() for t in templates]
    
    def duplicate_template(
        self,
        template_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Duplicate a template to user's library
        
        Args:
            template_id: Template to duplicate
            user_id: User ID for new template
            
        Returns:
            New template or None
        """
        original = self.db.query(PromptTemplate).filter(
            PromptTemplate.id == template_id
        ).first()
        
        if not original:
            return None
        
        if not self._can_access(original, user_id):
            return None
        
        # Create copy
        copy = PromptTemplate(
            user_id=user_id,
            title=f"{original.title} (копия)",
            description=original.description,
            prompt_text=original.prompt_text,
            category=original.category,
            subcategory=original.subcategory,
            variables=original.variables,
            tags=original.tags,
            is_public=False,
            is_system=False,
        )
        
        self.db.add(copy)
        self.db.commit()
        
        logger.info(f"Duplicated template {template_id} to {copy.id}")
        return copy.to_dict()
    
    def _can_access(self, template: PromptTemplate, user_id: str) -> bool:
        """Check if user can access template"""
        return (
            template.user_id == user_id or
            template.is_public or
            template.is_system
        )
    
    def _init_default_categories(self):
        """Initialize default categories"""
        for cat_data in DEFAULT_CATEGORIES:
            category = PromptCategory(**cat_data)
            self.db.add(category)
        
        try:
            self.db.commit()
            logger.info("Initialized default prompt categories")
        except Exception as e:
            logger.error(f"Error initializing categories: {e}")
            self.db.rollback()
    
    def init_system_prompts(self):
        """Initialize system prompt templates"""
        # Check if already initialized
        existing = self.db.query(PromptTemplate).filter(
            PromptTemplate.is_system == True
        ).first()
        
        if existing:
            logger.info("System prompts already initialized")
            return
        
        for prompt_data in DEFAULT_PROMPTS:
            prompt = PromptTemplate(
                user_id=None,
                is_system=True,
                is_public=True,
                **prompt_data
            )
            self.db.add(prompt)
        
        try:
            self.db.commit()
            logger.info(f"Initialized {len(DEFAULT_PROMPTS)} system prompts")
        except Exception as e:
            logger.error(f"Error initializing system prompts: {e}")
            self.db.rollback()

