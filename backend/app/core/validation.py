from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base for every request schema.

    ``extra="forbid"`` means a caller cannot smuggle a field the endpoint does
    not declare — notably ``status`` on a profile update. A silently-dropped
    field hides the attempt; a 422 makes it visible and testable.
    """

    model_config = ConfigDict(extra="forbid")


async def safe_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return 422 metadata that never contains the submitted value.

    FastAPI's default body echoes ``input`` and occasionally ``ctx``, which for
    an auth endpoint means the password, the code or the token ends up in a
    response and in any proxy that logs bodies. Only the field path, the error
    type and a generic message survive here.
    """
    errors = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path")]
        error_type = str(error.get("type", "value_error"))
        message = str(error.get("msg", "invalid value"))
        # A ctx entry can hold the offending value (e.g. "must be one of ['a','b']"
        # is fine, but a ValueError str() often is not), so it is dropped.
        errors.append({"field": ".".join(location) or "body", "type": error_type, "message": message})
    return JSONResponse(status_code=422, content={"detail": "Request validation failed", "errors": errors})
