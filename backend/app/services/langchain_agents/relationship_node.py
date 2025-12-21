"""Relationship extraction agent node for LangGraph - builds relationship graph"""
from typing import Dict, Any, Optional, List
from app.services.yandex_llm import ChatYandexGPT
from langchain_core.prompts import ChatPromptTemplate
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from sqlalchemy.orm import Session
from app.models.analysis import RelationshipNode, RelationshipEdge, ExtractedEntity
import logging
import json
import re
from difflib import SequenceMatcher
from collections import defaultdict

logger = logging.getLogger(__name__)


def relationship_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Relationship extraction agent node - builds relationship graph from entities
    
    According to expert recommendations, this agent extracts PERSON→ACTION→PERSON relationships
    and builds a graph structure for visualization with D3.js.
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with relationship_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Relationship agent: Starting relationship extraction for case {case_id}")
        
        if not db:
            raise ValueError("Database session required for relationship extraction")
        
        # Get extracted entities from database
        entities = db.query(ExtractedEntity).filter(
            ExtractedEntity.case_id == case_id
        ).all()
        
        if not entities:
            logger.warning(f"No entities found for relationship extraction in case {case_id}")
            new_state = state.copy()
            new_state["relationship_result"] = None
            return new_state
        
        # Entity linking: deduplicate entities using fuzzy matching
        merged_entities = _merge_duplicate_entities(entities)
        logger.info(f"Merged {len(entities)} entities to {len(merged_entities)} unique entities")
        
        # Group entities by type
        persons = [e for e in merged_entities if e.entity_type == "PERSON"]
        organizations = [e for e in merged_entities if e.entity_type == "ORG"]
        
        if not persons and not organizations:
            logger.warning(f"No PERSON or ORG entities found for relationship extraction")
            new_state = state.copy()
            new_state["relationship_result"] = None
            return new_state
        
        # Initialize LLM
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) or not config.YANDEX_FOLDER_ID:
            raise ValueError("YANDEX_API_KEY/YANDEX_IAM_TOKEN и YANDEX_FOLDER_ID должны быть настроены")
        
        llm = ChatYandexGPT(
            model_name=config.YANDEX_GPT_MODEL,
            temperature=0,
            max_tokens=2000
        )
        
        # Get relationship extraction prompt
        system_prompt = """Ты эксперт по извлечению связей между сущностями из юридических документов.

Твоя задача - найти связи между людьми, организациями и другими сущностями.

Типы связей:
- signed: подписал договор/документ
- works_for: работает в организации
- owns: владеет организацией/активами
- contacted: связался/встретился с
- represented_by: представлен адвокатом
- involved_in: участвует в событии/деле

Верни JSON в формате:
{
  "nodes": [
    {"node_id": "CEO_Ivanov", "type": "Person", "label": "Иванов Иван Иванович", "properties": {"title": "CEO"}},
    {"node_id": "Company_ABC", "type": "Organization", "label": "ООО 'АБВ'", "properties": {}}
  ],
  "edges": [
    {"source": "CEO_Ivanov", "target": "Company_ABC", "type": "works_for", "label": "работает в", "confidence": 0.95, "context": "Иванов является генеральным директором"}
  ]
}"""
        
        # Prepare entity context for LLM with enhanced context
        entity_context = []
        entities_to_process = merged_entities[:50]  # Limit to 50 entities to avoid token limits
        for entity in entities_to_process:
            context_info = entity.context or "нет контекста"
            # Include document info if available
            doc_info = f" (документ: {entity.source_file})" if hasattr(entity, 'source_file') and entity.source_file else ""
            entity_context.append(f"- {entity.entity_type}: {entity.entity_text} (контекст: {context_info}){doc_info}")
        
        entity_text = "\n".join(entity_context)
        
        # Get document chunks for additional context (for relationship extraction)
        doc_context = ""
        if document_processor:
            try:
                # Get sample documents to provide context for relationship extraction
                sample_docs = document_processor.retrieve_relevant_chunks(
                    case_id=case_id,
                    query="связи отношения взаимодействие между",
                    k=5,
                    db=db
                )
                if sample_docs:
                    doc_context = "\n".join([doc.page_content[:200] for doc in sample_docs[:3]])
            except Exception as e:
                logger.warning(f"Could not retrieve document context for relationships: {e}")
        
        user_prompt = f"""ИЗВЛЕЧЕННЫЕ СУЩНОСТИ:
{entity_text}

{f'КОНТЕКСТ ИЗ ДОКУМЕНТОВ:\n{doc_context}\n\n' if doc_context else ''}Найди связи между этими сущностями. Верни JSON с nodes и edges."""
        
        # Extract relationships using LLM
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", user_prompt)
            ])
            chain = prompt | llm
            response = chain.invoke({})
            
            # Parse JSON response
            content = response.content if hasattr(response, 'content') else str(response)
            # Extract JSON from response (may be wrapped in markdown code blocks)
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result_json = json.loads(json_match.group())
            else:
                result_json = json.loads(content)
        except Exception as e:
            logger.error(f"Error extracting relationships via LLM: {e}", exc_info=True)
            # Fallback: create simple relationships based on entity co-occurrence
            result_json = _create_simple_relationships(merged_entities)
        
        # Save nodes and edges to database
        nodes_map = {}  # node_id -> RelationshipNode
        saved_nodes = []
        saved_edges = []
        
        # Save nodes
        for node_data in result_json.get("nodes", []):
            node_id = node_data.get("node_id")
            if not node_id:
                continue
            
            # Check if node already exists
            existing_node = db.query(RelationshipNode).filter(
                RelationshipNode.case_id == case_id,
                RelationshipNode.node_id == node_id
            ).first()
            
            if existing_node:
                nodes_map[node_id] = existing_node
                continue
            
            # Create new node
            node = RelationshipNode(
                case_id=case_id,
                node_id=node_id,
                node_type=node_data.get("type", "Unknown"),
                node_label=node_data.get("label", node_id),
                properties=node_data.get("properties", {}),
                source_document=None  # Could be extracted from entity context
            )
            db.add(node)
            nodes_map[node_id] = node
            saved_nodes.append(node_data)
        
        db.flush()  # Flush to get node IDs
        
        # Save edges
        for edge_data in result_json.get("edges", []):
            source_id = edge_data.get("source")
            target_id = edge_data.get("target")
            
            if not source_id or not target_id:
                continue
            
            # Skip if nodes don't exist
            if source_id not in nodes_map or target_id not in nodes_map:
                continue
            
            # Check if edge already exists
            existing_edge = db.query(RelationshipEdge).filter(
                RelationshipEdge.case_id == case_id,
                RelationshipEdge.source_node_id == source_id,
                RelationshipEdge.target_node_id == target_id,
                RelationshipEdge.relationship_type == edge_data.get("type", "")
            ).first()
            
            if existing_edge:
                continue
            
            # Create new edge
            edge = RelationshipEdge(
                case_id=case_id,
                source_node_id=source_id,
                target_node_id=target_id,
                relationship_type=edge_data.get("type", "related"),
                relationship_label=edge_data.get("label"),
                confidence=str(edge_data.get("confidence", 0.5)),
                context=edge_data.get("context"),
                source_document=None,
                properties=edge_data.get("properties", {})
            )
            db.add(edge)
            saved_edges.append(edge_data)
        
        db.commit()
        
        logger.info(
            f"Relationship agent: Created {len(saved_nodes)} nodes and {len(saved_edges)} edges for case {case_id}"
        )
        
        # Create result
        result_data = {
            "nodes": saved_nodes,
            "edges": saved_edges,
            "total_nodes": len(saved_nodes),
            "total_edges": len(saved_edges)
        }
        
        # Update state
        new_state = state.copy()
        new_state["relationship_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Relationship agent error for case {case_id}: {e}", exc_info=True)
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "relationship",
            "error": str(e)
        })
        new_state["relationship_result"] = None
        return new_state


