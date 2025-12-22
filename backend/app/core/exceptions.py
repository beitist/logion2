class LogionException(Exception):
    """Base exception for Logion backend."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class ProjectNotFound(LogionException):
    """Raised when a requested project ID does not exist."""
    pass

class ResourceNotFound(LogionException):
    """Generic resource not found."""
    pass

class ModelError(LogionException):
    """Raised when an AI model fails to respond or load."""
    pass

class ConfigurationError(LogionException):
    """Raised when critical configuration (e.g. API keys) is missing."""
    pass
