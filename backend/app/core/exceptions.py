class ApiError(Exception):
    """Base for API-level errors with an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFoundError(ApiError):
    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message, status_code=404)
