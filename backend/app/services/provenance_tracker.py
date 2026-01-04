"""Provenance Tracker for tracking data sources"""
from typing import Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import logging

logger = logging.getLogger(__name__)


class SourceType(Enum):
    """Types of data sources"""
    WEB_SEARCH = "web_search"
    LEGISLATION = "legislation"
    SUPREME_COURT = "supreme_court"
    CASE_LAW = "case_law"
    DOCUMENT = "document"
    AGENT_OUTPUT = "agent_output"


@dataclass
class Provenance:
    """Provenance information for a piece of data"""
    content_hash: str
    source_type: SourceType
    source_id: str
    source_url: Optional[str] = None
    timestamp: Optional[datetime] = None
    query: Optional[str] = None
    tool_name: Optional[str] = None
    confidence: float = 0.5
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}


class ProvenanceTracker:
    """
    Tracks provenance of all data
    
    Records:
    - Source type and ID
    - URL and timestamp
    - Query used
    - Tool used
    - Content hash for deduplication
    """
    
    def __init__(self):
        self._provenances: Dict[str, Provenance] = {}
        logger.info("✅ ProvenanceTracker initialized")
    
    def track(
        self,
        content: str,
        source_type: SourceType,
        source_id: str,
        **kwargs
    ) -> Provenance:
        """
        Track provenance of content
        
        Args:
            content: Content to track
            source_type: Type of source
            source_id: Source identifier
            **kwargs: Additional metadata (url, query, tool_name, confidence, etc.)
        
        Returns:
            Provenance object
        """
        # Generate content hash for deduplication
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # Create provenance
        provenance = Provenance(
            content_hash=content_hash,
            source_type=source_type,
            source_id=source_id,
            source_url=kwargs.get("url"),
            query=kwargs.get("query"),
            tool_name=kwargs.get("tool_name"),
            confidence=kwargs.get("confidence", 0.5),
            metadata=kwargs.get("metadata", {})
        )
        
        # Store provenance
        self._provenances[content_hash] = provenance
        
        logger.debug(f"Tracked provenance: {source_type.value}/{source_id} (hash: {content_hash[:8]})")
        
        return provenance
    
    def get_provenance(self, content_hash: str) -> Optional[Provenance]:
        """
        Get provenance by content hash
        
        Args:
            content_hash: Content hash
        
        Returns:
            Provenance or None
        """
        return self._provenances.get(content_hash)
    
    def format_citation(self, provenance: Provenance) -> str:
        """
        Format provenance as citation
        
        Args:
            provenance: Provenance object
        
        Returns:
            Formatted citation string
        """
        parts = []
        
        if provenance.source_url:
            parts.append(f"Источник: {provenance.source_url}")
        
        if provenance.source_type == SourceType.LEGISLATION:
            parts.append("Официальное законодательство (pravo.gov.ru)")
        elif provenance.source_type == SourceType.SUPREME_COURT:
            parts.append("Позиция Верховного Суда РФ (vsrf.ru)")
        elif provenance.source_type == SourceType.CASE_LAW:
            parts.append("Судебная практика (kad.arbitr.ru)")
        
        if provenance.timestamp:
            parts.append(f"Дата: {provenance.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        
        if provenance.query:
            parts.append(f"Запрос: {provenance.query}")
        
        return " | ".join(parts) if parts else "Источник не указан"

