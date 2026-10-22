"""Request and response schemas (Pydantic), and the shared parsers."""

from flask import request
from pydantic import BaseModel, ValidationError

from app.errors import ApiError


def _invalid(error: ValidationError) -> ApiError:
    # Details name the field and the problem, never the submitted value, so
    # passwords and personal data are not echoed back or logged.
    details = [
        {"field": ".".join(str(part) for part in issue["loc"]), "message": issue["msg"]}
        for issue in error.errors(include_input=False, include_url=False)
    ]
    return ApiError(422, "invalid_request", "Some fields are missing or invalid.", details=details)


def parse_json_body[ModelT: BaseModel](model: type[ModelT]) -> ModelT:
    """Validate the JSON request body against `model`, or raise a 422 ApiError."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(422, "invalid_request", "The request body must be a JSON object.")
    try:
        return model.model_validate(body)
    except ValidationError as error:
        raise _invalid(error) from None


def parse_query[ModelT: BaseModel](model: type[ModelT]) -> ModelT:
    """Validate the URL query string against `model`, or raise a 422 ApiError.

    A parameter given more than once is refused rather than silently using
    one of the values.
    """
    if any(len(values) > 1 for values in request.args.listvalues()):
        raise ApiError(422, "invalid_request", "Each query parameter may appear only once.")
    try:
        return model.model_validate(request.args.to_dict())
    except ValidationError as error:
        raise _invalid(error) from None
