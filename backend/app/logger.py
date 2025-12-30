import logging
import sys
import os
import structlog
from logging.handlers import TimedRotatingFileHandler
from contextvars import ContextVar

# ContextVar for Correlation ID
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")

# Constants
LOG_FILE_PATH = os.path.join(os.getcwd(), "app.json")

def configure_logger():
    """
    Configures structlog to output JSON logs to file and Console (via Standard Logging).
    """
    
    # 1. Pipeline Config
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            # Render to JSON string BEFORE passing to stdlib
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 2. Processor to inject correlation ID (ContextVar)
    # Applied manually? No, we can add it to the processors list above if we define it first.
    # But defining it inside function makes it scoped.
    # Let's move add_correlation_id out or define it above.
    
    # 3. Configure Standard Logging Handlers
    
    # File Handler (JSON)
    file_handler = TimedRotatingFileHandler(
        LOG_FILE_PATH, when='midnight', interval=1, backupCount=3, encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    # The message is already JSON string from structlog, so we just pass it validly?
    # Standard logging formatter: '%(message)s'
    file_handler.setFormatter(logging.Formatter('%(message)s'))
    
    # Console Handler (Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(message)s'))

    # Root Logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    if root.handlers:
        for h in root.handlers:
            root.removeHandler(h)
            
    root.addHandler(file_handler)
    root.addHandler(console_handler)

def add_correlation_id(logger, log_method, event_dict):
    request_id = correlation_id_ctx.get()
    if request_id:
        event_dict["correlation_id"] = request_id
    return event_dict

# Re-configure with the processor included
def reconfigure():
     structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_correlation_id, # Inject ID
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
     
     # Setup Handlers
     # Setup Handlers
     file_handler = TimedRotatingFileHandler(
        LOG_FILE_PATH, when='midnight', interval=1, backupCount=3, encoding='utf-8'
    )
     file_handler.setLevel(logging.INFO)
     file_handler.setFormatter(logging.Formatter('%(message)s'))
     
     console_handler = logging.StreamHandler(sys.stdout)
     console_handler.setLevel(logging.INFO)
     console_handler.setFormatter(logging.Formatter('%(message)s'))

     root = logging.getLogger()
     root.setLevel(logging.INFO)
     root.handlers = [file_handler, console_handler]

reconfigure()

def get_logger(name: str):
    return structlog.get_logger(name)

# Constants
# LOG_FILE_PATH moved up

# Global Access
main_logger = get_logger("LogionBackend")
