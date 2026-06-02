from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Unauthorized"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Forbidden"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    detail = "Conflict"


class UnprocessableError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    detail = "Unprocessable entity"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_exception_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
