"""
hydra/plugins/amneziawg/presets.py — Carrier-пресеты обфускации для AmneziaWG.
"""
from __future__ import annotations
import random
from typing import Optional

CARRIER_PRESETS: dict[str, dict] = {
    "default": {
        "label": "Default (проводной интернет)",
        "jc_min": 3, "jc_max": 6,
        "jmin_min": 40, "jmin_max": 89,
        "jmax_delta_min": 50, "jmax_delta_max": 250,
        "i1_mode": "random",
        "description": "Универсальный пресет для проводного интернета. Jc 3-6 — компромисс между обфускацией и совместимостью.",
    },
    "mobile": {
        "label": "Mobile (универсальный для мобильных DPI)",
        "jc_min": 3, "jc_max": 3,
        "jmin_min": 30, "jmin_max": 50,
        "jmax_delta_min": 20, "jmax_delta_max": 80,
        "i1_mode": "random",
        "description": "Jc=3 фиксированный, узкий Jmax. Для мобильных с ТСПУ.",
    },
    "tele2": {
        "label": "Tele2 (Россия)",
        "jc_min": 3, "jc_max": 3,
        "jmin_min": 30, "jmin_max": 50,
        "jmax_delta_min": 20, "jmax_delta_max": 80,
        "i1_mode": "random",
        "description": "Jc=3 обязателен (Jc=4 ~30% успеха, Jc=5 <5%).",
    },
    "yota": {
        "label": "Yota (Россия)",
        "jc_min": 3, "jc_max": 3,
        "jmin_min": 30, "jmin_max": 50,
        "jmax_delta_min": 20, "jmax_delta_max": 80,
        "i1_mode": "random",
        "description": "Узкий Jmax обязателен — Jmax>300 блокируется.",
    },
    "megafon": {
        "label": "Мегафон (регионы)",
        "jc_min": 3, "jc_max": 3,
        "jmin_min": 30, "jmin_max": 50,
        "jmax_delta_min": 20, "jmax_delta_max": 80,
        "i1_mode": "absent",
        "description": "Без параметра I1 — иначе блокировка.",
    },
    "beeline": {
        "label": "Билайн (Россия)",
        "jc_min": 3, "jc_max": 6,
        "jmin_min": 40, "jmin_max": 89,
        "jmax_delta_min": 50, "jmax_delta_max": 250,
        "i1_mode": "random",
        "description": "Работает default preset.",
    },
    "tattelecom": {
        "label": "Таттелеком / Летай",
        "jc_min": 3, "jc_max": 3,
        "jmin_min": 30, "jmin_max": 50,
        "jmax_delta_min": 20, "jmax_delta_max": 80,
        "i1_mode": "random",
        "description": "Mobile preset подходит.",
    },
}

JC_MIN = 1
JC_MAX = 128
JMIN_MAX = 1280
JMAX_MAX = 1280
S3_MAX = 64
S4_MAX = 32


def generate_params(preset_name: str = "default") -> dict[str, str]:
    """
    Генерирует конкретные значения параметров обфускации по пресету.
    Возвращает dict с capitalized ключами: Jc, Jmin, Jmax, S1, S2, S3, S4, H1, H2, H3, H4, I1
    Значения возвращаются как строки.
    """
    preset = CARRIER_PRESETS.get(preset_name)
    if not preset:
        preset = CARRIER_PRESETS["default"]

    jc = random.randint(preset["jc_min"], preset["jc_max"])
    jmin = random.randint(preset["jmin_min"], preset["jmin_max"])
    jmax_delta = random.randint(preset["jmax_delta_min"], preset["jmax_delta_max"])
    jmax = min(jmin + jmax_delta, JMAX_MAX)

    s1, s2, s3, s4 = 0, 0, 0, 0
    h1, h2, h3, h4 = 1, 2, 3, 4

    i1_mode = preset["i1_mode"]
    if i1_mode == "random":
        i1_len = random.randint(24, 32)
        i1 = "".join(random.choices("0123456789abcdef", k=i1_len * 2))
    elif i1_mode == "binary":
        i1 = "".join(random.choices("0123456789abcdef", k=16))
    else:
        i1 = ""

    return {
        "Jc": str(jc),
        "Jmin": str(jmin),
        "Jmax": str(jmax),
        "S1": str(s1),
        "S2": str(s2),
        "S3": str(s3),
        "S4": str(s4),
        "H1": str(h1),
        "H2": str(h2),
        "H3": str(h3),
        "H4": str(h4),
        "I1": i1,
    }


def list_presets() -> list[dict]:
    """Возвращает список доступных пресетов с описаниями."""
    return [
        {"name": name, "label": p["label"], "description": p["description"]}
        for name, p in CARRIER_PRESETS.items()
    ]


def validate_params(params: dict) -> tuple[bool, str]:
    """
    Валидирует параметры обфускации.
    Возвращает (True, "") или (False, "сообщение об ошибке").
    """
    try:
        def get_int(k):
            val = params.get(k, 0)
            if isinstance(val, str) and val.isdigit():
                return int(val)
            return int(val)

        jc = get_int("Jc")
        if jc < JC_MIN or jc > JC_MAX:
            return False, f"Jc={jc} вне диапазона ({JC_MIN}-{JC_MAX})"

        jmin = get_int("Jmin")
        if jmin < 0 or jmin > JMIN_MAX:
            return False, f"Jmin={jmin} вне диапазона (0-{JMIN_MAX})"

        jmax = get_int("Jmax")
        if jmax < 0 or jmax > JMAX_MAX:
            return False, f"Jmax={jmax} вне диапазона (0-{JMAX_MAX})"
        if jmax < jmin:
            return False, f"Jmax ({jmax}) меньше Jmin ({jmin})"

        for key in ("S1", "S2"):
            v = get_int(key)
            if v < 0 or v > JMIN_MAX:
                return False, f"{key}={v} вне диапазона (0-{JMIN_MAX})"

        s3 = get_int("S3")
        if s3 < 0 or s3 > S3_MAX:
            return False, f"S3={s3} вне диапазона (0-{S3_MAX})"

        s4 = get_int("S4")
        if s4 < 0 or s4 > S4_MAX:
            return False, f"S4={s4} вне диапазона (0-{S4_MAX})"

        for key in ("H1", "H2", "H3", "H4"):
            v = get_int(key)
            if v < 0 or v > 255:
                return False, f"{key}={v} вне диапазона (0-255)"

        i1 = params.get("I1", "")
        if i1:
            if not isinstance(i1, str):
                return False, "I1 должен быть строкой"
            if not all(c in "0123456789abcdefABCDEF" for c in i1):
                return False, "I1 содержит не-hex символы"

        return True, ""
    except Exception as e:
        return False, f"Ошибка валидации параметров: {e}"
