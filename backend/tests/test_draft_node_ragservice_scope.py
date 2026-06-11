"""Регрессия: draft_node делегирует в decomposed pipeline, без локального RAGService."""
from __future__ import annotations

import ast
from pathlib import Path


def _draft_node_function_def() -> ast.FunctionDef:
    path = Path(__file__).resolve().parents[1] / "app/services/langchain_agents/graphs/chat_graph.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "draft_node":
            return node
    raise AssertionError("draft_node not found in chat_graph.py")


def test_draft_node_delegates_to_decomposed_pipeline():
    fn = _draft_node_function_def()
    calls_execute = any(
        isinstance(node, ast.Call)
        and isinstance(getattr(node.func, "id", None), str)
        and node.func.id == "execute_draft_pipeline"
        for node in ast.walk(fn)
    )
    imports_pipeline = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.services.draft_pipeline.runner"
        and any(alias.name == "execute_draft_pipeline" for alias in node.names)
        for node in ast.walk(fn)
    )
    assert imports_pipeline or calls_execute, "draft_node should call execute_draft_pipeline"

    inner_rag_imports = [
        child
        for child in ast.walk(fn)
        if isinstance(child, ast.ImportFrom)
        and child.module == "app.services.rag_service"
    ]
    assert inner_rag_imports == [], "draft_node should not import RAGService directly"
