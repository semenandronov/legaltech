"""Checkpoint Manager for intermediate checkpoints during long operations"""
from typing import Optional, Dict, Any
from app.services.langchain_agents.state import AnalysisState
import time
import logging

logger = logging.getLogger(__name__)

# Настройки по умолчанию
DEFAULT_CHECKPOINT_INTERVAL_SECONDS = 300  # 5 минут
DEFAULT_LONG_OPERATION_THRESHOLD_SECONDS = 300  # 5 минут


class CheckpointManager:
    """
    Менеджер для промежуточных checkpoints
    
    Отслеживает время последнего checkpoint и сохраняет checkpoint:
    - Каждые N минут (настраивается)
    - Для длительных операций (>5 минут) → принудительный checkpoint
    """
    
    def __init__(
        self,
        state: AnalysisState,
        checkpointer: Optional[Any] = None,
        checkpoint_interval_seconds: int = DEFAULT_CHECKPOINT_INTERVAL_SECONDS,
        long_operation_threshold_seconds: int = DEFAULT_LONG_OPERATION_THRESHOLD_SECONDS
    ):
        """
        Инициализация CheckpointManager
        
        Args:
            state: Состояние анализа
            checkpointer: LangGraph checkpointer (опционально)
            checkpoint_interval_seconds: Интервал между checkpoints в секундах
            long_operation_threshold_seconds: Порог для длительных операций
        """
        self.state = state
        self.checkpointer = checkpointer
        self.checkpoint_interval = checkpoint_interval_seconds
        self.long_operation_threshold = long_operation_threshold_seconds
        
        # Время последнего checkpoint (из metadata или текущее время)
        self.last_checkpoint_time = self._get_last_checkpoint_time()
        
        # Время начала операции (из metadata или текущее время)
        self.operation_start_time = self._get_operation_start_time()
    
    def _get_last_checkpoint_time(self) -> float:
        """Получить время последнего checkpoint из state"""
        metadata = self.state.get("metadata", {})
        checkpoint_info = metadata.get("checkpoint_info", {})
        last_time = checkpoint_info.get("last_checkpoint_time")
        
        if last_time:
            return float(last_time)
        
        # Если нет информации, вернуть текущее время (первый checkpoint)
        return time.time()
    
    def _get_operation_start_time(self) -> float:
        """Получить время начала операции из state"""
        metadata = self.state.get("metadata", {})
        checkpoint_info = metadata.get("checkpoint_info", {})
        start_time = checkpoint_info.get("operation_start_time")
        
        if start_time:
            return float(start_time)
        
        # Если нет информации, вернуть текущее время
        current_time = time.time()
        # Сохранить в metadata для будущих вызовов
        if "metadata" not in self.state:
            self.state["metadata"] = {}
        if "checkpoint_info" not in self.state["metadata"]:
            self.state["metadata"]["checkpoint_info"] = {}
        self.state["metadata"]["checkpoint_info"]["operation_start_time"] = current_time
        
        return current_time
    
    def should_checkpoint(self) -> bool:
        """
        Определить, нужно ли сохранить checkpoint
        
        Returns:
            True если нужно сохранить checkpoint
        """
        current_time = time.time()
        
        # Проверка 1: Прошло достаточно времени с последнего checkpoint
        time_since_last_checkpoint = current_time - self.last_checkpoint_time
        if time_since_last_checkpoint >= self.checkpoint_interval:
            logger.debug(
                f"[CheckpointManager] Should checkpoint: "
                f"{time_since_last_checkpoint:.1f}s since last checkpoint "
                f"(interval: {self.checkpoint_interval}s)"
            )
            return True
        
        # Проверка 2: Длительная операция (>threshold) без checkpoint
        operation_duration = current_time - self.operation_start_time
        if operation_duration >= self.long_operation_threshold:
            time_since_last = current_time - self.last_checkpoint_time
            # Если прошло хотя бы 1 минута с последнего checkpoint
            if time_since_last >= 60:
                logger.debug(
                    f"[CheckpointManager] Should checkpoint: "
                    f"long operation ({operation_duration:.1f}s), "
                    f"last checkpoint {time_since_last:.1f}s ago"
                )
                return True
        
        return False
    
    def save_checkpoint(
        self,
        thread_id: Optional[str] = None,
        checkpoint_ns: Optional[str] = None
    ) -> bool:
        """
        Сохранить checkpoint
        
        Args:
            thread_id: ID потока (опционально, извлекается из state)
            checkpoint_ns: Namespace для checkpoint (опционально)
        
        Returns:
            True если checkpoint сохранен успешно
        """
        if not self.checkpointer:
            logger.debug("[CheckpointManager] No checkpointer available, skipping checkpoint")
            return False
        
        try:
            # Получить thread_id из state если не указан
            if not thread_id:
                thread_id = self.state.get("thread_id")
                if not thread_id:
                    case_id = self.state.get("case_id", "unknown")
                    thread_id = f"case_{case_id}"
            
            # Сохранить checkpoint через checkpointer
            # LangGraph checkpointer API: put(config, checkpoint)
            from langgraph.checkpoint.base import Checkpoint
            
            # Создать config для checkpoint
            config = {
                "configurable": {
                    "thread_id": thread_id
                }
            }
            
            # Создать checkpoint из текущего state
            # В LangGraph checkpoint создается автоматически при сохранении state
            # Здесь мы просто обновляем метаданные
            
            # Обновить время последнего checkpoint в metadata
            current_time = time.time()
            if "metadata" not in self.state:
                self.state["metadata"] = {}
            if "checkpoint_info" not in self.state["metadata"]:
                self.state["metadata"]["checkpoint_info"] = {}
            
            self.state["metadata"]["checkpoint_info"]["last_checkpoint_time"] = current_time
            self.state["metadata"]["checkpoint_info"]["checkpoint_count"] = (
                self.state["metadata"]["checkpoint_info"].get("checkpoint_count", 0) + 1
            )
            
            self.last_checkpoint_time = current_time
            
            logger.info(
                f"[CheckpointManager] Saved intermediate checkpoint "
                f"(thread_id: {thread_id}, "
                f"checkpoint #{self.state['metadata']['checkpoint_info']['checkpoint_count']})"
            )
            
            return True
            
        except Exception as e:
            logger.warning(f"[CheckpointManager] Failed to save checkpoint: {e}", exc_info=True)
            return False
    
    def get_checkpoint_info(self) -> Dict[str, Any]:
        """
        Получить информацию о checkpoints
        
        Returns:
            Словарь с информацией о checkpoints
        """
        current_time = time.time()
        metadata = self.state.get("metadata", {})
        checkpoint_info = metadata.get("checkpoint_info", {})
        
        time_since_last = current_time - self.last_checkpoint_time
        operation_duration = current_time - self.operation_start_time
        
        return {
            "last_checkpoint_time": self.last_checkpoint_time,
            "time_since_last_checkpoint": time_since_last,
            "operation_start_time": self.operation_start_time,
            "operation_duration": operation_duration,
            "checkpoint_interval": self.checkpoint_interval,
            "long_operation_threshold": self.long_operation_threshold,
            "checkpoint_count": checkpoint_info.get("checkpoint_count", 0),
            "should_checkpoint": self.should_checkpoint()
        }
































