"""Citation quality metrics service for monitoring RAG responses

This service tracks citation quality metrics:
- Verified vs unverified citations
- Citation count per response
- Confidence levels
- Citation verification rates
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CitationMetrics:
    """Service for tracking citation quality metrics"""
    
    def __init__(self):
        """Initialize citation metrics service"""
        self.metrics: Dict[str, Any] = {
            "total_responses": 0,
            "total_claims": 0,
            "total_citations": 0,
            "verified_citations": 0,
            "unverified_citations": 0,
            "high_confidence_claims": 0,
            "medium_confidence_claims": 0,
            "low_confidence_claims": 0,
        }
    
    def record_response(
        self,
        response_data: Dict[str, Any],
        verification_results: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Record metrics from a RAG response
        
        Args:
            response_data: Structured response data (LegalRAGResponse or dict)
            verification_results: Optional list of verification results from Judge
        """
        try:
            self.metrics["total_responses"] += 1
            
            # Extract claims and citations
            if isinstance(response_data, dict):
                claims = response_data.get("claims", [])
                confidence_overall = response_data.get("confidence_overall", "medium")
            else:
                claims = getattr(response_data, "claims", [])
                confidence_overall = getattr(response_data, "confidence_overall", "medium")
            
            self.metrics["total_claims"] += len(claims)
            
            # Count citations and track confidence
            for i, claim in enumerate(claims):
                if isinstance(claim, dict):
                    citations = claim.get("citations", [])
                    confidence = claim.get("confidence", "medium")
                else:
                    citations = getattr(claim, "citations", [])
                    confidence = getattr(claim, "confidence", "medium")
                
                self.metrics["total_citations"] += len(citations)
                
                # Track confidence levels
                confidence_key = f"{confidence}_confidence_claims"
                if confidence_key in self.metrics:
                    self.metrics[confidence_key] += 1
                
                # Track verification if results provided
                if verification_results and i < len(verification_results):
                    result = verification_results[i]
                    if result.get("verified", False):
                        self.metrics["verified_citations"] += len(citations)
                    else:
                        self.metrics["unverified_citations"] += len(citations)
            
            logger.debug(
                f"Recorded metrics: {len(claims)} claims, "
                f"{sum(len(getattr(c, 'citations', c.get('citations', []))) for c in claims)} citations"
            )
            
        except Exception as e:
            logger.error(f"Error recording citation metrics: {e}", exc_info=True)
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics summary
        
        Returns:
            Dictionary with metrics and calculated rates
        """
        metrics = self.metrics.copy()
        
        # Calculate rates
        if metrics["total_responses"] > 0:
            metrics["avg_claims_per_response"] = metrics["total_claims"] / metrics["total_responses"]
            metrics["avg_citations_per_response"] = metrics["total_citations"] / metrics["total_responses"]
        else:
            metrics["avg_claims_per_response"] = 0.0
            metrics["avg_citations_per_response"] = 0.0
        
        if metrics["total_citations"] > 0:
            metrics["verification_rate"] = metrics["verified_citations"] / metrics["total_citations"]
            metrics["unverified_rate"] = metrics["unverified_citations"] / metrics["total_citations"]
        else:
            metrics["verification_rate"] = 0.0
            metrics["unverified_rate"] = 0.0
        
        if metrics["total_claims"] > 0:
            metrics["high_confidence_rate"] = metrics["high_confidence_claims"] / metrics["total_claims"]
            metrics["medium_confidence_rate"] = metrics["medium_confidence_claims"] / metrics["total_claims"]
            metrics["low_confidence_rate"] = metrics["low_confidence_claims"] / metrics["total_claims"]
        else:
            metrics["high_confidence_rate"] = 0.0
            metrics["medium_confidence_rate"] = 0.0
            metrics["low_confidence_rate"] = 0.0
        
        return metrics
    
    def get_metrics_summary(self) -> str:
        """
        Get formatted metrics summary as string
        
        Returns:
            Formatted string with metrics summary
        """
        metrics = self.get_metrics()
        
        summary = f"""Citation Quality Metrics:
- Total Responses: {metrics['total_responses']}
- Total Claims: {metrics['total_claims']} (avg: {metrics['avg_claims_per_response']:.2f} per response)
- Total Citations: {metrics['total_citations']} (avg: {metrics['avg_citations_per_response']:.2f} per response)
- Verified Citations: {metrics['verified_citations']} ({metrics['verification_rate']*100:.1f}%)
- Unverified Citations: {metrics['unverified_citations']} ({metrics['unverified_rate']*100:.1f}%)
- Confidence Distribution:
  - High: {metrics['high_confidence_claims']} ({metrics['high_confidence_rate']*100:.1f}%)
  - Medium: {metrics['medium_confidence_claims']} ({metrics['medium_confidence_rate']*100:.1f}%)
  - Low: {metrics['low_confidence_claims']} ({metrics['low_confidence_rate']*100:.1f}%)
"""
        return summary
    
    def reset_metrics(self) -> None:
        """Reset all metrics to zero"""
        self.metrics = {
            "total_responses": 0,
            "total_claims": 0,
            "total_citations": 0,
            "verified_citations": 0,
            "unverified_citations": 0,
            "high_confidence_claims": 0,
            "medium_confidence_claims": 0,
            "low_confidence_claims": 0,
        }
        logger.info("Citation metrics reset")
    
    def export_metrics(self, format: str = "dict") -> Any:
        """
        Export metrics in specified format
        
        Args:
            format: Export format ("dict", "json", "summary")
        
        Returns:
            Metrics in requested format
        """
        if format == "dict":
            return self.get_metrics()
        elif format == "json":
            import json
            return json.dumps(self.get_metrics(), indent=2, default=str)
        elif format == "summary":
            return self.get_metrics_summary()
        else:
            raise ValueError(f"Unsupported format: {format}")


# Global metrics instance
_global_metrics: Optional[CitationMetrics] = None


def get_citation_metrics() -> CitationMetrics:
    """Get global citation metrics instance"""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = CitationMetrics()
    return _global_metrics

