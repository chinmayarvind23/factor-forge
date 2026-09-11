"""Explicit failures preserve safe public messages separately from transport handling."""


class ResearchError(Exception):
    """A typed application failure can be mapped consistently by API and later CLI adapters."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        """Avoid embedding exception internals or input content in public error responses."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