def _merge_duplicate_entities(entities: List[ExtractedEntity], similarity_threshold: float = 0.85) -> List[ExtractedEntity]:
    """
    Merge duplicate entities using fuzzy string matching (entity linking)
    
    Args:
        entities: List of ExtractedEntity objects
        similarity_threshold: Minimum similarity score to consider entities as duplicates (0-1)
        
    Returns:
        List of merged/deduplicated entities
    """
    if not entities:
        return []
    
    # Group entities by type first (PERSON, ORG, etc.)
    entities_by_type = defaultdict(list)
    for entity in entities:
        entities_by_type[entity.entity_type].append(entity)
    
    merged = []
    
    for entity_type, type_entities in entities_by_type.items():
        # For each entity type, find and merge duplicates
        processed = set()
        
        for i, entity1 in enumerate(type_entities):
            if i in processed:
                continue
            
            # Start with this entity as the "canonical" one
            canonical = entity1
            canonical_text = entity1.entity_text.lower().strip()
            canonical_context = (canonical.context or "").lower()
            
            # Find similar entities
            similar_indices = [i]
            for j, entity2 in enumerate(type_entities[i+1:], start=i+1):
                if j in processed:
                    continue
                
                entity2_text = entity2.entity_text.lower().strip()
                
                # Calculate similarity
                similarity = SequenceMatcher(None, canonical_text, entity2_text).ratio()
                
                # Also check if one is substring of another (e.g., "Иванов" vs "Иванов И.И.")
                is_substring = canonical_text in entity2_text or entity2_text in canonical_text
                
                if similarity >= similarity_threshold or is_substring:
                    similar_indices.append(j)
                    processed.add(j)
                    
                    # Use the longer/more complete version as canonical
                    if len(entity2_text) > len(canonical_text):
                        canonical = entity2
                        canonical_text = entity2_text
                        canonical_context = (entity2.context or "").lower()
                    elif len(entity2_text) == len(canonical_text):
                        # Prefer entity with more context
                        if len(entity2.context or "") > len(canonical_context):
                            canonical = entity2
                            canonical_context = (entity2.context or "").lower()
            
            # Merge context from all similar entities
            all_contexts = [canonical.context or ""]
            for idx in similar_indices[1:]:
                ctx = type_entities[idx].context
                if ctx and ctx not in all_contexts:
                    all_contexts.append(ctx)
            
            # Update canonical entity with merged context
            if len(all_contexts) > 1:
                canonical.context = " | ".join([c for c in all_contexts if c])
            
            merged.append(canonical)
            processed.add(i)
    
    return merged


def _create_simple_relationships(entities: List[ExtractedEntity]) -> Dict[str, Any]:
    """Fallback: create simple relationships based on entity co-occurrence"""
    nodes = []
    edges = []
    
    # Create nodes from entities
    node_ids = set()
    for entity in entities:
        if entity.entity_type in ["PERSON", "ORG"]:
            node_id = f"{entity.entity_type}_{entity.entity_text.replace(' ', '_')}"
            if node_id not in node_ids:
                nodes.append({
                    "node_id": node_id,
                    "type": entity.entity_type,
                    "label": entity.entity_text,
                    "properties": {}
                })
                node_ids.add(node_id)
    
    # Create simple edges (same document = related)
    # This is a fallback, LLM should do better
    return {
        "nodes": nodes,
        "edges": edges
    }

