"""Data Lambda entry. Declares the FastAPI app and the Gateway tool door."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from pydantic import ValidationError

from ...constants import QUERY_TOOL_NAME
from ...exceptions import FinopsException
from ...schemas import InvestigateQuery
from .exception_handlers import _from_validation
from .exceptions import EndpointNotFoundError, UnknownToolError
from .routes import router, run_query
from .schemas import HttpEvent, LambdaContextView

app = FastAPI(title="FinOps Data")


@app.exception_handler(FinopsException)
async def finops_error(_request: Request, exc: FinopsException) -> JSONResponse:
    return JSONResponse(exc.as_dict(), status_code=exc.status_code)


@app.exception_handler(ValidationError)
@app.exception_handler(RequestValidationError)
async def validation_error(
    _request: Request, exc: ValidationError | RequestValidationError
) -> JSONResponse:
    err = _from_validation(exc)
    return JSONResponse(err.as_dict(), status_code=err.status_code)


@app.exception_handler(404)
async def not_found(request: Request, _exc: Exception) -> JSONResponse:
    err = EndpointNotFoundError(path=request.url.path)
    return JSONResponse(err.as_dict(), status_code=err.status_code)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

_mangum = Mangum(app, lifespan="off")


def _tool_response(event: dict[str, Any], tool_name: str | None) -> dict[str, Any]:
    """Gateway events are not API Gateway events, so Mangum does not see them."""
    if tool_name is not None and tool_name != QUERY_TOOL_NAME:
        return UnknownToolError(name=tool_name).as_dict()
    try:
        return run_query(InvestigateQuery.model_validate(event)).model_dump()
    except FinopsException as exc:
        return exc.as_dict()
    except ValidationError as exc:
        return _from_validation(exc).as_dict()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    view = LambdaContextView.model_validate(context if context is not None else {})
    http = HttpEvent.model_validate(event)
    if view.tool_name is not None or not http.is_http:
        return _tool_response(event, view.tool_name)
    return _mangum(event, context)
