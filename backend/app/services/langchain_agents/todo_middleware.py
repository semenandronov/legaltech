"""TodoList Middleware for planning (inspired by Deep Agents)"""
from typing import List, Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)


class TodoListMiddleware:
    """
    Middleware для планирования задач (вдохновлено Deep Agents)
    
    Позволяет агентам создавать и отслеживать списки задач (todos)
    для структурированного выполнения сложных задач.
    """
    
    def __init__(self, state: Optional[Dict[str, Any]] = None):
        """
        Initialize todo list middleware
        
        Args:
            state: Optional state dictionary to store todos
        """
        self.state = state or {}
        self.todos: List[Dict[str, Any]] = []
        
        # Load todos from state if available
        if "todos" in self.state:
            self.todos = self.state.get("todos", [])
    
    def write_todos(self, todos: List[Dict[str, Any]]) -> bool:
        """
        Записать план задач
        
        Args:
            todos: List of todo dictionaries with fields:
                - id: Unique identifier
                - description: Task description
                - status: "pending", "in_progress", "completed", "failed"
                - dependencies: List of todo IDs this depends on
                - priority: Optional priority level
                
        Returns:
            True if saved successfully
        """
        try:
            # Validate todos structure
            validated_todos = []
            for todo in todos:
                if not isinstance(todo, dict):
                    continue
                
                # Ensure required fields
                if "id" not in todo:
                    todo["id"] = f"todo_{len(validated_todos) + 1}"
                if "status" not in todo:
                    todo["status"] = "pending"
                if "dependencies" not in todo:
                    todo["dependencies"] = []
                
                validated_todos.append(todo)
            
            self.todos = validated_todos
            
            # Save to state if available
            if self.state is not None:
                self.state["todos"] = self.todos
            
            logger.info(f"TodoList: Written {len(self.todos)} todos")
            return True
            
        except Exception as e:
            logger.error(f"Error writing todos: {e}")
            return False
    
    def read_todos(self) -> List[Dict[str, Any]]:
        """
        Прочитать текущий план задач
        
        Returns:
            List of todo dictionaries
        """
        return self.todos.copy()
    
    def get_todo(self, todo_id: str) -> Optional[Dict[str, Any]]:
        """
        Получить конкретную задачу по ID
        
        Args:
            todo_id: Todo identifier
            
        Returns:
            Todo dictionary or None
        """
        for todo in self.todos:
            if todo.get("id") == todo_id:
                return todo
        return None
    
    def mark_complete(self, todo_id: str) -> bool:
        """
        Отметить задачу как выполненную
        
        Args:
            todo_id: Todo identifier
            
        Returns:
            True if marked successfully
        """
        for todo in self.todos:
            if todo.get("id") == todo_id:
                todo["status"] = "completed"
                logger.debug(f"TodoList: Marked {todo_id} as completed")
                return True
        logger.warning(f"TodoList: Todo {todo_id} not found")
        return False
    
    def mark_in_progress(self, todo_id: str) -> bool:
        """
        Отметить задачу как выполняемую
        
        Args:
            todo_id: Todo identifier
            
        Returns:
            True if marked successfully
        """
        for todo in self.todos:
            if todo.get("id") == todo_id:
                todo["status"] = "in_progress"
                logger.debug(f"TodoList: Marked {todo_id} as in_progress")
                return True
        return False
    
    def mark_failed(self, todo_id: str, error: Optional[str] = None) -> bool:
        """
        Отметить задачу как проваленную
        
        Args:
            todo_id: Todo identifier
            error: Optional error message
            
        Returns:
            True if marked successfully
        """
        for todo in self.todos:
            if todo.get("id") == todo_id:
                todo["status"] = "failed"
                if error:
                    todo["error"] = error
                logger.debug(f"TodoList: Marked {todo_id} as failed")
                return True
        return False
    
    def get_pending_todos(self) -> List[Dict[str, Any]]:
        """
        Получить список незавершенных задач
        
        Returns:
            List of pending todos
        """
        return [todo for todo in self.todos if todo.get("status") == "pending"]
    
    def get_completed_todos(self) -> List[Dict[str, Any]]:
        """
        Получить список завершенных задач
        
        Returns:
            List of completed todos
        """
        return [todo for todo in self.todos if todo.get("status") == "completed"]
    
    def get_ready_todos(self) -> List[Dict[str, Any]]:
        """
        Получить список задач, готовых к выполнению (зависимости выполнены)
        
        Returns:
            List of ready todos
        """
        completed_ids = {todo.get("id") for todo in self.get_completed_todos()}
        ready = []
        
        for todo in self.get_pending_todos():
            dependencies = todo.get("dependencies", [])
            if all(dep_id in completed_ids for dep_id in dependencies):
                ready.append(todo)
        
        return ready
    
    def get_progress(self) -> Dict[str, Any]:
        """
        Получить статистику прогресса
        
        Returns:
            Dictionary with progress statistics
        """
        total = len(self.todos)
        completed = len(self.get_completed_todos())
        pending = len(self.get_pending_todos())
        in_progress = len([t for t in self.todos if t.get("status") == "in_progress"])
        failed = len([t for t in self.todos if t.get("status") == "failed"])
        
        return {
            "total": total,
            "completed": completed,
            "pending": pending,
            "in_progress": in_progress,
            "failed": failed,
            "progress_percent": (completed / total * 100) if total > 0 else 0.0
        }
    
    def clear(self):
        """Очистить все todos"""
        self.todos = []
        if self.state is not None:
            self.state["todos"] = []

