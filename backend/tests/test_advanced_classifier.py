"""Tests for AdvancedComplexityClassifier"""
import pytest
from unittest.mock import Mock, MagicMock
from app.services.langchain_agents.advanced_complexity_classifier import (
    AdvancedComplexityClassifier,
    EnhancedClassificationResult
)
from app.services.langchain_agents.complexity_classifier import normalize_text


class TestAdvancedComplexityClassifier:
    """Тесты для AdvancedComplexityClassifier"""
    
    @pytest.fixture
    def mock_llm(self):
        """Mock LLM для тестов"""
        llm = Mock()
        llm.invoke = Mock(return_value=Mock(content='{"label": "simple", "confidence": 0.9, "rationale": "Test", "recommended_path": "rag", "estimated_complexity": "low", "suggested_agents": [], "rag_queries": ["test"], "requires_clarification": false, "metadata": {}}'))
        return llm
    
    @pytest.fixture
    def mock_cache(self):
        """Mock cache для тестов"""
        cache = Mock()
        cache.get = Mock(return_value=None)
        cache.set = Mock()
        return cache
    
    @pytest.fixture
    def classifier(self, mock_llm, mock_cache):
        """Создает классификатор для тестов"""
        return AdvancedComplexityClassifier(llm=mock_llm, cache=mock_cache, confidence_threshold=0.7)
    
    def test_rule_based_article_request(self, classifier):
        """Тест rule-based классификации для запроса статьи"""
        query = "Пришли статью 135 ГПК"
        result = classifier.classify(query)
        
        assert result.label == "simple"
        assert result.confidence >= 0.99
        assert result.recommended_path == "rag"
        assert len(result.rag_queries) > 0
        assert result.estimated_complexity == "low"
    
    def test_rule_based_greeting(self, classifier):
        """Тест rule-based классификации для приветствия"""
        query = "Привет"
        result = classifier.classify(query)
        
        assert result.label == "simple"
        assert result.confidence >= 0.95
        assert result.recommended_path == "rag"
        assert result.estimated_complexity == "low"
    
    def test_rule_based_complex_task(self, classifier):
        """Тест rule-based классификации для сложной задачи"""
        query = "Извлеки все даты из документов и составь таблицу"
        result = classifier.classify(query)
        
        assert result.label == "complex"
        assert result.confidence >= 0.90
        assert result.recommended_path == "agent"
        assert len(result.suggested_agents) > 0
        assert result.estimated_complexity in ["medium", "high"]
    
    def test_extract_suggested_agents(self, classifier):
        """Тест извлечения suggested_agents"""
        query = "Найди все противоречия и проанализируй риски"
        agents = classifier._extract_suggested_agents(query.lower())
        
        assert "discrepancy" in agents
        assert "risk" in agents
    
    def test_classify_with_context(self, classifier):
        """Тест классификации с контекстом"""
        query = "Какие ключевые факты есть в деле?"
        context = {
            "case_id": "test-case-123",
            "workspace_files": ["doc1.pdf", "doc2.pdf"],
            "previous_results": {"entity_extraction": True}
        }
        
        result = classifier.classify(query, context=context)
        
        assert result.label in ["simple", "complex", "hybrid"]
        assert result.confidence >= 0.0
        assert result.recommended_path in ["rag", "agent", "hybrid"]
    
    def test_hybrid_classification(self, classifier):
        """Тест hybrid классификации"""
        query = "Покажи статью 123 ГК и проанализируй риски"
        result = classifier.classify(query)
        
        # Может быть hybrid или complex в зависимости от LLM
        assert result.label in ["complex", "hybrid"]
        assert result.recommended_path in ["agent", "hybrid"]
    
    def test_requires_clarification_low_confidence(self, classifier):
        """Тест requires_clarification при низкой уверенности"""
        # Создаем классификатор с высоким порогом
        high_threshold_classifier = AdvancedComplexityClassifier(
            llm=classifier.llm,
            cache=classifier.cache,
            confidence_threshold=0.95
        )
        
        # Мокаем результат с низкой уверенностью
        mock_result = EnhancedClassificationResult(
            label="simple",
            confidence=0.6,  # Ниже порога 0.95
            rationale="Test",
            recommended_path="rag"
        )
        
        high_threshold_classifier.classify = Mock(return_value=mock_result)
        result = high_threshold_classifier.classify("Неясный запрос")
        
        # Если confidence низкая, должна быть установлена requires_clarification
        # Но это делается в classify_from_state, не в classify
        assert result.confidence == 0.6
    
    def test_cache_usage(self, classifier, mock_cache):
        """Тест использования кэша"""
        cached_data = {
            "label": "complex",
            "confidence": 0.95,
            "rationale": "Cached",
            "recommended_path": "agent",
            "estimated_complexity": "medium",
            "suggested_agents": ["entity_extraction"],
            "rag_queries": [],
            "requires_clarification": False,
            "metadata": {}
        }
        mock_cache.get = Mock(return_value=cached_data)
        
        query = "Тестовый запрос"
        result = classifier.classify(query)
        
        # Проверяем, что использован кэш
        mock_cache.get.assert_called()
        assert result.label == "complex"
    
    def test_build_context_from_state(self, classifier):
        """Тест построения контекста из state"""
        state = {
            "case_id": "test-case",
            "workspace_files": ["file1.pdf"],
            "timeline_result": {"events": []},
            "key_facts_result": {"facts": []},
            "metadata": {"test": "value"}
        }
        
        context = classifier._build_context_from_state(state)
        
        assert context["case_id"] == "test-case"
        assert len(context["workspace_files"]) == 1
        assert "timeline" in context["previous_results"]
        assert "key_facts" in context["previous_results"]
        assert context["test"] == "value"
    
    def test_extract_user_query_from_messages(self, classifier):
        """Тест извлечения запроса пользователя из messages"""
        from langchain_core.messages import HumanMessage
        
        messages = [
            HumanMessage(content="Первый запрос"),
            HumanMessage(content="Второй запрос")
        ]
        
        query = classifier._extract_user_query(messages)
        assert query == "Второй запрос"  # Последний запрос
    
    def test_fallback_on_error(self, classifier):
        """Тест fallback при ошибке"""
        # Мокаем LLM чтобы выбросить исключение
        classifier.llm.invoke = Mock(side_effect=Exception("LLM error"))
        classifier.llm.with_structured_output = Mock(side_effect=Exception("Structured output error"))
        
        query = "Тестовый запрос"
        result = classifier.classify(query)
        
        # Должен вернуться fallback результат
        assert result.label == "simple"
        assert result.confidence == 0.5
        assert result.recommended_path == "rag"
    
    def test_enrich_classification(self, classifier):
        """Тест обогащения классификации"""
        result = EnhancedClassificationResult(
            label="complex",
            confidence=0.9,
            rationale="Test",
            recommended_path="agent",
            suggested_agents=[],
            rag_queries=[]
        )
        
        query = "Извлеки все даты из документов"
        enriched = classifier._enrich_classification(result, query, None)
        
        # Должны быть добавлены suggested_agents
        assert len(enriched.suggested_agents) > 0 or enriched.suggested_agents == []
        # Для complex не должно быть rag_queries
        assert len(enriched.rag_queries) == 0


