"""Base error for the FinOps agent. Service catalogs subclass this."""

from __future__ import annotations


class FinopsException(Exception):
    """status_code, error_id, and message are class attributes. Subclasses override them."""

    status_code: int = 500
    error_id: str = "1000"
    message: str = "An unexpected error occurred"
    prefix: str = "FIN"

    def __init__(self, message: str | None = None, **kwargs: object) -> None:
        self.error_code = f"{self.prefix}-{self.error_id}"
        self.message = message or self.message.format(**kwargs)
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"error": self.message, "code": self.error_code}
