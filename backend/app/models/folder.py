"""Folder model for organizing files within cases"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class Folder(Base):
    """
    Folder model - organizes files within a case into folders.
    
    Similar to Harvey's Vault organization feature that allows
    creating folder structures within projects.
    """
    __tablename__ = "folders"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(String, ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Folder info
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(50), nullable=True)  # For UI customization
    icon = Column(String(50), nullable=True)  # Icon name
    
    # Ordering
    order_index = Column(Integer, default=0)
    
    # Metadata
    file_count = Column(Integer, default=0)  # Cached count of files
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Self-referential relationship for nested folders
    children = relationship(
        "Folder",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys=[parent_id]
    )
    parent = relationship(
        "Folder",
        back_populates="children",
        remote_side=[id],
        foreign_keys=[parent_id]
    )
    
    # Relationship to case
    case = relationship("Case", backref="folders")
    
    def to_dict(self, include_children: bool = False):
        """Convert to dictionary for API responses"""
        result = {
            "id": self.id,
            "case_id": self.case_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "icon": self.icon,
            "order_index": self.order_index,
            "file_count": self.file_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_children and self.children:
            result["children"] = [c.to_dict(include_children=True) for c in self.children]
        
        return result
    
    def update_file_count(self, db):
        """Update cached file count"""
        from app.models.case import File
        self.file_count = db.query(File).filter(
            File.folder_id == self.id
        ).count()


class FileTag(Base):
    """
    FileTag model - tags for organizing and filtering files.
    """
    __tablename__ = "file_tags"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    
    name = Column(String(100), nullable=False)
    color = Column(String(50), nullable=True)  # Tag color
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    case = relationship("Case", backref="file_tags")
    
    def to_dict(self):
        return {
            "id": self.id,
            "case_id": self.case_id,
            "name": self.name,
            "color": self.color,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class FileTagAssociation(Base):
    """
    Association table for many-to-many relationship between files and tags.
    """
    __tablename__ = "file_tag_associations"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id = Column(String, ForeignKey("file_tags.id", ondelete="CASCADE"), nullable=False, index=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


# SQL migration for adding folder_id to files table
FOLDER_MIGRATION_SQL = """
-- Add folder_id column to files table
ALTER TABLE files ADD COLUMN folder_id VARCHAR(255) REFERENCES folders(id) ON DELETE SET NULL;

-- Create index for folder_id
CREATE INDEX IF NOT EXISTS ix_files_folder_id ON files(folder_id);

-- Add order_index column to files for ordering within folders
ALTER TABLE files ADD COLUMN order_index INTEGER DEFAULT 0;

-- Add starred column for favorites
ALTER TABLE files ADD COLUMN starred BOOLEAN DEFAULT FALSE;
"""


class FolderService:
    """Service for managing folders"""
    
    def __init__(self, db):
        self.db = db
    
    def create_folder(
        self,
        case_id: str,
        name: str,
        parent_id: str = None,
        description: str = None,
        color: str = None,
        icon: str = None
    ) -> Folder:
        """Create a new folder"""
        # Get max order_index for siblings
        max_order = self.db.query(Folder).filter(
            Folder.case_id == case_id,
            Folder.parent_id == parent_id
        ).count()
        
        folder = Folder(
            case_id=case_id,
            parent_id=parent_id,
            name=name,
            description=description,
            color=color,
            icon=icon,
            order_index=max_order,
        )
        
        self.db.add(folder)
        self.db.commit()
        
        return folder
    
    def get_folders(self, case_id: str, parent_id: str = None) -> list:
        """Get folders for a case, optionally filtered by parent"""
        query = self.db.query(Folder).filter(
            Folder.case_id == case_id
        )
        
        if parent_id is not None:
            query = query.filter(Folder.parent_id == parent_id)
        else:
            query = query.filter(Folder.parent_id.is_(None))
        
        return query.order_by(Folder.order_index).all()
    
    def get_folder_tree(self, case_id: str) -> list:
        """Get full folder tree for a case"""
        root_folders = self.get_folders(case_id, parent_id=None)
        return [f.to_dict(include_children=True) for f in root_folders]
    
    def update_folder(self, folder_id: str, updates: dict) -> Folder:
        """Update a folder"""
        folder = self.db.query(Folder).filter(
            Folder.id == folder_id
        ).first()
        
        if not folder:
            return None
        
        allowed_fields = ["name", "description", "color", "icon", "parent_id", "order_index"]
        for field, value in updates.items():
            if field in allowed_fields:
                setattr(folder, field, value)
        
        folder.updated_at = datetime.utcnow()
        self.db.commit()
        
        return folder
    
    def delete_folder(self, folder_id: str) -> bool:
        """Delete a folder and its contents"""
        folder = self.db.query(Folder).filter(
            Folder.id == folder_id
        ).first()
        
        if not folder:
            return False
        
        self.db.delete(folder)
        self.db.commit()
        
        return True
    
    def move_folder(self, folder_id: str, new_parent_id: str = None) -> Folder:
        """Move a folder to a new parent"""
        folder = self.db.query(Folder).filter(
            Folder.id == folder_id
        ).first()
        
        if not folder:
            return None
        
        # Prevent moving folder into its own descendants
        if new_parent_id:
            parent = self.db.query(Folder).filter(
                Folder.id == new_parent_id
            ).first()
            
            # Check if new_parent is a descendant of folder
            current = parent
            while current:
                if current.id == folder_id:
                    raise ValueError("Cannot move folder into its own descendant")
                current = current.parent if hasattr(current, 'parent') else None
        
        folder.parent_id = new_parent_id
        folder.updated_at = datetime.utcnow()
        self.db.commit()
        
        return folder
    
    def reorder_folders(self, folder_ids: list) -> bool:
        """Reorder folders by providing ordered list of IDs"""
        for index, folder_id in enumerate(folder_ids):
            folder = self.db.query(Folder).filter(
                Folder.id == folder_id
            ).first()
            if folder:
                folder.order_index = index
        
        self.db.commit()
        return True

