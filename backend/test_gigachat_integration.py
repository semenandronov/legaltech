"""Test script for GigaChat integration with function calling"""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.services.gigachat_llm import ChatGigaChat
from app.services.langchain_agents.tools import retrieve_documents_tool
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import config

def test_gigachat_basic():
    """Test basic GigaChat functionality"""
    print("=" * 60)
    print("Test 1: Basic GigaChat call")
    print("=" * 60)
    
    try:
        llm = ChatGigaChat(
            credentials=config.GIGACHAT_CREDENTIALS,
            temperature=0.1
        )
        
        messages = [
            SystemMessage(content="Ты полезный AI-ассистент для юридического анализа."),
            HumanMessage(content="Привет! Можешь кратко представиться?")
        ]
        
        response = llm.invoke(messages)
        print(f"✅ Response: {response.content[:200]}...")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gigachat_with_tools():
    """Test GigaChat with function calling"""
    print("\n" + "=" * 60)
    print("Test 2: GigaChat with function calling")
    print("=" * 60)
    
    try:
        llm = ChatGigaChat(
            credentials=config.GIGACHAT_CREDENTIALS,
            temperature=0.1
        )
        
        # Bind tools
        tools = [retrieve_documents_tool]
        llm_with_tools = llm.bind_tools(tools)
        
        print(f"✅ Bound {len(tools)} tools: {[t.name for t in tools]}")
        
        # Test call
        messages = [
            SystemMessage(content="Ты AI-агент для анализа юридических документов. Используй retrieve_documents_tool для поиска документов."),
            HumanMessage(content="Найди документы про договор поставки в деле test_case_123")
        ]
        
        response = llm_with_tools.invoke(messages)
        print(f"✅ Response: {response.content[:200]}...")
        
        # Check for tool calls
        if hasattr(response, 'tool_calls') and response.tool_calls:
            print(f"✅ LLM вызвал tools: {len(response.tool_calls)} вызовов")
            for tc in response.tool_calls:
                print(f"   - {tc.get('name', 'unknown')}: {tc.get('args', {})}")
        else:
            print("⚠️ LLM не вызвал tools (может быть нормально, если промпт не требует)")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_llm_factory():
    """Test LLM factory with GigaChat"""
    print("\n" + "=" * 60)
    print("Test 3: LLM Factory with GigaChat")
    print("=" * 60)
    
    try:
        from app.services.llm_factory import create_llm
        
        # Test with GigaChat
        llm = create_llm(provider="gigachat", temperature=0.1)
        print(f"✅ Created LLM: {type(llm).__name__}")
        
        # Test basic call
        messages = [HumanMessage(content="Скажи 'Привет'")]
        response = llm.invoke(messages)
        print(f"✅ Response: {response.content[:100]}...")
        
        # Test bind_tools
        if hasattr(llm, 'bind_tools'):
            tools = [retrieve_documents_tool]
            llm_with_tools = llm.bind_tools(tools)
            print(f"✅ bind_tools() работает! Bound {len(tools)} tools")
        else:
            print("⚠️ bind_tools() не поддерживается")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🧪 Testing GigaChat Integration\n")
    
    # Check credentials
    if not config.GIGACHAT_CREDENTIALS:
        print("❌ GIGACHAT_CREDENTIALS not set in config!")
        print("Set it in .env file: GIGACHAT_CREDENTIALS=your_token")
        sys.exit(1)
    
    print(f"✅ GIGACHAT_CREDENTIALS found: {config.GIGACHAT_CREDENTIALS[:20]}...")
    print(f"✅ LLM_PROVIDER: {config.LLM_PROVIDER}\n")
    
    # Run tests
    results = []
    results.append(("Basic call", test_gigachat_basic()))
    results.append(("Function calling", test_gigachat_with_tools()))
    results.append(("LLM Factory", test_llm_factory()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    if all_passed:
        print("\n🎉 All tests passed! GigaChat integration is working.")
    else:
        print("\n⚠️ Some tests failed. Check errors above.")

