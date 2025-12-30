"""Helper utilities for intermediate checkpoints in LangGraph nodes"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
import logging
import time

logger = logging.getLogger(__name__)


class IntermediateCheckpoint:
    """Утилиты для промежуточных checkpoint'ов в длительных операциях"""
    
    @staticmethod
    def should_checkpoint(
        state: AnalysisState,
        node_name: str,
        checkpoint_interval: int = 60,
        force: bool = False
    ) -> bool:
        """
        Определить, нужно ли создать промежуточный checkpoint
        
        Args:
            state: Текущее состояние графа
            node_name: Имя узла, который выполняется
            checkpoint_interval: Интервал между checkpoint'ами в секундах
            force: Принудительно создать checkpoint
        
        Returns:
            True если нужно создать checkpoint
        """
        if force:
            return True
        
        # Проверяем метаданные для отслеживания времени последнего checkpoint'а
        metadata = state.get("metadata", {})
        checkpoint_times = metadata.get("checkpoint_times", {})
        
        last_checkpoint = checkpoint_times.get(node_name, 0)
        current_time = time.time()
        
        # Создаем checkpoint если прошло достаточно времени
        if current_time - last_checkpoint >= checkpoint_interval:
            return True
        
        return False
    
    @staticmethod
    def mark_checkpoint(
        state: AnalysisState,
        node_name: str,
        checkpoint_data: Optional[Dict[str, Any]] = None
    ) -> AnalysisState:
        """
        Отметить создание checkpoint'а в метаданных
        
        Args:
            state: Текущее состояние графа
            node_name: Имя узла
            checkpoint_data: Дополнительные данные для checkpoint'а
        
        Returns:
            Обновленное состояние
        """
        new_state = dict(state)
        
        # Инициализируем метаданные если их нет
        if "metadata" not in new_state:
            new_state["metadata"] = {}
        if "checkpoint_times" not in new_state["metadata"]:
            new_state["metadata"]["checkpoint_times"] = {}
        if "checkpoint_data" not in new_state["metadata"]:
            new_state["metadata"]["checkpoint_data"] = {}
        
        # Обновляем время последнего checkpoint'а
        new_state["metadata"]["checkpoint_times"][node_name] = time.time()
        
        # Сохраняем данные checkpoint'а если предоставлены
        if checkpoint_data:
            if node_name not in new_state["metadata"]["checkpoint_data"]:
                new_state["metadata"]["checkpoint_data"][node_name] = []
            new_state["metadata"]["checkpoint_data"][node_name].append({
                "timestamp": time.time(),
                "data": checkpoint_data
            })
        
        logger.debug(f"[Checkpoint] Marked checkpoint for node {node_name}")
        return new_state
    
    @staticmethod
    def optimize_checkpoint_size(state: AnalysisState) -> AnalysisState:
        """
        Оптимизировать размер checkpoint'а, удаляя ненужные данные
        
        Args:
            state: Текущее состояние графа
        
        Returns:
            Оптимизированное состояние
        """
        new_state = dict(state)
        
        # Удаляем большие промежуточные данные, которые не нужны для восстановления
        # Сохраняем только финальные результаты
        
        # Очищаем старые checkpoint данные (оставляем только последние)
        if "metadata" in new_state and "checkpoint_data" in new_state["metadata"]:
            checkpoint_data = new_state["metadata"]["checkpoint_data"]
            for node_name, checkpoints in checkpoint_data.items():
                # Оставляем только последние 5 checkpoint'ов для каждого узла
                if len(checkpoints) > 5:
                    new_state["metadata"]["checkpoint_data"][node_name] = checkpoints[-5:]
        
        # Можно добавить дополнительную оптимизацию:
        # - Сжатие больших строк
        # - Удаление временных данных
        # - Ограничение размера messages
        
        return new_state


def with_intermediate_checkpoint(
    node_func,
    checkpoint_interval: int = 60,
    optimize_size: bool = True
):
    """
    Декоратор для узлов графа, добавляющий поддержку промежуточных checkpoint'ов
    
    Args:
        node_func: Функция узла графа
        checkpoint_interval: Интервал между checkpoint'ами в секундах
        optimize_size: Оптимизировать размер checkpoint'а
    
    Returns:
        Обернутая функция узла с поддержкой checkpoint'ов
    """
    def wrapped_node(state: AnalysisState) -> AnalysisState:
        node_name = node_func.__name__
        
        # Проверяем, нужно ли создать промежуточный checkpoint
        if IntermediateCheckpoint.should_checkpoint(state, node_name, checkpoint_interval):
            logger.info(f"[Checkpoint] Creating intermediate checkpoint for node {node_name}")
            state = IntermediateCheckpoint.mark_checkpoint(state, node_name)
        
        # Оптимизируем размер перед выполнением
        if optimize_size:
            state = IntermediateCheckpoint.optimize_checkpoint_size(state)
        
        # Выполняем узел
        result_state = node_func(state)
        
        # Отмечаем финальный checkpoint
        result_state = IntermediateCheckpoint.mark_checkpoint(result_state, node_name, {
            "completed": True,
            "node": node_name
        })
        
        return result_state
    
    wrapped_node.__name__ = node_func.__name__
    wrapped_node.__doc__ = node_func.__doc__
    return wrapped_node

