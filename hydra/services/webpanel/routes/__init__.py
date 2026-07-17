"""hydra/services/webpanel/routes — сборка таблицы маршрутов API.

Каждый модуль-раздел экспортирует список ROUTES из кортежей:
    (method, path_regex, handler[, auth_required])
build_routes() объединяет их в список Route для сервера.
"""
from __future__ import annotations

from typing import Callable


def build_routes():
    from hydra.services.webpanel.server import Route
    from hydra.services.webpanel.routes import (
        auth, dashboard, system, protocols, plugin_wizards, users,
        subscriptions, telegram, monitoring, security, network, diagnostics,
    )

    modules = [
        auth, dashboard, system, protocols, plugin_wizards, users,
        subscriptions, telegram, monitoring, security, network, diagnostics,
    ]
    routes = []
    for mod in modules:
        for entry in getattr(mod, "ROUTES", []):
            method, pattern, handler = entry[0], entry[1], entry[2]
            auth_required = entry[3] if len(entry) > 3 else True
            routes.append(Route(method, pattern, handler, auth_required))
    return routes
