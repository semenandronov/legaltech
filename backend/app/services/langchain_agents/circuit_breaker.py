"""Circuit Breaker for preventing cascading failures"""
from typing import Dict, Optional
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)

# Пороговые значения
ERROR_RATE_THRESHOLD = 0.5  # 50% ошибок
ERROR_WINDOW_SECONDS = 300  # 5 минут
COOLDOWN_SECONDS = 60  # 1 минута cooldown


class CircuitState(str, Enum):
    """Состояние circuit breaker"""
    CLOSED = "closed"  # Нормальная работа
    OPEN = "open"  # Circuit открыт, используем fallback
    HALF_OPEN = "half_open"  # Тестируем восстановление


class AgentCircuitBreaker:
    """
    Circuit Breaker для агентов
    
    Отслеживает error rate для каждого агента:
    - При превышении threshold (50% ошибок за 5 минут) → открывает circuit
    - В открытом состоянии → использует fallback (skip/cached result)
    - Через cooldown период → пытается закрыть circuit (half-open)
    """
    
    def __init__(
        self,
        error_rate_threshold: float = ERROR_RATE_THRESHOLD,
        error_window_seconds: int = ERROR_WINDOW_SECONDS,
        cooldown_seconds: int = COOLDOWN_SECONDS
    ):
        """
        Инициализация Circuit Breaker
        
        Args:
            error_rate_threshold: Порог error rate (0.0-1.0)
            error_window_seconds: Окно времени для подсчета ошибок
            cooldown_seconds: Время cooldown перед попыткой восстановления
        """
        self.error_rate_threshold = error_rate_threshold
        self.error_window_seconds = error_window_seconds
        self.cooldown_seconds = cooldown_seconds
        
        # Состояние circuit для каждого агента
        self.circuit_states: Dict[str, CircuitState] = {}
        
        # История ошибок: agent_name -> [(timestamp, error_type), ...]
        self.error_history: Dict[str, list] = {}
        
        # Время открытия circuit для каждого агента
        self.circuit_opened_at: Dict[str, float] = {}
        
        # Счетчик успешных попыток в half-open состоянии
        self.half_open_success_count: Dict[str, int] = {}
    
    def record_success(self, agent_name: str) -> None:
        """
        Записать успешное выполнение агента
        
        Args:
            agent_name: Имя агента
        """
        # Если circuit в half-open состоянии, увеличить счетчик успехов
        if self.circuit_states.get(agent_name) == CircuitState.HALF_OPEN:
            self.half_open_success_count[agent_name] = self.half_open_success_count.get(agent_name, 0) + 1
            
            # Если достаточно успешных попыток, закрыть circuit
            if self.half_open_success_count[agent_name] >= 3:
                self.circuit_states[agent_name] = CircuitState.CLOSED
                self.circuit_opened_at.pop(agent_name, None)
                self.half_open_success_count[agent_name] = 0
                logger.info(f"[CircuitBreaker] Circuit closed for {agent_name} after successful recovery")
        
        # Очистить старые ошибки (успех означает, что агент работает)
        if agent_name in self.error_history:
            # Оставить только последние ошибки в окне
            current_time = time.time()
            self.error_history[agent_name] = [
                (ts, error_type) for ts, error_type in self.error_history[agent_name]
                if current_time - ts < self.error_window_seconds
            ]
    
    def record_error(self, agent_name: str, error_type: str = "unknown") -> None:
        """
        Записать ошибку агента
        
        Args:
            agent_name: Имя агента
            error_type: Тип ошибки
        """
        current_time = time.time()
        
        # Добавить ошибку в историю
        if agent_name not in self.error_history:
            self.error_history[agent_name] = []
        
        self.error_history[agent_name].append((current_time, error_type))
        
        # Очистить старые ошибки (старше error_window_seconds)
        self.error_history[agent_name] = [
            (ts, error_type) for ts, error_type in self.error_history[agent_name]
            if current_time - ts < self.error_window_seconds
        ]
        
        # Вычислить error rate
        error_rate = self._calculate_error_rate(agent_name)
        
        # Если error rate превышает threshold, открыть circuit
        if error_rate >= self.error_rate_threshold:
            if self.circuit_states.get(agent_name) != CircuitState.OPEN:
                self.circuit_states[agent_name] = CircuitState.OPEN
                self.circuit_opened_at[agent_name] = current_time
                logger.warning(
                    f"[CircuitBreaker] Circuit opened for {agent_name} "
                    f"(error_rate: {error_rate:.2%}, threshold: {self.error_rate_threshold:.2%})"
                )
        
        # Если circuit в half-open и произошла ошибка, снова открыть
        elif self.circuit_states.get(agent_name) == CircuitState.HALF_OPEN:
            self.circuit_states[agent_name] = CircuitState.OPEN
            self.circuit_opened_at[agent_name] = current_time
            self.half_open_success_count[agent_name] = 0
            logger.warning(f"[CircuitBreaker] Circuit reopened for {agent_name} after error in half-open state")
    
    def _calculate_error_rate(self, agent_name: str) -> float:
        """
        Вычислить error rate для агента
        
        Args:
            agent_name: Имя агента
        
        Returns:
            Error rate (0.0-1.0)
        """
        if agent_name not in self.error_history:
            return 0.0
        
        errors = self.error_history[agent_name]
        if not errors:
            return 0.0
        
        # Подсчитать ошибки в окне
        current_time = time.time()
        recent_errors = [
            (ts, error_type) for ts, error_type in errors
            if current_time - ts < self.error_window_seconds
        ]
        
        # Для простоты считаем error rate как долю ошибок
        # В реальности нужно учитывать общее количество попыток
        # Здесь используем упрощенную модель: если есть ошибки → считаем rate
        if len(recent_errors) > 0:
            # Упрощенная модель: если есть ошибки, считаем rate на основе количества
            # В production нужно отслеживать общее количество попыток
            return min(1.0, len(recent_errors) / 10.0)  # Упрощенная модель
        
        return 0.0
    
    def is_circuit_open(self, agent_name: str) -> bool:
        """
        Проверить, открыт ли circuit для агента
        
        Args:
            agent_name: Имя агента
        
        Returns:
            True если circuit открыт
        """
        state = self.circuit_states.get(agent_name, CircuitState.CLOSED)
        
        if state == CircuitState.CLOSED:
            return False
        
        if state == CircuitState.OPEN:
            # Проверить, прошло ли достаточно времени для cooldown
            opened_at = self.circuit_opened_at.get(agent_name)
            if opened_at:
                current_time = time.time()
                if current_time - opened_at >= self.cooldown_seconds:
                    # Перейти в half-open состояние
                    self.circuit_states[agent_name] = CircuitState.HALF_OPEN
                    self.half_open_success_count[agent_name] = 0
                    logger.info(f"[CircuitBreaker] Circuit half-open for {agent_name} (testing recovery)")
                    return False  # Разрешить попытку
            return True  # Circuit открыт
        
        # HALF_OPEN - разрешить попытку
        return False
    
    def get_state(self, agent_name: str) -> CircuitState:
        """
        Получить состояние circuit для агента
        
        Args:
            agent_name: Имя агента
        
        Returns:
            Состояние circuit
        """
        # Обновить состояние если нужно (cooldown)
        self.is_circuit_open(agent_name)
        
        return self.circuit_states.get(agent_name, CircuitState.CLOSED)
    
    def get_stats(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Получить статистику circuit breaker
        
        Args:
            agent_name: Имя агента (опционально, для фильтрации)
        
        Returns:
            Словарь со статистикой
        """
        if agent_name:
            error_rate = self._calculate_error_rate(agent_name)
            state = self.get_state(agent_name)
            error_count = len(self.error_history.get(agent_name, []))
            
            return {
                "agent": agent_name,
                "state": state.value,
                "error_rate": error_rate,
                "error_count": error_count,
                "opened_at": self.circuit_opened_at.get(agent_name)
            }
        else:
            # Статистика для всех агентов
            return {
                "total_agents": len(self.circuit_states),
                "open_circuits": sum(
                    1 for state in self.circuit_states.values()
                    if state == CircuitState.OPEN
                ),
                "half_open_circuits": sum(
                    1 for state in self.circuit_states.values()
                    if state == CircuitState.HALF_OPEN
                ),
                "closed_circuits": sum(
                    1 for state in self.circuit_states.values()
                    if state == CircuitState.CLOSED
                )
            }
    
    def reset(self, agent_name: Optional[str] = None) -> None:
        """
        Сбросить circuit breaker для агента или всех агентов
        
        Args:
            agent_name: Имя агента (опционально, для сброса конкретного агента)
        """
        if agent_name:
            self.circuit_states.pop(agent_name, None)
            self.error_history.pop(agent_name, None)
            self.circuit_opened_at.pop(agent_name, None)
            self.half_open_success_count.pop(agent_name, None)
            logger.info(f"[CircuitBreaker] Reset circuit breaker for {agent_name}")
        else:
            self.circuit_states.clear()
            self.error_history.clear()
            self.circuit_opened_at.clear()
            self.half_open_success_count.clear()
            logger.info("[CircuitBreaker] Reset all circuit breakers")


# Глобальный экземпляр
_circuit_breaker = None


def get_circuit_breaker() -> AgentCircuitBreaker:
    """Получить глобальный экземпляр AgentCircuitBreaker"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = AgentCircuitBreaker()
    return _circuit_breaker





























