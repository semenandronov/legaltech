"""Validation script for refactored agent system"""
import sys
import os
from typing import Dict, Any, List

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.langchain_agents.component_factory import ComponentFactory
from app.services.langchain_agents.unified_error_handler import UnifiedErrorHandler, ErrorType
from app.services.langchain_agents.fallback_handler import FallbackHandler
from app.services.langchain_agents.result_cache import get_result_cache
from app.services.langchain_agents.logging_config import get_agent_logger
from app.config import config


def validate_component_factory() -> Dict[str, Any]:
    """Validate ComponentFactory"""
    results = {
        "component": "ComponentFactory",
        "status": "ok",
        "issues": []
    }
    
    try:
        # Test required component creation
        def test_factory():
            return {"test": "ok"}
        
        component = ComponentFactory.create_required_component(
            "TestComponent",
            test_factory,
            "Test error"
        )
        
        if component.get("test") != "ok":
            results["issues"].append("Required component creation failed")
            results["status"] = "error"
        
        # Test optional component creation
        optional = ComponentFactory.create_optional_component(
            "OptionalComponent",
            test_factory
        )
        
        if optional.get("test") != "ok":
            results["issues"].append("Optional component creation failed")
            results["status"] = "error"
        
        # Test optional component failure (should return None)
        def failing_factory():
            raise ValueError("Expected failure")
        
        failed = ComponentFactory.create_optional_component(
            "FailingComponent",
            failing_factory
        )
        
        if failed is not None:
            results["issues"].append("Optional component should return None on failure")
            results["status"] = "error"
        
    except Exception as e:
        results["status"] = "error"
        results["issues"].append(f"Exception: {str(e)}")
    
    return results


def validate_error_handler() -> Dict[str, Any]:
    """Validate UnifiedErrorHandler"""
    results = {
        "component": "UnifiedErrorHandler",
        "status": "ok",
        "issues": []
    }
    
    try:
        handler = UnifiedErrorHandler(max_retries=3)
        
        # Test error classification
        timeout_error = TimeoutError("Operation timed out")
        error_type = handler.classify_error(timeout_error)
        
        if error_type != ErrorType.TIMEOUT:
            results["issues"].append(f"Timeout error misclassified as {error_type}")
            results["status"] = "error"
        
        # Test strategy selection
        strategy = handler.select_strategy(ErrorType.TIMEOUT, "timeline")
        from app.services.langchain_agents.unified_error_handler import ErrorStrategy
        if strategy != ErrorStrategy.RETRY:
            results["issues"].append(f"Timeout should use RETRY strategy, got {strategy}")
            results["status"] = "error"
        
        # Test error handling
        context = {"case_id": "test", "agent_name": "timeline"}
        error_result = handler.handle_agent_error("timeline", timeout_error, context, retry_count=0)
        
        if not error_result.should_retry:
            results["issues"].append("Timeout error should be retryable")
            results["status"] = "error"
        
        # Test exponential backoff
        delay1 = handler.get_retry_delay(0)
        delay2 = handler.get_retry_delay(1)
        
        if delay2 <= delay1:
            results["issues"].append("Exponential backoff not working")
            results["status"] = "error"
        
    except Exception as e:
        results["status"] = "error"
        results["issues"].append(f"Exception: {str(e)}")
    
    return results


def validate_fallback_handler() -> Dict[str, Any]:
    """Validate FallbackHandler"""
    results = {
        "component": "FallbackHandler",
        "status": "ok",
        "issues": []
    }
    
    try:
        handler = FallbackHandler(max_retries=3)
        
        # Check that unified_error_handler is initialized
        if handler.unified_error_handler is None:
            results["issues"].append("UnifiedErrorHandler not initialized")
            results["status"] = "error"
        
        # Test error handling
        error = TimeoutError("Timeout")
        from app.services.langchain_agents.state import create_initial_state
        state = create_initial_state("test_case", ["timeline"])
        
        result = handler.handle_failure("timeline", error, state, retry_count=0)
        
        if not hasattr(result, 'strategy'):
            results["issues"].append("FallbackResult missing strategy")
            results["status"] = "error"
        
    except Exception as e:
        results["status"] = "error"
        results["issues"].append(f"Exception: {str(e)}")
    
    return results


def validate_config() -> Dict[str, Any]:
    """Validate configuration"""
    results = {
        "component": "Configuration",
        "status": "ok",
        "issues": []
    }
    
    try:
        # Check agent settings
        if not isinstance(config.AGENT_ENABLED, bool):
            results["issues"].append("AGENT_ENABLED should be bool")
            results["status"] = "error"
        
        if config.AGENT_MAX_PARALLEL < 1:
            results["issues"].append("AGENT_MAX_PARALLEL should be >= 1")
            results["status"] = "error"
        
        if config.AGENT_TIMEOUT < 1:
            results["issues"].append("AGENT_TIMEOUT should be >= 1")
            results["status"] = "error"
        
        # Check that timeout is reasonable (not too high)
        if config.AGENT_TIMEOUT > 600:
            results["issues"].append(f"AGENT_TIMEOUT ({config.AGENT_TIMEOUT}s) is too high")
            results["status"] = "warning"
        
    except Exception as e:
        results["status"] = "error"
        results["issues"].append(f"Exception: {str(e)}")
    
    return results


def validate_result_cache() -> Dict[str, Any]:
    """Validate ResultCache"""
    results = {
        "component": "ResultCache",
        "status": "ok",
        "issues": []
    }
    
    try:
        cache = get_result_cache()
        
        # Test cache operations
        test_result = {"events": [{"date": "2024-01-01"}]}
        cache.set("test_case", "timeline", test_result)
        
        cached = cache.get("test_case", "timeline")
        
        if cached != test_result:
            results["issues"].append("Cache get/set not working")
            results["status"] = "error"
        
        # Test invalidation
        cache.invalidate("test_case", "timeline")
        invalidated = cache.get("test_case", "timeline")
        
        if invalidated is not None:
            results["issues"].append("Cache invalidation not working")
            results["status"] = "error"
        
        # Test stats
        stats = cache.get_stats()
        if "total_entries" not in stats:
            results["issues"].append("Cache stats missing total_entries")
            results["status"] = "error"
        
    except Exception as e:
        results["status"] = "error"
        results["issues"].append(f"Exception: {str(e)}")
    
    return results


def main():
    """Run all validations"""
    print("=" * 60)
    print("Agent System Validation")
    print("=" * 60)
    print()
    
    validations = [
        validate_component_factory,
        validate_error_handler,
        validate_fallback_handler,
        validate_config,
        validate_result_cache
    ]
    
    results: List[Dict[str, Any]] = []
    
    for validation_func in validations:
        print(f"Validating {validation_func.__name__}...")
        result = validation_func()
        results.append(result)
        
        status_icon = "✅" if result["status"] == "ok" else "❌" if result["status"] == "error" else "⚠️"
        print(f"{status_icon} {result['component']}: {result['status']}")
        
        if result["issues"]:
            for issue in result["issues"]:
                print(f"   - {issue}")
        print()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    ok_count = sum(1 for r in results if r["status"] == "ok")
    error_count = sum(1 for r in results if r["status"] == "error")
    warning_count = sum(1 for r in results if r["status"] == "warning")
    
    print(f"✅ OK: {ok_count}")
    print(f"❌ Errors: {error_count}")
    print(f"⚠️  Warnings: {warning_count}")
    print()
    
    if error_count > 0:
        print("❌ Validation failed - please fix errors")
        return 1
    elif warning_count > 0:
        print("⚠️  Validation passed with warnings")
        return 0
    else:
        print("✅ All validations passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())












































