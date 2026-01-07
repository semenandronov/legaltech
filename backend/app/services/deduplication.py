"""Deduplication utilities for timeline events and discrepancies using semantic similarity"""
from typing import List, Dict, Any, Optional
import logging
from app.services.yandex_embeddings import YandexEmbeddings
import numpy as np

logger = logging.getLogger(__name__)

# Try to import sklearn for cosine similarity
try:
    from sklearn.metrics.pairwise import cosine_similarity
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("sklearn not available, using manual cosine similarity calculation")


def calculate_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """
    Calculate cosine similarity between two vectors.
    
    Args:
        vec1: First vector
        vec2: Second vector
        
    Returns:
        Cosine similarity score (0-1)
    """
    if SKLEARN_AVAILABLE:
        return cosine_similarity([vec1], [vec2])[0][0]
    else:
        # Manual calculation
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)


def calculate_semantic_similarity(
    text1: str,
    text2: str,
    embeddings_model: Optional[YandexEmbeddings] = None
) -> float:
    """
    Calculate semantic similarity between two texts using embeddings.
    
    Args:
        text1: First text
        text2: Second text
        embeddings_model: Embeddings model instance (creates new if None)
        
    Returns:
        Semantic similarity score (0-1)
    """
    if embeddings_model is None:
        embeddings_model = YandexEmbeddings()
    
    try:
        emb1 = np.array(embeddings_model.embed_query(text1))
        emb2 = np.array(embeddings_model.embed_query(text2))
        return calculate_cosine_similarity(emb1, emb2)
    except Exception as e:
        logger.warning(f"Error calculating semantic similarity: {e}")
        # Fallback to simple text similarity
        return calculate_text_similarity(text1, text2)


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate simple text similarity based on common words.
    Fallback when embeddings are not available.
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity score (0-1)
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    return len(intersection) / len(union) if union else 0.0


def deduplicate_timeline_events(
    events: List[Any],
    similarity_threshold: float = 0.85,
    embeddings_model: Optional[YandexEmbeddings] = None
) -> List[Any]:
    """
    Deduplicate timeline events based on date, description, and semantic similarity.
    
    Args:
        events: List of TimelineEventModel objects or dicts
        similarity_threshold: Threshold for considering events as duplicates (0-1)
        embeddings_model: Embeddings model instance
        
    Returns:
        Deduplicated list of events
    """
    if len(events) <= 1:
        return events
    
    deduplicated = []
    seen_indices = set()
    
    for i, event1 in enumerate(events):
        if i in seen_indices:
            continue
        
        # Extract event data
        if hasattr(event1, 'date'):
            date1 = event1.date
            desc1 = getattr(event1, 'description', '')
            type1 = getattr(event1, 'event_type', '')
        elif isinstance(event1, dict):
            date1 = event1.get('date', '')
            desc1 = event1.get('description', '')
            type1 = event1.get('event_type', '')
        else:
            deduplicated.append(event1)
            continue
        
        # Find similar events
        similar_events = [event1]
        
        for j, event2 in enumerate(events[i+1:], start=i+1):
            if j in seen_indices:
                continue
            
            # Extract event2 data
            if hasattr(event2, 'date'):
                date2 = event2.date
                desc2 = getattr(event2, 'description', '')
                type2 = getattr(event2, 'event_type', '')
            elif isinstance(event2, dict):
                date2 = event2.get('date', '')
                desc2 = event2.get('description', '')
                type2 = event2.get('event_type', '')
            else:
                continue
            
            # Check if dates match (exact match)
            if date1 != date2:
                continue
            
            # Check if event types match
            if type1 and type2 and type1 != type2:
                continue
            
            # Calculate semantic similarity of descriptions
            similarity = calculate_semantic_similarity(desc1, desc2, embeddings_model)
            
            if similarity >= similarity_threshold:
                similar_events.append(event2)
                seen_indices.add(j)
        
        # Merge similar events
        if len(similar_events) > 1:
            merged_event = merge_timeline_events(similar_events)
            deduplicated.append(merged_event)
        else:
            deduplicated.append(event1)
        
        seen_indices.add(i)
    
    logger.info(f"Deduplicated {len(events)} events to {len(deduplicated)} events")
    return deduplicated


def merge_timeline_events(events: List[Any]) -> Any:
    """
    Merge multiple similar timeline events into one.
    
    Args:
        events: List of similar events to merge
        
    Returns:
        Merged event (same type as input events)
    """
    if not events:
        return None
    
    # Use first event as base
    base_event = events[0]
    
    # Merge metadata
    if hasattr(base_event, 'reasoning'):
        # Combine reasoning from all events
        reasoning_parts = [getattr(e, 'reasoning', '') for e in events if getattr(e, 'reasoning', None)]
        merged_reasoning = " | ".join(reasoning_parts) if reasoning_parts else getattr(base_event, 'reasoning', '')
        
        # Update base event
        if hasattr(base_event, 'event_metadata'):
            if base_event.event_metadata is None:
                base_event.event_metadata = {}
            base_event.event_metadata['reasoning'] = merged_reasoning
            # Use highest confidence
            confidences = [getattr(e, 'confidence', 0.0) or 0.0 for e in events]
            base_event.event_metadata['confidence'] = max(confidences) if confidences else 0.8
        else:
            base_event.reasoning = merged_reasoning
            base_event.confidence = max([getattr(e, 'confidence', 0.0) or 0.0 for e in events], default=0.8)
    
    # Merge source documents if different
    if hasattr(base_event, 'source_document'):
        source_docs = set([getattr(e, 'source_document', '') for e in events])
        if len(source_docs) > 1:
            # Keep the first one, but note others in reasoning
            logger.debug(f"Merging events with different source documents: {source_docs}")
    
    return base_event


