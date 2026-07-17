"""hydra/services/webpanel/errors.py — ошибки API и их HTTP-коды."""
from __future__ import annotations


class ApiError(Exception):
    """Ошибка бизнес-логики, транслируемая в HTTP-ответ.

    Обработчики маршрутов бросают ApiError с подходящим статусом; сервер
    сериализует её в JSON вида {"error": "..."} с этим кодом.
    """

    status: int = 400

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class BadRequest(ApiError):
    def __init__(self, message: str = "Некорректный запрос"):
        super().__init__(message, 400)


class Unauthorized(ApiError):
    def __init__(self, message: str = "Требуется авторизация"):
        super().__init__(message, 401)


class Forbidden(ApiError):
    def __init__(self, message: str = "Доступ запрещён"):
        super().__init__(message, 403)


class NotFound(ApiError):
    def __init__(self, message: str = "Не найдено"):
        super().__init__(message, 404)


class Conflict(ApiError):
    def __init__(self, message: str = "Конфликт состояния"):
        super().__init__(message, 409)


class ServerError(ApiError):
    def __init__(self, message: str = "Внутренняя ошибка сервера"):
        super().__init__(message, 500)
