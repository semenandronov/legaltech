"""Test script for checking all imports"""
import sys
import traceback

def test_imports():
    """Test all imports from langchain_agents"""
    errors = []
    
    print("Testing imports...")
    
    # Test main imports
    try:
        from app.services.langchain_agents import AgentCoordinator, AnalysisState
        print("✓ Main imports successful")
    except Exception as e:
        errors.append(f"Main imports: {e}")
        print(f"✗ Main imports failed: {e}")
    
    # Test state
    try:
        from app.services.langchain_agents.state import AnalysisState
        print("✓ State import successful")
    except Exception as e:
        errors.append(f"State import: {e}")
        print(f"✗ State import failed: {e}")
    
    # Test tools
    try:
        from app.services.langchain_agents.tools import get_all_tools, initialize_tools
        print("✓ Tools import successful")
    except Exception as e:
        errors.append(f"Tools import: {e}")
        print(f"✗ Tools import failed: {e}")
    
    # Test prompts
    try:
        from app.services.langchain_agents.prompts import get_agent_prompt, get_all_prompts
        print("✓ Prompts import successful")
    except Exception as e:
        errors.append(f"Prompts import: {e}")
        print(f"✗ Prompts import failed: {e}")
    
    # Test nodes
    try:
        from app.services.langchain_agents.timeline_node import timeline_agent_node
        print("✓ Timeline node import successful")
    except Exception as e:
        errors.append(f"Timeline node import: {e}")
        print(f"✗ Timeline node import failed: {e}")
    
    try:
        from app.services.langchain_agents.key_facts_node import key_facts_agent_node
        print("✓ Key facts node import successful")
    except Exception as e:
        errors.append(f"Key facts node import: {e}")
        print(f"✗ Key facts node import failed: {e}")
    
    try:
        from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
        print("✓ Discrepancy node import successful")
    except Exception as e:
        errors.append(f"Discrepancy node import: {e}")
        print(f"✗ Discrepancy node import failed: {e}")
    
    try:
        from app.services.langchain_agents.risk_node import risk_agent_node
        print("✓ Risk node import successful")
    except Exception as e:
        errors.append(f"Risk node import: {e}")
        print(f"✗ Risk node import failed: {e}")
    
    try:
        from app.services.langchain_agents.summary_node import summary_agent_node
        print("✓ Summary node import successful")
    except Exception as e:
        errors.append(f"Summary node import: {e}")
        print(f"✗ Summary node import failed: {e}")
    
    # Test supervisor
    try:
        from app.services.langchain_agents.supervisor import route_to_agent, create_supervisor_agent
        print("✓ Supervisor import successful")
    except Exception as e:
        errors.append(f"Supervisor import: {e}")
        print(f"✗ Supervisor import failed: {e}")
    
    # Test graph
    try:
        from app.services.langchain_agents.graph import create_analysis_graph
        print("✓ Graph import successful")
    except Exception as e:
        errors.append(f"Graph import: {e}")
        print(f"✗ Graph import failed: {e}")
    
    # Test coordinator
    try:
        from app.services.langchain_agents.coordinator import AgentCoordinator
        print("✓ Coordinator import successful")
    except Exception as e:
        errors.append(f"Coordinator import: {e}")
        print(f"✗ Coordinator import failed: {e}")
    
    # Summary
    if errors:
        print(f"\n✗ Found {len(errors)} import errors:")
        for error in errors:
            print(f"  - {error}")
        return False
    else:
        print("\n✓ All imports successful!")
        return True

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
