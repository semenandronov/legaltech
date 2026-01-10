"""Tests for Official Legal Sources Tools"""
import pytest
from app.services.langchain_agents.official_legal_sources_tool import (
    search_legislation_tool,
    search_supreme_court_tool,
    search_case_law_tool,
    smart_legal_search_tool
)


def test_search_legislation_tool_exists():
    """Test that search_legislation_tool exists and is callable"""
    assert search_legislation_tool is not None
    assert hasattr(search_legislation_tool, 'invoke')


def test_search_supreme_court_tool_exists():
    """Test that search_supreme_court_tool exists and is callable"""
    assert search_supreme_court_tool is not None
    assert hasattr(search_supreme_court_tool, 'invoke')


def test_search_case_law_tool_exists():
    """Test that search_case_law_tool exists and is callable"""
    assert search_case_law_tool is not None
    assert hasattr(search_case_law_tool, 'invoke')


def test_smart_legal_search_tool_exists():
    """Test that smart_legal_search_tool exists and is callable"""
    assert smart_legal_search_tool is not None
    assert hasattr(smart_legal_search_tool, 'invoke')


def test_tool_descriptions():
    """Test that tools have proper descriptions"""
    assert "pravo.gov.ru" in search_legislation_tool.description.lower()
    assert "vsrf.ru" in search_supreme_court_tool.description.lower()
    assert "kad.arbitr.ru" in search_case_law_tool.description.lower()



















