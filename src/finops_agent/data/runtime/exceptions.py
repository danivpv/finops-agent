"""Data API errors."""

from __future__ import annotations

from ...exceptions import FinopsException


class DataException(FinopsException):
    prefix = "DAT"


class EndpointNotFoundError(DataException):
    status_code = 404
    error_id = "1404"
    message = "Endpoint not found: {path}"


class UnknownToolError(DataException):
    status_code = 400
    error_id = "1400"
    message = "Unknown tool: {name}"


class UnknownDimensionError(DataException):
    status_code = 400
    error_id = "1402"
    message = "Unknown dimension: {name}"


class UnknownMetricError(DataException):
    status_code = 400
    error_id = "1403"
    message = "Unknown metric: {name}"


class InvalidBodyError(DataException):
    status_code = 400
    error_id = "1422"
    message = "Invalid request body"