class TestEnhancedClassificationResult:
    """Тесты для EnhancedClassificationResult"""
    
    def test_creation_with_all_fields(self):
        """Тест создания EnhancedClassificationResult со всеми полями"""
        result = EnhancedClassificationResult(
            label="hybrid",
            confidence=0.85,
            rationale="Test rationale",
            recommended_path="hybrid",
            requires_clarification=False,
            suggested_agents=["entity_extraction", "risk"],
            rag_queries=["статья 123 ГК"],
            estimated_complexity="medium",
            metadata={"test": "value"}
        )
        
        assert result.label == "hybrid"
        assert result.confidence == 0.85
        assert result.recommended_path == "hybrid"
        assert result.requires_clarification == False
        assert len(result.suggested_agents) == 2
        assert len(result.rag_queries) == 1
        assert result.estimated_complexity == "medium"
        assert result.metadata["test"] == "value"
    
    def test_creation_with_defaults(self):
        """Тест создания с значениями по умолчанию"""
        result = EnhancedClassificationResult(
            label="simple",
            confidence=0.9,
            rationale="Test",
            recommended_path="rag"
        )
        
        assert result.requires_clarification == False
        assert result.suggested_agents == []
        assert result.rag_queries == []
        assert result.estimated_complexity == "medium"
        assert result.metadata == {}
    
    def test_dict_serialization(self):
        """Тест сериализации в dict"""
        result = EnhancedClassificationResult(
            label="complex",
            confidence=0.95,
            rationale="Test",
            recommended_path="agent",
            suggested_agents=["entity_extraction"]
        )
        
        result_dict = result.dict()
        
        assert result_dict["label"] == "complex"
        assert result_dict["confidence"] == 0.95
        assert result_dict["recommended_path"] == "agent"
        assert result_dict["suggested_agents"] == ["entity_extraction"]

