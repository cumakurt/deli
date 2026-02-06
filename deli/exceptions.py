"""Custom exceptions for deli execution engine.

All deli-specific exceptions inherit from DeliError for unified error handling.
Each exception preserves the original cause chain for debugging.
"""

from __future__ import annotations

from typing import Any


class DeliError(Exception):
    """Base exception for all deli errors.
    
    Attributes:
        message: Human-readable error description
        context: Optional dictionary with additional debugging context
        original_error: Original exception that caused this error (if any)
    """

    def __init__(
        self,
        message: str,
        *args: object,
        context: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message, *args)
        self.message = message
        self.context = context or {}
        self.original_error = original_error
    
    def __str__(self) -> str:
        """Return formatted error message with context if available."""
        base = self.message
        if self.context:
            ctx_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            base = f"{base} [{ctx_str}]"
        if self.original_error:
            base = f"{base} (caused by: {type(self.original_error).__name__}: {self.original_error})"
        return base
    
    def with_context(self, **kwargs: Any) -> "DeliError":
        """Add context to this error and return self for chaining."""
        self.context.update(kwargs)
        return self


class DeliConfigError(DeliError):
    """Raised when configuration is invalid or file cannot be loaded.
    
    Common causes:
    - Config file not found
    - Invalid YAML syntax
    - Missing required fields
    - Invalid field values (e.g., users < 1)
    """


class DeliCollectionError(DeliError):
    """Raised when Postman collection is invalid or cannot be parsed.
    
    Common causes:
    - Collection file not found
    - Invalid JSON syntax
    - Unsupported collection format/version
    - Missing required fields in requests
    """


class DeliRunnerError(DeliError):
    """Raised when test run fails (e.g. no requests, runtime error).
    
    Common causes:
    - No requests to execute
    - Network connectivity issues
    - Target server unreachable
    - Resource exhaustion (memory, file descriptors)
    """
