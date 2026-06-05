"""Регрессия: draft_node не должен импортировать RAGService внутри функции."""
from __future__ import annotations

import ast
from pathlib import Path


def _draft_node_function_def() -> ast.FunctionDef:
    chat_graph_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "langchain_agents"
        / "graphs"
        / "chat_graph.py"
    )
    tree = ast.parse(chat_graph_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "draft_node":
            return node
    raise AssertionError("draft_node not found in chat_graph.py")


def test_draft_node_does_not_shadow_module_ragservice_import():
    """
    Локальный `from app.services.rag_service import RAGService` внутри draft_node
    делает имя локальным на всю функцию и ломает RAGService() выше по коду
    (UnboundLocalError при approve плана).
    """
    fn = _draft_node_function_def()
    inner_rag_imports = [
        child
        for child in ast.walk(fn)
        if isinstance(child, ast.ImportFrom)
        and child.module == "app.services.rag_service"
        and any(alias.name == "RAGService" for alias in child.names)
    ]
    assert inner_rag_imports == []

    assigns_rag_svc = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "rag_svc" for t in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "RAGService"
        for node in ast.walk(fn)
    )
    assert assigns_rag_svc, "draft_node should create rag_svc = RAGService() once"
