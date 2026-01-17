"""Playbook Service for managing playbooks and rules"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from app.models.playbook import (
    Playbook, 
    PlaybookRule, 
    PlaybookCheck,
    CONTRACT_TYPES,
    CLAUSE_CATEGORIES,
    JURISDICTIONS,
)
from datetime import datetime
import logging
import uuid

logger = logging.getLogger(__name__)


class PlaybookService:
    """
    Service for managing Playbooks - наборы правил для проверки контрактов.
    
    Поддерживает:
    - CRUD операции для Playbooks и Rules
    - Системные и пользовательские playbooks
    - Публичные и приватные playbooks
    """
    
    def __init__(self, db: Session):
        """Initialize playbook service"""
        self.db = db
    
    # ==================== PLAYBOOK CRUD ====================
    
    def get_playbooks(
        self,
        user_id: str,
        document_type: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        include_system: bool = True,
        include_public: bool = True,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get available playbooks for a user
        
        Args:
            user_id: User ID
            document_type: Filter by contract type
            jurisdiction: Filter by jurisdiction
            include_system: Include system playbooks
            include_public: Include public playbooks
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of playbook dictionaries
        """
        query = self.db.query(Playbook)
        
        # Visibility filter
        visibility_filters = [Playbook.user_id == user_id]
        if include_system:
            visibility_filters.append(Playbook.is_system == True)
        if include_public:
            visibility_filters.append(Playbook.is_public == True)
        
        query = query.filter(or_(*visibility_filters))
        
        # Contract type filter
        if document_type:
            query = query.filter(Playbook.document_type == document_type)
        
        # Jurisdiction filter
        if jurisdiction:
            query = query.filter(Playbook.jurisdiction == jurisdiction)
        
        # Order by system first, then usage
        query = query.order_by(
            Playbook.is_system.desc(),
            Playbook.usage_count.desc(),
            Playbook.created_at.desc()
        )
        
        playbooks = query.offset(offset).limit(limit).all()
        return [p.to_dict() for p in playbooks]
    
    def get_playbook(
        self,
        playbook_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific playbook
        
        Args:
            playbook_id: Playbook ID
            user_id: User ID for access check
            
        Returns:
            Playbook dictionary or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return None
        
        # Check access
        if not self._can_access(playbook, user_id):
            return None
        
        return playbook.to_dict()
    
    def get_playbook_by_name(
        self,
        name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a playbook by name (mainly for system playbooks)
        
        Args:
            name: Playbook name
            
        Returns:
            Playbook dictionary or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.name == name
        ).first()
        
        if not playbook:
            return None
        
        return playbook.to_dict()
    
    def create_playbook(
        self,
        user_id: str,
        name: str,
        display_name: str,
        document_type: str,
        description: Optional[str] = None,
        jurisdiction: Optional[str] = None,
        is_public: bool = False,
        rules: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Create a new playbook
        
        Args:
            user_id: User ID
            name: Unique name
            display_name: Display name
            document_type: Contract type
            description: Description
            jurisdiction: Jurisdiction
            is_public: Public visibility
            rules: Initial rules
            
        Returns:
            Created playbook dictionary
        """
        # Check if name already exists
        existing = self.db.query(Playbook).filter(
            Playbook.name == name
        ).first()
        
        if existing:
            raise ValueError(f"Playbook with name '{name}' already exists")
        
        playbook = Playbook(
            user_id=user_id,
            name=name,
            display_name=display_name,
            description=description,
            document_type=document_type,
            jurisdiction=jurisdiction,
            is_public=is_public,
            is_system=False,
        )
        
        self.db.add(playbook)
        self.db.flush()  # Get ID
        
        # Add rules if provided
        if rules:
            for rule_data in rules:
                rule = self._create_rule_object(playbook.id, rule_data)
                self.db.add(rule)
        
        self.db.commit()
        self.db.refresh(playbook)
        
        logger.info(f"Created playbook: {playbook.id} - {playbook.display_name}")
        return playbook.to_dict()
    
    def update_playbook(
        self,
        playbook_id: str,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a playbook
        
        Args:
            playbook_id: Playbook ID
            user_id: User ID for access check
            updates: Fields to update
            
        Returns:
            Updated playbook or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return None
        
        # Only owner can update (system playbooks can't be updated by users)
        if playbook.user_id != user_id or playbook.is_system:
            return None
        
        # Update allowed fields
        allowed_fields = [
            "display_name", "description", "document_type",
            "jurisdiction", "is_public"
        ]
        
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(playbook, field, value)
        
        playbook.updated_at = datetime.utcnow()
        playbook.version += 1
        
        self.db.commit()
        self.db.refresh(playbook)
        
        logger.info(f"Updated playbook: {playbook_id}")
        return playbook.to_dict()
    
    def delete_playbook(
        self,
        playbook_id: str,
        user_id: str
    ) -> bool:
        """
        Delete a playbook
        
        Args:
            playbook_id: Playbook ID
            user_id: User ID for access check
            
        Returns:
            True if deleted
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return False
        
        # Only owner can delete (system playbooks can't be deleted)
        if playbook.user_id != user_id or playbook.is_system:
            return False
        
        self.db.delete(playbook)
        self.db.commit()
        
        logger.info(f"Deleted playbook: {playbook_id}")
        return True
    
    def duplicate_playbook(
        self,
        playbook_id: str,
        user_id: str,
        new_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Duplicate a playbook to user's library
        
        Args:
            playbook_id: Playbook to duplicate
            user_id: User ID for new playbook
            new_name: Optional new name
            
        Returns:
            New playbook or None
        """
        original = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not original:
            return None
        
        if not self._can_access(original, user_id):
            return None
        
        # Generate unique name
        if new_name:
            name = new_name
        else:
            base_name = f"{original.name}_copy"
            name = base_name
            counter = 1
            while self.db.query(Playbook).filter(Playbook.name == name).first():
                name = f"{base_name}_{counter}"
                counter += 1
        
        # Create copy
        copy = Playbook(
            user_id=user_id,
            name=name,
            display_name=f"{original.display_name} (копия)",
            description=original.description,
            document_type=original.document_type,
            jurisdiction=original.jurisdiction,
            is_public=False,
            is_system=False,
        )
        
        self.db.add(copy)
        self.db.flush()
        
        # Copy rules
        for rule in original.rules:
            new_rule = PlaybookRule(
                playbook_id=copy.id,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                rule_name=rule.rule_name,
                description=rule.description,
                condition_type=rule.condition_type,
                condition_config=rule.condition_config,
                extraction_prompt=rule.extraction_prompt,
                validation_prompt=rule.validation_prompt,
                suggested_clause_template=rule.suggested_clause_template,
                fallback_options=rule.fallback_options,
                priority=rule.priority,
                severity=rule.severity,
                is_active=rule.is_active,
            )
            self.db.add(new_rule)
        
        self.db.commit()
        self.db.refresh(copy)
        
        logger.info(f"Duplicated playbook {playbook_id} to {copy.id}")
        return copy.to_dict()
    
    def use_playbook(
        self,
        playbook_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Use a playbook (increments usage counter)
        
        Args:
            playbook_id: Playbook ID
            user_id: User ID
            
        Returns:
            Playbook dictionary or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return None
        
        if not self._can_access(playbook, user_id):
            return None
        
        playbook.increment_usage()
        self.db.commit()
        
        return playbook.to_dict()
    
    # ==================== RULES CRUD ====================
    
    def add_rule(
        self,
        playbook_id: str,
        user_id: str,
        rule_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Add a rule to playbook
        
        Args:
            playbook_id: Playbook ID
            user_id: User ID for access check
            rule_data: Rule data
            
        Returns:
            Created rule or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return None
        
        # Only owner can add rules
        if playbook.user_id != user_id or playbook.is_system:
            return None
        
        rule = self._create_rule_object(playbook_id, rule_data)
        self.db.add(rule)
        
        playbook.updated_at = datetime.utcnow()
        playbook.version += 1
        
        self.db.commit()
        self.db.refresh(rule)
        
        logger.info(f"Added rule {rule.id} to playbook {playbook_id}")
        return rule.to_dict()
    
    def update_rule(
        self,
        playbook_id: str,
        rule_id: str,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Update a rule
        
        Args:
            playbook_id: Playbook ID
            rule_id: Rule ID
            user_id: User ID for access check
            updates: Fields to update
            
        Returns:
            Updated rule or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return None
        
        # Only owner can update rules
        if playbook.user_id != user_id or playbook.is_system:
            return None
        
        rule = self.db.query(PlaybookRule).filter(
            and_(
                PlaybookRule.id == rule_id,
                PlaybookRule.playbook_id == playbook_id
            )
        ).first()
        
        if not rule:
            return None
        
        # Update allowed fields
        allowed_fields = [
            "rule_type", "clause_category", "rule_name", "description",
            "condition_type", "condition_config", "extraction_prompt",
            "validation_prompt", "suggested_clause_template", "fallback_options",
            "priority", "severity", "is_active"
        ]
        
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(rule, field, value)
        
        rule.updated_at = datetime.utcnow()
        playbook.updated_at = datetime.utcnow()
        playbook.version += 1
        
        self.db.commit()
        self.db.refresh(rule)
        
        logger.info(f"Updated rule {rule_id}")
        return rule.to_dict()
    
    def delete_rule(
        self,
        playbook_id: str,
        rule_id: str,
        user_id: str
    ) -> bool:
        """
        Delete a rule
        
        Args:
            playbook_id: Playbook ID
            rule_id: Rule ID
            user_id: User ID for access check
            
        Returns:
            True if deleted
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            return False
        
        # Only owner can delete rules
        if playbook.user_id != user_id or playbook.is_system:
            return False
        
        rule = self.db.query(PlaybookRule).filter(
            and_(
                PlaybookRule.id == rule_id,
                PlaybookRule.playbook_id == playbook_id
            )
        ).first()
        
        if not rule:
            return False
        
        self.db.delete(rule)
        playbook.updated_at = datetime.utcnow()
        playbook.version += 1
        
        self.db.commit()
        
        logger.info(f"Deleted rule {rule_id}")
        return True
    
    def get_rule(
        self,
        playbook_id: str,
        rule_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific rule
        
        Args:
            playbook_id: Playbook ID
            rule_id: Rule ID
            user_id: User ID for access check
            
        Returns:
            Rule dictionary or None
        """
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook or not self._can_access(playbook, user_id):
            return None
        
        rule = self.db.query(PlaybookRule).filter(
            and_(
                PlaybookRule.id == rule_id,
                PlaybookRule.playbook_id == playbook_id
            )
        ).first()
        
        if not rule:
            return None
        
        return rule.to_dict()
    
    # ==================== CHECKS ====================
    
    def get_checks(
        self,
        user_id: str,
        playbook_id: Optional[str] = None,
        case_id: Optional[str] = None,
        document_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get playbook checks
        
        Args:
            user_id: User ID
            playbook_id: Filter by playbook
            case_id: Filter by case
            document_id: Filter by document
            status: Filter by status
            limit: Max results
            offset: Pagination offset
            
        Returns:
            List of check dictionaries
        """
        query = self.db.query(PlaybookCheck).filter(
            PlaybookCheck.user_id == user_id
        )
        
        if playbook_id:
            query = query.filter(PlaybookCheck.playbook_id == playbook_id)
        
        if case_id:
            query = query.filter(PlaybookCheck.case_id == case_id)
        
        if document_id:
            query = query.filter(PlaybookCheck.document_id == document_id)
        
        if status:
            query = query.filter(PlaybookCheck.overall_status == status)
        
        query = query.order_by(PlaybookCheck.created_at.desc())
        
        checks = query.offset(offset).limit(limit).all()
        return [c.to_dict(include_details=False) for c in checks]
    
    def get_check(
        self,
        check_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific check with full details
        
        Args:
            check_id: Check ID
            user_id: User ID for access check
            
        Returns:
            Check dictionary or None
        """
        check = self.db.query(PlaybookCheck).filter(
            and_(
                PlaybookCheck.id == check_id,
                PlaybookCheck.user_id == user_id
            )
        ).first()
        
        if not check:
            return None
        
        return check.to_dict(include_details=True)
    
    # ==================== HELPERS ====================
    
    def _can_access(self, playbook: Playbook, user_id: str) -> bool:
        """Check if user can access playbook"""
        return (
            playbook.user_id == user_id or
            playbook.is_public or
            playbook.is_system
        )
    
    def _create_rule_object(
        self,
        playbook_id: str,
        rule_data: Dict[str, Any]
    ) -> PlaybookRule:
        """Create PlaybookRule object from data"""
        return PlaybookRule(
            playbook_id=playbook_id,
            rule_type=rule_data.get("rule_type", "red_line"),
            clause_category=rule_data.get("clause_category", "other"),
            rule_name=rule_data.get("rule_name", "Unnamed Rule"),
            description=rule_data.get("description"),
            condition_type=rule_data.get("condition_type", "must_exist"),
            condition_config=rule_data.get("condition_config", {}),
            extraction_prompt=rule_data.get("extraction_prompt"),
            validation_prompt=rule_data.get("validation_prompt"),
            suggested_clause_template=rule_data.get("suggested_clause_template"),
            fallback_options=rule_data.get("fallback_options"),
            priority=rule_data.get("priority", 0),
            severity=rule_data.get("severity", "medium"),
            is_active=rule_data.get("is_active", True),
        )
    
    # ==================== METADATA ====================
    
    def get_document_types(self) -> List[Dict[str, str]]:
        """Get available contract types"""
        return CONTRACT_TYPES
    
    def get_clause_categories(self) -> List[Dict[str, str]]:
        """Get available clause categories"""
        return CLAUSE_CATEGORIES
    
    def get_jurisdictions(self) -> List[Dict[str, str]]:
        """Get available jurisdictions"""
        return JURISDICTIONS
    
    def get_rule_types(self) -> List[Dict[str, str]]:
        """Get available rule types"""
        return [
            {"name": "red_line", "display_name": "Red Line (обязательное требование)"},
            {"name": "fallback", "display_name": "Fallback (можно обсудить)"},
            {"name": "no_go", "display_name": "No-Go (неприемлемо)"},
        ]
    
    def get_condition_types(self) -> List[Dict[str, str]]:
        """Get available condition types"""
        return [
            {"name": "must_exist", "display_name": "Должен существовать"},
            {"name": "must_not_exist", "display_name": "Не должен существовать"},
            {"name": "value_check", "display_name": "Проверка значения"},
            {"name": "duration_check", "display_name": "Проверка срока"},
            {"name": "text_match", "display_name": "Текст содержит"},
            {"name": "text_not_match", "display_name": "Текст не содержит"},
        ]

