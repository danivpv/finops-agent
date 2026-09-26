"""Map a Pydantic validation error onto a FinopsException."""

from __future__ import annotations

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from ...exceptions import FinopsException
from .exceptions import InvalidBodyError


def _from_validation(exc: ValidationError | RequestValidationError) -> FinopsException:
    err = exc.errors()[0] if exc.errors() else {}
    cause = (err.get("ctx") or {}).get("error")
    if isinstance(cause, FinopsException):
        return cause
    message = str(err.get("msg", InvalidBodyError.message)).removeprefix(
        "Value error, "
    )
    return InvalidBodyError(message=message)
