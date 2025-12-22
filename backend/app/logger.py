import logging
import sys
import os
import structlog
from logging.handlers import TimedRotatingFileHandler
from .middleware.correlation import get_request_id

# Constants
LOG_FILE_PATH = os.path.join(os.getcwd(), "app.json")

def configure_logger():
    """
    Configures structlog to output JSON logs.
    """
    
    # Processor to inject correlation ID
    def add_correlation_id(logger, log_method, event_dict):
        request_id = get_request_id()
        if request_id:
            event_dict["correlation_id"] = request_id
        return event_dict

    # 1. Configure Structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_correlation_id,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str):
    return structlog.get_logger(name)

# Auto-configure on import
configure_logger()

# Global Access
main_logger = get_logger("LogionBackend")
