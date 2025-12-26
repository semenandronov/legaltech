"""External data sources for Legal AI Vault"""
from .base_source import BaseSource, SourceResult, VaultSource
from .source_router import SourceRouter, get_source_router, initialize_source_router
from .web_search import WebSearchSource
from .garant_source import GarantSource
from .consultant_source import ConsultantPlusSource

__all__ = [
    "BaseSource",
    "SourceResult",
    "VaultSource",
    "SourceRouter",
    "get_source_router",
    "initialize_source_router",
    "WebSearchSource",
    "GarantSource",
    "ConsultantPlusSource",
]

