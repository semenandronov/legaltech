"""Tests for Agent Self-Awareness Service"""
import pytest
from app.services.agent_self_awareness import SelfAwarenessService, GapType


def test_identify_knowledge_gaps_missing_norm():
    """Test identifying MISSING_NORM gap"""
    service = SelfAwarenessService()
    
    case_documents = "Документы дела без упоминания статей"
    agent_output = "Для анализа нужна норма права о форс-мажоре"
    
    gaps = service.identify_knowledge_gaps(
        case_documents=case_documents,
        agent_output=agent_output,
        task_type="risk_analysis"
    )
    
    assert GapType.MISSING_NORM in gaps


def test_identify_knowledge_gaps_missing_precedent():
    """Test identifying MISSING_PRECEDENT gap"""
    service = SelfAwarenessService()
    
    case_documents = "Документы дела"
    agent_output = "Нужны аналогичные дела для сравнения"
    
    gaps = service.identify_knowledge_gaps(
        case_documents=case_documents,
        agent_output=agent_output,
        task_type="risk_analysis"
    )
    
    assert GapType.MISSING_PRECEDENT in gaps


def test_identify_knowledge_gaps_missing_court_position():
    """Test identifying MISSING_COURT_POSITION gap"""
    service = SelfAwarenessService()
    
    case_documents = "Документы дела"
    agent_output = "Нужна позиция Верховного Суда по этому вопросу"
    
    gaps = service.identify_knowledge_gaps(
        case_documents=case_documents,
        agent_output=agent_output,
        task_type="risk_analysis"
    )
    
    assert GapType.MISSING_COURT_POSITION in gaps


def test_should_search():
    """Test should_search method"""
    service = SelfAwarenessService()
    
    # Should search
    gaps = [GapType.MISSING_NORM]
    assert service.should_search(gaps)
    
    # Should not search
    gaps = []
    assert not service.should_search(gaps)


def test_generate_search_strategy():
    """Test generating search strategy"""
    service = SelfAwarenessService()
    
    gaps = [GapType.MISSING_NORM, GapType.MISSING_PRECEDENT]
    strategy = service.generate_search_strategy(gaps)
    
    assert len(strategy) == 2
    assert strategy[0]["tool"] == "search_legislation_tool"
    assert strategy[1]["tool"] == "search_case_law_tool"
















