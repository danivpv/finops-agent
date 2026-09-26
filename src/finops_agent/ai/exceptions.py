"""Agent errors raised while planning or calling the Data Lambda."""

from __future__ import annotations

from ..exceptions import FinopsException
from .constants import PROMPT_UNAVAILABLE_MESSAGE


class AgentException(FinopsException):
    prefix = "AGT"


class QueryBudgetError(AgentException):
    status_code = 400
    error_id = "2400"
    message = "Query budget exhausted: at most {max_steps} queries per question."


class QueryFailedError(AgentException):
    status_code = 502
    error_id = "2502"
    message = "{detail}"


class UnexpectedGatewayResponse(AgentException):
    status_code = 502
    error_id = "2503"
    message = "unexpected gateway response"


class PromptUnavailableError(AgentException):
    status_code = 503
    error_id = "2504"
    message = PROMPT_UNAVAILABLE_MESSAGE
