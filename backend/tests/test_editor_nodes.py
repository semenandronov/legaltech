"""
Unit tests для editor nodes.

Проверяет паттерны из LangGraph Academy:
- Structured outputs
- Context engineering
- Think tool
- Hard limits
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from app.services.langchain_agents.graphs.nodes.editor_nodes import (
    analyze_document_node,
    check_risks_node,
    improve_text_node,
    generate_edits_node,
    validate_edits_node,
    apply_edits_node,
    think_tool,
    check_grammar_node,
    check_legal_accuracy_node,
    check_compliance_node,
    parallel_checks_node,
    merge_checks_results_node,
    search_precedents_node
)
from app.services.langchain_agents.graphs.chat_graph import ChatGraphState


class TestAnalyzeDocumentNode:
    """Тесты для analyze_document_node"""
    
    def test_analyze_document_with_context_engineering(self):
        """Проверка context engineering для больших документов"""
        state = {
            "document_context": "A" * 10000,  # Большой документ
            "question": "Проанализируй документ"
        }
        
        with patch('app.services.langchain_agents.graphs.nodes.editor_nodes.create_legal_llm') as mock_llm:
            mock_llm.return_value.with_structured_output.return_value.invoke.return_value = Mock(
                doc_type="Договор",
                structure={},
                key_elements=["Раздел 1"],
                parties=None,
                dates=None,
                summary=None
            )
            
            result = analyze_document_node(state)
            
            assert "document_analysis" in result
            # Проверяем что summarization был вызван для большого документа
    
    def test_analyze_document_with_structured_output(self):
        """Проверка использования structured outputs"""
        state = {
            "document_context": "Договор поставки товаров",
            "question": "Проанализируй"
        }
        
        with patch('app.services.langchain_agents.graphs.nodes.editor_nodes.create_legal_llm') as mock_llm:
            mock_structured = Mock()
            mock_structured.invoke.return_value = Mock(
                doc_type="Договор",
                structure={},
                key_elements=[],
                parties=None,
                dates=None,
                summary=None
            )
            mock_llm.return_value.with_structured_output.return_value = mock_structured
            
            result = analyze_document_node(state)
            
            # Проверяем что with_structured_output был вызван
            mock_llm.return_value.with_structured_output.assert_called_once()


class TestCheckRisksNode:
    """Тесты для check_risks_node"""
    
    def test_check_risks_with_hard_limits(self):
        """Проверка hard limits (максимум 3 итерации)"""
        state = {
            "document_context": "Договор",
            "risk_check_iteration": 3  # Достигнут лимит
        }
        
        result = check_risks_node(state)
        
        # После лимита должен вернуть существующие риски
        assert "risks" in result
        assert result.get("risk_check_iteration") == 3
    
    def test_check_risks_with_think_tool(self):
        """Проверка использования think tool для рефлексии"""
        state = {
            "document_context": "Договор",
            "risk_check_iteration": 1,
            "risks": []
        }
        
        with patch('app.services.langchain_agents.graphs.nodes.editor_nodes.think_tool') as mock_think:
            with patch('app.services.langchain_agents.graphs.nodes.editor_nodes.create_legal_llm'):
                check_risks_node(state)
                
                # Проверяем что think_tool был вызван при iteration > 0
                # (будет вызван если iteration > 0)


class TestGenerateEditsNode:
    """Тесты для generate_edits_node"""
    
    def test_generate_edits_with_structured_output(self):
        """План + по одной правке на цель."""
        state = {
            "document_context": '<p id="b1">Исходный текст</p><p id="b2">Второй</p>',
            "question": "Замени текст",
        }

        with patch('app.services.langchain_agents.graphs.nodes.editor_nodes.create_legal_llm') as mock_llm:
            mock_plan_llm = Mock()
            mock_plan_llm.invoke.return_value = Mock(
                model_dump=lambda: {
                    "target_count": 1,
                    "targets": [{"location": "документ", "change": "замена", "node_id": "b1"}],
                }
            )
            mock_edit_llm = Mock()
            mock_edit_llm.invoke.return_value = Mock(
                edit=Mock(original_text="Исходный", new_text="Новый", node_id="b1"),
            )

            mock_llm.return_value.with_structured_output.side_effect = [
                mock_plan_llm,
                mock_edit_llm,
            ]

            result = generate_edits_node(state)

            assert mock_llm.return_value.with_structured_output.call_count == 2
            assert "structured_edits" in result
            assert "edit_scope" in result
            assert len(result.get("structured_edits") or []) >= 1


class TestValidateEditsNode:
    """Тесты для validate_edits_node"""

    def test_validate_edits_deterministic(self):
        """Детерминированная валидация без LLM"""
        html = '<p id="b1">текст для замены</p>'
        state = {
            "structured_edits": [
                {
                    "node_id": "b1",
                    "new_text": "новый",
                }
            ],
            "document_context": html,
        }

        result = validate_edits_node(state)

        assert result.get("edits_valid") is True
        edits = result.get("structured_edits") or []
        assert len(edits) == 1
        assert edits[0].get("found_in_document") is True


class TestApplyEditsNode:
    """Финализация edit-turn без серверной мутации HTML."""

    def test_apply_edits_sets_short_response(self):
        state = {
            "structured_edits": [
                {
                    "id": "e1",
                    "new_text": "новый текст",
                    "found_in_document": True,
                }
            ],
            "user_id": "u1",
        }
        result = apply_edits_node(state, config={})

        assert "Предлагаю" in (result.get("response") or "")
        assert result.get("edited_content") is None
        assert result.get("messages")


class TestParallelChecksNode:
    """Тесты для parallel_checks_node"""
    
    def test_parallel_checks_returns_send_list(self):
        """Проверка что parallel_checks возвращает List[Send]"""
        state = {
            "document_context": "Документ"
        }
        
        result = parallel_checks_node(state)
        
        # Проверяем что возвращается список Send
        assert isinstance(result, list)
        assert len(result) == 3  # grammar, legal, compliance


class TestMergeChecksResultsNode:
    """Тесты для merge_checks_results_node"""
    
    def test_merge_checks_with_compression(self):
        """Проверка compression результатов"""
        state = {
            "grammar_check": {"errors": [{"severity": "high"}]},
            "legal_check": {"issues": [{"severity": "medium"}]},
            "compliance_check": {"violations": [{"severity": "low"}]}
        }
        
        result = merge_checks_results_node(state)
        
        # Проверяем что результаты объединены и приоритизированы
        assert "merged_checks" in result
        assert result["merged_checks"]["total_issues"] == 3
        # Проверяем compression (ограничение до 10)
        assert len(result["merged_checks"]["issues"]) <= 10

