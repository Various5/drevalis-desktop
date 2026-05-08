"""Domain exceptions for the Drevalis application.

These exceptions are raised by service-layer code and caught by
route handlers, which convert them to appropriate HTTP status codes.
This separation keeps services free of FastAPI imports.
"""

from __future__ import annotations

from uuid import UUID


class NotFoundError(Exception):
    """Base class for resource-not-found errors."""

    def __init__(self, resource: str, resource_id: UUID | str) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")


class InvalidStatusError(Exception):
    """Raised when an operation is attempted on a resource in an invalid state."""

    def __init__(
        self, resource: str, resource_id: UUID | str, current: str, allowed: list[str]
    ) -> None:
        self.resource = resource
        self.resource_id = resource_id
        self.current = current
        self.allowed = allowed
        super().__init__(
            f"{resource} {resource_id} has status '{current}', expected one of {allowed}"
        )


class ValidationError(Exception):
    """Raised when input validation fails at the service layer."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
