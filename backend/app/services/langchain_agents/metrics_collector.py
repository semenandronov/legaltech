"""Metrics Collector for aggregating and storing agent metrics"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Collector for aggregating metrics from agent callbacks
    
    Stores metrics in database for analysis and monitoring
    """
    
    def __init__(self, db: Session):
        """
        Initialize metrics collector
        
        Args:
            db: Database session
        """
        self.db = db
        self._ensure_table()
    
    def _ensure_table(self):
        """Create metrics table if it doesn't exist"""
        try:
            # Check if table exists
            result = self.db.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = 'agent_metrics'
                )
            """))
            table_exists = result.scalar()
            
            if not table_exists:
                # Create table for storing agent metrics
                self.db.execute(text("""
                    CREATE TABLE IF NOT EXISTS agent_metrics (
                        id SERIAL PRIMARY KEY,
                        case_id VARCHAR(255) NOT NULL,
                        agent_type VARCHAR(100) NOT NULL,
                        metrics JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(case_id, agent_type, created_at)
                    )
                """))
                
                # Create indexes
                self.db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_agent_metrics_case_id 
                    ON agent_metrics(case_id)
                """))
                
                self.db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent_type 
                    ON agent_metrics(agent_type)
                """))
                
                self.db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_agent_metrics_created_at 
                    ON agent_metrics(created_at)
                """))
                
                # GIN index for JSONB queries
                self.db.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_agent_metrics_metrics_gin 
                    ON agent_metrics USING GIN(metrics)
                """))
                
                self.db.commit()
                logger.info("✅ Agent metrics table created")
        except Exception as e:
            logger.warning(f"Metrics table may already exist: {e}")
            try:
                self.db.rollback()
            except:
                pass
    
    def record_agent_metrics(
        self,
        case_id: str,
        agent_type: str,
        metrics: Dict[str, Any],
        model_info: Optional[Dict[str, Any]] = None,
        cache_stats: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Record metrics for an agent execution
        
        Args:
            case_id: Case identifier
            agent_type: Type of agent (timeline, key_facts, etc.)
            metrics: Metrics dictionary from callback.get_metrics()
            model_info: Optional model information (model name, type, cost_tier)
            cache_stats: Optional cache statistics (route_cache_hit, rag_cache_hit)
            
        Returns:
            Record ID or None if failed
        """
        try:
            # Ensure table exists
            self._ensure_table()
            
            # Расширить metrics с информацией о модели и кэше
            extended_metrics = metrics.copy()
            
            # Добавить информацию о модели
            if model_info:
                extended_metrics["model"] = {
                    "name": model_info.get("model", "unknown"),
                    "type": model_info.get("type", "unknown"),  # lite/pro
                    "cost_tier": model_info.get("cost_tier", "unknown")  # low/high
                }
            
            # Добавить статистику кэша
            if cache_stats:
                extended_metrics["cache"] = {
                    "route_cache_hit": cache_stats.get("route_cache_hit", False),
                    "rag_cache_hit": cache_stats.get("rag_cache_hit", False),
                    "rule_based_router_used": cache_stats.get("rule_based_router_used", False)
                }
            
            # Вычислить стоимость (приблизительно)
            if model_info and "tokens_used" in metrics:
                tokens_used = metrics.get("tokens_used", 0)
                model_type = model_info.get("type", "pro")
                # Приблизительные цены (нужно обновить на реальные)
                cost_per_1k_tokens = 0.01 if model_type == "lite" else 0.05
                estimated_cost = (tokens_used / 1000) * cost_per_1k_tokens
                extended_metrics["estimated_cost"] = estimated_cost
                extended_metrics["cost_per_1k_tokens"] = cost_per_1k_tokens
            
            # Insert metrics
            result = self.db.execute(
                text("""
                    INSERT INTO agent_metrics (case_id, agent_type, metrics, created_at)
                    VALUES (:case_id, :agent_type, :metrics, CURRENT_TIMESTAMP)
                    RETURNING id
                """),
                {
                    "case_id": case_id,
                    "agent_type": agent_type,
                    "metrics": json.dumps(extended_metrics, ensure_ascii=False)
                }
            )
            
            record_id = result.scalar()
            self.db.commit()
            
            logger.debug(
                f"Recorded metrics for {agent_type} agent in case {case_id} "
                f"(model: {model_info.get('type', 'unknown') if model_info else 'unknown'}, "
                f"tokens: {metrics.get('tokens_used', 0)})"
            )
            return record_id
            
        except Exception as e:
            logger.error(f"Error recording metrics for {agent_type}: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return None
    
    def get_agent_metrics(
        self,
        case_id: str,
        agent_type: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get metrics for a specific agent in a case
        
        Args:
            case_id: Case identifier
            agent_type: Type of agent
            limit: Maximum number of records to return
            
        Returns:
            List of metrics dictionaries
        """
        try:
            results = self.db.execute(
                text("""
                    SELECT id, metrics, created_at
                    FROM agent_metrics
                    WHERE case_id = :case_id AND agent_type = :agent_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {
                    "case_id": case_id,
                    "agent_type": agent_type,
                    "limit": limit
                }
            ).fetchall()
            
            metrics_list = []
            for row in results:
                metrics_list.append({
                    "id": row[0],
                    "metrics": json.loads(row[1]) if isinstance(row[1], str) else row[1],
                    "created_at": row[2].isoformat() if row[2] else None
                })
            
            return metrics_list
            
        except Exception as e:
            logger.error(f"Error getting metrics for {agent_type}: {e}")
            return []
    
    def get_case_metrics(self, case_id: str) -> Dict[str, Any]:
        """
        Get aggregated metrics for a case (all agents)
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with aggregated metrics
        """
        try:
            results = self.db.execute(
                text("""
                    SELECT agent_type, metrics, created_at
                    FROM agent_metrics
                    WHERE case_id = :case_id
                    ORDER BY created_at DESC
                """),
                {"case_id": case_id}
            ).fetchall()
            
            # Aggregate metrics by agent type
            aggregated = {}
            total_llm_calls = 0
            total_tool_calls = 0
            total_tokens = 0
            total_errors = 0
            total_execution_time = 0.0
            
            for row in results:
                agent_type = row[0]
                metrics = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                created_at = row[2]
                
                if agent_type not in aggregated:
                    aggregated[agent_type] = {
                        "latest": metrics,
                        "history": []
                    }
                
                aggregated[agent_type]["history"].append({
                    "metrics": metrics,
                    "created_at": created_at.isoformat() if created_at else None
                })
                
                # Aggregate totals
                total_llm_calls += metrics.get("llm_calls", 0)
                total_tool_calls += metrics.get("tool_calls", 0)
                total_tokens += metrics.get("tokens_used", 0)
                total_errors += metrics.get("error_count", 0)
                exec_time = metrics.get("execution_time")
                if exec_time:
                    total_execution_time += exec_time
            
            return {
                "case_id": case_id,
                "agents": aggregated,
                "totals": {
                    "llm_calls": total_llm_calls,
                    "tool_calls": total_tool_calls,
                    "tokens_used": total_tokens,
                    "error_count": total_errors,
                    "total_execution_time": total_execution_time,
                    "agent_count": len(aggregated)
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting case metrics: {e}")
            return {
                "case_id": case_id,
                "agents": {},
                "totals": {}
            }
    
    def get_agent_type_stats(self, agent_type: str, limit: int = 100) -> Dict[str, Any]:
        """
        Get statistics for a specific agent type across all cases
        
        Args:
            agent_type: Type of agent
            limit: Maximum number of records to analyze
            
        Returns:
            Statistics dictionary
        """
        try:
            results = self.db.execute(
                text("""
                    SELECT metrics
                    FROM agent_metrics
                    WHERE agent_type = :agent_type
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {
                    "agent_type": agent_type,
                    "limit": limit
                }
            ).fetchall()
            
            if not results:
                return {
                    "agent_type": agent_type,
                    "count": 0,
                    "averages": {}
                }
            
            # Calculate averages
            total_llm_calls = 0
            total_tool_calls = 0
            total_tokens = 0
            total_errors = 0
            total_execution_time = 0.0
            count = 0
            
            for row in results:
                metrics = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                total_llm_calls += metrics.get("llm_calls", 0)
                total_tool_calls += metrics.get("tool_calls", 0)
                total_tokens += metrics.get("tokens_used", 0)
                total_errors += metrics.get("error_count", 0)
                exec_time = metrics.get("execution_time")
                if exec_time:
                    total_execution_time += exec_time
                count += 1
            
            return {
                "agent_type": agent_type,
                "count": count,
                "averages": {
                    "llm_calls": total_llm_calls / count if count > 0 else 0,
                    "tool_calls": total_tool_calls / count if count > 0 else 0,
                    "tokens_used": total_tokens / count if count > 0 else 0,
                    "error_count": total_errors / count if count > 0 else 0,
                    "execution_time": total_execution_time / count if count > 0 else 0.0
                },
                "totals": {
                    "llm_calls": total_llm_calls,
                    "tool_calls": total_tool_calls,
                    "tokens_used": total_tokens,
                    "error_count": total_errors,
                    "execution_time": total_execution_time
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting stats for {agent_type}: {e}")
            return {
                "agent_type": agent_type,
                "count": 0,
                "averages": {}
            }

