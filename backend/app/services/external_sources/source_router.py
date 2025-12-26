"""Source router for managing multiple data sources"""
from typing import List, Dict, Any, Optional, Set
from .base_source import BaseSource, SourceResult, VaultSource
import asyncio
import logging

logger = logging.getLogger(__name__)


class SourceRouter:
    """
    Routes queries to appropriate data sources and aggregates results.
    Implements the pattern shown in Harvey's Assistant interface.
    """
    
    def __init__(self):
        """Initialize the source router"""
        self._sources: Dict[str, BaseSource] = {}
        self._default_sources: Set[str] = {"vault"}  # Always include vault by default
    
    def register_source(self, source: BaseSource) -> None:
        """
        Register a data source
        
        Args:
            source: Source instance to register
        """
        self._sources[source.name] = source
        logger.info(f"Registered source: {source.name}")
    
    def unregister_source(self, name: str) -> bool:
        """
        Unregister a data source
        
        Args:
            name: Name of source to unregister
            
        Returns:
            True if source was unregistered
        """
        if name in self._sources:
            del self._sources[name]
            logger.info(f"Unregistered source: {name}")
            return True
        return False
    
    def get_source(self, name: str) -> Optional[BaseSource]:
        """Get a source by name"""
        return self._sources.get(name)
    
    def get_available_sources(self) -> List[Dict[str, Any]]:
        """
        Get list of all available sources with their status
        
        Returns:
            List of source info dictionaries
        """
        return [source.get_info() for source in self._sources.values()]
    
    def get_enabled_sources(self) -> List[str]:
        """Get names of all enabled sources"""
        return [name for name, source in self._sources.items() if source.enabled]
    
    def set_default_sources(self, source_names: Set[str]) -> None:
        """Set default sources to use when none specified"""
        self._default_sources = source_names
    
    async def initialize_all(self) -> Dict[str, bool]:
        """
        Initialize all registered sources
        
        Returns:
            Dictionary of source name -> initialization success
        """
        results = {}
        for name, source in self._sources.items():
            try:
                results[name] = await source.ensure_initialized()
            except Exception as e:
                logger.error(f"Failed to initialize source {name}: {e}")
                results[name] = False
        return results
    
    async def search(
        self,
        query: str,
        source_names: Optional[List[str]] = None,
        max_results_per_source: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        parallel: bool = True
    ) -> Dict[str, List[SourceResult]]:
        """
        Search across multiple sources
        
        Args:
            query: Search query
            source_names: List of source names to search (None = default sources)
            max_results_per_source: Max results from each source
            filters: Filters to apply (passed to each source)
            parallel: Whether to search sources in parallel
            
        Returns:
            Dictionary of source_name -> list of SourceResult
        """
        # Determine which sources to use
        if source_names is None:
            sources_to_use = self._default_sources
        else:
            sources_to_use = set(source_names)
        
        # Filter to only enabled and registered sources
        active_sources = [
            self._sources[name] 
            for name in sources_to_use 
            if name in self._sources and self._sources[name].enabled
        ]
        
        if not active_sources:
            logger.warning("No active sources to search")
            return {}
        
        results: Dict[str, List[SourceResult]] = {}
        
        if parallel:
            # Search all sources in parallel
            async def search_source(source: BaseSource) -> tuple:
                try:
                    await source.ensure_initialized()
                    source_results = await source.search(
                        query=query,
                        max_results=max_results_per_source,
                        filters=filters
                    )
                    return source.name, source_results
                except Exception as e:
                    logger.error(f"Error searching source {source.name}: {e}", exc_info=True)
                    return source.name, []
            
            tasks = [search_source(source) for source in active_sources]
            search_results = await asyncio.gather(*tasks)
            
            for source_name, source_results in search_results:
                results[source_name] = source_results
        else:
            # Search sources sequentially
            for source in active_sources:
                try:
                    await source.ensure_initialized()
                    source_results = await source.search(
                        query=query,
                        max_results=max_results_per_source,
                        filters=filters
                    )
                    results[source.name] = source_results
                except Exception as e:
                    logger.error(f"Error searching source {source.name}: {e}", exc_info=True)
                    results[source.name] = []
        
        # Log summary
        total_results = sum(len(r) for r in results.values())
        logger.info(
            f"Source search completed: {len(active_sources)} sources, "
            f"{total_results} total results"
        )
        
        return results
    
    def aggregate_results(
        self,
        results: Dict[str, List[SourceResult]],
        max_total: int = 20,
        dedup_threshold: float = 0.9
    ) -> List[SourceResult]:
        """
        Aggregate and rank results from multiple sources
        
        Args:
            results: Results from search()
            max_total: Maximum total results to return
            dedup_threshold: Similarity threshold for deduplication
            
        Returns:
            Sorted and deduplicated list of results
        """
        all_results: List[SourceResult] = []
        
        # Flatten results
        for source_name, source_results in results.items():
            all_results.extend(source_results)
        
        if not all_results:
            return []
        
        # Sort by relevance score (descending)
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)
        
        # Simple deduplication based on content similarity
        deduplicated: List[SourceResult] = []
        seen_content_hashes: Set[int] = set()
        
        for result in all_results:
            # Simple hash-based dedup (can be improved with semantic similarity)
            content_hash = hash(result.content[:200] if len(result.content) > 200 else result.content)
            
            if content_hash not in seen_content_hashes:
                seen_content_hashes.add(content_hash)
                deduplicated.append(result)
                
                if len(deduplicated) >= max_total:
                    break
        
        logger.info(
            f"Aggregated results: {len(all_results)} -> {len(deduplicated)} after dedup"
        )
        
        return deduplicated
    
    def format_for_llm(
        self,
        results: List[SourceResult],
        max_chars: int = 15000
    ) -> str:
        """
        Format aggregated results for LLM context
        
        Args:
            results: Aggregated results
            max_chars: Maximum characters for context
            
        Returns:
            Formatted string for LLM prompt
        """
        if not results:
            return ""
        
        formatted_parts = []
        current_chars = 0
        
        for i, result in enumerate(results, 1):
            # Build source reference
            source_ref = f"[Источник {i}: {result.source_name}"
            if result.title:
                source_ref += f" - {result.title}"
            if result.url:
                source_ref += f" ({result.url})"
            source_ref += "]"
            
            # Truncate content if needed
            available_chars = max_chars - current_chars - len(source_ref) - 10
            if available_chars <= 0:
                break
            
            content = result.content
            if len(content) > available_chars:
                content = content[:available_chars] + "..."
            
            formatted = f"{source_ref}\n{content}"
            formatted_parts.append(formatted)
            current_chars += len(formatted) + 2  # +2 for newlines
            
            if current_chars >= max_chars:
                break
        
        return "\n\n".join(formatted_parts)


# Global router instance
_global_router: Optional[SourceRouter] = None


def get_source_router() -> SourceRouter:
    """Get the global source router instance"""
    global _global_router
    if _global_router is None:
        _global_router = SourceRouter()
        # Register vault source by default
        _global_router.register_source(VaultSource())
    return _global_router


def initialize_source_router(rag_service=None) -> SourceRouter:
    """
    Initialize the global source router with services
    
    Args:
        rag_service: RAG service for vault source
        
    Returns:
        Initialized SourceRouter
    """
    global _global_router
    _global_router = SourceRouter()
    
    # Register vault source with RAG service
    vault_source = VaultSource(rag_service=rag_service)
    _global_router.register_source(vault_source)
    
    logger.info("Source router initialized with vault source")
    
    return _global_router

