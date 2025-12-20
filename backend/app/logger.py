import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Constants
LOG_FILE_PATH = os.path.join(os.getcwd(), "app.log")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

def get_logger(name: str):
    """
    Returns a configured logger instance.
    Ensures that we only have one file handler and one stream handler per logger.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Check if handlers are already set to avoid duplication
    if not logger.handlers:
        # 1. File Handler (Rotating)
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(file_handler)

        # 2. Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO) # Keep console cleaner
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(console_handler)

    return logger

# Global instance for quick access
main_logger = get_logger("LogionBackend")
