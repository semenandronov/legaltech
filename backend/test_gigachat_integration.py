"""Test script for GigaChat integration with function calling"""
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# Используем официальную библиотеку langchain-gigachat от AI Forever
from langchain_gigachat.chat_models import GigaChat
from app.services.langchain_agents.tools import retrieve_documents_tool
from app.services.gigachat_token_helper import test_gigachat_credentials, get_gigachat_access_token
from langchain_core.messages import HumanMessage, SystemMessage
from app.config import config

def test_gigachat_basic():
    """Test basic GigaChat functionality"""
    print("=" * 60)
    print("Test 1: Basic GigaChat call")
    print("=" * 60)
    
    try:
        llm = GigaChat(
            credentials=config.GIGACHAT_CREDENTIALS,
            temperature=0.1,
            verify_ssl_certs=config.GIGACHAT_VERIFY_SSL
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
        llm = GigaChat(
            credentials=config.GIGACHAT_CREDENTIALS,
            temperature=0.1,
            verify_ssl_certs=config.GIGACHAT_VERIFY_SSL
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
        print(f"   Using: langchain-gigachat (official from AI Forever)")
        
        # Test basic call
        messages = [HumanMessage(content="Скажи 'Привет'")]
        response = llm.invoke(messages)
        print(f"✅ Response: {response.content[:100]}...")
        
        # Test bind_tools (langchain-gigachat должен поддерживать)
        if hasattr(llm, 'bind_tools'):
            tools = [retrieve_documents_tool]
            llm_with_tools = llm.bind_tools(tools)
            print(f"✅ bind_tools() работает! Bound {len(tools)} tools")
        else:
            print("⚠️ bind_tools() не поддерживается (может быть в другой версии)")
        
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_token_helper():
    """Test GigaChat token helper"""
    print("\n" + "=" * 60)
    print("Test 0: GigaChat Token Helper")
    print("=" * 60)
    
    try:
        # Test credentials validation
        print("Testing credentials validation...")
        is_valid = test_gigachat_credentials()
        
        if is_valid:
            print("✅ Credentials are valid!")
            
            # Try to get access token
            print("\nTesting access token retrieval...")
            token = get_gigachat_access_token()
            if token:
                print(f"✅ Access token obtained: {token[:20]}...")
                print("   (Token is valid for 30 minutes)")
            else:
                print("⚠️ Could not get access token (but credentials are valid)")
        else:
            print("❌ Credentials are invalid or token retrieval failed")
            print("   Check your GIGACHAT_CREDENTIALS in .env file")
            print("   Make sure you're using Authorization Key, not Access Token")
        
        return is_valid
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
        print("Set it in .env file: GIGACHAT_CREDENTIALS=your_authorization_key")
        print("\nTo get authorization key:")
        print("1. Go to https://developers.sber.ru/studio")
        print("2. Create a GigaChat API project")
        print("3. Go to 'Настройки API' → 'Получить ключ'")
        print("4. Copy the Authorization Key (not Access Token!)")
        sys.exit(1)
    
    print(f"✅ GIGACHAT_CREDENTIALS found: {config.GIGACHAT_CREDENTIALS[:20]}...")
    print(f"✅ LLM_PROVIDER: {config.LLM_PROVIDER}\n")
    print("ℹ️  Note: GIGACHAT_CREDENTIALS should be Authorization Key (not Access Token)")
    print("   SDK will automatically get and refresh Access Token as needed.\n")
    
    # Run tests
    results = []
    results.append(("Token helper", test_token_helper()))
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

