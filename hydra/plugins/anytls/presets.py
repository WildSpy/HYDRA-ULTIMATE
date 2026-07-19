"""
hydra/plugins/anytls/presets.py — AnyTLS padding scheme presets.

Предоставляет 4 пресета обфускации трафика для AnyTLS (disabled / web_browsing / streaming / messaging).
"""
from __future__ import annotations

PRESETS = {
    "disabled": {
        "name": "disabled",
        "label": "🔓 Отключена",
        "description": "Передача трафика без маскировки и паддинга",
        "padding_scheme": [
            "stop=0"
        ]
    },
    "web_browsing": {
        "name": "web_browsing",
        "label": "🌐 Веб-серфинг",
        "description": "Имитация обычного просмотра веб-страниц (по умолчанию)",
        "padding_scheme": [
            "stop=10",
            "0=30-100",
            "1=100-500",
            "2=500-1200",
            "3=100-300",
            "4=400-800",
            "5=500-1000",
            "6=200-600",
            "7=300-800",
            "8=500-1000",
            "9=100-500",
        ]
    },
    "streaming": {
        "name": "streaming",
        "label": "📺 Стриминг",
        "description": "Имитация загрузки медиапотоков (крупные пакеты данных)",
        "padding_scheme": [
            "stop=6",
            "0=50-100",
            "1=200-500",
            "2=1000-1500,c,1000-1500,c,1000-1500",
            "3=1000-1500",
            "4=1000-1500",
            "5=1000-1500",
        ]
    },
    "messaging": {
        "name": "messaging",
        "label": "💬 Мессенджеры",
        "description": "Имитация переписки в чатах (быстрые мелкие пакеты)",
        "padding_scheme": [
            "stop=15",
            "0=10-30",
            "1=20-50",
            "2=10-40",
            "3=10-40",
            "4=20-60",
            "5=10-30",
            "6=15-45",
            "7=20-50",
            "8=10-30",
            "9=10-30",
            "10=20-60",
            "11=10-30",
            "12=15-45",
            "13=20-50",
            "14=10-30",
        ]
    }
}


def list_presets() -> list[dict]:
    """Возвращает список всех доступных пресетов."""
    return list(PRESETS.values())


def get_preset(name: str) -> dict:
    """Возвращает информацию о пресете по его имени."""
    preset = PRESETS.get(name)
    if not preset:
        preset = PRESETS["web_browsing"]
    return preset
