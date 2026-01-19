"""Tests for Legal Reasoning Model"""
import pytest
from app.services.legal_reasoning_model import LegalReasoningModel, TaskType, SourceType


def test_identify_task_type_find_norm():
    """Test identifying FIND_NORM task type"""
    model = LegalReasoningModel()
    
    # Test with article mention
    task = model.identify_task_type("статья 393 ГК РФ")
    assert task == TaskType.FIND_NORM
    
    # Test with norm mention
    task = model.identify_task_type("нужна норма права")
    assert task == TaskType.FIND_NORM


def test_identify_task_type_find_court_position():
    """Test identifying FIND_COURT_POSITION task type"""
    model = LegalReasoningModel()
    
    task = model.identify_task_type("разъяснения Верховного Суда")
    assert task == TaskType.FIND_COURT_POSITION


def test_identify_task_type_find_precedent():
    """Test identifying FIND_PRECEDENT task type"""
    model = LegalReasoningModel()
    
    task = model.identify_task_type("аналогичные дела")
    assert task == TaskType.FIND_PRECEDENT


def test_determine_source_type():
    """Test determining source type from task"""
    model = LegalReasoningModel()
    
    source = model.determine_source_type(TaskType.FIND_NORM)
    assert source == SourceType.PRAVO
    
    source = model.determine_source_type(TaskType.FIND_COURT_POSITION)
    assert source == SourceType.VS
    
    source = model.determine_source_type(TaskType.FIND_PRECEDENT)
    assert source == SourceType.KAD


def test_formulate_query():
    """Test query formulation"""
    model = LegalReasoningModel()
    
    query = model.formulate_query(TaskType.FIND_NORM, "статья 401 ГК РФ")
    assert "статья" in query.lower()
    assert "401" in query or "гк" in query.lower()


def test_should_search():
    """Test should_search method"""
    model = LegalReasoningModel()
    
    # Should search
    assert model.should_search("неясно толкование нормы")
    assert model.should_search("нужна норма права")
    
    # Should not search
    assert not model.should_search("все понятно и ясно")







































