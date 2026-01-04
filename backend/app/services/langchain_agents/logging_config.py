"""Centralized logging configuration for agent system"""
import logging
import sys
import os
from typing import Optional

# Log levels
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}


def setup_agent_logging(
    level: Optional[str] = None,
    format_string: Optional[str] = None
) -> None:
    """
    Setup centralized logging for agent system
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string (optional)
    """
    # Get log level from config or parameter
    log_level_str = level or os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = LOG_LEVELS.get(log_level_str, logging.INFO)
    
    # Default format
    if format_string is None:
        format_string = (
            "%(asctime)s - %(name)s - %(levelname)s - "
            "[%(filename)s:%(lineno)d] - %(message)s"
        )
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=format_string,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific loggers for agent components
    agent_loggers = {
        "app.services.langchain_agents": logging.INFO,
        "app.services.langchain_agents.coordinator": logging.INFO,
        "app.services.langchain_agents.supervisor": logging.DEBUG,
        "app.services.langchain_agents.graph": logging.DEBUG,
    }
    
    for logger_name, logger_level in agent_loggers.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(logger_level)
    
    # Suppress noisy third-party loggers
    noisy_loggers = [
        "httpx",
        "httpcore",
        "urllib3",
        "asyncio"
    ]
    
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_agent_logger(name: str) -> logging.Logger:
    """
    Get logger for agent component with consistent naming
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# Initialize logging on import
import os
setup_agent_logging()