def deduplicate_discrepancies(
    discrepancies: List[Any],
    similarity_threshold: float = 0.80,
    embeddings_model: Optional[YandexEmbeddings] = None
) -> List[Any]:
    """
    Deduplicate discrepancies based on description and semantic similarity.
    
    Args:
        discrepancies: List of DiscrepancyModel objects or dicts
        similarity_threshold: Threshold for considering discrepancies as duplicates (0-1)
        embeddings_model: Embeddings model instance
        
    Returns:
        Deduplicated list of discrepancies
    """
    if len(discrepancies) <= 1:
        return discrepancies
    
    deduplicated = []
    seen_indices = set()
    
    for i, disc1 in enumerate(discrepancies):
        if i in seen_indices:
            continue
        
        # Extract discrepancy data
        if hasattr(disc1, 'description'):
            desc1 = disc1.description
            type1 = getattr(disc1, 'type', '')
            docs1 = getattr(disc1, 'source_documents', [])
        elif isinstance(disc1, dict):
            desc1 = disc1.get('description', '')
            type1 = disc1.get('type', '')
            docs1 = disc1.get('source_documents', [])
        else:
            deduplicated.append(disc1)
            continue
        
        # Find similar discrepancies
        similar_discs = [disc1]
        
        for j, disc2 in enumerate(discrepancies[i+1:], start=i+1):
            if j in seen_indices:
                continue
            
            # Extract disc2 data
            if hasattr(disc2, 'description'):
                desc2 = disc2.description
                type2 = getattr(disc2, 'type', '')
                docs2 = getattr(disc2, 'source_documents', [])
            elif isinstance(disc2, dict):
                desc2 = disc2.get('description', '')
                type2 = disc2.get('type', '')
                docs2 = disc2.get('source_documents', [])
            else:
                continue
            
            # Check if types match
            if type1 and type2 and type1 != type2:
                continue
            
            # Calculate semantic similarity
            similarity = calculate_semantic_similarity(desc1, desc2, embeddings_model)
            
            if similarity >= similarity_threshold:
                similar_discs.append(disc2)
                seen_indices.add(j)
        
        # Merge similar discrepancies
        if len(similar_discs) > 1:
            merged_disc = merge_discrepancies(similar_discs)
            deduplicated.append(merged_disc)
        else:
            deduplicated.append(disc1)
        
        seen_indices.add(i)
    
    logger.info(f"Deduplicated {len(discrepancies)} discrepancies to {len(deduplicated)} discrepancies")
    return deduplicated


def merge_discrepancies(discrepancies: List[Any]) -> Any:
    """
    Merge multiple similar discrepancies into one.
    
    Args:
        discrepancies: List of similar discrepancies to merge
        
    Returns:
        Merged discrepancy (same type as input discrepancies)
    """
    if not discrepancies:
        return None
    
    # Use first discrepancy as base
    base_disc = discrepancies[0]
    
    # Merge source documents
    all_docs = set()
    for disc in discrepancies:
        if hasattr(disc, 'source_documents'):
            docs = disc.source_documents
            if isinstance(docs, list):
                all_docs.update(docs)
            elif isinstance(docs, str):
                all_docs.add(docs)
        elif isinstance(disc, dict):
            docs = disc.get('source_documents', [])
            if isinstance(docs, list):
                all_docs.update(docs)
            elif isinstance(docs, str):
                all_docs.add(docs)
    
    # Update base discrepancy
    if hasattr(base_disc, 'source_documents'):
        base_disc.source_documents = list(all_docs) if all_docs else getattr(base_disc, 'source_documents', [])
    elif isinstance(base_disc, dict):
        base_disc['source_documents'] = list(all_docs) if all_docs else base_disc.get('source_documents', [])
    
    # Merge reasoning
    if hasattr(base_disc, 'reasoning'):
        reasoning_parts = [getattr(d, 'reasoning', '') for d in discrepancies if getattr(d, 'reasoning', None)]
        merged_reasoning = " | ".join(reasoning_parts) if reasoning_parts else getattr(base_disc, 'reasoning', '')
        
        if hasattr(base_disc, 'details'):
            if base_disc.details is None:
                base_disc.details = {}
            base_disc.details['reasoning'] = merged_reasoning
            # Use highest confidence
            confidences = [getattr(d, 'confidence', 0.0) or 0.0 for d in discrepancies]
            base_disc.details['confidence'] = max(confidences) if confidences else 0.8
        else:
            base_disc.reasoning = merged_reasoning
            base_disc.confidence = max([getattr(d, 'confidence', 0.0) or 0.0 for d in discrepancies], default=0.8)
    
    return base_disc


































